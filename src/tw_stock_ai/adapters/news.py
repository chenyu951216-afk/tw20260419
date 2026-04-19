from __future__ import annotations

from datetime import datetime, timezone

from tw_stock_ai.adapters.base import AdapterFetchRequest, AdapterFetchResult, NewsDataAdapter
from tw_stock_ai.adapters.http_utils import http_get_csv_rows, roc_datetime_to_utc
from tw_stock_ai.adapters.unavailable import UnavailableNewsAdapter
from tw_stock_ai.config import Settings, get_settings


class MopsListedCompanyNewsAdapter(NewsDataAdapter):
    adapter_name = "mops_listed_company_news"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def fetch(self, request: AdapterFetchRequest) -> AdapterFetchResult:
        fetched_at = datetime.now(timezone.utc)
        rows, fieldnames = http_get_csv_rows(
            self.settings.mops_listed_daily_info_url,
            timeout=self.settings.mops_timeout_seconds,
        )
        raw_items: list[dict] = []
        cleaned_items: list[dict] = []
        symbol_filter = set(request.symbols)

        for row in rows:
            symbol = str(row.get("公司代號", "")).strip()
            if symbol_filter and symbol not in symbol_filter:
                continue
            published_at = roc_datetime_to_utc(row.get("發言日期"), row.get("發言時間"))
            if published_at is None:
                continue
            if request.start_date and published_at.date() < request.start_date:
                continue
            if request.end_date and published_at.date() > request.end_date:
                continue
            title = str(row.get("主旨", "")).strip()
            if not title:
                continue

            raw_items.append(
                {
                    "record_key": f"{symbol}:{row.get('發言日期')}:{row.get('發言時間')}",
                    "source_url": self.settings.mops_listed_daily_info_url,
                    "symbol": symbol,
                    "payload": row,
                }
            )
            cleaned_items.append(
                {
                    "symbol": symbol or None,
                    "title": title,
                    "source_name": self.adapter_name,
                    "source_url": self.settings.mops_listed_daily_info_url,
                    "published_at": published_at,
                    "raw_payload": {
                        "provider": "mops",
                        "fieldnames": fieldnames,
                        **row,
                    },
                }
            )
            if request.limit and len(cleaned_items) >= request.limit:
                break

        return AdapterFetchResult(
            adapter_name=self.adapter_name,
            dataset=self.dataset,
            status="ready",
            fetched_at=fetched_at,
            raw_items=raw_items,
            cleaned_items=cleaned_items,
            detail=None if cleaned_items else "no_news_rows_loaded",
            metadata={"provider": "mops", "scope": "listed_companies"},
        )

__all__ = ["NewsDataAdapter", "MopsListedCompanyNewsAdapter", "UnavailableNewsAdapter"]
