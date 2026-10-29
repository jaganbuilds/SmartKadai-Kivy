"""
SmartKadai AI Sales Forecasting - Safe Data Preparation and Validation Module.

Key Principles and Safety Guarantees:
1. Strict Read-Only SQLite Access: Connects exclusively in read-only mode (mode=ro, PRAGMA query_only = ON)
   to ensure the live database is never mutated, locked, or modified.
2. Four-Category Historical Date Classification:
   - Category 1 (Confirmed Trading Day): At least one recorded transaction for the store.
   - Category 2 (Confirmed Closed Day): Explicitly recorded shop closure/holiday.
   - Category 3 (Unknown Internal Gap): Unrecorded calendar dates between min_date and max_date.
   - Category 4 (Elapsed Unobserved Date): Calendar dates after max_date (up to current system date).
3. Active-Trading-Day Primary Baseline: Demand estimation defaults to confirmed active trading days,
   preventing artificial demand dilution when store closure status is unknown.
4. No Synthetic Post-Data Zeroes: Dates after the last observed transaction are NEVER filled with 0s.
5. Legitimate Zero-Demand Tracking: On a confirmed trading day, catalog products with 0 sales are
   preserved as legitimate zero demand (units_sold = 0, is_zero_filled = False).
6. Separation of Units and Revenue: Units sold and revenue (calculated from actual transaction selling prices)
   are maintained as distinct, non-fungible metrics.
7. Data Sufficiency Tiering: Evaluates sample volume against honest retail thresholds (Tier 0 to Tier 4).
"""

from dataclasses import dataclass, asdict
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set
import collections
import csv
import sqlite3


class DateCategory:
    """Four-category date classification for retail sales time series."""
    CONFIRMED_TRADING_DAY = "confirmed_trading_day"
    CONFIRMED_CLOSED_DAY = "confirmed_closed_day"
    UNKNOWN_INTERNAL_GAP = "unknown_internal_gap"
    ELAPSED_UNOBSERVED_DATE = "elapsed_unobserved_date"


@dataclass
class DailyProductSale:
    """Represents daily aggregated sales for a specific product and date."""
    date: str
    product_id: str
    product_name: str
    units_sold: int
    revenue: float
    transaction_count: int
    is_zero_filled: bool = False
    is_synthetic: bool = False
    date_category: str = DateCategory.CONFIRMED_TRADING_DAY

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SalesDataPreparation:
    """
    Data preparation, validation, and time-series aggregation pipeline for SmartKadai.
    """

    def __init__(
        self,
        db_path: Path,
        zero_fill_missing_dates: bool = False,
        zero_fill_internal_gaps: Optional[bool] = None,
        confirmed_closed_dates: Optional[List[str]] = None,
        rapid_tx_threshold_seconds: int = 300,
        as_of_date: Optional[str] = None
    ):
        """
        Initialize the data preparation pipeline.

        Args:
            db_path: Path to the SQLite database (e.g. smartkadai.db).
            zero_fill_missing_dates: Legacy parameter alias. If True and zero_fill_internal_gaps is None,
                                     internal gap dates between min and max date will be zero-filled.
            zero_fill_internal_gaps: Configurable setting. If True, unknown internal gap dates
                                     between min_date and max_date are populated with 0 with an audit warning.
                                     Defaults to False (active trading days basis).
            confirmed_closed_dates: Optional list of YYYY-MM-DD strings representing confirmed store closures.
            rapid_tx_threshold_seconds: Time window (seconds) to flag rapid successive purchases.
            as_of_date: Optional reference date (YYYY-MM-DD) representing the system/observation date.
                        If provided, post-data elapsed days between max_date and as_of_date are audited.
        """
        self.db_path = Path(db_path)
        
        # Determine internal gap policy: prefer explicit parameter, fall back to legacy alias
        if zero_fill_internal_gaps is not None:
            self.zero_fill_internal_gaps = bool(zero_fill_internal_gaps)
        else:
            self.zero_fill_internal_gaps = bool(zero_fill_missing_dates)

        self.zero_fill_missing_dates = self.zero_fill_internal_gaps  # Backwards compatibility

        self.confirmed_closed_dates: Set[str] = set(confirmed_closed_dates or [])
        self.rapid_tx_threshold_seconds = rapid_tx_threshold_seconds
        self.as_of_date = as_of_date

    def load_raw_data(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Connect to SQLite in strict read-only mode and retrieve products and sales.

        Guarantees:
        - Uses URI mode=ro and PRAGMA query_only = ON to prevent any write operations.
        - Foreign keys enforced.
        - Connection and cursor are closed cleanly in finally block.

        Returns:
            Tuple of (products_list, sales_list) as standard dictionaries.
        """
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database file not found at: {self.db_path}")

        resolved_path = self.db_path.resolve().as_posix()
        uri = f"file:{resolved_path}?mode=ro"

        conn = sqlite3.connect(uri, uri=True)
        try:
            conn.execute("PRAGMA query_only = ON")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            products_rows = cursor.execute("""
                SELECT product_id, product_name, selling_price, current_stock,
                       supplier_lead_days, safety_stock
                FROM products
                ORDER BY product_id ASC
            """).fetchall()

            sales_rows = cursor.execute("""
                SELECT sale_id, bill_id, timestamp, date, product_id,
                       quantity_sold, selling_price
                FROM sales
                ORDER BY date ASC, sale_id ASC
            """).fetchall()

            products = [dict(r) for r in products_rows]
            sales = [dict(r) for r in sales_rows]
            return products, sales
        finally:
            conn.close()

    def validate_records(
        self,
        products: List[Dict[str, Any]],
        sales: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Validate data integrity, date formats, quantities, prices, missing fields,
        and rapid duplicate-looking transactions.

        No records are deleted or modified. Valid and invalid records are partitioned.
        """
        valid_product_ids = {p["product_id"]: p["product_name"] for p in products}

        valid_sales = []
        invalid_sales = []

        date_format_errors = []
        referential_integrity_errors = []
        quantity_errors = []
        price_errors = []
        missing_bill_ids = []
        missing_timestamps = []
        timestamp_format_counts = collections.defaultdict(int)
        rapid_transactions = []

        product_tx_history = collections.defaultdict(list)

        for sale in sales:
            sale_id = sale.get("sale_id")
            s_date = str(sale.get("date") or "").strip()
            s_pid = str(sale.get("product_id") or "").strip()
            s_qty = sale.get("quantity_sold")
            s_price = sale.get("selling_price")
            s_bill = sale.get("bill_id")
            s_ts = sale.get("timestamp")

            is_valid = True
            reasons = []

            # 1. Date Format Validation (Strict YYYY-MM-DD)
            parsed_date = None
            try:
                parsed_date = datetime.strptime(s_date, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                date_format_errors.append({
                    "sale_id": sale_id,
                    "invalid_date": s_date
                })
                is_valid = False
                reasons.append(f"Invalid date format: '{s_date}'")

            # 2. Product ID Referential Integrity
            if s_pid not in valid_product_ids:
                referential_integrity_errors.append({
                    "sale_id": sale_id,
                    "invalid_product_id": s_pid
                })
                is_valid = False
                reasons.append(f"Product ID '{s_pid}' not in catalog")

            # 3. Quantity Validation (must be positive integer)
            if not isinstance(s_qty, int) or s_qty <= 0:
                quantity_errors.append({
                    "sale_id": sale_id,
                    "invalid_quantity": s_qty
                })
                is_valid = False
                reasons.append(f"Invalid quantity: {s_qty}")

            # 4. Price Validation (must be non-negative)
            if not isinstance(s_price, (int, float)) or s_price < 0:
                price_errors.append({
                    "sale_id": sale_id,
                    "invalid_price": s_price
                })
                is_valid = False
                reasons.append(f"Invalid price: {s_price}")

            # 5. Missing Bill ID Tracking (informational, not fatal to daily sales)
            if s_bill is None or str(s_bill).strip() == "":
                missing_bill_ids.append(sale_id)

            # 6. Missing Timestamp Tracking (informational, daily aggregation relies on date)
            parsed_dt = None
            if s_ts is None or str(s_ts).strip() == "":
                missing_timestamps.append(sale_id)
                timestamp_format_counts["Missing / NULL"] += 1
            else:
                s_ts_clean = str(s_ts).strip()
                for fmt, name in [
                    ("%Y-%m-%dT%H:%M:%S", "ISO 8601 (T-separator)"),
                    ("%Y-%m-%d %H:%M:%S", "SQL Datetime (space-separator)"),
                    ("%Y-%m-%dT%H:%M:%S.%f", "ISO 8601 with microseconds"),
                    ("%Y-%m-%d %H:%M:%S.%f", "SQL Datetime with microseconds")
                ]:
                    try:
                        parsed_dt = datetime.strptime(s_ts_clean, fmt)
                        timestamp_format_counts[name] += 1
                        break
                    except ValueError:
                        continue
                if parsed_dt is None:
                    timestamp_format_counts["Unparseable Custom"] += 1

            # 7. Rapid Successive Purchases Check (same product, same date)
            if parsed_date:
                product_tx_history[s_pid].append({
                    "sale_id": sale_id,
                    "date": parsed_date,
                    "datetime": parsed_dt,
                    "quantity": s_qty,
                    "bill_id": s_bill
                })

            if is_valid:
                valid_sales.append(sale)
            else:
                invalid_sales.append({
                    "sale": sale,
                    "reasons": reasons
                })

        # Check for rapid successive transactions
        for pid, tx_list in product_tx_history.items():
            tx_list_sorted = sorted(tx_list, key=lambda x: x["sale_id"])
            for i in range(len(tx_list_sorted) - 1):
                cur = tx_list_sorted[i]
                nxt = tx_list_sorted[i + 1]

                if cur["date"] == nxt["date"]:
                    is_rapid = False
                    delta_desc = ""
                    if cur["datetime"] and nxt["datetime"]:
                        delta_sec = abs((nxt["datetime"] - cur["datetime"]).total_seconds())
                        if delta_sec <= self.rapid_tx_threshold_seconds:
                            is_rapid = True
                            delta_desc = f"{int(delta_sec)} seconds apart"
                    else:
                        if abs(nxt["sale_id"] - cur["sale_id"]) == 1:
                            is_rapid = True
                            delta_desc = "Consecutive sale_ids on same date (timestamp missing)"

                    if is_rapid:
                        rapid_transactions.append({
                            "product_id": pid,
                            "product_name": valid_product_ids.get(pid, "Unknown"),
                            "date": str(cur["date"]),
                            "sale_id_1": cur["sale_id"],
                            "sale_id_2": nxt["sale_id"],
                            "qty_1": cur["quantity"],
                            "qty_2": nxt["quantity"],
                            "timing_note": delta_desc
                        })

        return {
            "total_sales_checked": len(sales),
            "valid_sales_count": len(valid_sales),
            "invalid_sales_count": len(invalid_sales),
            "valid_sales": valid_sales,
            "invalid_sales": invalid_sales,
            "total_products_checked": len(products),
            "date_format_errors": date_format_errors,
            "referential_integrity_errors": referential_integrity_errors,
            "quantity_errors": quantity_errors,
            "price_errors": price_errors,
            "missing_bill_ids": missing_bill_ids,
            "missing_timestamps": missing_timestamps,
            "timestamp_format_counts": dict(timestamp_format_counts),
            "rapid_transactions": rapid_transactions,
            "has_critical_errors": bool(date_format_errors or referential_integrity_errors or quantity_errors or price_errors)
        }

    def generate_continuous_date_range(self, start_date: date, end_date: date) -> List[date]:
        """Generate an uninterrupted daily calendar sequence [start_date, end_date]."""
        if start_date > end_date:
            return []
        days_count = (end_date - start_date).days + 1
        return [start_date + timedelta(days=i) for i in range(days_count)]

    def classify_historical_dates(
        self,
        min_date: date,
        max_date: date,
        active_dates: Set[date],
        as_of_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """
        Classify all calendar dates into the 4 Step-2 categories:
        1. Confirmed trading days
        2. Confirmed closed days
        3. Unknown internal gaps
        4. Elapsed unobserved dates (post-data)
        """
        calendar_span = self.generate_continuous_date_range(min_date, max_date)
        
        confirmed_trading = []
        confirmed_closed = []
        unknown_internal = []
        elapsed_unobserved = []

        for d in calendar_span:
            d_str = d.strftime("%Y-%m-%d")
            if d in active_dates:
                confirmed_trading.append(d_str)
            elif d_str in self.confirmed_closed_dates:
                confirmed_closed.append(d_str)
            else:
                unknown_internal.append(d_str)

        # Elapsed dates after max_date up to as_of_date
        if as_of_date and as_of_date > max_date:
            elapsed_span = self.generate_continuous_date_range(max_date + timedelta(days=1), as_of_date)
            for d in elapsed_span:
                elapsed_unobserved.append(d.strftime("%Y-%m-%d"))

        return {
            "confirmed_trading_days": confirmed_trading,
            "confirmed_closed_days": confirmed_closed,
            "unknown_internal_gaps": unknown_internal,
            "elapsed_unobserved_dates": elapsed_unobserved,
            "total_calendar_days_in_history": len(calendar_span),
            "active_trading_days_count": len(confirmed_trading),
            "internal_gap_count": len(unknown_internal),
            "confirmed_closed_count": len(confirmed_closed),
            "elapsed_unobserved_count": len(elapsed_unobserved)
        }

    def aggregate_daily_sales(
        self,
        products: List[Dict[str, Any]],
        sales: List[Dict[str, Any]]
    ) -> Tuple[List[DailyProductSale], Dict[str, Any]]:
        """
        Aggregate sales by product and date adhering to the 4-category date policy.

        Rules:
        - Quantity sold is aggregated by date and product.
        - Revenue is computed from recorded transaction selling prices * quantities.
        - Revenue and units sold are kept strictly separate.
        - Active trading days are the primary forecasting foundation.
        - On confirmed trading days, catalog products with 0 sales have units_sold=0, is_zero_filled=False.
        - Internal gap days are only included if zero_fill_internal_gaps=True, with an explicit audit warning.
        - Elapsed unobserved dates (post-data) are NEVER filled with synthetic zeroes.

        Returns:
            Tuple of (aggregated_daily_sales, date_range_metadata).
        """
        product_map = {p["product_id"]: p["product_name"] for p in products}

        # Filter valid sales records
        valid_sales = []
        valid_dates = []
        for s in sales:
            try:
                d = datetime.strptime(str(s["date"]).strip(), "%Y-%m-%d").date()
                pid = str(s.get("product_id", "")).strip()
                qty = s.get("quantity_sold")
                sp = s.get("selling_price")

                if pid in product_map and isinstance(qty, int) and qty > 0 and isinstance(sp, (int, float)) and sp >= 0:
                    valid_sales.append((d, s))
                    valid_dates.append(d)
            except (ValueError, TypeError):
                continue

        if not valid_dates:
            return [], {
                "min_date": None,
                "max_date": None,
                "as_of_date": self.as_of_date,
                "total_calendar_days": 0,
                "active_sales_days": 0,
                "missing_calendar_days": 0,
                "internal_gap_days": 0,
                "confirmed_closed_days": 0,
                "elapsed_unobserved_days": 0,
                "aggregation_mode": "empty",
                "zero_fill_applied": self.zero_fill_internal_gaps,
                "data_sufficiency_tier": "Tier 0 — No Historical Data",
                "audit_warnings": ["No valid sales records found in database."]
            }

        min_date = min(valid_dates)
        max_date = max(valid_dates)
        active_dates_set = set(valid_dates)

        # Parse as_of_date if supplied
        parsed_as_of = None
        if self.as_of_date:
            try:
                parsed_as_of = datetime.strptime(self.as_of_date, "%Y-%m-%d").date()
            except ValueError:
                parsed_as_of = None

        classification = self.classify_historical_dates(min_date, max_date, active_dates_set, parsed_as_of)

        # Group sales by (date, product_id)
        grouped_sales = collections.defaultdict(lambda: {"units": 0, "revenue": 0.0, "tx_count": 0})
        for d, s in valid_sales:
            pid = s["product_id"]
            qty = int(s["quantity_sold"])
            price = float(s["selling_price"])
            key = (d, pid)
            grouped_sales[key]["units"] += qty
            grouped_sales[key]["revenue"] += (qty * price)
            grouped_sales[key]["tx_count"] += 1

        aggregated_records: List[DailyProductSale] = []
        audit_warnings: List[str] = []

        # Determine target dates to include in the output sequence
        if self.zero_fill_internal_gaps:
            # Mode: continuous calendar days between min_date and max_date
            target_dates = self.generate_continuous_date_range(min_date, max_date)
            aggregation_mode = "continuous_calendar_days_with_internal_zero_fill"
            if classification["internal_gap_count"] > 0:
                audit_warnings.append(
                    f"AUDIT WARNING: {classification['internal_gap_count']} internal unrecorded date(s) "
                    f"({', '.join(classification['unknown_internal_gaps'])}) were zero-filled. "
                    "If the shop was closed on these dates, estimated daily demand will be downward-biased."
                )
        else:
            # Mode: confirmed active trading days (Primary Recommended Baseline)
            target_dates = sorted(active_dates_set)
            aggregation_mode = "active_trading_days_primary"

        # Populate records per target date and catalog product
        for cal_date in target_dates:
            cal_str = cal_date.strftime("%Y-%m-%d")
            is_active_day = cal_date in active_dates_set

            for pid, pname in product_map.items():
                key = (cal_date, pid)

                if key in grouped_sales:
                    # Case A: Product had transactions on this date
                    info = grouped_sales[key]
                    aggregated_records.append(DailyProductSale(
                        date=cal_str,
                        product_id=pid,
                        product_name=pname,
                        units_sold=info["units"],
                        revenue=round(info["revenue"], 2),
                        transaction_count=info["tx_count"],
                        is_zero_filled=False,
                        is_synthetic=False,
                        date_category=DateCategory.CONFIRMED_TRADING_DAY
                    ))
                elif is_active_day:
                    # Case B: Store was open (confirmed trading day), but 0 units of this product were sold
                    aggregated_records.append(DailyProductSale(
                        date=cal_str,
                        product_id=pid,
                        product_name=pname,
                        units_sold=0,
                        revenue=0.0,
                        transaction_count=0,
                        is_zero_filled=False,  # Authentic observed zero demand on active trading day
                        is_synthetic=False,
                        date_category=DateCategory.CONFIRMED_TRADING_DAY
                    ))
                else:
                    # Case C: Unknown internal gap date with zero-fill enabled
                    aggregated_records.append(DailyProductSale(
                        date=cal_str,
                        product_id=pid,
                        product_name=pname,
                        units_sold=0,
                        revenue=0.0,
                        transaction_count=0,
                        is_zero_filled=True,   # Synthetic zero-fill for unrecorded date
                        is_synthetic=False,
                        date_category=DateCategory.UNKNOWN_INTERNAL_GAP
                    ))

        # Evaluate Data Sufficiency Tier
        active_days_count = len(active_dates_set)
        if active_days_count == 0:
            tier_desc = "Tier 0 — No Historical Data"
        elif active_days_count < 7:
            tier_desc = f"Tier 1 — Preliminary Baseline Only ({active_days_count} active days; ML prohibited)"
        elif active_days_count < 14:
            tier_desc = f"Tier 2 — Weekly Baseline ({active_days_count} active days; 7-day pattern tracking)"
        elif active_days_count < 30:
            tier_desc = f"Tier 3 — Evaluated Baseline ({active_days_count} active days; backtesting eligible)"
        else:
            tier_desc = f"Tier 4 — Local ML Eligible ({active_days_count} active days; regression models supported)"

        if classification["elapsed_unobserved_count"] > 0:
            audit_warnings.append(
                f"NOTICE: {classification['elapsed_unobserved_count']} post-data calendar day(s) have elapsed "
                f"since last sale ({max_date.strftime('%Y-%m-%d')}). In accordance with Step-2 policy, "
                "these dates were NOT backfilled with synthetic zeroes into the sales demand series."
            )

        date_metadata = {
            "min_date": min_date.strftime("%Y-%m-%d"),
            "max_date": max_date.strftime("%Y-%m-%d"),
            "as_of_date": self.as_of_date,
            "total_calendar_days": classification["total_calendar_days_in_history"],
            "active_sales_days": classification["active_trading_days_count"],
            "missing_calendar_days": classification["internal_gap_count"],
            "internal_gap_days": classification["internal_gap_count"],
            "internal_gap_dates": classification["unknown_internal_gaps"],
            "confirmed_closed_days": classification["confirmed_closed_count"],
            "elapsed_unobserved_days": classification["elapsed_unobserved_count"],
            "elapsed_unobserved_dates": classification["elapsed_unobserved_dates"],
            "aggregation_mode": aggregation_mode,
            "zero_fill_applied": self.zero_fill_internal_gaps,
            "data_sufficiency_tier": tier_desc,
            "audit_warnings": audit_warnings
        }

        return aggregated_records, date_metadata

    def generate_data_quality_report(
        self,
        products: List[Dict[str, Any]],
        sales: List[Dict[str, Any]],
        validation_results: Dict[str, Any],
        date_metadata: Dict[str, Any],
        aggregated_records: List[DailyProductSale]
    ) -> str:
        """
        Generate a comprehensive, human-readable data-quality and readiness report.
        """
        lines = []
        lines.append("# SmartKadai AI Sales Forecasting — Data Quality & Preparation Report")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**Database Source:** `{self.db_path.name}` (SQLite Strict Read-Only)")
        lines.append(f"**Data Sufficiency Assessment:** {date_metadata.get('data_sufficiency_tier')}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # 1. Executive Summary
        lines.append("## 1. Executive Summary")
        total_tx = len(sales)
        valid_cnt = validation_results.get("valid_sales_count", total_tx)
        invalid_cnt = validation_results.get("invalid_sales_count", 0)
        total_units = sum(int(s.get("quantity_sold", 0)) for s in sales if isinstance(s.get("quantity_sold"), int))
        total_rev = sum(
            int(s.get("quantity_sold", 0)) * float(s.get("selling_price", 0.0))
            for s in sales
            if isinstance(s.get("quantity_sold"), int) and isinstance(s.get("selling_price"), (int, float))
        )
        lines.append(f"- **Total Catalog Products:** {len(products)}")
        lines.append(f"- **Total Raw Sales Rows:** {total_tx} ({valid_cnt} valid, {invalid_cnt} invalid)")
        lines.append(f"- **Total Units Sold:** {total_units:,} units")
        lines.append(f"- **Total Recorded Revenue:** ₹{total_rev:,.2f}")
        lines.append(f"- **Observed Date Span:** `{date_metadata.get('min_date')}` to `{date_metadata.get('max_date')}` ({date_metadata.get('total_calendar_days')} calendar days)")
        lines.append(f"- **Confirmed Trading Days:** {date_metadata.get('active_sales_days')} days")
        lines.append(f"- **Internal Unrecorded Gap Days:** {date_metadata.get('internal_gap_days')} days")
        lines.append(f"- **Elapsed Post-Data Days:** {date_metadata.get('elapsed_unobserved_days')} days")
        lines.append(f"- **Aggregation Pipeline Mode:** `{date_metadata.get('aggregation_mode')}`")
        lines.append("")

        # 2. Historical Date Classification & Assumptions
        lines.append("## 2. Historical Date Policy & Assumptions")
        lines.append("- **Category 1 (Confirmed Trading Days):** Dates with observed retail transactions. Used as primary demand rate basis.")
        lines.append("- **Category 2 (Confirmed Closed Days):** Excluded from store trading demand calculations when explicit closure records exist.")
        lines.append(f"- **Category 3 (Unknown Internal Gaps):** {date_metadata.get('internal_gap_days')} day(s) detected: `{date_metadata.get('internal_gap_dates')}`.")
        if date_metadata.get("zero_fill_applied"):
            lines.append("  > [!WARNING]")
            lines.append("  > **Internal Gap Zero-Fill is ENABLED:** Gap dates were inserted as 0 units. If the shop was closed for a weekly holiday, demand estimates will be downward-biased.")
        else:
            lines.append("  > [!NOTE]")
            lines.append("  > **Active Trading Days Basis (Primary Default):** Internal gaps without confirmed store closure are omitted from daily demand rates, avoiding arbitrary demand dilution.")
        lines.append(f"- **Category 4 (Elapsed Post-Data Days):** {date_metadata.get('elapsed_unobserved_days')} day(s) elapsed after last sale. Step-2 policy strictly prohibits filling post-data dates with synthetic zeroes.")
        lines.append("")

        # 3. Data Integrity & Validation Findings
        lines.append("## 3. Data Integrity & Validation Findings")
        d_errs = validation_results["date_format_errors"]
        status_d = "[PASS] Valid YYYY-MM-DD" if not d_errs else f"[FAIL] {len(d_errs)} invalid records"
        lines.append(f"- **Date Format Consistency:** {status_d}")

        fk_errs = validation_results["referential_integrity_errors"]
        status_fk = "[PASS] All product IDs exist in catalog" if not fk_errs else f"[FAIL] {len(fk_errs)} orphaned product IDs"
        lines.append(f"- **Referential Integrity:** {status_fk}")

        q_errs = validation_results["quantity_errors"]
        p_errs = validation_results["price_errors"]
        lines.append(f"- **Quantity Boundary Check (`quantity_sold > 0`):** {'[PASS] All positive' if not q_errs else f'[FAIL] {len(q_errs)} invalid quantities'}")
        lines.append(f"- **Price Boundary Check (`selling_price >= 0`):** {'[PASS] All valid' if not p_errs else f'[FAIL] {len(p_errs)} negative prices'}")

        missing_bills = validation_results["missing_bill_ids"]
        missing_ts = validation_results["missing_timestamps"]
        lines.append(f"- **Missing `bill_id`:** {len(missing_bills)} of {total_tx} records ({len(missing_bills)/max(total_tx,1)*100:.1f}%)")
        lines.append(f"  - *Impact:* Product-level sales are intact; bill grouping uses individual transaction IDs where bill_id is NULL.")
        lines.append(f"- **Missing `timestamp`:** {len(missing_ts)} of {total_tx} records ({len(missing_ts)/max(total_tx,1)*100:.1f}%)")
        lines.append(f"  - *Impact:* Daily aggregation uses the verified `date` column; missing timestamps do not block daily forecasting.")

        lines.append("- **Timestamp Format Distribution:**")
        for fmt_name, count in validation_results["timestamp_format_counts"].items():
            lines.append(f"  - `{fmt_name}`: {count} records")

        rapid_tx = validation_results["rapid_transactions"]
        lines.append(f"- **Rapid Sequential Transactions Flagged:** {len(rapid_tx)} cluster(s) detected (preserved without deletion)")
        lines.append("")

        # 4. Product-Level Aggregation Summary
        lines.append("## 4. Product Sales Aggregation Summary")
        lines.append("| Product ID | Product Name | Total Units Sold | Total Revenue | Active Sales Days | Avg Daily Units (Active Days) | Lead Days | Safety Stock |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|")

        prod_agg = collections.defaultdict(lambda: {"units": 0, "rev": 0.0, "active_days": 0})
        for rec in aggregated_records:
            if rec.units_sold > 0:
                prod_agg[rec.product_id]["units"] += rec.units_sold
                prod_agg[rec.product_id]["rev"] += rec.revenue
                prod_agg[rec.product_id]["active_days"] += 1

        for p in products:
            pid = p["product_id"]
            pname = p["product_name"]
            info = prod_agg[pid]
            active_d = info["active_days"]
            avg_units = (info["units"] / active_d) if active_d > 0 else 0.0
            lead = p.get("supplier_lead_days", 0)
            safety = p.get("safety_stock", 0)
            lines.append(f"| {pid} | {pname} | {info['units']} units | ₹{info['rev']:,.2f} | {active_d} | {avg_units:.1f} | {lead}d | {safety} |")
        lines.append("")

        # 5. Audit Warnings & Alerts
        warnings = date_metadata.get("audit_warnings", [])
        if warnings:
            lines.append("## 5. Audit Warnings")
            for w in warnings:
                lines.append(f"- {w}")
            lines.append("")

        # 6. Recommendation
        lines.append("## 6. AI/ML Forecasting Readiness & Recommendation")
        lines.append(f"- **Current Volume Tier:** {date_metadata.get('data_sufficiency_tier')}")
        lines.append("- **Prohibited Action:** Do NOT train a stand-alone neural network or regression model on this 4-day sample.")
        lines.append("- **Recommended Baseline:** Use Recent-Weighted Moving Average (WMA) or Simple Observed Mean on confirmed trading days.")

        return "\n".join(lines)

    def export_aggregated_csv(
        self,
        aggregated_records: List[DailyProductSale],
        output_path: Path
    ) -> Path:
        """Export daily aggregated product sales to CSV."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "date",
            "product_id",
            "product_name",
            "units_sold",
            "revenue",
            "transaction_count",
            "is_zero_filled",
            "is_synthetic",
            "date_category"
        ]

        with open(output_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for rec in aggregated_records:
                writer.writerow(rec.to_dict())

        return output_path

    def run_pipeline(self, output_dir: Optional[Path] = None) -> Dict[str, Any]:
        """
        Execute the full data preparation and validation pipeline.
        """
        if output_dir is None:
            output_dir = Path(__file__).parent / "output"
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        products, sales = self.load_raw_data()
        validation_results = self.validate_records(products, sales)
        aggregated_records, date_metadata = self.aggregate_daily_sales(products, sales)

        report_content = self.generate_data_quality_report(
            products, sales, validation_results, date_metadata, aggregated_records
        )
        report_path = output_dir / "data_quality_report.md"
        report_path.write_text(report_content, encoding="utf-8")

        csv_path = output_dir / "daily_aggregated_sales.csv"
        self.export_aggregated_csv(aggregated_records, csv_path)

        return {
            "status": "success",
            "report_path": report_path,
            "csv_path": csv_path,
            "validation_results": validation_results,
            "date_metadata": date_metadata,
            "total_aggregated_rows": len(aggregated_records)
        }


if __name__ == "__main__":
    base_dir = Path(__file__).parent.parent
    db_file = base_dir / "smartkadai.db"
    prep = SalesDataPreparation(db_file, zero_fill_internal_gaps=False, as_of_date=datetime.now().strftime("%Y-%m-%d"))
    res = prep.run_pipeline()
    print("Data preparation pipeline complete.")
    print(f"Report: {res['report_path']}")
    print(f"Aggregated CSV: {res['csv_path']}")
    print(f"Total aggregated rows: {res['total_aggregated_rows']}")
    print(f"Sufficiency Tier: {res['date_metadata']['data_sufficiency_tier']}")
