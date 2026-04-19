from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from tw_stock_ai.config import get_settings
from tw_stock_ai.models import Base

settings = get_settings()


def _sqlite_connect_args(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def ensure_runtime_dirs() -> None:
    Path("data").mkdir(parents=True, exist_ok=True)
    Path("data/logs").mkdir(parents=True, exist_ok=True)


ensure_runtime_dirs()

engine = create_engine(
    settings.database_url,
    future=True,
    pool_pre_ping=True,
    connect_args=_sqlite_connect_args(settings.database_url),
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_compat_columns()


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def _ensure_sqlite_compat_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    expected_columns = {
        "fundamental_snapshots": {
            "revenue_mom": "FLOAT",
            "eps": "FLOAT",
            "roe": "FLOAT",
            "free_cash_flow": "FLOAT",
            "pe_ratio": "FLOAT",
            "pb_ratio": "FLOAT",
            "dividend_yield": "FLOAT",
        },
        "screening_candidates": {
            "rank_position": "INTEGER",
            "symbol_name": "VARCHAR(120)",
            "take_profit_1": "FLOAT",
            "take_profit_2": "FLOAT",
            "holding_days_min": "INTEGER",
            "holding_days_max": "INTEGER",
            "risk_flags": "JSON DEFAULT '{}'",
            "value_score": "FLOAT",
            "growth_score": "FLOAT",
            "quality_score": "FLOAT",
            "valuation_score": "FLOAT",
            "catalyst_score": "FLOAT",
            "value_summary": "TEXT",
            "value_risks": "JSON DEFAULT '{}'",
        },
        "holdings": {
            "opened_date": "DATE",
            "custom_stop_loss": "FLOAT",
            "custom_target_price": "FLOAT",
            "symbol_name": "VARCHAR(120)",
            "current_trend": "VARCHAR(30)",
            "alert_status": "VARCHAR(30)",
            "last_action": "VARCHAR(30)",
            "last_confidence": "FLOAT",
            "last_monitor_reasons": "JSON DEFAULT '{}'",
            "last_monitor_evidence": "JSON DEFAULT '{}'",
            "last_monitored_at": "DATETIME",
        },
        "ai_analysis_records": {
            "cache_key": "VARCHAR(255)",
        },
    }

    inspector = inspect(engine)
    with engine.begin() as connection:
        for table_name, columns in expected_columns.items():
            if table_name not in inspector.get_table_names():
                continue
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, column_type in columns.items():
                if column_name in existing:
                    continue
                connection.execute(
                    text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
                )


init_db()
