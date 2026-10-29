"""
Unit tests for SmartKadai forecasting data preparation and validation.
Uses an isolated temporary SQLite database — NEVER touches the real database.
"""

import os
import sys
import tempfile
import unittest
import sqlite3
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from forecasting.data_preparation import SalesDataPreparation, DailyProductSale


class TestSalesDataPreparation(unittest.TestCase):
    """Test suite for SalesDataPreparation module."""

    def setUp(self):
        """Create a temporary SQLite test database."""
        import gc
        gc.collect()
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "test_smartkadai.db"
        self._create_mock_database()

    def tearDown(self):
        """Clean up temporary files."""
        import gc
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

            # Sample Products
            conn.executemany("""
                INSERT INTO products VALUES (?, ?, ?, ?, ?, ?)
            """, [
                ("P01", "Basmati Rice", 75.0, 50, 3, 10),
                ("P02", "White Sugar", 42.0, 30, 2, 8),
                ("P03", "Cow Milk", 28.0, 20, 1, 5)
            ])

            # Sample Sales across Day 1 (2026-10-01) and Day 3 (2026-10-03).
            # Note: Day 2 (2026-10-02) is intentionally omitted to test gap handling.
            conn.executemany("""
                INSERT INTO sales (bill_id, timestamp, date, product_id, quantity_sold, selling_price)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [
                # Day 1: 2026-10-01
                ("BILL-001", "2026-10-01T10:00:00", "2026-10-01", "P01", 4, 75.0),
                ("BILL-001", "2026-10-01T10:00:00", "2026-10-01", "P02", 2, 42.0),
                ("BILL-002", "2026-10-01T10:02:30", "2026-10-01", "P01", 1, 75.0), # Rapid sale for P01 (150s after bill 1)
                
                # Day 3: 2026-10-03
                ("BILL-003", "2026-10-03T14:30:00", "2026-10-03", "P02", 5, 42.0),
                ("BILL-004", "2026-10-03T16:00:00", "2026-10-03", "P03", 6, 28.0),
                (None, None, "2026-10-03", "P01", 3, 75.0)  # Missing bill_id and timestamp
            ])

    def test_load_raw_data(self):
        """Verify reading products and sales in read-only mode."""
        prep = SalesDataPreparation(self.db_path)
        products, sales = prep.load_raw_data()
        self.assertEqual(len(products), 3)
        self.assertEqual(len(sales), 6)
        self.assertEqual(products[0]["product_id"], "P01")

    def test_aggregation_and_zero_fill_enabled(self):
        """Test continuous date indexing with missing date zero-filling."""
        prep = SalesDataPreparation(self.db_path, zero_fill_missing_dates=True)
        products, sales = prep.load_raw_data()
        aggregated, meta = prep.aggregate_daily_sales(products, sales)

        # Min: 2026-10-01, Max: 2026-10-03 -> 3 calendar days
        self.assertEqual(meta["min_date"], "2026-10-01")
        self.assertEqual(meta["max_date"], "2026-10-03")
        self.assertEqual(meta["total_calendar_days"], 3)
        self.assertEqual(meta["active_sales_days"], 2)
        self.assertEqual(meta["missing_calendar_days"], 1)
        self.assertTrue(meta["zero_fill_applied"])

        # 3 calendar days * 3 products = 9 total daily records
        self.assertEqual(len(aggregated), 9)

        # Verify Day 1 aggregation (P01: 4 + 1 = 5 units)
        day1_p01 = [r for r in aggregated if r.date == "2026-10-01" and r.product_id == "P01"][0]
        self.assertEqual(day1_p01.units_sold, 5)
        self.assertEqual(day1_p01.revenue, 375.0)
        self.assertEqual(day1_p01.transaction_count, 2)
        self.assertFalse(day1_p01.is_zero_filled)

        # Verify Day 2 (2026-10-02) is zero-filled for all 3 products
        day2_records = [r for r in aggregated if r.date == "2026-10-02"]
        self.assertEqual(len(day2_records), 3)
        for r in day2_records:
            self.assertEqual(r.units_sold, 0)
            self.assertEqual(r.revenue, 0.0)
            self.assertEqual(r.transaction_count, 0)
            self.assertTrue(r.is_zero_filled)
            self.assertFalse(r.is_synthetic)

    def test_aggregation_with_zero_fill_disabled(self):
        """Test aggregation when zero-filling is explicitly turned off."""
        prep = SalesDataPreparation(self.db_path, zero_fill_missing_dates=False)
        products, sales = prep.load_raw_data()
        aggregated, meta = prep.aggregate_daily_sales(products, sales)

        self.assertFalse(meta["zero_fill_applied"])
        # Only dates with sales: Day 1 (P01, P02) and Day 3 (P01, P02, P03) = 5 rows
        self.assertEqual(len(aggregated), 5)
        # Verify no record exists for Day 2
        day2_records = [r for r in aggregated if r.date == "2026-10-02"]
        self.assertEqual(len(day2_records), 0)

    def test_validation_detects_anomalies(self):
        """Verify data validation detects missing fields, bad formats, and rapid transactions."""
        # Inject deliberate anomalies into the test database
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO sales (bill_id, timestamp, date, product_id, quantity_sold, selling_price)
                VALUES ('BAD-DATE', '2026-10-01', '01/10/2026', 'P01', 1, 75.0)
            """)
            conn.execute("""
                INSERT INTO sales (bill_id, timestamp, date, product_id, quantity_sold, selling_price)
                VALUES ('BAD-PID', '2026-10-01T12:00:00', '2026-10-01', 'GHOST_ID', 2, 50.0)
            """)

        prep = SalesDataPreparation(self.db_path, rapid_tx_threshold_seconds=300)
        products, sales = prep.load_raw_data()
        val = prep.validate_records(products, sales)

        # Date format error should be detected
        self.assertEqual(len(val["date_format_errors"]), 1)
        self.assertEqual(val["date_format_errors"][0]["invalid_date"], "01/10/2026")

        # Referential integrity error should be detected
        self.assertEqual(len(val["referential_integrity_errors"]), 1)
        self.assertEqual(val["referential_integrity_errors"][0]["invalid_product_id"], "GHOST_ID")

        # Missing bill_id and timestamp from fixture should be counted
        self.assertGreaterEqual(len(val["missing_bill_ids"]), 1)
        self.assertGreaterEqual(len(val["missing_timestamps"]), 1)

        # Rapid transaction should be flagged (P01 on 2026-10-01 150s apart)
        self.assertGreaterEqual(len(val["rapid_transactions"]), 1)
        rapid = val["rapid_transactions"][0]
        self.assertEqual(rapid["product_id"], "P01")
        self.assertIn("150 seconds", rapid["timing_note"])

        # Critical errors flag
        self.assertTrue(val["has_critical_errors"])

    def test_full_pipeline_output(self):
        """Test full pipeline execution, CSV output, and report generation."""
        out_dir = Path(self.temp_dir.name) / "output"
        prep = SalesDataPreparation(self.db_path, zero_fill_missing_dates=True)
        res = prep.run_pipeline(output_dir=out_dir)

        self.assertEqual(res["status"], "success")
        self.assertTrue(res["report_path"].exists())
        self.assertTrue(res["csv_path"].exists())

        # Check CSV content
        with open(res["csv_path"], "r", encoding="utf-8") as f:
            lines = f.readlines()
            # Header + 9 aggregated rows = 10 lines
            self.assertEqual(len(lines), 10)
            self.assertIn("date,product_id,product_name,units_sold,revenue", lines[0])

        # Check Report content
        report_text = res["report_path"].read_text(encoding="utf-8")
        self.assertIn("SmartKadai AI Sales Forecasting", report_text)
        self.assertIn("Configurable Assumptions", report_text)
        self.assertIn("Zero-Fill Assumption Enabled", report_text)
        self.assertIn("Product Sales Aggregation Summary", report_text)


if __name__ == "__main__":
    unittest.main()
