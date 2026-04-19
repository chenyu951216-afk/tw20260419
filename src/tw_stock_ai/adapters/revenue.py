from __future__ import annotations

from datetime import datetime, timezone

from tw_stock_ai.adapters.base import AdapterFetchRequest, AdapterFetchResult, RevenueDataAdapter
from tw_stock_ai.adapters.http_utils import http_get_csv_rows, parse_float, roc_year_month_to_date
from tw_stock_ai.adapters.unavailable import UnavailableRevenueAdapter
from tw_stock_ai.config import Settings, get_settings


class MopsListedRevenueAdapter(RevenueDataAdapter):
    adapter_name = "mops_listed_revenue"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def fetch(self, request: AdapterFetchRequest) -> AdapterFetchResult:
        fetched_at = datetime.now(timezone.utc)
        rows, fieldnames = http_get_csv_rows(
            self.settings.mops_listed_monthly_revenue_url,
            timeout=self.settings.mops_timeout_seconds,
        )
        raw_items: list[dict] = []
        cleaned_items: list[dict] = []
        symbol_filter = set(request.symbols)

        for row in rows:
            symbol = str(row.get("公司代號", "")).strip()
            if not symbol or (symbol_filter and symbol not in symbol_filter):
                continue
            revenue_month = roc_year_month_to_date(row.get("資料年月"))
            if revenue_month is None:
                continue
            raw_items.append(
                {
                    "record_key": f"{symbol}:{revenue_month.isoformat()}",
                    "source_url": self.settings.mops_listed_monthly_revenue_url,
                    "symbol": symbol,
                    "payload": row,
                }
            )
            cleaned_items.append(
                {
                    "symbol": symbol,
                    "revenue_month": revenue_month,
                    "monthly_revenue": parse_float(row.get("營業收入-當月營收")),
                    "revenue_mom": parse_float(row.get("營業收入-上月比較增減(%)")),
                    "revenue_yoy": parse_float(row.get("營業收入-去年同月增減(%)")),
                    "source_name": self.adapter_name,
                    "source_url": self.settings.mops_listed_monthly_revenue_url,
                    "raw_payload": {
                        "provider": "mops",
                        "fieldnames": fieldnames,
                        **row,
                    },
                }
            )

        return AdapterFetchResult(
            adapter_name=self.adapter_name,
            dataset=self.dataset,
            status="ready",
            fetched_at=fetched_at,
            raw_items=raw_items,
            cleaned_items=cleaned_items,
            detail=None if cleaned_items else "no_revenue_rows_loaded",
            metadata={"provider": "mops", "scope": "listed_companies"},
        )

__all__ = ["RevenueDataAdapter", "MopsListedRevenueAdapter", "UnavailableRevenueAdapter"]
