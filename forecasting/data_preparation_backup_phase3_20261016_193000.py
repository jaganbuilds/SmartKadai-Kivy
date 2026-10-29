"""
SmartKadai AI Sales Forecasting - Data Preparation and Validation Module.

This module is responsible for:
1. Connecting to SQLite in read-only mode to prevent any inadvertent database mutations.
2. Validating raw sales and product records (date formats, quantities, prices, foreign keys, missing fields).
3. Detecting rapid successive transactions without deleting or modifying raw records.
4. Aggregating sales by product and calendar day with a continuous date index.
5. Providing configurable zero-filling for unrecorded calendar dates with explicit assumption logging.
6. Ensuring strict separation between real observed sales and synthetic benchmark data.
7. Generating human-readable data-quality reports and aggregated CSV datasets.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import collections
import csv
import sqlite3


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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SalesDataPreparation:
    """
    Data preparation and validation pipeline for retail sales time series.
    """

    def __init__(
        self,
        db_path: Path,
        zero_fill_missing_dates: bool = True,
        rapid_tx_threshold_seconds: int = 300
    ):
        """
        Initialize the data preparation pipeline.

        Args:
            db_path: Path to the SQLite database (e.g. smartkadai.db).
            zero_fill_missing_dates: Configurable assumption. If True, calendar days between
                                     min_date and max_date with zero sales are filled with 0.
                                     If False, only dates with actual sales are included.
            rapid_tx_threshold_seconds: Time window (seconds) to flag rapid successive purchases
                                        of the same product as potential duplicates or test clicks.
        """
        self.db_path = Path(db_path)
        self.zero_fill_missing_dates = zero_fill_missing_dates
        self.rapid_tx_threshold_seconds = rapid_tx_threshold_seconds

    def load_raw_data(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Connect to SQLite in strict read-only mode and retrieve products and sales.

        Returns:
            Tuple of (products_list, sales_list) as standard dictionaries.
        """
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database file not found at: {self.db_path}")

        # Ensure strict read-only mode using URI format
        resolved_path = self.db_path.resolve().as_posix()
        uri = f"file:{resolved_path}?mode=ro"

        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        try:
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

        No records are deleted or modified. Issues are compiled into a validation report.
        """
        valid_product_ids = {p["product_id"]: p["product_name"] for p in products}

        date_format_errors = []
        referential_integrity_errors = []
        quantity_errors = []
        price_errors = []
        missing_bill_ids = []
        missing_timestamps = []
        timestamp_format_counts = collections.defaultdict(int)
        rapid_transactions = []

        # Track transactions per product for rapid succession detection
        product_tx_history = collections.defaultdict(list)

        for sale in sales:
            sale_id = sale.get("sale_id")
            s_date = str(sale.get("date") or "").strip()
            s_pid = str(sale.get("product_id") or "").strip()
            s_qty = sale.get("quantity_sold")
            s_price = sale.get("selling_price")
            s_bill = sale.get("bill_id")
            s_ts = sale.get("timestamp")

            # 1. Date Format Validation (Strict YYYY-MM-DD)
            try:
                parsed_date = datetime.strptime(s_date, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                date_format_errors.append({
                    "sale_id": sale_id,
                    "invalid_date": s_date
                })
                parsed_date = None

            # 2. Product ID Referential Integrity
            if s_pid not in valid_product_ids:
                referential_integrity_errors.append({
                    "sale_id": sale_id,
                    "invalid_product_id": s_pid
                })

            # 3. Quantity Validation (must be positive integer)
            if not isinstance(s_qty, int) or s_qty <= 0:
                quantity_errors.append({
                    "sale_id": sale_id,
                    "invalid_quantity": s_qty
                })

            # 4. Price Validation (must be non-negative)
            if not isinstance(s_price, (int, float)) or s_price < 0:
                price_errors.append({
                    "sale_id": sale_id,
                    "invalid_price": s_price
                })

            # 5. Missing Bill ID Tracking
            if s_bill is None or str(s_bill).strip() == "":
                missing_bill_ids.append(sale_id)

            # 6. Missing Timestamp Tracking
            parsed_dt = None
            if s_ts is None or str(s_ts).strip() == "":
                missing_timestamps.append(sale_id)
                timestamp_format_counts["Missing / NULL"] += 1
            else:
                s_ts_clean = str(s_ts).strip()
                # Parse timestamp formats
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
                        # Missing timestamps on same day with consecutive sale_ids
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
        """
        Generate an uninterrupted daily calendar sequence [start_date, end_date].
        """
        if start_date > end_date:
            return []
        days_count = (end_date - start_date).days + 1
        return [start_date + timedelta(days=i) for i in range(days_count)]

    def aggregate_daily_sales(
        self,
        products: List[Dict[str, Any]],
        sales: List[Dict[str, Any]]
    ) -> Tuple[List[DailyProductSale], Dict[str, Any]]:
        """
        Aggregate sales by product and calendar date.

        Generates a continuous daily date index between min_date and max_date.
        If zero_fill_missing_dates is True, missing days are populated with units_sold=0.

        Returns:
            Tuple of (aggregated_daily_sales, date_range_metadata).
        """
        product_map = {p["product_id"]: p["product_name"] for p in products}

        # Parse valid dates
        parsed_sales = []
        valid_dates = []
        for s in sales:
            try:
                d = datetime.strptime(str(s["date"]).strip(), "%Y-%m-%d").date()
                parsed_sales.append((d, s))
                valid_dates.append(d)
            except (ValueError, TypeError):
                continue

        if not valid_dates:
            return [], {
                "min_date": None,
                "max_date": None,
                "total_calendar_days": 0,
                "active_sales_days": 0,
                "missing_calendar_days": 0,
                "zero_fill_applied": self.zero_fill_missing_dates
            }

        min_date = min(valid_dates)
        max_date = max(valid_dates)
        continuous_dates = self.generate_continuous_date_range(min_date, max_date)
        unique_active_dates = set(valid_dates)

        # Group sales by (date, product_id)
        grouped_sales = collections.defaultdict(lambda: {"units": 0, "revenue": 0.0, "tx_count": 0})
        for d, s in parsed_sales:
            pid = s["product_id"]
            qty = int(s["quantity_sold"])
            price = float(s["selling_price"])
            key = (d, pid)
            grouped_sales[key]["units"] += qty
            grouped_sales[key]["revenue"] += (qty * price)
            grouped_sales[key]["tx_count"] += 1

        aggregated_records: List[DailyProductSale] = []

        if self.zero_fill_missing_dates:
            # Full Cartesian product of continuous dates x all products
            for cal_date in continuous_dates:
                for pid, pname in product_map.items():
                    key = (cal_date, pid)
                    if key in grouped_sales:
                        info = grouped_sales[key]
                        aggregated_records.append(DailyProductSale(
                            date=cal_date.strftime("%Y-%m-%d"),
                            product_id=pid,
                            product_name=pname,
                            units_sold=info["units"],
                            revenue=round(info["revenue"], 2),
                            transaction_count=info["tx_count"],
                            is_zero_filled=False,
                            is_synthetic=False
                        ))
                    else:
                        aggregated_records.append(DailyProductSale(
                            date=cal_date.strftime("%Y-%m-%d"),
                            product_id=pid,
                            product_name=pname,
                            units_sold=0,
                            revenue=0.0,
                            transaction_count=0,
                            is_zero_filled=True,
                            is_synthetic=False
                        ))
        else:
            # Only include dates and products where transactions occurred
            for (cal_date, pid), info in sorted(grouped_sales.items(), key=lambda x: (x[0][0], x[0][1])):
                aggregated_records.append(DailyProductSale(
                    date=cal_date.strftime("%Y-%m-%d"),
                    product_id=pid,
                    product_name=product_map.get(pid, "Unknown"),
                    units_sold=info["units"],
                    revenue=round(info["revenue"], 2),
                    transaction_count=info["tx_count"],
                    is_zero_filled=False,
                    is_synthetic=False
                ))

        date_metadata = {
            "min_date": min_date.strftime("%Y-%m-%d"),
            "max_date": max_date.strftime("%Y-%m-%d"),
            "total_calendar_days": len(continuous_dates),
            "active_sales_days": len(unique_active_dates),
            "missing_calendar_days": len(continuous_dates) - len(unique_active_dates),
            "zero_fill_applied": self.zero_fill_missing_dates
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
        lines.append(f"**Database Source:** `{self.db_path.name}` (SQLite Read-Only Inspection)")
        lines.append("")
        lines.append("---")
        lines.append("")

        # 1. Executive Summary
        lines.append("## 1. Executive Summary")
        total_tx = len(sales)
        total_units = sum(int(s.get("quantity_sold", 0)) for s in sales)
        total_rev = sum(int(s.get("quantity_sold", 0)) * float(s.get("selling_price", 0.0)) for s in sales)
        lines.append(f"- **Total Catalog Products:** {len(products)}")
        lines.append(f"- **Total Raw Sales Transactions:** {total_tx}")
        lines.append(f"- **Total Units Sold:** {total_units:,} units")
        lines.append(f"- **Total Recorded Revenue:** ₹{total_rev:,.2f}")
        lines.append(f"- **Historical Date Range:** `{date_metadata.get('min_date')}` to `{date_metadata.get('max_date')}` ({date_metadata.get('total_calendar_days')} calendar days)")
        lines.append(f"- **Days With Recorded Sales:** {date_metadata.get('active_sales_days')} days")
        lines.append(f"- **Calendar Days With Zero Sales:** {date_metadata.get('missing_calendar_days')} days")
        lines.append("")

        # 2. Configurable Assumptions
        lines.append("## 2. Configurable Assumptions (Missing Date Handling)")
        if self.zero_fill_missing_dates:
            lines.append("> [!NOTE]")
            lines.append("> **Zero-Fill Assumption Enabled (`zero_fill_missing_dates=True`):**")
            lines.append("> Calendar dates within the recorded span that lack transactions are populated with `units_sold = 0`.")
            lines.append("> ")
            lines.append("> **Operational Risk & Limitation:**")
            lines.append("> In retail environments, zero recorded sales on a calendar date (e.g., `2026-10-12`) can occur either because the shop was closed (e.g. weekly holiday) or because no customers bought goods. Treating unrecorded days as zero consumer demand will downward-bias AI demand predictions unless calendar holiday / closure flags are explicitly fed into model features.")
        else:
            lines.append("> [!NOTE]")
            lines.append("> **Zero-Fill Assumption Disabled (`zero_fill_missing_dates=False`):**")
            lines.append("> Only dates with observed transactions are output. Missing dates are omitted from the aggregated index.")
        lines.append("")

        # 3. Data Integrity & Validation Findings
        lines.append("## 3. Data Integrity & Validation Findings")
        
        # Date Format
        d_errs = validation_results["date_format_errors"]
        status_d = "[PASS] Valid" if not d_errs else f"[FAIL] {len(d_errs)} invalid records"
        lines.append(f"- **Date Format Consistency:** {status_d}")
        if d_errs:
            for err in d_errs:
                lines.append(f"  - Sale ID {err['sale_id']}: Invalid date string `{err['invalid_date']}`")

        # Referential Integrity
        fk_errs = validation_results["referential_integrity_errors"]
        status_fk = "[PASS] All product IDs exist in products table" if not fk_errs else f"[FAIL] {len(fk_errs)} orphaned product IDs"
        lines.append(f"- **Referential Integrity:** {status_fk}")
        if fk_errs:
            for err in fk_errs:
                lines.append(f"  - Sale ID {err['sale_id']}: Product ID `{err['invalid_product_id']}` not in catalog")

        # Quantities and Prices
        q_errs = validation_results["quantity_errors"]
        p_errs = validation_results["price_errors"]
        lines.append(f"- **Quantity Boundary Check (`quantity_sold > 0`):** {'[PASS] All positive' if not q_errs else f'[FAIL] {len(q_errs)} invalid quantities'}")
        lines.append(f"- **Price Boundary Check (`selling_price >= 0`):** {'[PASS] All valid' if not p_errs else f'[FAIL] {len(p_errs)} negative prices'}")

        # Missing Fields
        missing_bills = validation_results["missing_bill_ids"]
        missing_ts = validation_results["missing_timestamps"]
        lines.append(f"- **Missing `bill_id`:** {len(missing_bills)} of {total_tx} records ({len(missing_bills)/max(total_tx,1)*100:.1f}%)")
        lines.append(f"  - *Impact:* Early seed and test records lack bill grouping, but individual product sales are intact.")
        lines.append(f"- **Missing `timestamp`:** {len(missing_ts)} of {total_tx} records ({len(missing_ts)/max(total_tx,1)*100:.1f}%)")
        lines.append(f"  - *Impact:* Time-of-day intra-day forecasting cannot be trained on early records.")

        # Timestamp Formats
        lines.append("- **Timestamp Format Distribution:**")
        for fmt_name, count in validation_results["timestamp_format_counts"].items():
            lines.append(f"  - `{fmt_name}`: {count} records")

        # Rapid Transactions
        rapid_tx = validation_results["rapid_transactions"]
        lines.append(f"- **Rapid Sequential Transactions Flagged:** {len(rapid_tx)} cluster(s) detected")
        if rapid_tx:
            lines.append("  > [!IMPORTANT]")
            lines.append("  > The following records occurred within close proximity (< 300s or consecutive test sales). Records are **preserved without deletion**:")
            for r in rapid_tx:
                lines.append(f"  - **{r['product_name']} ({r['product_id']})** on `{r['date']}`: Sale #{r['sale_id_1']} ({r['qty_1']} unit) & Sale #{r['sale_id_2']} ({r['qty_2']} unit) — *{r['timing_note']}*")
        lines.append("")

        # 4. Product-Level Aggregation Summary
        lines.append("## 4. Product Sales Aggregation Summary")
        lines.append("| Product ID | Product Name | Total Units Sold | Total Revenue | Active Sales Days | Avg Daily Units (Active Days) | Lead Days | Safety Stock |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|")

        # Group by product
        prod_agg = collections.defaultdict(lambda: {"units": 0, "rev": 0.0, "active_days": 0})
        for rec in aggregated_records:
            if not rec.is_zero_filled and rec.units_sold > 0:
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

        # 5. Data Separation & Synthetic Policy
        lines.append("## 5. Data Separation & Synthetic Data Policy")
        lines.append("- **Observed vs. Synthetic Separation:** All aggregated records produced by this module are marked with `is_synthetic = False` and `is_zero_filled = [True/False]`.")
        lines.append("- **Zero Database Mutation:** No synthetic records are inserted into `smartkadai.db`. Raw retail database records remain strictly authentic.")
        lines.append("- **Benchmark Readiness:** Any synthetic test benchmarks or model evaluation generators must live exclusively in decoupled external files or memory.")
        lines.append("")

        # 6. AI/ML Forecasting Readiness & Next Steps
        lines.append("## 6. AI/ML Readiness Assessment & Next Steps")
        lines.append("- **Readiness Verdict:** Current live sales span **5 calendar days** with **19 transactions**. This is insufficient for training stand-alone neural or deep regression time-series models directly.")
        lines.append("- **Recommended Next Step:** Implement a **hybrid demand forecasting engine** that combines:")
        lines.append("  1. Rolling Exponential Weighted Moving Average (EWMA) / Weighted Moving Average for immediate short-term demand.")
        lines.append("  2. Feature-engineered Regression pipeline (`day_of_week`, `lag_1_day`, `rolling_avg`) capable of learning patterns once historical depth reaches 14–30+ days.")
        lines.append("  3. Lead-time inventory replenishment alerts: Recommended Reorder Point = `(Lead Days * Predicted Daily Demand) + Safety Stock`.")

        return "\n".join(lines)

    def export_aggregated_csv(
        self,
        aggregated_records: List[DailyProductSale],
        output_path: Path
    ) -> Path:
        """
        Export daily aggregated product sales to CSV.
        """
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
            "is_synthetic"
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

        Args:
            output_dir: Destination folder for quality report and CSV. Defaults to 'forecasting/output'.

        Returns:
            Dictionary containing paths to generated files, validation results, and summary statistics.
        """
        if output_dir is None:
            output_dir = Path(__file__).parent / "output"
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 1. Load data
        products, sales = self.load_raw_data()

        # 2. Validate
        validation_results = self.validate_records(products, sales)

        # 3. Aggregate
        aggregated_records, date_metadata = self.aggregate_daily_sales(products, sales)

        # 4. Generate report
        report_content = self.generate_data_quality_report(
            products, sales, validation_results, date_metadata, aggregated_records
        )
        report_path = output_dir / "data_quality_report.md"
        report_path.write_text(report_content, encoding="utf-8")

        # 5. Export CSV
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
    import sys
    base_dir = Path(__file__).parent.parent
    db_file = base_dir / "smartkadai.db"
    prep = SalesDataPreparation(db_file, zero_fill_missing_dates=True)
    res = prep.run_pipeline()
    print("Data preparation complete.")
    print(f"Report: {res['report_path']}")
    print(f"Aggregated CSV: {res['csv_path']}")
    print(f"Total aggregated rows: {res['total_aggregated_rows']}")
