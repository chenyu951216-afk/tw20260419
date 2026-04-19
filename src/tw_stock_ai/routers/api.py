from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from tw_stock_ai.adapters import ManualCsvPriceAdapter
from tw_stock_ai.config import get_settings
from tw_stock_ai.db import get_session
from tw_stock_ai.models import DailyReportRun, Holding, ScreeningCandidate, ScreeningRun
from tw_stock_ai.schemas import (
    CostSnapshotRead,
    DailyReportRunRead,
    EffectiveSettingsRead,
    HealthResponse,
    HoldingCreate,
    HoldingRead,
    ImportResult,
    ScreeningRunRead,
)
from tw_stock_ai.services.ai_analysis import AIAnalysisService
from tw_stock_ai.services.app_settings import build_effective_settings, get_settings_for_ui
from tw_stock_ai.services.cost_control import CostControlService
from tw_stock_ai.services.jobs import get_latest_daily_report, run_daily_screening_and_push, serialize_daily_report
from tw_stock_ai.services.portfolio import enrich_holding
from tw_stock_ai.services.position_monitor import PositionMonitorService
from tw_stock_ai.services.rate_limits import RateLimitExceededError, RateLimitService
from tw_stock_ai.services.screener import get_latest_run, run_screening

router = APIRouter(prefix="/api")


def _serialize_candidate(session: Session, candidate: ScreeningCandidate) -> dict:
    ai_service = AIAnalysisService()
    return {
        **candidate.__dict__,
        "ai_analyses": [
            item.model_dump()
            for item in ai_service.latest_for_target(
                session,
                target_type="screening_candidate",
                target_id=candidate.id,
            )
        ],
    }


def _serialize_holding(session: Session, holding: Holding) -> HoldingRead:
    result = enrich_holding(session, holding)
    session.commit()
    session.refresh(holding)
    return result


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        app_name=settings.app_name,
        env=settings.app_env,
        database_url=settings.database_url,
        scheduler_enabled=settings.enable_scheduler,
        time=datetime.now(),
    )


@router.post("/ingestion/manual/prices", response_model=ImportResult)
async def ingest_manual_prices(file: UploadFile = File(...)) -> ImportResult:
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="only_csv_supported")
    adapter = ManualCsvPriceAdapter()
    return adapter.ingest(file.file)


@router.post("/screenings/run", response_model=ScreeningRunRead)
def trigger_screening(session: Session = Depends(get_session)) -> ScreeningRunRead:
    settings = build_effective_settings(session)
    rate_limits = RateLimitService(settings)
    try:
        rate_limits.enforce(
            session,
            operation="manual_screening_run",
            limit=settings.rate_limit_screening_runs_per_window,
        )
    except RateLimitExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    run = run_screening(session)
    rate_limits.record(session, operation="manual_screening_run", status=run.status, metadata={"run_id": run.id})
    session.commit()
    candidates = session.scalars(
        select(ScreeningCandidate)
        .where(ScreeningCandidate.run_id == run.id)
        .order_by(ScreeningCandidate.rank_position.asc(), ScreeningCandidate.symbol.asc())
    ).all()
    return ScreeningRunRead.model_validate(
        {**run.__dict__, "candidates": [_serialize_candidate(session, candidate) for candidate in candidates]}
    )


@router.get("/screenings/latest", response_model=ScreeningRunRead | None)
def latest_screening(session: Session = Depends(get_session)) -> ScreeningRunRead | None:
    run, candidates = get_latest_run(session)
    if run is None:
        return None
    return ScreeningRunRead.model_validate(
        {**run.__dict__, "candidates": [_serialize_candidate(session, candidate) for candidate in candidates]}
    )


@router.get("/screenings/runs", response_model=list[ScreeningRunRead])
def list_screenings(session: Session = Depends(get_session)) -> list[ScreeningRunRead]:
    runs = session.scalars(
        select(ScreeningRun).order_by(ScreeningRun.created_at.desc()).limit(20)
    ).all()
    results: list[ScreeningRunRead] = []
    for run in runs:
        candidates = session.scalars(
            select(ScreeningCandidate)
            .where(ScreeningCandidate.run_id == run.id)
            .order_by(ScreeningCandidate.rank_position.asc(), ScreeningCandidate.symbol.asc())
        ).all()
        results.append(
            ScreeningRunRead.model_validate(
                {**run.__dict__, "candidates": [_serialize_candidate(session, candidate) for candidate in candidates]}
            )
        )
    return results


@router.post("/discord/reports/run", response_model=DailyReportRunRead)
def run_discord_report(session: Session = Depends(get_session)) -> DailyReportRunRead:
    report = run_daily_screening_and_push(session, trigger_source="manual_api")
    return serialize_daily_report(session, report)


@router.get("/discord/reports/latest", response_model=DailyReportRunRead | None)
def latest_discord_report(session: Session = Depends(get_session)) -> DailyReportRunRead | None:
    report = get_latest_daily_report(session)
    if report is None:
        return None
    return serialize_daily_report(session, report)


@router.get("/system/costs", response_model=CostSnapshotRead)
def system_costs(session: Session = Depends(get_session)) -> CostSnapshotRead:
    snapshot = CostControlService(build_effective_settings(session)).build_snapshot(session)
    return CostSnapshotRead.model_validate(snapshot)


@router.get("/settings/effective", response_model=EffectiveSettingsRead)
def effective_settings(session: Session = Depends(get_session)) -> EffectiveSettingsRead:
    return EffectiveSettingsRead.model_validate(get_settings_for_ui(session))


@router.post("/holdings", response_model=HoldingRead)
def create_holding(payload: HoldingCreate, session: Session = Depends(get_session)) -> HoldingRead:
    holding = Holding(
        symbol=payload.symbol.strip(),
        quantity=payload.quantity,
        average_cost=payload.average_cost,
        opened_date=payload.opened_date or date.today(),
        custom_stop_loss=payload.custom_stop_loss,
        custom_target_price=payload.custom_target_price,
        symbol_name=payload.symbol_name,
        note=payload.note,
    )
    session.add(holding)
    session.commit()
    session.refresh(holding)
    return _serialize_holding(session, holding)


@router.get("/holdings", response_model=list[HoldingRead])
def list_holdings(session: Session = Depends(get_session)) -> list[HoldingRead]:
    holdings = session.scalars(select(Holding).order_by(Holding.created_at.desc())).all()
    return [_serialize_holding(session, item) for item in holdings]


@router.get("/holdings/{holding_id}", response_model=HoldingRead)
def get_holding(holding_id: int, session: Session = Depends(get_session)) -> HoldingRead:
    holding = session.get(Holding, holding_id)
    if holding is None:
        raise HTTPException(status_code=404, detail="holding_not_found")
    return _serialize_holding(session, holding)


@router.post("/holdings/monitor", response_model=list[HoldingRead])
def monitor_holdings(session: Session = Depends(get_session)) -> list[HoldingRead]:
    return PositionMonitorService().monitor_all_positions(session)


@router.post("/holdings/{holding_id}/monitor", response_model=HoldingRead)
def monitor_holding(holding_id: int, session: Session = Depends(get_session)) -> HoldingRead:
    holding = session.get(Holding, holding_id)
    if holding is None:
        raise HTTPException(status_code=404, detail="holding_not_found")
    result = PositionMonitorService().monitor_position(session, holding)
    session.commit()
    return result


@router.post("/ai/screenings/{run_id}/analyze-top")
def analyze_top_candidates(run_id: int, session: Session = Depends(get_session)) -> list[dict]:
    settings = build_effective_settings(session)
    ai_service = AIAnalysisService(settings=settings)
    results = ai_service.analyze_top_candidates(session, run_id)
    return [item.model_dump() for item in results]


@router.post("/ai/holdings/{holding_id}/analyze")
def analyze_holding(holding_id: int, session: Session = Depends(get_session)) -> list[dict]:
    settings = build_effective_settings(session)
    ai_service = AIAnalysisService(settings=settings)
    results = ai_service.analyze_holding(session, holding_id)
    return [item.model_dump() for item in results]
