"""
SmartKadai Automated End-to-End Workflow Test Suite.

STRICT SAFETY RULES:
- Never writes to or modifies the live database ('smartkadai.db').
- Tests execute exclusively against isolated temporary clones of 'smartkadai_test.db'.
- Does not modify 'main.py' or existing application logic.
"""

import csv
import gc
import math
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, date
from pathlib import Path

# Configure environment before Kivy imports
os.environ["KIVY_NO_ARGS"] = "1"
os.environ["KIVY_LOG_MODE"] = "PYTHON"

PROJECT_ROOT = Path(__file__).parent.resolve()
LIVE_DB_PATH = (PROJECT_ROOT / "smartkadai.db").resolve()
TEST_DB_TEMPLATE = (PROJECT_ROOT / "smartkadai_test.db").resolve()

# Ensure project root is in sys.path
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import main
from forecasting import ForecastEngine, SalesDataPreparation


class SmartKadaiE2ETestBase(unittest.TestCase):
    """Base test class providing strict database isolation and UI harness."""

    def setUp(self):
        # Safety assertion: verify live database and template existence
        self.assertTrue(LIVE_DB_PATH.exists(), f"Live DB not found at {LIVE_DB_PATH}")
        self.assertTrue(TEST_DB_TEMPLATE.exists(), f"Test DB template not found at {TEST_DB_TEMPLATE}")

        # Create isolated temporary database for this test
        self.temp_dir = tempfile.mkdtemp(prefix="smartkadai_test_")
        self.temp_db_path = (Path(self.temp_dir) / "isolated_test.db").resolve()
        shutil.copy2(TEST_DB_TEMPLATE, self.temp_db_path)

        # STRICT SAFETY CHECK: ensure temp DB is NOT the live DB
        self.assertNotEqual(
            self.temp_db_path,
            LIVE_DB_PATH,
            "CRITICAL SAFETY VIOLATION: Test database resolved to live database!"
        )

        # Override main.DB_PATH for isolated execution
        self.orig_db_path = main.DB_PATH
        main.DB_PATH = self.temp_db_path

        # Capture app messages and mock popups to avoid UI blocking
        self.captured_messages = []
        self.app = main.SmartKadaiApp()
        self.app.build()
        self.app.message = lambda title, text: self.captured_messages.append((title, text))

    def tearDown(self):
        # Restore original DB_PATH
        main.DB_PATH = self.orig_db_path

        # Cleanup Kivy widget tree and app
        if hasattr(self, "app") and self.app.root:
            self.app.root.clear_widgets()

        # Force garbage collection to release SQLite locks on Windows
        gc.collect()

        # Delete isolated temporary database
        try:
            if self.temp_db_path.exists():
                self.temp_db_path.unlink()
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir, ignore_errors=True)
        except OSError:
            pass


class TestBillingAndInventoryE2E(SmartKadaiE2ETestBase):
    """End-to-end tests for billing, calculations, stock reduction, and persistence."""

    def test_bill_calculations_and_totals(self):
        """Verify line totals, dynamic quantity adjustments, and grand total sum."""
        self.app.show_billing()

        # Find widgets
        add_btn = [w for w in self.app.root.walk() if isinstance(w, main.PrimaryButton) and "+ Add to Bill" in w.text][0]
        qty_input = [w for w in self.app.root.walk() if isinstance(w, main.StyledInput) and w.hint_text == "Qty"][0]
        spinner = [w for w in self.app.root.walk() if isinstance(w, main.Spinner)][0]

        # Select Rice (P001, ₹60.00) and set quantity = 2
        rice_key = [k for k in spinner.values if "Rice" in k][0]
        spinner.text = rice_key
        qty_input.text = "2"
        add_btn.dispatch("on_release")

        self.assertEqual(len(self.app.cart), 1)
        rice_item = self.app.cart[0]
        self.assertEqual(rice_item["product_id"], "P001")
        self.assertEqual(rice_item["quantity"], 2)
        self.assertEqual(rice_item["line_total"], 120.0)

        # Select Sugar (P002, ₹45.00) and set quantity = 3
        sugar_key = [k for k in spinner.values if "Sugar" in k][0]
        spinner.text = sugar_key
        qty_input.text = "3"
        add_btn.dispatch("on_release")

        self.assertEqual(len(self.app.cart), 2)
        sugar_item = self.app.cart[1]
        self.assertEqual(sugar_item["product_id"], "P002")
        self.assertEqual(sugar_item["quantity"], 3)
        self.assertEqual(sugar_item["line_total"], 135.0)

        # Check grand total sum
        expected_grand_total = 120.0 + 135.0  # 255.0
        actual_grand_total = sum(it["line_total"] for it in self.app.cart)
        self.assertEqual(actual_grand_total, expected_grand_total)

    def test_invalid_quantity_handling(self):
        """Verify 0, negative, and non-numeric quantities are rejected with alerts."""
        self.app.show_billing()

        add_btn = [w for w in self.app.root.walk() if isinstance(w, main.PrimaryButton) and "+ Add to Bill" in w.text][0]
        qty_input = [w for w in self.app.root.walk() if isinstance(w, main.StyledInput) and w.hint_text == "Qty"][0]

        invalid_inputs = ["0", "-1", "-10", "abc", "2.5", ""]
        for invalid_val in invalid_inputs:
            qty_input.text = invalid_val
            add_btn.dispatch("on_release")
            self.assertEqual(len(self.app.cart), 0, f"Cart accepted invalid quantity: '{invalid_val}'")
            self.assertTrue(any("Invalid Quantity" in m[0] for m in self.captured_messages))
            self.captured_messages.clear()

    def test_empty_cart_checkout(self):
        """Verify checkout button is disabled on empty cart and checkout is blocked."""
        self.app.show_billing()

        checkout_btn = [w for w in self.app.root.walk() if isinstance(w, main.Button) and "Confirm & Save Bill" in w.text][0]
        self.assertTrue(checkout_btn.disabled, "Checkout button should be disabled when cart is empty")

        # Directly invoking on_confirm_checkout on empty cart
        checkout_btn.dispatch("on_release")
        self.assertTrue(any("Empty Bill" in m[0] for m in self.captured_messages))

        # Ensure no sales rows were added
        with sqlite3.connect(self.temp_db_path) as conn:
            sales_count = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
            self.assertEqual(sales_count, 20)  # Unaltered initial count

    def test_insufficient_stock_prevention(self):
        """Verify adding more than available stock is blocked by validation."""
        self.app.show_billing()

        add_btn = [w for w in self.app.root.walk() if isinstance(w, main.PrimaryButton) and "+ Add to Bill" in w.text][0]
        qty_input = [w for w in self.app.root.walk() if isinstance(w, main.StyledInput) and w.hint_text == "Qty"][0]
        spinner = [w for w in self.app.root.walk() if isinstance(w, main.Spinner)][0]

        # Rice stock in template is 18. Try adding 25 units.
        rice_key = [k for k in spinner.values if "Rice" in k][0]
        spinner.text = rice_key
        qty_input.text = "25"
        add_btn.dispatch("on_release")

        self.assertEqual(len(self.app.cart), 0, "Item with insufficient stock was added to cart")
        self.assertTrue(any("Stock Limit Exceeded" in m[0] for m in self.captured_messages))

    def test_atomic_stock_reduction_and_sales_persistence(self):
        """Verify multi-item checkout atomically decrements stock and writes sales rows."""
        self.app.show_billing()

        add_btn = [w for w in self.app.root.walk() if isinstance(w, main.PrimaryButton) and "+ Add to Bill" in w.text][0]
        qty_input = [w for w in self.app.root.walk() if isinstance(w, main.StyledInput) and w.hint_text == "Qty"][0]
        spinner = [w for w in self.app.root.walk() if isinstance(w, main.Spinner)][0]
        checkout_btn = [w for w in self.app.root.walk() if isinstance(w, main.Button) and "Confirm & Save Bill" in w.text][0]

        # Read initial stock for Rice (P001, 18) and Sugar (P002, 25)
        with sqlite3.connect(self.temp_db_path) as conn:
            init_rice = conn.execute("SELECT current_stock FROM products WHERE product_id = 'P001'").fetchone()[0]
            init_sugar = conn.execute("SELECT current_stock FROM products WHERE product_id = 'P002'").fetchone()[0]

        # Add 2 Rice
        spinner.text = [k for k in spinner.values if "Rice" in k][0]
        qty_input.text = "2"
        add_btn.dispatch("on_release")

        # Add 3 Sugar
        spinner.text = [k for k in spinner.values if "Sugar" in k][0]
        qty_input.text = "3"
        add_btn.dispatch("on_release")

        self.assertFalse(checkout_btn.disabled)

        # Execute checkout
        checkout_btn.dispatch("on_release")

        # Cart must be cleared
        self.assertEqual(len(self.app.cart), 0)

        # Verify database changes
        with sqlite3.connect(self.temp_db_path) as conn:
            new_rice = conn.execute("SELECT current_stock FROM products WHERE product_id = 'P001'").fetchone()[0]
            new_sugar = conn.execute("SELECT current_stock FROM products WHERE product_id = 'P002'").fetchone()[0]
            self.assertEqual(new_rice, init_rice - 2)
            self.assertEqual(new_sugar, init_sugar - 3)

            # Check sales rows
            sales_rows = conn.execute("""
                SELECT sale_id, bill_id, date, timestamp, product_id, quantity_sold, selling_price
                FROM sales
                ORDER BY sale_id DESC
                LIMIT 2
            """).fetchall()

            self.assertEqual(len(sales_rows), 2)
            row_sugar = sales_rows[0]
            row_rice = sales_rows[1]

            # Verify identical bill_id across both items
            self.assertTrue(row_sugar[1].startswith("SK-"))
            self.assertEqual(row_sugar[1], row_rice[1])

            # Verify line attributes
            self.assertEqual(row_sugar[4], "P002")
            self.assertEqual(row_sugar[5], 3)
            self.assertEqual(row_sugar[6], 45.0)

            self.assertEqual(row_rice[4], "P001")
            self.assertEqual(row_rice[5], 2)
            self.assertEqual(row_rice[6], 60.0)

    def test_duplicate_bill_submission_prevention(self):
        """Verify checkout button is disabled on release, preventing double-clicks."""
        self.app.show_billing()

        add_btn = [w for w in self.app.root.walk() if isinstance(w, main.PrimaryButton) and "+ Add to Bill" in w.text][0]
        checkout_btn = [w for w in self.app.root.walk() if isinstance(w, main.Button) and "Confirm & Save Bill" in w.text][0]

        # Add 1 unit of Milk (P003)
        add_btn.dispatch("on_release")
        self.assertFalse(checkout_btn.disabled)

        # Execute checkout
        checkout_btn.dispatch("on_release")

        # Immediately after successful checkout, cart is empty and button is disabled
        self.assertEqual(len(self.app.cart), 0)
        self.assertTrue(checkout_btn.disabled)

        # Attempt second click
        checkout_btn.dispatch("on_release")

        # Verify only 1 sale row was recorded for this checkout
        with sqlite3.connect(self.temp_db_path) as conn:
            sales_count = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
            self.assertEqual(sales_count, 21)  # Exactly 1 new sale added

    def test_transaction_rollback_on_stock_conflict(self):
        """Verify atomic rollback if stock becomes insufficient during checkout."""
        self.app.show_billing()

        # Add 2 items directly to cart
        self.app.cart = [
            {"product_id": "P001", "product_name": "Rice", "selling_price": 60.0, "current_stock": 18, "quantity": 2, "line_total": 120.0},
            {"product_id": "P002", "product_name": "Sugar", "selling_price": 45.0, "current_stock": 25, "quantity": 5, "line_total": 225.0}
        ]

        # Artificially deplete Sugar stock in database to 0 to trigger mid-transaction failure
        with sqlite3.connect(self.temp_db_path) as conn:
            conn.execute("UPDATE products SET current_stock = 0 WHERE product_id = 'P002'")

        checkout_btn = [w for w in self.app.root.walk() if isinstance(w, main.Button) and "Confirm & Save Bill" in w.text][0]
        checkout_btn.disabled = False
        checkout_btn.dispatch("on_release")

        # Checkout should fail
        self.assertTrue(any("Checkout Failed" in m[0] for m in self.captured_messages))

        # Verify rollback: Rice stock must NOT have been reduced (should remain 18)
        with sqlite3.connect(self.temp_db_path) as conn:
            rice_stock = conn.execute("SELECT current_stock FROM products WHERE product_id = 'P001'").fetchone()[0]
            self.assertEqual(rice_stock, 18, "Rice stock changed despite transaction failure!")

            # No new sales rows should have been inserted
            sales_count = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
            self.assertEqual(sales_count, 20)

        # Checkout button re-enabled for retry
        self.assertFalse(checkout_btn.disabled)

    def test_forecast_refresh_after_bill(self):
        """Verify AI forecasting engine ingests new bill transactions and updates metrics."""
        # 1. Baseline forecast before sale (Primary active trading days baseline)
        prep_before = SalesDataPreparation(self.temp_db_path, zero_fill_internal_gaps=False)
        prods_raw, sales_raw_before = prep_before.load_raw_data()
        agg_before, meta_before = prep_before.aggregate_daily_sales(prods_raw, sales_raw_before)
        engine = ForecastEngine(method="recent_weighted", insufficient_history_days=7)
        rep_before = engine.generate_forecast_report(prods_raw, agg_before, meta_before)

        rice_fc_before = next(p for p in rep_before.products_forecast if p.product_id == "P001")
        initial_stock = rice_fc_before.current_stock

        # 2. Execute bill of 5 units of Rice
        self.app.show_billing()
        self.app.cart = [
            {"product_id": "P001", "product_name": "Rice", "selling_price": 60.0, "current_stock": initial_stock, "quantity": 5, "line_total": 300.0}
        ]
        checkout_btn = [w for w in self.app.root.walk() if isinstance(w, main.Button) and "Confirm & Save Bill" in w.text][0]
        checkout_btn.disabled = False
        checkout_btn.dispatch("on_release")

        # 3. Forecast after sale (Primary active trading days baseline)
        prep_after = SalesDataPreparation(self.temp_db_path, zero_fill_internal_gaps=False)
        prods_raw_after, sales_raw_after = prep_after.load_raw_data()
        self.assertEqual(len(sales_raw_after), len(sales_raw_before) + 1)

        agg_after, meta_after = prep_after.aggregate_daily_sales(prods_raw_after, sales_raw_after)
        rep_after = engine.generate_forecast_report(prods_raw_after, agg_after, meta_after)

        rice_fc_after = next(p for p in rep_after.products_forecast if p.product_id == "P001")
        self.assertEqual(rice_fc_after.current_stock, initial_stock - 5)
        # Verify runway days decreased due to lower stock
        self.assertLessEqual(rice_fc_after.stockout_runway_days, rice_fc_before.stockout_runway_days)

    def test_database_persistence_across_app_restart(self):
        """Simulate fresh app restart and verify data persistence in dashboard metrics."""
        # Execute bill: 2 units of Milk (P003, ₹30.00 = ₹60.00 total)
        self.app.show_billing()
        self.app.cart = [
            {"product_id": "P003", "product_name": "Milk", "selling_price": 30.0, "current_stock": 24, "quantity": 2, "line_total": 60.0}
        ]
        checkout_btn = [w for w in self.app.root.walk() if isinstance(w, main.Button) and "Confirm & Save Bill" in w.text][0]
        checkout_btn.disabled = False
        checkout_btn.dispatch("on_release")

        # Simulate complete app shutdown by deleting app instance
        del self.app
        gc.collect()

        # Reconnect with fresh connection via fetch_dashboard_data
        metrics = main.fetch_dashboard_data(self.temp_db_path)
        self.assertIsNone(metrics["error"])
        self.assertGreaterEqual(metrics["today_sales"], 60.0)
        self.assertGreaterEqual(metrics["today_bills"], 1)

        # Check that Milk appears in recent sales
        recent_names = [r[2] for r in metrics["recent_sales"]]
        self.assertIn("Milk", recent_names)

    def test_cart_quantity_adjustment_and_stock_limits(self):
        """Verify [+] and [-] buttons dynamically adjust line total, enforce stock limits, and remove on 0."""
        self.app.show_billing()

        add_btn = [w for w in self.app.root.walk() if isinstance(w, main.PrimaryButton) and "+ Add to Bill" in w.text][0]
        qty_input = [w for w in self.app.root.walk() if isinstance(w, main.StyledInput) and w.hint_text == "Qty"][0]
        spinner = [w for w in self.app.root.walk() if isinstance(w, main.Spinner)][0]

        # Select Rice (P001, 18 in stock, ₹60) and add 2 units
        spinner.text = [k for k in spinner.values if "Rice" in k][0]
        qty_input.text = "2"
        add_btn.dispatch("on_release")

        self.assertEqual(len(self.app.cart), 1)
        self.assertEqual(self.app.cart[0]["quantity"], 2)
        self.assertEqual(self.app.cart[0]["line_total"], 120.0)

        # Locate [+] and [-] buttons in the cart row
        cart_rows = [w for w in self.app.root.walk() if isinstance(w, main.BoxLayout) and len(w.children) == 4]
        # Find the plus and minus buttons inside the qty box
        plus_btn = [w for w in self.app.root.walk() if isinstance(w, main.Button) and w.text == "+"][0]
        minus_btn = [w for w in self.app.root.walk() if isinstance(w, main.Button) and w.text == "-"][0]

        # Click [+] -> quantity should become 3, line total 180.0
        plus_btn.dispatch("on_release")
        self.assertEqual(self.app.cart[0]["quantity"], 3)
        self.assertEqual(self.app.cart[0]["line_total"], 180.0)

        # Click [-] -> quantity should become 2, line total 120.0
        minus_btn.dispatch("on_release")
        self.assertEqual(self.app.cart[0]["quantity"], 2)
        self.assertEqual(self.app.cart[0]["line_total"], 120.0)

        # Click [-] again -> quantity 1, line total 60.0
        minus_btn.dispatch("on_release")
        self.assertEqual(self.app.cart[0]["quantity"], 1)
        self.assertEqual(self.app.cart[0]["line_total"], 60.0)

        # Click [-] when quantity is 1 -> item should be removed from cart
        minus_btn.dispatch("on_release")
        self.assertEqual(len(self.app.cart), 0)

        # Checkout button should now be disabled
        checkout_btn = [w for w in self.app.root.walk() if isinstance(w, main.Button) and "Confirm & Save Bill" in w.text][0]
        self.assertTrue(checkout_btn.disabled)

        # Re-add Rice with maximum stock (18) and test hitting [+] beyond stock
        qty_input.text = "18"
        add_btn.dispatch("on_release")
        self.assertEqual(self.app.cart[0]["quantity"], 18)

        plus_btn_max = [w for w in self.app.root.walk() if isinstance(w, main.Button) and w.text == "+"][0]
        plus_btn_max.dispatch("on_release")
        # Should stay at 18 and alert stock limit
        self.assertEqual(self.app.cart[0]["quantity"], 18)
        self.assertTrue(any("Stock Limit" in m[0] for m in self.captured_messages))

    def test_safe_cart_cancellation(self):
        """Verify 'Clear Bill' safely resets the entire cart without touching the database."""
        self.app.show_billing()

        add_btn = [w for w in self.app.root.walk() if isinstance(w, main.PrimaryButton) and "+ Add to Bill" in w.text][0]
        qty_input = [w for w in self.app.root.walk() if isinstance(w, main.StyledInput) and w.hint_text == "Qty"][0]
        spinner = [w for w in self.app.root.walk() if isinstance(w, main.Spinner)][0]
        clear_btn = [w for w in self.app.root.walk() if isinstance(w, main.Button) and "Clear Bill" in w.text][0]
        checkout_btn = [w for w in self.app.root.walk() if isinstance(w, main.Button) and "Confirm & Save Bill" in w.text][0]

        # Add Rice
        spinner.text = [k for k in spinner.values if "Rice" in k][0]
        qty_input.text = "2"
        add_btn.dispatch("on_release")

        # Add Sugar
        spinner.text = [k for k in spinner.values if "Sugar" in k][0]
        qty_input.text = "3"
        add_btn.dispatch("on_release")

        self.assertEqual(len(self.app.cart), 2)
        self.assertFalse(checkout_btn.disabled)
        self.assertFalse(clear_btn.disabled)

        # Execute safe cancellation
        clear_btn.dispatch("on_release")

        # Assert cart is clean and checkout is disabled
        self.assertEqual(len(self.app.cart), 0)
        self.assertTrue(checkout_btn.disabled)

        # Assert no sales written
        with sqlite3.connect(self.temp_db_path) as conn:
            sales_count = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
            self.assertEqual(sales_count, 20)

    def test_pre_checkout_sanity_checks(self):
        """Verify pre-checkout validation blocks invalid totals, negative prices, or over-stock items."""
        self.app.show_billing()
        checkout_btn = [w for w in self.app.root.walk() if isinstance(w, main.Button) and "Confirm & Save Bill" in w.text][0]

        # Case 1: Corrupted negative quantity in cart
        self.app.cart = [
            {"product_id": "P001", "product_name": "Rice", "selling_price": 60.0, "current_stock": 18, "quantity": -2, "line_total": -120.0}
        ]
        checkout_btn.disabled = False
        checkout_btn.dispatch("on_release")
        self.assertTrue(any("Cart Validation Error" in m[0] for m in self.captured_messages))
        self.captured_messages.clear()

        # Case 2: Over-stock quantity in cart
        self.app.cart = [
            {"product_id": "P001", "product_name": "Rice", "selling_price": 60.0, "current_stock": 18, "quantity": 99, "line_total": 5940.0}
        ]
        checkout_btn.disabled = False
        checkout_btn.dispatch("on_release")
        self.assertTrue(any("Stock Limit Exceeded" in m[0] for m in self.captured_messages))
        self.captured_messages.clear()

        # Case 3: Zero or negative grand total
        self.app.cart = [
            {"product_id": "P001", "product_name": "Rice", "selling_price": 0.0, "current_stock": 18, "quantity": 1, "line_total": 0.0}
        ]
        checkout_btn.disabled = False
        checkout_btn.dispatch("on_release")
        self.assertTrue(any("Invalid Bill Total" in m[0] for m in self.captured_messages))

        # Ensure no database changes occurred
        with sqlite3.connect(self.temp_db_path) as conn:
            sales_count = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
            self.assertEqual(sales_count, 20)

    def test_multi_product_complex_bill_with_odd_quantities(self):
        """Verify checkout with 3 distinct items, odd quantities, accurate grand total, and shared bill ID."""
        self.app.show_billing()

        add_btn = [w for w in self.app.root.walk() if isinstance(w, main.PrimaryButton) and "+ Add to Bill" in w.text][0]
        qty_input = [w for w in self.app.root.walk() if isinstance(w, main.StyledInput) and w.hint_text == "Qty"][0]
        spinner = [w for w in self.app.root.walk() if isinstance(w, main.Spinner)][0]
        checkout_btn = [w for w in self.app.root.walk() if isinstance(w, main.Button) and "Confirm & Save Bill" in w.text][0]

        # Product 1: Rice (P001, ₹60.00, stock 18) x 3 = ₹180.00
        spinner.text = [k for k in spinner.values if "Rice" in k][0]
        qty_input.text = "3"
        add_btn.dispatch("on_release")

        # Product 2: Milk (P003, ₹30.00, stock 24) x 4 = ₹120.00
        spinner.text = [k for k in spinner.values if "Milk" in k][0]
        qty_input.text = "4"
        add_btn.dispatch("on_release")

        # Product 3: Cooking Oil (P005, ₹150.00, stock 29) x 1 = ₹150.00
        spinner.text = [k for k in spinner.values if "Cooking Oil" in k][0]
        qty_input.text = "1"
        add_btn.dispatch("on_release")

        self.assertEqual(len(self.app.cart), 3)
        expected_grand_total = 180.0 + 120.0 + 150.0  # 450.0
        self.assertEqual(sum(it["line_total"] for it in self.app.cart), expected_grand_total)

        # Checkout
        checkout_btn.dispatch("on_release")

        # Verify DB updates
        with sqlite3.connect(self.temp_db_path) as conn:
            # Check stocks
            rice_stock = conn.execute("SELECT current_stock FROM products WHERE product_id = 'P001'").fetchone()[0]
            milk_stock = conn.execute("SELECT current_stock FROM products WHERE product_id = 'P003'").fetchone()[0]
            oil_stock = conn.execute("SELECT current_stock FROM products WHERE product_id = 'P005'").fetchone()[0]

            self.assertEqual(rice_stock, 18 - 3)  # 15
            self.assertEqual(milk_stock, 24 - 4)  # 20
            self.assertEqual(oil_stock, 29 - 1)   # 28

            # Check sales rows
            recent_sales = conn.execute("""
                SELECT bill_id, product_id, quantity_sold, selling_price
                FROM sales
                ORDER BY sale_id DESC
                LIMIT 3
            """).fetchall()

            self.assertEqual(len(recent_sales), 3)
            # All 3 rows must share the exact same bill_id
            shared_bill_id = recent_sales[0][0]
            self.assertTrue(shared_bill_id.startswith("SK-"))
            self.assertTrue(all(r[0] == shared_bill_id for r in recent_sales))

            # Verify line items
            pids = {r[1]: (r[2], r[3]) for r in recent_sales}
            self.assertEqual(pids["P001"], (3, 60.0))
            self.assertEqual(pids["P003"], (4, 30.0))
            self.assertEqual(pids["P005"], (1, 150.0))


class TestStockManagementAndSQLiteSafety(SmartKadaiE2ETestBase):
    """
    Phase Three automated test suite for SQLite connection safety,
    stock management, product deletion protection, supplier lead-time,
    and regression safety.
    """

    def test_sqlite_connection_safety_and_foreign_keys(self):
        """Verify get_db_connection sets PRAGMA foreign_keys = ON and busy_timeout = 5000, enforcing FK constraints."""
        conn = main.get_db_connection(self.temp_db_path)
        try:
            fk_status = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            self.assertEqual(fk_status, 1, "Foreign keys must be enabled on every connection.")

            busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            self.assertEqual(busy_timeout, 5000, "busy_timeout must be configured to 5000ms.")

            # Verify foreign-key constraint enforcement by attempting an orphan sale insert
            with self.assertRaises(sqlite3.IntegrityError):
                with conn:
                    conn.execute("""
                        INSERT INTO sales (bill_id, timestamp, date, product_id, quantity_sold, selling_price)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, ("SK-TEST-FK", "2026-10-16 12:00:00", "2026-10-16", "NON_EXISTENT_P9999", 1, 100.0))
        finally:
            conn.close()

    def test_stock_restocking_and_correct_stock_increases(self):
        """Verify quick preset restocking and custom dialog restocking increment stock accurately in DB."""
        # 1. Quick preset restock: +10 units to Rice (P001, initial stock 18)
        self.app.quick_add_stock_value("P001", "Rice", 10)

        with main.get_db_connection(self.temp_db_path) as conn:
            rice_stock = conn.execute("SELECT current_stock FROM products WHERE product_id = 'P001'").fetchone()[0]
            self.assertEqual(rice_stock, 18 + 10)  # 28

        self.assertTrue(any("Stock Added" in m[0] and "28" in m[1] for m in self.captured_messages))
        self.captured_messages.clear()

        # 2. Custom dialog restock: +15 units to Sugar (P002, initial stock 25)
        self.app.open_quick_restock_dialog("P002", "Sugar")
        popup = main.Window.children[0]
        qty_input = [w for w in popup.content.walk() if isinstance(w, main.StyledInput)][0]
        confirm_btn = [w for w in popup.content.walk() if getattr(w, "text", "") == "Confirm Add"][0]

        qty_input.text = "15"
        confirm_btn.dispatch("on_release")

        with main.get_db_connection(self.temp_db_path) as conn:
            sugar_stock = conn.execute("SELECT current_stock FROM products WHERE product_id = 'P002'").fetchone()[0]
            self.assertEqual(sugar_stock, 25 + 15)  # 40

        self.assertTrue(any("Stock Added" in m[0] and "40" in m[1] for m in self.captured_messages))

    def test_invalid_restock_quantities(self):
        """Verify zero, negative, and non-numeric restock attempts are rejected with clear messages."""
        # Case 1: Zero quantity in quick_add_stock_value
        self.app.quick_add_stock_value("P001", "Rice", 0)
        self.assertTrue(any("Invalid Quantity" in m[0] for m in self.captured_messages))
        self.captured_messages.clear()

        # Case 2: Negative quantity in quick_add_stock_value
        self.app.quick_add_stock_value("P001", "Rice", -5)
        self.assertTrue(any("Invalid Quantity" in m[0] for m in self.captured_messages))
        self.captured_messages.clear()

        # Case 3: Zero or negative in restock dialog
        self.app.open_quick_restock_dialog("P001", "Rice")
        popup = main.Window.children[0]
        qty_input = [w for w in popup.content.walk() if isinstance(w, main.StyledInput)][0]
        confirm_btn = [w for w in popup.content.walk() if getattr(w, "text", "") == "Confirm Add"][0]

        qty_input.text = "0"
        confirm_btn.dispatch("on_release")
        self.assertTrue(any("Invalid Quantity" in m[0] for m in self.captured_messages))
        self.captured_messages.clear()

        qty_input.text = "-10"
        confirm_btn.dispatch("on_release")
        self.assertTrue(any("Invalid Quantity" in m[0] for m in self.captured_messages))
        self.captured_messages.clear()

        qty_input.text = "abc"
        confirm_btn.dispatch("on_release")
        self.assertTrue(any("Invalid Quantity" in m[0] for m in self.captured_messages))

        # Ensure database stock was never modified
        with main.get_db_connection(self.temp_db_path) as conn:
            stock = conn.execute("SELECT current_stock FROM products WHERE product_id = 'P001'").fetchone()[0]
            self.assertEqual(stock, 18)

    def test_missing_or_invalid_product_id_restock(self):
        """Verify restocking a nonexistent product ID fails safely without database corruption."""
        self.app.quick_add_stock_value("NON_EXISTENT_P9999", "Ghost Product", 10)
        self.assertTrue(any("Error" in m[0] or "not found" in m[1] for m in self.captured_messages))

        with main.get_db_connection(self.temp_db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            self.assertEqual(count, 5)

    def test_product_deletion_blocked_with_sales_history(self):
        """Verify permanent deletion of a product with historical sales is strictly blocked with shopkeeper explanation."""
        # Rice (P001) has historical sales in smartkadai_test.db
        self.app.open_delete_product_dialog("P001", "Rice")
        popup = main.Window.children[0]
        del_btn = [w for w in popup.content.walk() if getattr(w, "text", "") == "Delete"][0]

        del_btn.dispatch("on_release")

        # Must display clear shopkeeper-friendly explanation
        self.assertTrue(any("Cannot Delete Product" in m[0] for m in self.captured_messages))
        self.assertTrue(any("historical sales record" in m[1] and "stock to 0" in m[1] for m in self.captured_messages))

        # Verify product is preserved in database
        with main.get_db_connection(self.temp_db_path) as conn:
            rice_row = conn.execute("SELECT product_id, product_name FROM products WHERE product_id = 'P001'").fetchone()
            self.assertIsNotNone(rice_row)
            self.assertEqual(rice_row[0], "P001")

            sales_count = conn.execute("SELECT COUNT(*) FROM sales WHERE product_id = 'P001'").fetchone()[0]
            self.assertGreater(sales_count, 0)

    def test_product_deletion_allowed_without_sales_history(self):
        """Verify safe permanent deletion of a product that has no historical sales records."""
        # Insert a clean new product without sales history
        with main.get_db_connection(self.temp_db_path) as conn:
            conn.execute("""
                INSERT INTO products (product_id, product_name, selling_price, current_stock, supplier_lead_days, safety_stock)
                VALUES ('P999', 'Temporary Unsold Item', 45.0, 10, 3, 2)
            """)

        self.app.open_delete_product_dialog("P999", "Temporary Unsold Item")
        popup = main.Window.children[0]
        del_btn = [w for w in popup.content.walk() if getattr(w, "text", "") == "Delete"][0]

        del_btn.dispatch("on_release")

        # Must report successful deletion
        self.assertTrue(any("Deleted" in m[0] for m in self.captured_messages))

        # Verify product is removed from database
        with main.get_db_connection(self.temp_db_path) as conn:
            item_row = conn.execute("SELECT product_id FROM products WHERE product_id = 'P999'").fetchone()
            self.assertIsNone(item_row)

    def test_supplier_lead_time_save_edit_and_validation(self):
        """Verify supplier lead time configuration, edit persistence, validation, and AI forecast integration."""
        # 1. Edit existing product lead time (Rice from 3 to 7 days)
        self.app.open_edit_product_dialog("P001", "Rice", 60.0, 5, supplier_lead_days=3)
        popup = main.Window.children[0]
        inputs = [w for w in popup.content.walk() if isinstance(w, main.StyledInput)]
        # inputs: [name, price, safety, lead]
        lead_inp = inputs[3]
        update_btn = [w for w in popup.content.walk() if getattr(w, "text", "") == "Update Product"][0]

        lead_inp.text = "7"
        update_btn.dispatch("on_release")

        with main.get_db_connection(self.temp_db_path) as conn:
            updated_lead = conn.execute("SELECT supplier_lead_days FROM products WHERE product_id = 'P001'").fetchone()[0]
            self.assertEqual(updated_lead, 7)

        # 2. Add new product with custom lead time
        self.captured_messages.clear()
        self.app.open_add_product_dialog()
        popup_add = main.Window.children[0]
        add_inputs = [w for w in popup_add.content.walk() if isinstance(w, main.StyledInput)]
        # add_inputs: [id, name, price, stock, safety, lead]
        add_inputs[0].text = "P888"
        add_inputs[1].text = "Toor Dal"
        add_inputs[2].text = "120.0"
        add_inputs[3].text = "30"
        add_inputs[4].text = "6"
        add_inputs[5].text = "5"
        save_btn = [w for w in popup_add.content.walk() if getattr(w, "text", "") == "Save Product"][0]

        save_btn.dispatch("on_release")

        with main.get_db_connection(self.temp_db_path) as conn:
            dal_row = conn.execute("SELECT product_name, supplier_lead_days FROM products WHERE product_id = 'P888'").fetchone()
            self.assertIsNotNone(dal_row)
            self.assertEqual(dal_row[1], 5)

        # 3. Validation rejection of negative lead time
        self.captured_messages.clear()
        self.app.open_add_product_dialog()
        popup_bad = main.Window.children[0]
        bad_inputs = [w for w in popup_bad.content.walk() if isinstance(w, main.StyledInput)]
        bad_inputs[0].text = "P777"
        bad_inputs[1].text = "Bad Lead Item"
        bad_inputs[2].text = "50.0"
        bad_inputs[3].text = "10"
        bad_inputs[4].text = "5"
        bad_inputs[5].text = "-3"
        save_bad_btn = [w for w in popup_bad.content.walk() if getattr(w, "text", "") == "Save Product"][0]

        save_bad_btn.dispatch("on_release")
        self.assertTrue(any("Validation Error" in m[0] and "non-negative" in m[1] for m in self.captured_messages))

        with main.get_db_connection(self.temp_db_path) as conn:
            bad_row = conn.execute("SELECT product_id FROM products WHERE product_id = 'P777'").fetchone()
            self.assertIsNone(bad_row)

        # 4. Verify AI sales forecast reorder calculation uses the updated lead-time value
        prep = SalesDataPreparation(self.temp_db_path, zero_fill_missing_dates=True)
        prods_raw, sales_raw = prep.load_raw_data()
        agg_daily, meta = prep.aggregate_daily_sales(prods_raw, sales_raw)

        engine = ForecastEngine()
        report = engine.generate_forecast_report(prods_raw, agg_daily, meta)

        rice_fc = next(p for p in report.products_forecast if p.product_id == "P001")
        self.assertEqual(rice_fc.supplier_lead_days, 7)
        # Expected reorder point: ceil(daily_demand * 7) + safety_stock
        expected_lead_demand = rice_fc.estimated_daily_demand * 7.0
        expected_reorder_point = math.ceil(expected_lead_demand) + rice_fc.safety_stock
        self.assertEqual(rice_fc.reorder_point, expected_reorder_point)

    def test_transaction_rollback_and_billing_regression(self):
        """Verify transaction rollback on database errors and check billing regression workflows."""
        # 1. Verify atomic rollback on transaction failure
        initial_stock = 18
        with main.get_db_connection(self.temp_db_path) as conn:
            try:
                with conn:
                    conn.execute("UPDATE products SET current_stock = 999 WHERE product_id = 'P001'")
                    # Force a constraint violation to trigger rollback
                    conn.execute("INSERT INTO sales (bill_id, timestamp, date, product_id, quantity_sold, selling_price) VALUES (?, ?, ?, ?, ?, ?)",
                                 ("SK-FAIL", "now", "now", "NON_EXISTENT_ID", 1, 10))
            except sqlite3.IntegrityError:
                pass

        with main.get_db_connection(self.temp_db_path) as conn:
            stock_after_fail = conn.execute("SELECT current_stock FROM products WHERE product_id = 'P001'").fetchone()[0]
            self.assertEqual(stock_after_fail, initial_stock, "Stock update must be rolled back on failed transaction.")

        # 2. Verify normal billing checkout regression workflow still functions correctly
        self.app.show_billing()
        self.app.cart = [
            {"product_id": "P001", "product_name": "Rice", "selling_price": 60.0, "current_stock": 18, "quantity": 2, "line_total": 120.0},
            {"product_id": "P004", "product_name": "Toor Dal", "selling_price": 45.0, "current_stock": 12, "quantity": 3, "line_total": 135.0}
        ]
        checkout_btn = [w for w in self.app.root.walk() if isinstance(w, main.Button) and "Confirm & Save Bill" in w.text][0]
        checkout_btn.disabled = False
        checkout_btn.dispatch("on_release")

        with main.get_db_connection(self.temp_db_path) as conn:
            p1_stock = conn.execute("SELECT current_stock FROM products WHERE product_id = 'P001'").fetchone()[0]
            p4_stock = conn.execute("SELECT current_stock FROM products WHERE product_id = 'P004'").fetchone()[0]
            self.assertEqual(p1_stock, 16)
            self.assertEqual(p4_stock, 9)


class TestSalesReportAndAnalytics(SmartKadaiE2ETestBase):
    """
    Phase Four automated test suite for Sales Reporting date filters,
    multi-product bill aggregation, boundary dates, and robust CSV exports.
    """

    def get_report_metrics(self):
        """Helper to extract the 4 summary card values from the active sales report screen."""
        labels = [w for w in self.app.root.walk() if isinstance(w, main.Label)]
        metrics = {}
        for lbl in labels:
            txt = getattr(lbl, "text", "")
            if txt in ["PERIOD REVENUE", "COMPLETED BILLS", "UNITS SOLD", "AVG BILL VALUE"]:
                parent = lbl.parent
                val_lbl = [w for w in parent.children if isinstance(w, main.Label) and "[b]" in w.text][0]
                val_clean = val_lbl.text.replace("[b]", "").replace("[/b]", "").replace("\u20b9", "").strip()
                metrics[txt] = val_clean
        return metrics

    def test_sales_report_date_filters_today_week_all(self):
        """Verify Today, Last 7 Days, and All Time filters report accurate revenue, bills, units, and averages."""
        # 1. 'Today' filter with reference date 2026-10-14 (has 3 sales rows in test DB)
        self.app.show_sales_report("today", reference_date=date(2026, 10, 14))
        m_today = self.get_report_metrics()
        self.assertEqual(m_today["PERIOD REVENUE"], "240.00")
        self.assertEqual(m_today["COMPLETED BILLS"], "3")
        self.assertEqual(m_today["UNITS SOLD"], "3")
        self.assertEqual(m_today["AVG BILL VALUE"], "80.00")

        # 2. 'Last 7 Days' filter with reference date 2026-10-14 (covers 2026-10-08 to 2026-10-14 inclusive)
        self.app.show_sales_report("week", reference_date=date(2026, 10, 14))
        m_week = self.get_report_metrics()
        self.assertEqual(m_week["PERIOD REVENUE"], "4,470.00")
        self.assertEqual(m_week["COMPLETED BILLS"], "20")
        self.assertEqual(m_week["UNITS SOLD"], "74")
        self.assertEqual(m_week["AVG BILL VALUE"], "223.50")

        # 3. 'All Time' filter
        self.app.show_sales_report("all", reference_date=date(2026, 10, 14))
        m_all = self.get_report_metrics()
        self.assertEqual(m_all["PERIOD REVENUE"], "4,470.00")
        self.assertEqual(m_all["COMPLETED BILLS"], "20")
        self.assertEqual(m_all["UNITS SOLD"], "74")
        self.assertEqual(m_all["AVG BILL VALUE"], "223.50")

    def test_sales_at_exact_date_boundaries(self):
        """Verify 7-day window boundary enforcement: includes lower bound, excludes outside dates."""
        # Reference date: 2026-10-17. The 7-day calendar window is 2026-10-11 to 2026-10-17 inclusive.
        # Test DB has rows on:
        # 2026-10-10: 5 rows (30 units, 1725.0) -> OUTSIDE window, must be excluded
        # 2026-10-11: 5 rows (30 units, 1920.0) -> EXACT LOWER BOUND, must be included
        # 2026-10-13: 7 rows (11 units, 585.0)  -> INSIDE window, must be included
        # 2026-10-14: 3 rows (3 units, 240.0)   -> INSIDE window, must be included
        self.app.show_sales_report("week", reference_date=date(2026, 10, 17))
        m = self.get_report_metrics()
        self.assertEqual(m["PERIOD REVENUE"], "2,745.00")
        self.assertEqual(m["COMPLETED BILLS"], "15")
        self.assertEqual(m["UNITS SOLD"], "44")
        self.assertEqual(m["AVG BILL VALUE"], "183.00")

    def test_multi_product_bill_aggregation_no_duplicate_bills(self):
        """Verify that multiple line items under the same bill_id increment completed bills count by exactly 1."""
        # Insert a 3-item bill on 2026-10-16
        with main.get_db_connection(self.temp_db_path) as conn:
            conn.execute("""
                INSERT INTO sales (bill_id, timestamp, date, product_id, quantity_sold, selling_price)
                VALUES ('SK-MULTI-BILL-01', '2026-10-16 11:00:00', '2026-10-16', 'P001', 2, 60.0),
                       ('SK-MULTI-BILL-01', '2026-10-16 11:00:00', '2026-10-16', 'P002', 1, 45.0),
                       ('SK-MULTI-BILL-01', '2026-10-16 11:00:00', '2026-10-16', 'P003', 3, 30.0)
            """)

        self.app.show_sales_report("today", reference_date=date(2026, 10, 16))
        m = self.get_report_metrics()
        # 1 unique bill, 6 units total (2+1+3), total revenue = 120 + 45 + 90 = 255.00
        self.assertEqual(m["COMPLETED BILLS"], "1")
        self.assertEqual(m["UNITS SOLD"], "6")
        self.assertEqual(m["PERIOD REVENUE"], "255.00")
        self.assertEqual(m["AVG BILL VALUE"], "255.00")

    def test_empty_date_range_graceful_handling(self):
        """Verify reports for dates with zero sales display clean zeros and empty table message without division errors."""
        self.app.show_sales_report("today", reference_date=date(2026, 12, 1))
        m = self.get_report_metrics()
        self.assertEqual(m["PERIOD REVENUE"], "0.00")
        self.assertEqual(m["COMPLETED BILLS"], "0")
        self.assertEqual(m["UNITS SOLD"], "0")
        self.assertEqual(m["AVG BILL VALUE"], "0.00")

        empty_labels = [w for w in self.app.root.walk() if isinstance(w, main.Label) and "No transactions" in getattr(w, "text", "")]
        self.assertTrue(len(empty_labels) >= 1)

    def test_csv_export_headers_and_row_totals_consistency(self):
        """Verify CSV export writes valid headers, correct row counts, and exported totals match report metrics."""
        export_file = Path(self.temp_dir) / "test_all_export.csv"
        result_path = self.app.export_sales_to_csv("all", reference_date=date(2026, 10, 14), export_path=export_file)

        self.assertIsNotNone(result_path)
        self.assertTrue(export_file.exists())

        with open(export_file, mode="r", encoding="utf-8-sig") as f:
            reader = list(csv.reader(f))

        headers = reader[0]
        self.assertEqual(headers, [
            "Sale ID", "Bill Reference", "Date", "Timestamp", "Product ID",
            "Product Name", "Quantity Sold", "Unit Price (Rs)", "Line Total (Rs)"
        ])

        data_rows = reader[1:]
        self.assertEqual(len(data_rows), 20)

        # Sum line items from exported CSV
        csv_total_units = sum(int(r[6]) for r in data_rows)
        csv_total_rev = round(sum(float(r[8]) for r in data_rows), 2)
        csv_distinct_bills = len(set(r[1] for r in data_rows))

        self.assertEqual(csv_total_units, 74)
        self.assertEqual(csv_total_rev, 4470.00)
        self.assertEqual(csv_distinct_bills, 20)

    def test_csv_export_special_characters_and_tamil(self):
        """Verify CSV export correctly preserves product names with commas, quotes, and Tamil unicode text."""
        special_name = 'அரிசி, "Super" Ponni Rice'
        with main.get_db_connection(self.temp_db_path) as conn:
            conn.execute("UPDATE products SET product_name = ? WHERE product_id = 'P001'", (special_name,))

        export_file = Path(self.temp_dir) / "test_special_export.csv"
        self.app.export_sales_to_csv("all", export_path=export_file)

        with open(export_file, mode="r", encoding="utf-8-sig") as f:
            reader = list(csv.reader(f))

        rice_rows = [r for r in reader[1:] if r[4] == "P001"]
        self.assertTrue(len(rice_rows) > 0)
        for r in rice_rows:
            self.assertEqual(r[5], special_name, "Special characters, quotes, and Tamil text must remain uncorrupted.")

    def test_csv_export_empty_report_handling(self):
        """Verify exporting an empty report safely writes headers and alerts the user without crashing."""
        export_file = Path(self.temp_dir) / "test_empty_export.csv"
        self.captured_messages.clear()
        self.app.export_sales_to_csv("today", reference_date=date(2026, 12, 1), export_path=export_file)

        self.assertTrue(export_file.exists())
        with open(export_file, mode="r", encoding="utf-8-sig") as f:
            reader = list(csv.reader(f))

        # Only header row present
        self.assertEqual(len(reader), 1)
        self.assertTrue(any("Export Notice" in m[0] or "No transactions" in m[1] for m in self.captured_messages))

    def test_sales_report_billing_integration_regression(self):
        """Verify new checkout transaction immediately reflects in sales report with updated revenue and units."""
        self.app.show_billing()
        self.app.cart = [
            {"product_id": "P001", "product_name": "Rice", "selling_price": 60.0, "current_stock": 18, "quantity": 2, "line_total": 120.0},
            {"product_id": "P004", "product_name": "Toor Dal", "selling_price": 45.0, "current_stock": 12, "quantity": 1, "line_total": 45.0}
        ]
        checkout_btn = [w for w in self.app.root.walk() if isinstance(w, main.Button) and "Confirm & Save Bill" in w.text][0]
        checkout_btn.disabled = False
        checkout_btn.dispatch("on_release")

        # Checkout completed: navigate to Today sales report
        today_date = datetime.now().date()
        self.app.show_sales_report("today", reference_date=today_date)
        m = self.get_report_metrics()
        self.assertEqual(m["COMPLETED BILLS"], "1")
        self.assertEqual(m["UNITS SOLD"], "3")
        self.assertEqual(m["PERIOD REVENUE"], "165.00")
        self.assertEqual(m["AVG BILL VALUE"], "165.00")


class TestForecastingUIIntegration(SmartKadaiE2ETestBase):
    """
    Phase Five Step 5: Automated integration tests for AI Sales Forecasting
    UI navigation, metric presentation, caching, invalidation, zero-demand display,
    and graceful error handling.
    """

    def test_forecast_screen_navigation_and_rendering(self):
        """Verify navigation to Forecast screen renders KPIs, preliminary baseline banner, and table."""
        self.app.open_section("AI Sales Forecast")
        self.assertIsNotNone(self.app.cached_forecast_report)
        report = self.app.cached_forecast_report
        self.assertEqual(report.total_products, 5)

        # Walk UI tree and collect label texts
        all_labels = [w.text for w in self.app.root.walk() if isinstance(w, main.Label) and w.text]

        # 1. Verify preliminary baseline banner is clearly displayed with 4 active trading days
        banner_present = any("PRELIMINARY BASELINE — only 4 active trading days" in txt for txt in all_labels)
        self.assertTrue(banner_present, "Preliminary baseline banner with 'only 4 active trading days' not found in UI.")

        # 2. Verify experimental baseline disclaimer text is present (backward compatibility)
        experimental_present = any("EXPERIMENTAL BASELINE" in txt for txt in all_labels)
        self.assertTrue(experimental_present, "Experimental baseline text not found in UI.")

        # 3. Verify MAE / RMSE / MAPE are strictly withheld from the UI
        self.assertFalse(any("MAE:" in txt for txt in all_labels), "MAE was unexpectedly displayed in UI.")
        self.assertFalse(any("RMSE:" in txt for txt in all_labels), "RMSE was unexpectedly displayed in UI.")
        self.assertFalse(any("MAPE:" in txt for txt in all_labels), "MAPE was unexpectedly displayed in UI.")

        # 4. Verify Next-Day & 7-Day Revenue and Units KPI cards exist in UI
        self.assertTrue(any("NEXT-DAY ESTIMATED REVENUE" in txt for txt in all_labels))
        self.assertTrue(any("NEXT-DAY ESTIMATED UNITS" in txt for txt in all_labels))
        self.assertTrue(any("7-DAY ESTIMATED REVENUE" in txt for txt in all_labels))
        self.assertTrue(any("7-DAY ESTIMATED UNITS" in txt for txt in all_labels))

        # 5. Verify store-wide totals in UI match engine report calculations
        self.assertAlmostEqual(report.estimated_daily_revenue, 828.00, places=2)
        self.assertAlmostEqual(report.estimated_daily_units, 13.50, places=2)
        self.assertAlmostEqual(report.estimated_next_7_days_revenue, 5796.00, places=2)
        self.assertAlmostEqual(report.estimated_next_7_days_units, 94.50, places=2)

        # 6. Verify table headers exist in UI
        for th in ["PRODUCT", "STOCK", "DAILY DEMAND", "7-DAY DEMAND", "RUNWAY", "REORDER PT", "LEAD-TIME STATUS", "7-DAY RISK"]:
            self.assertTrue(any(th in txt for txt in all_labels), f"Table header '{th}' missing from UI.")

    def test_forecast_caching_and_manual_refresh(self):
        """Verify calculations are cached in memory and recalculated upon manual refresh."""
        # Initial display caches the report
        self.app.show_forecast()
        rep1 = self.app.cached_forecast_report
        self.assertIsNotNone(rep1)

        # Subsequent visit without refresh reuses the exact same cached report object
        self.app.show_forecast(refresh=False)
        self.assertIs(self.app.cached_forecast_report, rep1)

        # Manual refresh generates a fresh report instance
        self.app.show_forecast(refresh=True)
        rep2 = self.app.cached_forecast_report
        self.assertIsNotNone(rep2)
        self.assertIsNot(rep2, rep1)

    def test_forecast_cache_invalidation_on_checkout_and_restock(self):
        """Verify cache is automatically invalidated when stock is updated or bills are completed."""
        self.app.show_forecast()
        self.assertIsNotNone(self.app.cached_forecast_report)

        # 1. Restock Rice via quick restock
        self.app.quick_add_stock_value("P001", "Rice", 10)
        self.assertIsNone(self.app.cached_forecast_report, "Cache was not invalidated after restock.")

        # Re-enter forecast screen: recalculates fresh report with new stock
        self.app.show_forecast()
        rice_rep = next(p for p in self.app.cached_forecast_report.products_forecast if p.product_id == "P001")
        self.assertEqual(rice_rep.current_stock, 28)  # 18 + 10 = 28

        # 2. Complete a bill checkout
        self.app.show_billing()
        self.app.cart = [
            {"product_id": "P001", "product_name": "Rice", "selling_price": 60.0, "current_stock": 28, "quantity": 3, "line_total": 180.0}
        ]
        checkout_btn = [w for w in self.app.root.walk() if isinstance(w, main.Button) and "Confirm & Save Bill" in w.text][0]
        checkout_btn.disabled = False
        checkout_btn.dispatch("on_release")

        self.assertIsNone(self.app.cached_forecast_report, "Cache was not invalidated after bill checkout.")

    def test_forecast_zero_demand_display(self):
        """Verify products with zero demand display 'No observed demand' cleanly in the table."""
        # Insert a new product that has never had any sales
        with main.get_db_connection(self.temp_db_path) as conn:
            conn.execute(
                "INSERT INTO products (product_id, product_name, selling_price, current_stock, supplier_lead_days, safety_stock) "
                "VALUES ('P999', 'Zero Demand Product', 100.0, 50, 3, 5)"
            )
        self.app.invalidate_forecast_cache()
        self.app.show_forecast(refresh=True)

        all_labels = [w.text for w in self.app.root.walk() if isinstance(w, main.Label) and w.text]
        p999_in_ui = any("Zero Demand Product" in txt for txt in all_labels)
        self.assertTrue(p999_in_ui, "New product 'Zero Demand Product' not displayed in table.")

        zero_demand_labels = [txt for txt in all_labels if "No observed demand" in txt]
        self.assertGreaterEqual(len(zero_demand_labels), 1, "'No observed demand' text not displayed for zero-sale product.")

    def test_forecast_service_graceful_error_handling(self):
        """Verify forecasting catches database/engine errors gracefully and allows returning to dashboard."""
        # Point DB_PATH to an unreadable/nonexistent file
        main.DB_PATH = Path(self.temp_dir) / "corrupt_db_not_exist.db"
        self.app.show_forecast(refresh=True)

        all_labels = [w.text for w in self.app.root.walk() if isinstance(w, main.Label) and w.text]
        notice_present = any("Forecasting Service Notice" in txt for txt in all_labels)
        self.assertTrue(notice_present, "Forecasting Service Notice card was not displayed on error.")

        # Find 'Return to Dashboard' button and activate it
        ret_btns = [w for w in self.app.root.walk() if isinstance(w, main.Button) and "Return to Dashboard" in w.text]
        self.assertEqual(len(ret_btns), 1)
        ret_btns[0].dispatch("on_release")

        # Returned to Dashboard safely
        dash_labels = [w.text for w in self.app.root.walk() if isinstance(w, main.Label) and w.text]
        self.assertTrue(any("Today's Overview" in txt for txt in dash_labels))


if __name__ == "__main__":
    unittest.main()

