from __future__ import annotations

from datetime import date, datetime, timezone

from tw_stock_ai.adapters.base import AdapterFetchRequest, AdapterFetchResult, FundamentalsDataAdapter
from tw_stock_ai.adapters.http_utils import http_get_csv_rows, parse_float, roc_date_to_date
from tw_stock_ai.adapters.unavailable import UnavailableFundamentalsAdapter
from tw_stock_ai.config import Settings, get_settings


class TwseMopsListedFundamentalsAdapter(FundamentalsDataAdapter):
    adapter_name = "twse_mops_listed_fundamentals"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def fetch(self, request: AdapterFetchRequest) -> AdapterFetchResult:
        fetched_at = datetime.now(timezone.utc)
        symbol_filter = set(request.symbols)
        raw_items: list[dict] = []
        cleaned_items: list[dict] = []

        profile_rows, _ = http_get_csv_rows(
            self.settings.mops_listed_company_profile_url,
            timeout=self.settings.mops_timeout_seconds,
        )
        valuation_rows, _ = http_get_csv_rows(
            self.settings.twse_valuation_url,
            timeout=self.settings.mops_timeout_seconds,
        )
        eps_rows, _ = http_get_csv_rows(
            self.settings.mops_listed_eps_url,
            timeout=self.settings.mops_timeout_seconds,
        )
        income_rows, _ = http_get_csv_rows(
            self.settings.mops_listed_income_statement_url,
            timeout=self.settings.mops_timeout_seconds,
        )
        balance_rows, _ = http_get_csv_rows(
            self.settings.mops_listed_balance_sheet_url,
            timeout=self.settings.mops_timeout_seconds,
        )

        profiles_by_symbol: dict[str, dict] = {}
        for row in profile_rows:
            symbol = str(row.get("公司代號", "")).strip()
            if not symbol or (symbol_filter and symbol not in symbol_filter):
                continue
            profiles_by_symbol[symbol] = row

        valuation_by_symbol: dict[str, dict] = {}
        for row in valuation_rows:
            symbol = str(row.get("股票代號", "")).strip()
            if not symbol or (symbol_filter and symbol not in symbol_filter):
                continue
            valuation_by_symbol[symbol] = row

        latest_eps_by_symbol = self._latest_rows(eps_rows, symbol_filter=symbol_filter)
        latest_income_by_symbol = self._latest_rows(income_rows, symbol_filter=symbol_filter)
        latest_balance_by_symbol = self._latest_rows(balance_rows, symbol_filter=symbol_filter)

        all_symbols = sorted(
            set(profiles_by_symbol)
            | set(valuation_by_symbol)
            | set(latest_eps_by_symbol)
            | set(latest_income_by_symbol)
            | set(latest_balance_by_symbol)
        )

        for symbol in all_symbols:
            profile = profiles_by_symbol.get(symbol, {})
            valuation = valuation_by_symbol.get(symbol, {})
            eps_row = latest_eps_by_symbol.get(symbol, {})
            income = latest_income_by_symbol.get(symbol, {})
            balance = latest_balance_by_symbol.get(symbol, {})
            snapshot_date = self._resolve_snapshot_date(
                valuation.get("日期"),
                profile.get("出表日期"),
                eps_row.get("出表日期"),
                income.get("出表日期"),
                balance.get("出表日期"),
            ) or date.today()

            if profile:
                raw_items.append(
                    {
                        "record_key": f"profile:{symbol}",
                        "source_url": self.settings.mops_listed_company_profile_url,
                        "symbol": symbol,
                        "payload": profile,
                    }
                )
                cleaned_items.append(
                    {
                        "statement_kind": "security_profile",
                        "symbol": symbol,
                        "snapshot_date": snapshot_date,
                        "symbol_name": profile.get("公司簡稱") or profile.get("公司名稱"),
                        "company_name": profile.get("公司名稱"),
                        "industry": profile.get("產業別"),
                        "market": "TWSE",
                        "source_name": self.adapter_name,
                        "source_url": self.settings.mops_listed_company_profile_url,
                        "raw_payload": {"provider": "mops", **profile},
                    }
                )

            pe_ratio = parse_float(valuation.get("本益比"))
            pb_ratio = parse_float(valuation.get("股價淨值比"))
            dividend_yield = parse_float(valuation.get("殖利率(%)"))
            eps_value = parse_float(eps_row.get("基本每股盈餘(元)")) or parse_float(income.get("基本每股盈餘（元）"))
            revenue = parse_float(income.get("營業收入"))
            gross_profit = parse_float(income.get("營業毛利（毛損）淨額")) or parse_float(income.get("營業毛利（毛損）"))
            operating_income = parse_float(income.get("營業利益（損失）"))
            net_income = parse_float(income.get("本期淨利（淨損）")) or parse_float(income.get("稅後淨利"))
            debt_ratio = self._calculate_debt_ratio(balance)
            gross_margin = (gross_profit / revenue * 100.0) if gross_profit is not None and revenue not in (None, 0.0) else None
            operating_margin = (
                operating_income / revenue * 100.0
                if operating_income is not None and revenue not in (None, 0.0)
                else None
            )
            roe = self._calculate_roe(net_income, balance, pe_ratio=pe_ratio, pb_ratio=pb_ratio)

            raw_items.append(
                {
                    "record_key": f"fundamentals:{symbol}:{snapshot_date.isoformat()}",
                    "source_url": self.settings.twse_valuation_url,
                    "symbol": symbol,
                    "payload": {
                        "valuation": valuation,
                        "eps": eps_row,
                        "income": income,
                        "balance": balance,
                    },
                }
            )
            cleaned_items.append(
                {
                    "statement_kind": "fundamentals",
                    "symbol": symbol,
                    "snapshot_date": snapshot_date,
                    "source_name": self.adapter_name,
                    "source_url": self.settings.twse_valuation_url,
                    "eps": eps_value,
                    "roe": roe,
                    "gross_margin": gross_margin,
                    "operating_margin": operating_margin,
                    "free_cash_flow": None,
                    "debt_ratio": debt_ratio,
                    "pe_ratio": pe_ratio,
                    "pb_ratio": pb_ratio,
                    "dividend_yield": dividend_yield,
                    "raw_payload": {
                        "provider": "twse_mops",
                        "derived": {
                            "debt_ratio_formula": "total_liabilities / total_assets * 100" if debt_ratio is not None else None,
                            "gross_margin_formula": "gross_profit / revenue * 100" if gross_margin is not None else None,
                            "operating_margin_formula": (
                                "operating_income / revenue * 100" if operating_margin is not None else None
                            ),
                            "roe_formula": (
                                "net_income / total_equity * 100"
                                if net_income is not None and balance.get("權益總計")
                                else "pb_ratio / pe_ratio * 100"
                                if roe is not None and pe_ratio not in (None, 0.0) and pb_ratio is not None
                                else None
                            ),
                        },
                        "valuation": valuation,
                        "eps": eps_row,
                        "income": income,
                        "balance": balance,
                    },
                }
            )
            if income or eps_row:
                cleaned_items.append(
                    {
                        "statement_kind": "financial_statement",
                        "symbol": symbol,
                        "statement_date": snapshot_date,
                        "period_type": "quarterly",
                        "revenue": revenue,
                        "gross_profit": gross_profit,
                        "operating_income": operating_income,
                        "net_income": net_income,
                        "eps": eps_value,
                        "source_name": self.adapter_name,
                        "source_url": self.settings.mops_listed_income_statement_url,
                        "raw_payload": {"provider": "mops", "income": income, "eps": eps_row},
                    }
                )

        return AdapterFetchResult(
            adapter_name=self.adapter_name,
            dataset=self.dataset,
            status="ready",
            fetched_at=fetched_at,
            raw_items=raw_items,
            cleaned_items=cleaned_items,
            detail=None if cleaned_items else "no_fundamental_rows_loaded",
            metadata={"provider": "twse_mops", "scope": "listed_companies"},
        )

    @staticmethod
    def _latest_rows(rows: list[dict[str, str]], *, symbol_filter: set[str]) -> dict[str, dict]:
        latest: dict[str, dict] = {}
        for row in rows:
            symbol = str(row.get("公司代號", "")).strip()
            if not symbol or (symbol_filter and symbol not in symbol_filter):
                continue
            current_date = roc_date_to_date(row.get("出表日期"))
            previous_date = roc_date_to_date(latest.get(symbol, {}).get("出表日期"))
            if previous_date is None or (current_date is not None and current_date >= previous_date):
                latest[symbol] = row
        return latest

    @staticmethod
    def _resolve_snapshot_date(*values: str | None) -> date | None:
        for value in values:
            parsed = roc_date_to_date(value)
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _calculate_debt_ratio(balance_row: dict[str, str]) -> float | None:
        total_assets = parse_float(balance_row.get("資產總計"))
        total_liabilities = parse_float(balance_row.get("負債總計"))
        if total_assets in (None, 0.0) or total_liabilities is None:
            return None
        return total_liabilities / total_assets * 100.0

    @staticmethod
    def _calculate_roe(
        net_income: float | None,
        balance_row: dict[str, str],
        *,
        pe_ratio: float | None,
        pb_ratio: float | None,
    ) -> float | None:
        total_equity = parse_float(balance_row.get("權益總計"))
        if net_income is not None and total_equity not in (None, 0.0):
            return net_income / total_equity * 100.0
        if pe_ratio not in (None, 0.0) and pb_ratio is not None:
            return pb_ratio / pe_ratio * 100.0
        return None


__all__ = ["FundamentalsDataAdapter", "TwseMopsListedFundamentalsAdapter", "UnavailableFundamentalsAdapter"]
