"""
Unit tests for SmartKadai pure-Python forecast engine.
Verifies demand estimation, reorder calculations, runway, zero demand,
insufficient history, and input validation without touching any live database.
"""

import sys
import unittest
import math
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from forecasting.data_preparation import DailyProductSale
from forecasting.forecast_engine import (
    ForecastEngine,
    ProductForecastResult,
    ForecastReport
)


class TestForecastEngine(unittest.TestCase):
    """Test suite for ForecastEngine."""

    def setUp(self):
        self.sample_product = {
            "product_id": "P001",
            "product_name": "Ponni Rice 5kg",
            "current_stock": 15,
            "safety_stock": 5,
            "supplier_lead_days": 3,
            "selling_price": 60.0
        }

        # 5 days of sales for P001: [2, 4, 0, 6, 8]
        self.sample_sales = [
            DailyProductSale(date="2026-10-10", product_id="P001", product_name="Ponni Rice 5kg", units_sold=2, revenue=120.0, transaction_count=1, is_zero_filled=False),
            DailyProductSale(date="2026-10-11", product_id="P001", product_name="Ponni Rice 5kg", units_sold=4, revenue=240.0, transaction_count=1, is_zero_filled=False),
            DailyProductSale(date="2026-10-12", product_id="P001", product_name="Ponni Rice 5kg", units_sold=0, revenue=0.0, transaction_count=0, is_zero_filled=True), # Unrecorded day
            DailyProductSale(date="2026-10-13", product_id="P001", product_name="Ponni Rice 5kg", units_sold=6, revenue=360.0, transaction_count=2, is_zero_filled=False),
            DailyProductSale(date="2026-10-14", product_id="P001", product_name="Ponni Rice 5kg", units_sold=8, revenue=480.0, transaction_count=1, is_zero_filled=False),
        ]

    def test_recent_weighted_moving_average(self):
        """Test linear recent-weighted moving average calculation."""
        engine = ForecastEngine(method="recent_weighted", insufficient_history_days=7)
        res = engine.calculate_product_forecast(self.sample_product, self.sample_sales)

        # Sales: [2, 4, 0, 6, 8]
        # Weights: [1, 2, 3, 4, 5], sum = 15
        # Weighted sum: (1*2) + (2*4) + (3*0) + (4*6) + (5*8) = 2 + 8 + 0 + 24 + 40 = 74
        # Expected daily demand: 74 / 15 = 4.9333... -> 4.93
        self.assertEqual(res.estimated_daily_demand, 4.93)
        self.assertEqual(res.historical_units_sold, 20)
        self.assertEqual(res.historical_total_days, 5)
        self.assertEqual(res.historical_active_days, 4)
        self.assertEqual(res.zero_sales_days, 1)

        # 7-day demand: 4.93 * 7 = 34.51
        self.assertEqual(res.estimated_next_7_days_demand, round(4.93 * 7, 2))

        # Reorder point: ceil(4.93 * 3) + 5 = ceil(14.79) + 5 = 15 + 5 = 20
        expected_reorder = math.ceil(4.93 * 3) + 5
        self.assertEqual(res.reorder_point, 20)

        # Suggested order: max(0, 20 - 15) = 5
        self.assertEqual(res.suggested_order_quantity, 5)
        self.assertTrue(res.is_restock_recommended)

        # Stockout runway: 15 / 4.93 = 3.04... -> 3.0 days
        self.assertEqual(res.stockout_runway_days, 3.0)

        # Check assumptions & transparency
        self.assertTrue(res.is_experimental)
        self.assertTrue(res.is_insufficient_history)  # 5 days < 7 days threshold
        self.assertTrue(any("unrecorded calendar day(s)" in a for a in res.data_assumptions))

    def test_simple_average_method(self):
        """Test simple arithmetic average forecasting."""
        engine = ForecastEngine(method="simple_average")
        res = engine.calculate_product_forecast(self.sample_product, self.sample_sales)

        # Sales: [2, 4, 0, 6, 8], sum = 20, len = 5 -> average = 4.0
        self.assertEqual(res.estimated_daily_demand, 4.0)
        self.assertEqual(res.estimated_next_7_days_demand, 28.0)
        # Reorder point: ceil(4.0 * 3) + 5 = 12 + 5 = 17
        self.assertEqual(res.reorder_point, 17)
        # Current stock = 15 -> suggested order = 17 - 15 = 2
        self.assertEqual(res.suggested_order_quantity, 2)
        # Stockout runway: 15 / 4.0 = 3.75 -> 3.8 days
        self.assertEqual(res.stockout_runway_days, 3.8)

    def test_exponential_smoothing_method(self):
        """Test exponential smoothing (EWMA) method."""
        engine = ForecastEngine(method="exponential_smoothing", ewma_alpha=0.5)
        res = engine.calculate_product_forecast(self.sample_product, self.sample_sales)

        # y = [2, 4, 0, 6, 8]
        # s_1 = 2
        # s_2 = 0.5*4 + 0.5*2 = 3.0
        # s_3 = 0.5*0 + 0.5*3.0 = 1.5
        # s_4 = 0.5*6 + 0.5*1.5 = 3.75
        # s_5 = 0.5*8 + 0.5*3.75 = 5.875 -> 5.88
        self.assertEqual(res.estimated_daily_demand, 5.88)
        self.assertEqual(res.estimated_next_7_days_demand, round(5.88 * 7, 2))

    def test_zero_demand_handling(self):
        """Verify handling when product has 0 units sold across all days."""
        zero_sales = [
            DailyProductSale(date="2026-10-10", product_id="P001", product_name="Ponni Rice 5kg", units_sold=0, revenue=0.0, transaction_count=0, is_zero_filled=True),
            DailyProductSale(date="2026-10-11", product_id="P001", product_name="Ponni Rice 5kg", units_sold=0, revenue=0.0, transaction_count=0, is_zero_filled=True),
        ]
        engine = ForecastEngine()
        res = engine.calculate_product_forecast(self.sample_product, zero_sales)

        self.assertEqual(res.historical_units_sold, 0)
        self.assertEqual(res.estimated_daily_demand, 0.0)
        self.assertEqual(res.estimated_next_7_days_demand, 0.0)
        self.assertIsNone(res.stockout_runway_days)  # No depletion rate
        # Reorder point: ceil(0 * 3) + 5 = 5 (safety stock)
        self.assertEqual(res.reorder_point, 5)
        # Current stock is 15 > 5, suggested order = 0
        self.assertEqual(res.suggested_order_quantity, 0)
        self.assertFalse(res.is_restock_recommended)
        self.assertTrue(any("Zero demand" in n for n in res.notes))

    def test_sufficient_stock_no_reorder_needed(self):
        """Verify suggested order is 0 when current stock exceeds reorder level."""
        high_stock_product = dict(self.sample_product)
        high_stock_product["current_stock"] = 100  # Plenty of stock
        engine = ForecastEngine()
        res = engine.calculate_product_forecast(high_stock_product, self.sample_sales)

        self.assertEqual(res.reorder_point, 20)
        self.assertEqual(res.suggested_order_quantity, 0)
        self.assertFalse(res.is_restock_recommended)
        self.assertFalse(res.is_at_reorder_point)
        # Runway: 100 / 4.93 = 20.28... -> 20.3 days
        self.assertEqual(res.stockout_runway_days, 20.3)

    def test_stock_below_reorder_point(self):
        """Verify behavior when current_stock < reorder_point (restock triggered with positive order)."""
        # Reorder point is 20 for this product with WMA demand (4.93 * 3 = 14.79 -> 15 + 5 = 20)
        low_stock_product = dict(self.sample_product, current_stock=12)
        engine = ForecastEngine()
        res = engine.calculate_product_forecast(low_stock_product, self.sample_sales)

        self.assertEqual(res.reorder_point, 20)
        self.assertEqual(res.current_stock, 12)
        # Stock is below reorder point: restock recommended
        self.assertTrue(res.is_restock_recommended)
        self.assertFalse(res.is_at_reorder_point)
        # Suggested order equals the exact deficit: 20 - 12 = 8
        self.assertEqual(res.suggested_order_quantity, 8)
        self.assertTrue(any("Restock recommended: current stock (12 units) is below" in n for n in res.notes))

    def test_stock_exactly_at_reorder_point(self):
        """Verify behavior when current_stock == reorder_point (boundary case)."""
        # Reorder point is 20. Set current_stock to exactly 20.
        at_boundary_product = dict(self.sample_product, current_stock=20)
        engine = ForecastEngine()
        res = engine.calculate_product_forecast(at_boundary_product, self.sample_sales)

        self.assertEqual(res.reorder_point, 20)
        self.assertEqual(res.current_stock, 20)
        # Stock is precisely at boundary: deficit is 0
        self.assertEqual(res.suggested_order_quantity, 0)
        # Under deficit-to-reorder policy, restock is False when deficit is 0
        self.assertFalse(res.is_restock_recommended)
        self.assertTrue(res.is_at_reorder_point)
        # Explanatory note is explicitly recorded
        self.assertTrue(any("Stock is exactly at reorder threshold (20 == 20 units)" in n for n in res.notes))

    def test_stock_above_reorder_point(self):
        """Verify behavior when current_stock > reorder_point."""
        above_product = dict(self.sample_product, current_stock=28)
        engine = ForecastEngine()
        res = engine.calculate_product_forecast(above_product, self.sample_sales)

        self.assertEqual(res.reorder_point, 20)
        self.assertEqual(res.current_stock, 28)
        self.assertEqual(res.suggested_order_quantity, 0)
        self.assertFalse(res.is_restock_recommended)
        self.assertFalse(res.is_at_reorder_point)

    def test_7_day_demand_exceeding_stock_reported_separately_from_lead_time_reorder(self):
        """
        Verify that a 7-day demand deficit is reported separately from the lead-time reorder decision.
        Scenario: Supplier lead time is short (1 day), so current stock is sufficient for lead time,
        but consumer demand over 7 days will deplete shelf stock.
        """
        short_lead_product = {
            "product_id": "P099",
            "product_name": "Fresh Bread",
            "current_stock": 10,
            "safety_stock": 3,
            "supplier_lead_days": 1,  # Fast delivery (1 day)
            "selling_price": 40.0
        }
        # Daily sales: [4, 4, 4, 4, 4] -> daily demand = 4.0 units/day
        constant_sales = [
            DailyProductSale(date="2026-10-10", product_id="P099", product_name="Fresh Bread", units_sold=4, revenue=160.0, transaction_count=1, is_zero_filled=False),
            DailyProductSale(date="2026-10-11", product_id="P099", product_name="Fresh Bread", units_sold=4, revenue=160.0, transaction_count=1, is_zero_filled=False),
            DailyProductSale(date="2026-10-12", product_id="P099", product_name="Fresh Bread", units_sold=4, revenue=160.0, transaction_count=1, is_zero_filled=False),
            DailyProductSale(date="2026-10-13", product_id="P099", product_name="Fresh Bread", units_sold=4, revenue=160.0, transaction_count=1, is_zero_filled=False),
            DailyProductSale(date="2026-10-14", product_id="P099", product_name="Fresh Bread", units_sold=4, revenue=160.0, transaction_count=1, is_zero_filled=False),
        ]
        engine = ForecastEngine()
        res = engine.calculate_product_forecast(short_lead_product, constant_sales)

        # 1. Lead-time reorder calculations:
        # daily_demand = 4.0, lead_days = 1 -> lead_time_demand = 4.0
        # reorder_point = ceil(4.0) + 3 = 4 + 3 = 7
        self.assertEqual(res.reorder_point, 7)
        # current_stock (10) > reorder_point (7) -> Lead-time restock is NOT recommended
        self.assertFalse(res.is_restock_recommended)
        self.assertEqual(res.suggested_order_quantity, 0)

        # 2. 7-Day Planning Horizon Check (reported independently):
        # 7-day demand = 4.0 * 7 = 28.0 units
        self.assertEqual(res.estimated_next_7_days_demand, 28.0)
        # current_stock is only 10 units -> 7-day stockout alert MUST trigger
        self.assertTrue(res.is_7_day_stockout_risk)
        # 7-day deficit = 28.0 - 10 = 18.0 units
        self.assertEqual(res.demand_7_day_deficit, 18.0)
        # Stockout runway = 10 / 4.0 = 2.5 days (stock runs out well before day 7)
        self.assertEqual(res.stockout_runway_days, 2.5)

        # Confirm note specifically mentions 7-day alert
        self.assertTrue(any("7-day demand alert: projected 7-day demand (28.0 units) exceeds current stock" in n for n in res.notes))

    def test_invalid_product_inputs(self):
        """Verify input validation catches negative stock, invalid types, and missing IDs."""
        engine = ForecastEngine()

        # Missing product_id
        with self.assertRaises(ValueError):
            engine.calculate_product_forecast({"product_name": "No ID"}, self.sample_sales)

        # Negative current_stock
        bad_stock = dict(self.sample_product, current_stock=-5)
        with self.assertRaises(ValueError):
            engine.calculate_product_forecast(bad_stock, self.sample_sales)

        # Negative safety_stock
        bad_safety = dict(self.sample_product, safety_stock=-1)
        with self.assertRaises(ValueError):
            engine.calculate_product_forecast(bad_safety, self.sample_sales)

        # Negative lead_days
        bad_lead = dict(self.sample_product, supplier_lead_days=-2)
        with self.assertRaises(ValueError):
            engine.calculate_product_forecast(bad_lead, self.sample_sales)

        # Negative price
        bad_price = dict(self.sample_product, selling_price=-10.0)
        with self.assertRaises(ValueError):
            engine.calculate_product_forecast(bad_price, self.sample_sales)

    def test_invalid_sales_inputs(self):
        """Verify sales records with invalid dates or negative quantities raise errors."""
        engine = ForecastEngine()

        # Negative units sold
        bad_qty_sale = [
            {"date": "2026-10-10", "product_id": "P001", "units_sold": -3}
        ]
        with self.assertRaises(ValueError):
            engine.calculate_product_forecast(self.sample_product, bad_qty_sale)

        # Bad date format
        bad_date_sale = [
            {"date": "10-10-2026", "product_id": "P001", "units_sold": 5}
        ]
        with self.assertRaises(ValueError):
            engine.calculate_product_forecast(self.sample_product, bad_date_sale)

    def test_invalid_engine_parameters(self):
        """Verify engine initialization rejects invalid methods or alpha values."""
        with self.assertRaises(ValueError):
            ForecastEngine(method="deep_learning_transformer")

        with self.assertRaises(ValueError):
            ForecastEngine(method="exponential_smoothing", ewma_alpha=1.5)

        with self.assertRaises(ValueError):
            ForecastEngine(method="exponential_smoothing", ewma_alpha=-0.1)

    def test_generate_forecast_report(self):
        """Verify multi-product store forecast report generation."""
        products = [
            self.sample_product,
            {
                "product_id": "P002",
                "product_name": "Refined Sugar",
                "current_stock": 2,
                "safety_stock": 5,
                "supplier_lead_days": 2,
                "selling_price": 45.0
            }
        ]
        sales = list(self.sample_sales) + [
            DailyProductSale(date="2026-10-10", product_id="P002", product_name="Refined Sugar", units_sold=3, revenue=135.0, transaction_count=1, is_zero_filled=False),
            DailyProductSale(date="2026-10-11", product_id="P002", product_name="Refined Sugar", units_sold=3, revenue=135.0, transaction_count=1, is_zero_filled=False),
            DailyProductSale(date="2026-10-12", product_id="P002", product_name="Refined Sugar", units_sold=0, revenue=0.0, transaction_count=0, is_zero_filled=True),
            DailyProductSale(date="2026-10-13", product_id="P002", product_name="Refined Sugar", units_sold=3, revenue=135.0, transaction_count=1, is_zero_filled=False),
            DailyProductSale(date="2026-10-14", product_id="P002", product_name="Refined Sugar", units_sold=3, revenue=135.0, transaction_count=1, is_zero_filled=False),
        ]

        engine = ForecastEngine()
        meta = {
            "min_date": "2026-10-10",
            "max_date": "2026-10-14",
            "total_calendar_days": 5,
            "missing_calendar_days": 1,
            "zero_fill_applied": True
        }
        report = engine.generate_forecast_report(products, sales, date_metadata=meta)

        self.assertEqual(report.total_products, 2)
        self.assertEqual(len(report.products_forecast), 2)
        self.assertEqual(report.date_range_start, "2026-10-10")
        self.assertEqual(report.date_range_end, "2026-10-14")
        self.assertIn("EXPERIMENTAL BASELINE", report.disclaimer)
        self.assertTrue(any("Missing calendar dates" in g for g in report.global_assumptions))

        # Check P002 results
        p2_res = [r for r in report.products_forecast if r.product_id == "P002"][0]
        # P002 daily units: [3, 3, 0, 3, 3] -> weighted: (1*3 + 2*3 + 3*0 + 4*3 + 5*3)/15 = (3 + 6 + 0 + 12 + 15)/15 = 36/15 = 2.4
        self.assertEqual(p2_res.estimated_daily_demand, 2.4)
        # Reorder point: ceil(2.4 * 2) + 5 = ceil(4.8) + 5 = 5 + 5 = 10
        self.assertEqual(p2_res.reorder_point, 10)
        # Current stock is 2, suggested order = 10 - 2 = 8
        self.assertEqual(p2_res.suggested_order_quantity, 8)
        self.assertTrue(p2_res.is_restock_recommended)
        # Runway: 2 / 2.4 = 0.833... -> 0.8 days
        self.assertEqual(p2_res.stockout_runway_days, 0.8)


if __name__ == "__main__":
    unittest.main()
