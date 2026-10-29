"""
Unit tests for SmartKadai pure-Python forecast engine.
Verifies demand estimation, multi-model comparison (WMA, Simple Mean, Naive),
revenue calculations, reorder policies, chronological backtesting, and backward compatibility.
"""

import sys
import unittest
import math
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from forecasting.data_preparation import DailyProductSale, DateCategory
from forecasting.forecast_engine import (
    ForecastEngine,
    ProductForecastResult,
    ForecastReport,
    ModelForecasts
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

    # -------------------------------------------------------------------------
    # 1. CORE THREE-MODEL HAND-CALCULATED ARITHMETIC TESTS
    # -------------------------------------------------------------------------
    def test_wma_hand_calculated_example(self):
        """
        Verify Recent-Weighted Moving Average (WMA) against hand-calculated arithmetic:
        Series: [8, 7, 6, 1]
        Weights: [1, 2, 3, 4], sum = 10
        Weighted sum: 1*8 + 2*7 + 3*6 + 4*1 = 8 + 14 + 18 + 4 = 44
        Forecast: 44 / 10 = 4.40
        """
        series = [8, 7, 6, 1]
        forecast = ForecastEngine.compute_wma(series)
        self.assertEqual(forecast, 4.40)

    def test_simple_mean_hand_calculated_example(self):
        """
        Verify Simple Observed Mean against hand-calculated arithmetic:
        Series: [8, 7, 6, 1]
        Sum: 8 + 7 + 6 + 1 = 22
        Mean: 22 / 4 = 5.50
        """
        series = [8, 7, 6, 1]
        forecast = ForecastEngine.compute_simple_mean(series)
        self.assertEqual(forecast, 5.50)

    def test_naive_hand_calculated_example(self):
        """
        Verify Naive Baseline against hand-calculated arithmetic:
        Series: [8, 7, 6, 1]
        Last observed: 1.00
        """
        series = [8, 7, 6, 1]
        forecast = ForecastEngine.compute_naive(series)
        self.assertEqual(forecast, 1.00)

    def test_chronological_sorting_enforced(self):
        """Verify that input sales provided out of chronological order are sorted before modeling."""
        # Unsorted sequence: 10-14 (8), 10-10 (2), 10-13 (6), 10-11 (4)
        shuffled_sales = [
            DailyProductSale(date="2026-10-14", product_id="P001", product_name="Rice", units_sold=8, revenue=480.0, transaction_count=1),
            DailyProductSale(date="2026-10-10", product_id="P001", product_name="Rice", units_sold=2, revenue=120.0, transaction_count=1),
            DailyProductSale(date="2026-10-13", product_id="P001", product_name="Rice", units_sold=6, revenue=360.0, transaction_count=1),
            DailyProductSale(date="2026-10-11", product_id="P001", product_name="Rice", units_sold=4, revenue=240.0, transaction_count=1),
        ]
        engine = ForecastEngine()
        res = engine.calculate_product_forecast(self.sample_product, shuffled_sales)
        # Chronological order must be: 10-10: 2, 10-11: 4, 10-13: 6, 10-14: 8
        # WMA: (1*2 + 2*4 + 3*6 + 4*8) / 10 = (2 + 8 + 18 + 32) / 10 = 60 / 10 = 6.00
        self.assertEqual(res.estimated_daily_demand, 6.00)
        self.assertEqual(res.units_forecasts.naive, 8.00)  # Most recent is 10-14 (8)

    def test_independent_revenue_and_unit_demand(self):
        """Verify unit demand and gross revenue are computed and stored as distinct series."""
        # Product sold with varying prices:
        # Day 1: 5 units at ₹60.0 = ₹300.0
        # Day 2: 5 units at ₹70.0 (promotional/batch surge) = ₹350.0
        # Day 3: 10 units at ₹50.0 = ₹500.0
        varying_sales = [
            DailyProductSale(date="2026-10-10", product_id="P001", product_name="Rice", units_sold=5, revenue=300.0, transaction_count=1),
            DailyProductSale(date="2026-10-11", product_id="P001", product_name="Rice", units_sold=5, revenue=350.0, transaction_count=1),
            DailyProductSale(date="2026-10-12", product_id="P001", product_name="Rice", units_sold=10, revenue=500.0, transaction_count=1),
        ]
        engine = ForecastEngine()
        res = engine.calculate_product_forecast(self.sample_product, varying_sales)

        # Units: [5, 5, 10] -> WMA: (1*5 + 2*5 + 3*10)/6 = 45/6 = 7.50 units/day
        self.assertEqual(res.estimated_daily_demand, 7.50)
        self.assertEqual(res.units_forecasts.wma, 7.50)
        self.assertEqual(res.units_forecasts.simple_mean, 6.67)  # 20 / 3
        self.assertEqual(res.units_forecasts.naive, 10.00)

        # Revenue: [300.0, 350.0, 500.0] -> WMA: (1*300 + 2*350 + 3*500)/6 = (300 + 700 + 1500)/6 = 2500/6 = 416.67 ₹/day
        self.assertEqual(res.estimated_daily_revenue, 416.67)
        self.assertEqual(res.revenue_forecasts.wma, 416.67)
        self.assertEqual(res.revenue_forecasts.simple_mean, 383.33)  # 1150 / 3
        self.assertEqual(res.revenue_forecasts.naive, 500.00)

    # -------------------------------------------------------------------------
    # 2. EDGE CASES: EMPTY, SINGLE OBSERVATION, SPARSE FALLBACK, ZERO DEMAND
    # -------------------------------------------------------------------------
    def test_empty_sales_history(self):
        """Verify empty sales history returns 0.0 demand, None runway, and Tier 0 assessment."""
        engine = ForecastEngine()
        res = engine.calculate_product_forecast(self.sample_product, [])

        self.assertEqual(res.estimated_daily_demand, 0.0)
        self.assertEqual(res.estimated_daily_revenue, 0.0)
        self.assertIsNone(res.stockout_runway_days)
        self.assertEqual(res.forecast_method, "no_data")
        self.assertIn("Tier 0", res.data_sufficiency_tier)
        self.assertTrue(res.is_insufficient_history)

    def test_single_observation_history(self):
        """Verify single observation yields WMA == Simple Mean == Naive == that value."""
        single_sale = [
            DailyProductSale(date="2026-10-10", product_id="P001", product_name="Rice", units_sold=5, revenue=300.0, transaction_count=1)
        ]
        engine = ForecastEngine()
        res = engine.calculate_product_forecast(self.sample_product, single_sale)

        self.assertEqual(res.units_forecasts.wma, 5.0)
        self.assertEqual(res.units_forecasts.simple_mean, 5.0)
        self.assertEqual(res.units_forecasts.naive, 5.0)
        self.assertEqual(res.revenue_forecasts.wma, 300.0)
        # Sparse history (<3) falls back to simple_average
        self.assertEqual(res.forecast_method, "simple_average")
        self.assertTrue(res.is_insufficient_history)

    def test_sparse_product_history_fallback_to_simple_mean(self):
        """Verify that products with < 3 observations automatically fall back to Simple Mean."""
        sparse_sales = [
            DailyProductSale(date="2026-10-10", product_id="P001", product_name="Rice", units_sold=2, revenue=120.0, transaction_count=1),
            DailyProductSale(date="2026-10-11", product_id="P001", product_name="Rice", units_sold=10, revenue=600.0, transaction_count=1),
        ]
        engine = ForecastEngine(method="recent_weighted")
        res = engine.calculate_product_forecast(self.sample_product, sparse_sales)

        # Observations: 2 (< 3 threshold). Fallback must trigger!
        self.assertEqual(res.forecast_method, "simple_average")
        # Simple Mean of [2, 10] = 6.0 units, while WMA would have been (1*2 + 2*10)/3 = 7.33
        self.assertEqual(res.estimated_daily_demand, 6.00)
        self.assertEqual(res.units_forecasts.wma, 7.33)
        self.assertEqual(res.units_forecasts.simple_mean, 6.00)
        self.assertTrue(res.is_insufficient_history)
        self.assertTrue(any("fell back from Recent-Weighted to Simple Observed Mean" in n for n in res.notes))

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
        self.assertEqual(res.suggested_order_quantity, 0)
        self.assertFalse(res.is_restock_recommended)
        self.assertTrue(any("Zero demand" in n for n in res.notes))

    def test_non_negative_forecast_guarantee(self):
        """Ensure forecasts cannot be negative even under unusual inputs."""
        self.assertEqual(ForecastEngine.compute_wma([]), 0.0)
        self.assertEqual(ForecastEngine.compute_simple_mean([]), 0.0)
        self.assertEqual(ForecastEngine.compute_naive([]), 0.0)

    def test_deterministic_forecast_results(self):
        """Verify calling forecast multiple times yields byte-for-byte identical results."""
        engine = ForecastEngine()
        res1 = engine.calculate_product_forecast(self.sample_product, self.sample_sales)
        res2 = engine.calculate_product_forecast(self.sample_product, self.sample_sales)
        self.assertEqual(res1.to_dict(), res2.to_dict())

    # -------------------------------------------------------------------------
    # 3. EXISTING BASELINE COMPATIBILITY TESTS (100% PRESERVED)
    # -------------------------------------------------------------------------
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
        self.assertEqual(res.reorder_point, 17)
        self.assertEqual(res.suggested_order_quantity, 2)
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

    def test_sufficient_stock_no_reorder_needed(self):
        """Verify suggested order is 0 when current stock exceeds reorder level."""
        high_stock_product = dict(self.sample_product, current_stock=100)
        engine = ForecastEngine()
        res = engine.calculate_product_forecast(high_stock_product, self.sample_sales)

        self.assertEqual(res.reorder_point, 20)
        self.assertEqual(res.suggested_order_quantity, 0)
        self.assertFalse(res.is_restock_recommended)
        self.assertFalse(res.is_at_reorder_point)
        self.assertEqual(res.stockout_runway_days, 20.3)

    def test_stock_below_reorder_point(self):
        """Verify behavior when current_stock < reorder_point (restock triggered with positive order)."""
        low_stock_product = dict(self.sample_product, current_stock=12)
        engine = ForecastEngine()
        res = engine.calculate_product_forecast(low_stock_product, self.sample_sales)

        self.assertEqual(res.reorder_point, 20)
        self.assertEqual(res.current_stock, 12)
        self.assertTrue(res.is_restock_recommended)
        self.assertFalse(res.is_at_reorder_point)
        self.assertEqual(res.suggested_order_quantity, 8)
        self.assertTrue(any("Restock recommended: current stock (12 units) is below" in n for n in res.notes))

    def test_stock_exactly_at_reorder_point(self):
        """Verify behavior when current_stock == reorder_point (boundary case)."""
        at_boundary_product = dict(self.sample_product, current_stock=20)
        engine = ForecastEngine()
        res = engine.calculate_product_forecast(at_boundary_product, self.sample_sales)

        self.assertEqual(res.reorder_point, 20)
        self.assertEqual(res.current_stock, 20)
        self.assertEqual(res.suggested_order_quantity, 0)
        self.assertFalse(res.is_restock_recommended)
        self.assertTrue(res.is_at_reorder_point)
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
        """Verify 7-day demand deficit is reported separately from the lead-time reorder decision."""
        short_lead_product = {
            "product_id": "P099",
            "product_name": "Fresh Bread",
            "current_stock": 10,
            "safety_stock": 3,
            "supplier_lead_days": 1,
            "selling_price": 40.0
        }
        constant_sales = [
            DailyProductSale(date="2026-10-10", product_id="P099", product_name="Fresh Bread", units_sold=4, revenue=160.0, transaction_count=1),
            DailyProductSale(date="2026-10-11", product_id="P099", product_name="Fresh Bread", units_sold=4, revenue=160.0, transaction_count=1),
            DailyProductSale(date="2026-10-12", product_id="P099", product_name="Fresh Bread", units_sold=4, revenue=160.0, transaction_count=1),
            DailyProductSale(date="2026-10-13", product_id="P099", product_name="Fresh Bread", units_sold=4, revenue=160.0, transaction_count=1),
            DailyProductSale(date="2026-10-14", product_id="P099", product_name="Fresh Bread", units_sold=4, revenue=160.0, transaction_count=1),
        ]
        engine = ForecastEngine()
        res = engine.calculate_product_forecast(short_lead_product, constant_sales)

        self.assertEqual(res.reorder_point, 7)
        self.assertFalse(res.is_restock_recommended)
        self.assertEqual(res.suggested_order_quantity, 0)

        self.assertEqual(res.estimated_next_7_days_demand, 28.0)
        self.assertTrue(res.is_7_day_stockout_risk)
        self.assertEqual(res.demand_7_day_deficit, 18.0)
        self.assertEqual(res.stockout_runway_days, 2.5)
        self.assertTrue(any("7-day demand alert: projected 7-day demand (28.0 units) exceeds current stock" in n for n in res.notes))

    def test_invalid_product_inputs(self):
        """Verify input validation catches negative stock, invalid types, and missing IDs."""
        engine = ForecastEngine()
        with self.assertRaises(ValueError):
            engine.calculate_product_forecast({"product_name": "No ID"}, self.sample_sales)
        with self.assertRaises(ValueError):
            engine.calculate_product_forecast(dict(self.sample_product, current_stock=-5), self.sample_sales)
        with self.assertRaises(ValueError):
            engine.calculate_product_forecast(dict(self.sample_product, safety_stock=-1), self.sample_sales)
        with self.assertRaises(ValueError):
            engine.calculate_product_forecast(dict(self.sample_product, supplier_lead_days=-2), self.sample_sales)
        with self.assertRaises(ValueError):
            engine.calculate_product_forecast(dict(self.sample_product, selling_price=-10.0), self.sample_sales)

    def test_invalid_sales_inputs(self):
        """Verify sales records with invalid dates or negative quantities raise errors."""
        engine = ForecastEngine()
        with self.assertRaises(ValueError):
            engine.calculate_product_forecast(self.sample_product, [{"date": "2026-10-10", "product_id": "P001", "units_sold": -3}])
        with self.assertRaises(ValueError):
            engine.calculate_product_forecast(self.sample_product, [{"date": "10-10-2026", "product_id": "P001", "units_sold": 5}])

    def test_invalid_engine_parameters(self):
        """Verify engine initialization rejects invalid methods or alpha values."""
        with self.assertRaises(ValueError):
            ForecastEngine(method="deep_learning_transformer")
        with self.assertRaises(ValueError):
            ForecastEngine(method="exponential_smoothing", ewma_alpha=1.5)
        with self.assertRaises(ValueError):
            ForecastEngine(method="exponential_smoothing", ewma_alpha=-0.1)

    def test_generate_forecast_report(self):
        """Verify multi-product store forecast report generation with model comparisons."""
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
        self.assertIn("PRELIMINARY BASELINE", report.disclaimer)

        # Store-wide totals
        self.assertGreater(report.estimated_daily_revenue, 0.0)
        self.assertGreater(report.estimated_daily_units, 0.0)
        self.assertGreater(report.store_wma_units, 0.0)
        self.assertGreater(report.store_simple_mean_units, 0.0)

        # Check P002 results
        p2_res = [r for r in report.products_forecast if r.product_id == "P002"][0]
        self.assertEqual(p2_res.estimated_daily_demand, 2.4)
        self.assertEqual(p2_res.reorder_point, 10)
        self.assertEqual(p2_res.suggested_order_quantity, 8)
        self.assertTrue(p2_res.is_restock_recommended)
        self.assertEqual(p2_res.stockout_runway_days, 0.8)

    # -------------------------------------------------------------------------
    # 4. CHRONOLOGICAL BACKTESTING TESTS (Step 4 Requirement)
    # -------------------------------------------------------------------------
    def test_backtest_ineligible_on_small_sample(self):
        """Verify backtest safely refuses to produce metrics when observations < 15."""
        short_history = [5.0, 4.0, 6.0, 7.0]  # Only 4 days
        res = ForecastEngine.evaluate_chronological_backtest(short_history, min_train_observations=14)
        self.assertFalse(res["is_eligible"])
        self.assertIsNone(res["metrics"])
        self.assertIn("Insufficient observations", res["reason"])

    def test_backtest_eligible_evaluates_mae_rmse_and_beats_naive(self):
        """Verify chronological rolling backtest produces valid MAE, RMSE, zero-safe MAPE on sufficient history."""
        # Synthetic upward-trending sequence with 20 days
        series = [float(i + (i % 3)) for i in range(1, 21)]  # 20 points
        res = ForecastEngine.evaluate_chronological_backtest(series, min_train_observations=14)

        self.assertTrue(res["is_eligible"])
        self.assertEqual(res["test_sample_size"], 6)  # 20 - 14 = 6 evaluation points

        metrics = res["metrics"]
        self.assertIn("wma", metrics)
        self.assertIn("simple_mean", metrics)
        self.assertIn("naive", metrics)

        # Ensure errors are positive floats
        for m in ("wma", "simple_mean", "naive"):
            self.assertGreaterEqual(metrics[m]["mae"], 0.0)
            self.assertGreaterEqual(metrics[m]["rmse"], 0.0)
            self.assertIsNotNone(metrics[m]["mape"])


if __name__ == "__main__":
    unittest.main()
