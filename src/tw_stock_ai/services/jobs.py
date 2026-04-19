from __future__ import annotations

from datetime import date

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from tw_stock_ai.config import get_settings
from tw_stock_ai.db import SessionLocal
from tw_stock_ai.models import DailyReportRun, DiscordDeliveryLog
from tw_stock_ai.notifiers.registry import build_default_notifier
from tw_stock_ai.schemas import DailyReportRunRead
from tw_stock_ai.services.ai_analysis import AIAnalysisService
from tw_stock_ai.services.app_settings import build_effective_settings
from tw_stock_ai.services.cost_control import CostControlService
from tw_stock_ai.services.daily_report import DailyReportGenerator, serialize_report_run
from tw_stock_ai.services.feature_flags import FeatureFlagService
from tw_stock_ai.services.logging_config import get_logger
from tw_stock_ai.services.rate_limits import RateLimitExceededError, RateLimitService
from tw_stock_ai.services.screener import run_screening

logger = get_logger("tw_stock_ai.jobs")


def build_scheduler() -> BackgroundScheduler:
    with SessionLocal() as session:
        settings = build_effective_settings(session)
    scheduler = BackgroundScheduler(timezone=settings.scheduler_timezone)
    logger.info(
        "scheduler_configured timezone=%s hour=%s minute=%s weekdays=%s",
        settings.scheduler_timezone,
        settings.screening_hour,
        settings.screening_minute,
        settings.screening_weekdays,
    )
    scheduler.add_job(
        func=run_daily_screening_job,
        trigger="cron",
        day_of_week=settings.screening_weekdays,
        hour=settings.screening_hour,
        minute=settings.screening_minute,
        id="daily-screening-discord-push",
        replace_existing=True,
    )
    return scheduler


def run_daily_screening_job() -> dict:
    with SessionLocal() as session:
        report = run_daily_screening_and_push(session, trigger_source="scheduler")
        return DailyReportRunRead.model_validate(
            serialize_report_run(report, _load_delivery_logs(session, report.id))
        ).model_dump()


def run_daily_screening_and_push(session: Session, *, trigger_source: str) -> DailyReportRun:
    settings = build_effective_settings(session)
    flags = FeatureFlagService(settings)
    rate_limits = RateLimitService(settings)
    notifier = build_default_notifier(settings)
    cost_control = CostControlService(settings)
    generator = DailyReportGenerator(
        top_n=settings.discord_daily_report_top_n,
        reason_max_length=settings.discord_reason_max_length,
        risk_max_length=settings.discord_risk_max_length,
    )
    report = DailyReportRun(
        report_kind="discord_top_picks",
        report_date=date.today(),
        trigger_source=trigger_source,
        status="running",
        qualified_count=0,
        top_n=settings.discord_daily_report_top_n,
        rendered_content="",
        payload_json={},
    )
    session.add(report)
    session.flush()

    try:
        if flags.is_enabled("cost_guardrails", session):
            rate_limits.enforce(
                session,
                operation="discord_report_run",
                limit=settings.rate_limit_discord_reports_per_window,
            )

        if not flags.is_enabled("daily_report", session):
            report.status = "skipped"
            report.error_detail = "feature_daily_report_enabled=false"
            report.rendered_content = "daily report disabled"
            report.payload_json = {"reason": "feature_daily_report_enabled=false"}
            session.commit()
            session.refresh(report)
            return report

        screening_run = run_screening(session)
        logger.info("screening_completed run_id=%s trigger_source=%s", screening_run.id, trigger_source)
        AIAnalysisService(settings=settings).analyze_top_candidates(session, screening_run.id)
        generator.populate_report_run(
            session,
            report_run=report,
            screening_run_id=screening_run.id,
            report_date=screening_run.as_of_date,
        )
        if flags.is_enabled("discord_notifications", session) and cost_control.within_overall_budget(
            session,
            settings.estimated_notification_cost_per_send_twd,
        ):
            notifier.send(session, report_run=report)
            logger.info("notification_sent report_run_id=%s status=%s", report.id, report.status)
        else:
            report.status = "skipped"
            report.error_detail = "discord_notifications_disabled_or_budget_blocked"
    except Exception as exc:  # noqa: BLE001
        logger.exception("daily_screening_and_push_failed trigger_source=%s error=%s", trigger_source, exc)
        report.status = "failed"
        report.error_detail = str(exc)
        report.rendered_content = (
            "台股短線每日推播\n"
            f"日期: {report.report_date.isoformat()}\n"
            "daily report generation failed"
        )
        report.payload_json = {
            "report_date": report.report_date.isoformat(),
            "screening_run_id": report.screening_run_id,
            "qualified_count": 0,
            "top_n": settings.discord_daily_report_top_n,
            "items": [],
            "job_error": str(exc),
        }
        rate_limits.record(
            session,
            operation="discord_report_run",
            status="failed",
            metadata={"trigger_source": trigger_source, "error": str(exc)},
        )
    else:
        rate_limits.record(
            session,
            operation="discord_report_run",
            status=report.status,
            metadata={"trigger_source": trigger_source, "qualified_count": report.qualified_count},
        )
    session.commit()
    session.refresh(report)
    return report


def get_latest_daily_report(session: Session) -> DailyReportRun | None:
    return session.scalar(
        select(DailyReportRun).order_by(desc(DailyReportRun.created_at), desc(DailyReportRun.id))
    )


def _load_delivery_logs(session: Session, report_run_id: int) -> list[DiscordDeliveryLog]:
    return session.scalars(
        select(DiscordDeliveryLog)
        .where(DiscordDeliveryLog.report_run_id == report_run_id)
        .order_by(DiscordDeliveryLog.attempt_no.asc(), DiscordDeliveryLog.created_at.asc())
    ).all()


def serialize_daily_report(session: Session, report: DailyReportRun) -> DailyReportRunRead:
    return DailyReportRunRead.model_validate(
        serialize_report_run(report, _load_delivery_logs(session, report.id))
    )
