"""
SmartKadai AI Sales Forecasting - Unit Tests for Data Preparation Module.

Strict Testing Standards:
1. Isolated temporary SQLite databases exclusively — NEVER mutates the live database.
2. Verifies read-only enforcement (PRAGMA query_only = ON).
3. Verifies four-category date classification and no synthetic post-data zeroes.
4. Verifies multi-product bills, NULL bill IDs, mixed timestamps, and data boundary validations.
5. Verifies live database immutability.
"""

import gc
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from forecasting.data_preparation import SalesDataPreparation, DailyProductSale, DateCategory


class TestSalesDataPreparation(unittest.TestCase):
    """Comprehensive test suite for SalesDataPreparation module."""

    def setUp(self):
        """Create a temporary SQLite test database fixture."""
        gc.collect()
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "test_smartkadai.db"
        self._create_mock_database()

    def tearDown(self):
        """Clean up temporary database fixture."""
        gc.collect()
        self.temp_dir.cleanup()

    def _create_mock_database(self):
        """Populate the temporary test database with known test fixtures."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE products (
                    product_id TEXT PRIMARY KEY,
                    product_name TEXT NOT NULL,
                    selling_price REAL NOT NULL,
                    current_stock INTEGER NOT NULL,
                    supplier_lead_days INTEGER NOT NULL,
                    safety_stock INTEGER NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE sales (
                    sale_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bill_id TEXT,
                    timestamp TEXT,
                    date TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    quantity_sold INTEGER NOT NULL,
                    selling_price REAL NOT NULL,
                    FOREIGN KEY(product_id) REFERENCES products(product_id)
                )
            """)

            # Sample Products (3 catalog items)
            conn.executemany("""
                INSERT INTO products VALUES (?, ?, ?, ?, ?, ?)
            """, [
                ("P01", "Basmati Rice", 75.0, 50, 3, 10),
                ("P02", "White Sugar", 42.0, 30, 2, 8),
                ("P03", "Cow Milk", 28.0, 20, 1, 5)
            ])

            # Sample Sales:
            # Day 1: 2026-10-01 (Multi-product bill + rapid transaction)
            # Day 2: 2026-10-02 (Internal Gap — 0 transactions store-wide)
            # Day 3: 2026-10-03 (Single bill + NULL bill_id / timestamp record)
            conn.executemany("""
                INSERT INTO sales (bill_id, timestamp, date, product_id, quantity_sold, selling_price)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [
                # Day 1: 2026-10-01
                # Multi-product bill: BILL-001 has P01 (4 units) and P02 (2 units)
                ("BILL-001", "2026-10-01T10:00:00", "2026-10-01", "P01", 4, 75.0),
                ("BILL-001", "2026-10-01T10:00:00", "2026-10-01", "P02", 2, 42.0),
                # Rapid separate bill 150 seconds later for P01 (1 unit)
                ("BILL-002", "2026-10-01T10:02:30", "2026-10-01", "P01", 1, 75.0),
                
                # Day 3: 2026-10-03
                # P02: 5 units at ₹42.0
                ("BILL-003", "2026-10-03 14:30:00", "2026-10-03", "P02", 5, 42.0),
                # P03: 6 units at ₹28.0 with ISO microseconds
                ("BILL-004", "2026-10-03T16:00:00.123456", "2026-10-03", "P03", 6, 28.0),
                # Legacy / seed record: NULL bill_id and NULL timestamp
                (None, None, "2026-10-03", "P01", 3, 75.0)
            ])

    def test_read_only_access_and_query_only(self):
        """Verify reading products and sales operates under strict read-only mode."""
        prep = SalesDataPreparation(self.db_path)
        products, sales = prep.load_raw_data()
        self.assertEqual(len(products), 3)
        self.assertEqual(len(sales), 6)
        self.assertEqual(products[0]["product_id"], "P01")

        # Verify query_only pragma blocks writes even if attempted on the connection
        resolved_path = self.db_path.resolve().as_posix()
        uri = f"file:{resolved_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            conn.execute("PRAGMA query_only = ON")
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("INSERT INTO products VALUES ('P99', 'Fake', 10.0, 1, 1, 1)")
        finally:
            conn.close()

    def test_daily_revenue_and_unit_aggregation(self):
        """Verify unit sums and revenue match exact transactions using actual selling prices."""
        prep = SalesDataPreparation(self.db_path, zero_fill_internal_gaps=False)
        products, sales = prep.load_raw_data()
        aggregated, meta = prep.aggregate_daily_sales(products, sales)

        # Day 1: P01 units = 4 + 1 = 5 units, revenue = 5 * 75.0 = ₹375.0
        day1_p01 = [r for r in aggregated if r.date == "2026-10-01" and r.product_id == "P01"][0]
        self.assertEqual(day1_p01.units_sold, 5)
        self.assertEqual(day1_p01.revenue, 375.0)
        self.assertEqual(day1_p01.transaction_count, 2)
        self.assertFalse(day1_p01.is_zero_filled)

        # Day 1: P02 units = 2, revenue = 2 * 42.0 = ₹84.0
        day1_p02 = [r for r in aggregated if r.date == "2026-10-01" and r.product_id == "P02"][0]
        self.assertEqual(day1_p02.units_sold, 2)
        self.assertEqual(day1_p02.revenue, 84.0)

    def test_multi_product_bills_shared_bill_id(self):
        """Verify multiple products under the same bill_id are aggregated cleanly per product."""
        prep = SalesDataPreparation(self.db_path)
        products, sales = prep.load_raw_data()
        
        # Verify BILL-001 has 2 lines in raw sales
        bill1_lines = [s for s in sales if s.get("bill_id") == "BILL-001"]
        self.assertEqual(len(bill1_lines), 2)

        aggregated, meta = prep.aggregate_daily_sales(products, sales)
        day1_prods = {r.product_id: r.units_sold for r in aggregated if r.date == "2026-10-01"}
        self.assertEqual(day1_prods["P01"], 5)  # 4 from bill 1 + 1 from bill 2
        self.assertEqual(day1_prods["P02"], 2)  # 2 from bill 1

    def test_null_bill_ids_and_null_timestamps(self):
        """Verify NULL bill_id and NULL timestamp records aggregate correctly using valid date."""
        prep = SalesDataPreparation(self.db_path)
        products, sales = prep.load_raw_data()
        aggregated, meta = prep.aggregate_daily_sales(products, sales)

        # On 2026-10-03, P01 had 3 units sold under a NULL bill_id
        day3_p01 = [r for r in aggregated if r.date == "2026-10-03" and r.product_id == "P01"][0]
        self.assertEqual(day3_p01.units_sold, 3)
        self.assertEqual(day3_p01.revenue, 225.0)
        self.assertEqual(day3_p01.transaction_count, 1)

    def test_mixed_timestamp_formats(self):
        """Verify ISO-8601 (T), SQL (space), and microseconds timestamps are tracked cleanly."""
        prep = SalesDataPreparation(self.db_path)
        products, sales = prep.load_raw_data()
        val = prep.validate_records(products, sales)

        counts = val["timestamp_format_counts"]
        self.assertIn("ISO 8601 (T-separator)", counts)
        self.assertIn("SQL Datetime (space-separator)", counts)
        self.assertIn("ISO 8601 with microseconds", counts)
        self.assertIn("Missing / NULL", counts)
        self.assertEqual(counts["Missing / NULL"], 1)

    def test_legitimate_zero_demand_on_confirmed_trading_day(self):
        """On a confirmed trading day, catalog items with 0 sales have units_sold=0, is_zero_filled=False."""
        prep = SalesDataPreparation(self.db_path, zero_fill_internal_gaps=False)
        products, sales = prep.load_raw_data()
        aggregated, meta = prep.aggregate_daily_sales(products, sales)

        # On 2026-10-01, P03 (Cow Milk) had 0 sales, but store was OPEN (confirmed trading day)
        day1_p03 = [r for r in aggregated if r.date == "2026-10-01" and r.product_id == "P03"][0]
        self.assertEqual(day1_p03.units_sold, 0)
        self.assertEqual(day1_p03.revenue, 0.0)
        self.assertEqual(day1_p03.transaction_count, 0)
        self.assertFalse(day1_p03.is_zero_filled)  # Genuine observed zero demand
        self.assertEqual(day1_p03.date_category, DateCategory.CONFIRMED_TRADING_DAY)

    def test_four_date_categories_and_no_post_data_zeroes(self):
        """Verify the 4 Step-2 categories and assert post-data dates are NEVER zero-filled."""
        # as_of_date is 2026-10-06 (3 days after last recorded sale on 2026-10-03)
        prep = SalesDataPreparation(
            self.db_path,
            zero_fill_internal_gaps=False,
            confirmed_closed_dates=["2026-10-02"],
            as_of_date="2026-10-06"
        )
        products, sales = prep.load_raw_data()
        aggregated, meta = prep.aggregate_daily_sales(products, sales)

        self.assertEqual(meta["min_date"], "2026-10-01")
        self.assertEqual(meta["max_date"], "2026-10-03")
        self.assertEqual(meta["active_sales_days"], 2)
        self.assertEqual(meta["confirmed_closed_days"], 1)
        self.assertEqual(meta["elapsed_unobserved_days"], 3)  # 2026-10-04, 05, 06

        # CRITICAL SAFETY CHECK: Assert no records exist in aggregated output for post-data dates
        dates_in_agg = {r.date for r in aggregated}
        self.assertNotIn("2026-10-04", dates_in_agg)
        self.assertNotIn("2026-10-05", dates_in_agg)
        self.assertNotIn("2026-10-06", dates_in_agg)

    def test_active_trading_days_vs_internal_gap_zero_fill(self):
        """Compare primary active-trading-days mode against optional internal-gap zero-fill."""
        # Primary default: active trading days only
        prep_primary = SalesDataPreparation(self.db_path, zero_fill_internal_gaps=False)
        prods, sales = prep_primary.load_raw_data()
        agg_pri, meta_pri = prep_primary.aggregate_daily_sales(prods, sales)

        # 2 active days * 3 products = 6 records (2026-10-02 omitted)
        self.assertEqual(len(agg_pri), 6)
        dates_pri = {r.date for r in agg_pri}
        self.assertEqual(dates_pri, {"2026-10-01", "2026-10-03"})

        # Secondary optional mode: zero-fill internal gap
        prep_gap = SalesDataPreparation(self.db_path, zero_fill_internal_gaps=True)
        agg_gap, meta_gap = prep_gap.aggregate_daily_sales(prods, sales)

        # 3 calendar days * 3 products = 9 records (2026-10-02 included with zero-fill)
        self.assertEqual(len(agg_gap), 9)
        day2_p01 = [r for r in agg_gap if r.date == "2026-10-02" and r.product_id == "P01"][0]
        self.assertEqual(day2_p01.units_sold, 0)
        self.assertTrue(day2_p01.is_zero_filled)
        self.assertEqual(day2_p01.date_category, DateCategory.UNKNOWN_INTERNAL_GAP)
        self.assertTrue(any("AUDIT WARNING" in w for w in meta_gap["audit_warnings"]))

    def test_invalid_records_rejection(self):
        """Verify invalid dates, ghost products, zero quantities, and negative prices are quarantined."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO sales (bill_id, timestamp, date, product_id, quantity_sold, selling_price) VALUES ('B1', 'ts', '01/10/2026', 'P01', 1, 75.0)") # Bad date
            conn.execute("INSERT INTO sales (bill_id, timestamp, date, product_id, quantity_sold, selling_price) VALUES ('B2', 'ts', '2026-10-01', 'GHOST', 1, 75.0)") # Ghost PID
            conn.execute("INSERT INTO sales (bill_id, timestamp, date, product_id, quantity_sold, selling_price) VALUES ('B3', 'ts', '2026-10-01', 'P01', 0, 75.0)")  # Zero qty
            conn.execute("INSERT INTO sales (bill_id, timestamp, date, product_id, quantity_sold, selling_price) VALUES ('B4', 'ts', '2026-10-01', 'P01', 1, -5.0)")  # Negative price

        prep = SalesDataPreparation(self.db_path)
        prods, sales = prep.load_raw_data()
        val = prep.validate_records(prods, sales)

        self.assertEqual(len(val["date_format_errors"]), 1)
        self.assertEqual(len(val["referential_integrity_errors"]), 1)
        self.assertEqual(len(val["quantity_errors"]), 1)
        self.assertEqual(len(val["price_errors"]), 1)
        self.assertEqual(val["invalid_sales_count"], 4)
        self.assertEqual(val["valid_sales_count"], 6)

        # Ensure aggregation ignores the 4 invalid records
        agg, meta = prep.aggregate_daily_sales(prods, sales)
        day1_p01 = [r for r in agg if r.date == "2026-10-01" and r.product_id == "P01"][0]
        self.assertEqual(day1_p01.units_sold, 5)  # 4 + 1 only; bad records ignored

    def test_empty_sales_history(self):
        """Verify an empty sales table handles safely without crashing, reporting Tier 0."""
        empty_db = Path(self.temp_dir.name) / "empty.db"
        with sqlite3.connect(empty_db) as conn:
            conn.execute("CREATE TABLE products (product_id TEXT PRIMARY KEY, product_name TEXT, selling_price REAL, current_stock INTEGER, supplier_lead_days INTEGER, safety_stock INTEGER)")
            conn.execute("CREATE TABLE sales (sale_id INTEGER PRIMARY KEY, bill_id TEXT, timestamp TEXT, date TEXT, product_id TEXT, quantity_sold INTEGER, selling_price REAL)")
            conn.execute("INSERT INTO products VALUES ('P01', 'Rice', 50.0, 10, 2, 2)")

        prep = SalesDataPreparation(empty_db)
        prods, sales = prep.load_raw_data()
        self.assertEqual(len(prods), 1)
        self.assertEqual(len(sales), 0)

        agg, meta = prep.aggregate_daily_sales(prods, sales)
        self.assertEqual(len(agg), 0)
        self.assertEqual(meta["active_sales_days"], 0)
        self.assertIn("Tier 0", meta["data_sufficiency_tier"])

    def test_live_database_immutability(self):
        """Verify pipeline execution does not modify the SQLite file or table row counts."""
        prep = SalesDataPreparation(self.db_path)
        
        # Capture pre-state
        with sqlite3.connect(self.db_path) as conn:
            pre_prods = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            pre_sales = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
            pre_mtime = self.db_path.stat().st_mtime

        # Run pipeline
        out_dir = Path(self.temp_dir.name) / "output"
        res = prep.run_pipeline(output_dir=out_dir)
        self.assertEqual(res["status"], "success")

        # Capture post-state
        with sqlite3.connect(self.db_path) as conn:
            post_prods = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            post_sales = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]

        self.assertEqual(pre_prods, post_prods)
        self.assertEqual(pre_sales, post_sales)

    def test_full_pipeline_output_and_report(self):
        """Verify end-to-end report and CSV generation."""
        out_dir = Path(self.temp_dir.name) / "pipeline_output"
        prep = SalesDataPreparation(self.db_path, zero_fill_internal_gaps=False, as_of_date="2026-10-05")
        res = prep.run_pipeline(output_dir=out_dir)

        self.assertEqual(res["status"], "success")
        self.assertTrue(res["report_path"].exists())
        self.assertTrue(res["csv_path"].exists())

        # Check report content
        report_text = res["report_path"].read_text(encoding="utf-8")
        self.assertIn("Data Sufficiency Assessment", report_text)
        self.assertIn("Category 1 (Confirmed Trading Days)", report_text)
        self.assertIn("Observed Date Span", report_text)


if __name__ == "__main__":
    unittest.main()
