from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from tw_stock_ai.adapters import (
    AdapterFetchRequest,
)
from tw_stock_ai.config import get_settings
from tw_stock_ai.adapters.base import BaseDataAdapter
from tw_stock_ai.models import DataRefreshItem, DataRefreshRun
from tw_stock_ai.schemas import DataRefreshRunRead
from tw_stock_ai.services.adapter_registry import AdapterRegistry
from tw_stock_ai.services.cache import AdapterCacheService
from tw_stock_ai.services.data_store import DataStoreService
from tw_stock_ai.services.feature_flags import FeatureFlagService
from tw_stock_ai.services.logging_config import get_logger
from tw_stock_ai.services.serialization import to_jsonable
from tw_stock_ai.services.usage_tracking import UsageTracker

logger = get_logger("tw_stock_ai.data_refresh")


class DataRefreshCoordinator:
    def __init__(
        self,
        adapters: dict[str, BaseDataAdapter] | None = None,
        registry: AdapterRegistry | None = None,
        *,
        cache_service: AdapterCacheService | None = None,
        data_store: DataStoreService | None = None,
    ) -> None:
        self.settings = get_settings()
        self.registry = registry or AdapterRegistry()
        if adapters:
            self.registry.register_many(adapters)
        self.adapters = self.registry.as_dict()
        self.cache_service = cache_service or AdapterCacheService()
        self.data_store = data_store or DataStoreService()
        self.flags = FeatureFlagService(self.settings)
        self.usage_tracker = UsageTracker()

    def refresh_all(
        self,
        session: Session,
        requests: dict[str, AdapterFetchRequest] | None = None,
        *,
        trigger_source: str = "manual",
    ) -> DataRefreshRunRead:
        requests = requests or {}
        started_at = datetime.now(timezone.utc)
        run = DataRefreshRun(
            trigger_source=trigger_source,
            status="running",
            started_at=started_at,
            summary={},
        )
        session.add(run)
        session.flush()
        logger.info("data_refresh_started run_id=%s trigger_source=%s", run.id, trigger_source)

        items: list[DataRefreshItem] = []
        overall_status = "completed"
        summary: dict[str, dict] = {}

        for dataset, adapter in self.adapters.items():
            request = requests.get(dataset, AdapterFetchRequest())
            item, item_summary = self._refresh_dataset(
                session=session,
                run_id=run.id,
                adapter=adapter,
                request=request,
            )
            items.append(item)
            summary[dataset] = item_summary
            if item.status in {"failed", "unavailable"} and overall_status != "failed":
                overall_status = item.status

        run.status = overall_status
        run.completed_at = datetime.now(timezone.utc)
        run.summary = summary
        session.add_all(items)
        session.commit()
        session.refresh(run)
        logger.info("data_refresh_completed run_id=%s status=%s", run.id, run.status)
        return DataRefreshRunRead.model_validate({**run.__dict__, "items": items})

    def _refresh_dataset(
        self,
        *,
        session: Session,
        run_id: int,
        adapter: BaseDataAdapter,
        request: AdapterFetchRequest,
    ) -> tuple[DataRefreshItem, dict]:
        cache_key = request.cache_key()
        cached_entry = None if request.force_refresh else self.cache_service.get(
            session,
            adapter_name=adapter.adapter_name,
            cache_key=cache_key,
        )
        if cached_entry is not None:
            result = self.cache_service.to_result(cached_entry)
        else:
            if adapter.dataset == "news" and not self.flags.is_enabled("news_fetch", session):
                result = adapter.unavailable_result(
                    "news_fetch_feature_disabled",
                    request=request,
                    detail="feature_news_fetch_enabled=false",
                )
            else:
                try:
                    result = adapter.fetch(request)
                except Exception as exc:  # noqa: BLE001
                    result = adapter.unavailable_result(
                        "adapter_execution_failed",
                        request=request,
                        detail=str(exc),
                    )
                    result.errors.append(str(exc))
                    result.status = "failed"
            self.usage_tracker.record(
                session,
                event_type="external_api_call",
                operation=f"refresh:{adapter.dataset}",
                provider=adapter.adapter_name,
                status=result.status,
                estimated_cost_twd=self.settings.estimated_external_api_cost_per_call_twd,
                metadata={"symbols": request.symbols, "from_cache": False},
            )
            expires_at = adapter.cache_expiry(request)
            self.cache_service.set(
                session,
                adapter_name=adapter.adapter_name,
                dataset=adapter.dataset,
                cache_key=cache_key,
                result=result,
                expires_at=expires_at,
            )

        raw_stored = 0
        cleaned_stored = 0
        if not result.from_cache:
            raw_stored = self.data_store.persist_raw(session, result)
            cleaned_stored = self.data_store.persist_cleaned(session, result)
        item = DataRefreshItem(
            run_id=run_id,
            dataset=adapter.dataset,
            adapter_name=adapter.adapter_name,
            status=result.status,
            records_received=result.records_received,
            records_cleaned=result.records_cleaned,
            records_stored=cleaned_stored,
            from_cache=result.from_cache,
            detail=result.detail,
            fetched_at=result.fetched_at,
            metadata_json=to_jsonable(
                {
                "raw_records_stored": raw_stored,
                "errors": result.errors,
                "unavailable_reason": result.unavailable_reason,
                **result.metadata,
                }
            ),
        )
        session.flush()
        return item, {
            "status": item.status,
            "records_received": item.records_received,
            "records_cleaned": item.records_cleaned,
            "records_stored": item.records_stored,
            "from_cache": item.from_cache,
            "detail": item.detail,
        }
