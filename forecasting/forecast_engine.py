"""
SmartKadai AI Sales Forecasting - Pure-Python Forecast Engine.

Provides transparent, explainable demand estimation, multi-model comparison,
and inventory replenishment calculations using:
1. Model A: Recent-Weighted Moving Average (WMA) — Primary Baseline
2. Model B: Simple Observed Mean — Documented Fallback
3. Model C: Naive Baseline (Last-observation) — Benchmark Baseline

Strict Safety, Transparency, and Compliance Guarantees:
1. Pure Python standard library implementation (no pandas, no scikit-learn, offline-first).
2. Clearly labeled as PRELIMINARY BASELINE ESTIMATES, not trained ML predictions.
3. Separates unit demand (units/day) and gross revenue (₹/day) as independent series.
4. Non-negative constraints: forecasts are guaranteed non-negative (>= 0.00).
5. Automatic fallback to Simple Observed Mean when product history is sparse (< 3 observations).
6. Respects Step-3 4-category date policy: does not append synthetic zeroes for post-data dates.
7. Strictly read-only computation; does not mutate any database or input records.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, date
import math
from typing import Dict, List, Optional, Union, Any, Tuple

try:
    from .data_preparation import DailyProductSale, DateCategory
except ImportError:
    # Allow standalone execution
    from data_preparation import DailyProductSale, DateCategory


@dataclass
class ModelForecasts:
    """Detailed forecast for a single metric across the three baseline models."""
    wma: float
    simple_mean: float
    naive: float
    selected: float
    selected_method: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProductForecastResult:
    """Detailed forecast, model comparison, and inventory recommendation for a single product."""
    product_id: str
    product_name: str
    current_stock: int
    safety_stock: int
    supplier_lead_days: int
    selling_price: float

    # Historical observations
    historical_units_sold: int
    historical_active_days: int
    historical_total_days: int
    zero_sales_days: int

    # Primary baseline estimates (backwards compatible)
    estimated_daily_demand: float
    estimated_next_7_days_demand: float
    forecast_method: str

    # Inventory replenishment recommendations (Lead-Time Decision)
    reorder_point: int
    suggested_order_quantity: int
    stockout_runway_days: Optional[float]
    is_restock_recommended: bool
    is_at_reorder_point: bool

    # 7-day planning horizon vs available stock (reported separately from lead-time decision)
    is_7_day_stockout_risk: bool
    demand_7_day_deficit: float

    # Step 4: Three-Model Comparison (Units and Revenue)
    units_forecasts: Optional[ModelForecasts] = None
    revenue_forecasts: Optional[ModelForecasts] = None
    estimated_daily_revenue: float = 0.0
    estimated_next_7_days_revenue: float = 0.0

    # Assumptions & Transparency
    is_insufficient_history: bool = False
    data_sufficiency_tier: str = "Tier 1 — Preliminary Baseline"
    data_assumptions: List[str] = None
    notes: List[str] = None
    is_experimental: bool = True

    def __post_init__(self):
        if self.data_assumptions is None:
            self.data_assumptions = []
        if self.notes is None:
            self.notes = []

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.units_forecasts:
            d["units_forecasts"] = self.units_forecasts.to_dict()
        if self.revenue_forecasts:
            d["revenue_forecasts"] = self.revenue_forecasts.to_dict()
        return d


@dataclass
class ForecastReport:
    """Complete store forecast report across all catalog products."""
    generated_at: str
    total_products: int
    date_range_start: Optional[str]
    date_range_end: Optional[str]
    total_calendar_days: int
    forecast_method: str
    products_forecast: List[ProductForecastResult]
    global_assumptions: List[str]

    # Store-wide totals across products
    estimated_daily_revenue: float = 0.0
    estimated_next_7_days_revenue: float = 0.0
    estimated_daily_units: float = 0.0
    estimated_next_7_days_units: float = 0.0

    # Store comparison totals across the three models
    store_wma_revenue: float = 0.0
    store_simple_mean_revenue: float = 0.0
    store_naive_revenue: float = 0.0
    store_wma_units: float = 0.0
    store_simple_mean_units: float = 0.0
    store_naive_units: float = 0.0
    data_sufficiency_tier: str = "Tier 1 — Preliminary Baseline"

    disclaimer: str = (
        "PRELIMINARY BASELINE (EXPERIMENTAL BASELINE) ESTIMATES ONLY. "
        "These projections use statistical weighted moving averages on limited historical sales. "
        "They are transparent baseline estimates for inventory replenishment guidance, not trained "
        "machine learning predictions, and must not be interpreted as guaranteed sales."
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "total_products": self.total_products,
            "date_range_start": self.date_range_start,
            "date_range_end": self.date_range_end,
            "total_calendar_days": self.total_calendar_days,
            "forecast_method": self.forecast_method,
            "estimated_daily_revenue": self.estimated_daily_revenue,
            "estimated_next_7_days_revenue": self.estimated_next_7_days_revenue,
            "estimated_daily_units": self.estimated_daily_units,
            "estimated_next_7_days_units": self.estimated_next_7_days_units,
            "store_wma_revenue": self.store_wma_revenue,
            "store_simple_mean_revenue": self.store_simple_mean_revenue,
            "store_naive_revenue": self.store_naive_revenue,
            "store_wma_units": self.store_wma_units,
            "store_simple_mean_units": self.store_simple_mean_units,
            "store_naive_units": self.store_naive_units,
            "data_sufficiency_tier": self.data_sufficiency_tier,
            "global_assumptions": self.global_assumptions,
            "disclaimer": self.disclaimer,
            "products_forecast": [p.to_dict() for p in self.products_forecast]
        }


class ForecastEngine:
    """
    Pure-Python demand estimation, multi-model baseline comparison,
    and inventory replenishment calculation engine.
    """

    SUPPORTED_METHODS = ("recent_weighted", "exponential_smoothing", "simple_average", "naive")

    def __init__(
        self,
        method: str = "recent_weighted",
        ewma_alpha: float = 0.35,
        insufficient_history_days: int = 7
    ):
        """
        Initialize the forecasting engine.

        Args:
            method: Primary baseline method ('recent_weighted', 'simple_average', 'exponential_smoothing', 'naive').
            ewma_alpha: Smoothing factor for exponential smoothing (between 0.0 and 1.0).
            insufficient_history_days: Store-wide threshold below which history is flagged as preliminary.
        """
        if method not in self.SUPPORTED_METHODS:
            raise ValueError(f"Unsupported forecast method '{method}'. Supported: {self.SUPPORTED_METHODS}")
        if not (0.0 < ewma_alpha <= 1.0):
            raise ValueError(f"ewma_alpha must be between 0.0 and 1.0, got {ewma_alpha}")

        self.method = method
        self.ewma_alpha = ewma_alpha
        self.insufficient_history_days = insufficient_history_days

    @staticmethod
    def compute_wma(series: List[Union[int, float]]) -> float:
        """
        Compute Recent-Weighted Moving Average (Linear WMA) on a chronological series.
        Day 1 has weight 1, Day 2 has weight 2, ..., Day n has weight n.
        """
        if not series:
            return 0.0
        if all(v == 0 for v in series):
            return 0.0
        n = len(series)
        weights = list(range(1, n + 1))
        total_weight = sum(weights)
        weighted_sum = sum(w * float(v) for w, v in zip(weights, series))
        val = weighted_sum / total_weight
        return max(0.0, round(val, 2))

    @staticmethod
    def compute_simple_mean(series: List[Union[int, float]]) -> float:
        """Compute Simple Observed Mean (Arithmetic Average) on a series."""
        if not series:
            return 0.0
        if all(v == 0 for v in series):
            return 0.0
        val = sum(float(v) for v in series) / len(series)
        return max(0.0, round(val, 2))

    @staticmethod
    def compute_naive(series: List[Union[int, float]]) -> float:
        """Compute Naive Baseline forecast (most recent observed value)."""
        if not series:
            return 0.0
        return max(0.0, round(float(series[-1]), 2))

    def compute_ewma(self, series: List[Union[int, float]]) -> float:
        """Compute Exponential Weighted Moving Average (EWMA) on a series."""
        if not series:
            return 0.0
        if all(v == 0 for v in series):
            return 0.0
        s = float(series[0])
        for y in series[1:]:
            s = (self.ewma_alpha * float(y)) + ((1.0 - self.ewma_alpha) * s)
        return max(0.0, round(s, 2))

    def _calculate_daily_demand(
        self,
        daily_units: List[int]
    ) -> float:
        """
        Calculate estimated daily demand using the engine's configured primary method.
        Preserves backward compatibility with legacy tests.
        """
        if not daily_units:
            return 0.0
        if all(u == 0 for u in daily_units):
            return 0.0

        if self.method == "simple_average":
            return self.compute_simple_mean(daily_units)
        elif self.method == "recent_weighted":
            return self.compute_wma(daily_units)
        elif self.method == "naive":
            return self.compute_naive(daily_units)
        elif self.method == "exponential_smoothing":
            return self.compute_ewma(daily_units)

        return 0.0

    def calculate_product_forecast(
        self,
        product: Dict[str, Any],
        daily_sales: List[Union[DailyProductSale, Dict[str, Any]]]
    ) -> ProductForecastResult:
        """
        Calculate demand forecast, model comparison, and replenishment recommendations for a single product.

        Args:
            product: Product metadata dict containing 'product_id', 'product_name',
                     'current_stock', 'safety_stock', 'supplier_lead_days', 'selling_price'.
            daily_sales: List of DailyProductSale objects or dicts for this product.

        Returns:
            ProductForecastResult instance with complete calculations and transparent assumptions.
        """
        # 1. Validate product metadata inputs
        pid = str(product.get("product_id") or "").strip()
        if not pid:
            raise ValueError("Product record missing required 'product_id'")

        pname = str(product.get("product_name") or f"Product {pid}").strip()

        try:
            current_stock = int(product.get("current_stock", 0))
            if current_stock < 0:
                raise ValueError(f"current_stock cannot be negative: {current_stock}")
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid current_stock for product '{pid}': {exc}")

        try:
            safety_stock = int(product.get("safety_stock", 0))
            if safety_stock < 0:
                raise ValueError(f"safety_stock cannot be negative: {safety_stock}")
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid safety_stock for product '{pid}': {exc}")

        try:
            lead_days = int(product.get("supplier_lead_days", 0))
            if lead_days < 0:
                raise ValueError(f"supplier_lead_days cannot be negative: {lead_days}")
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid supplier_lead_days for product '{pid}': {exc}")

        try:
            price = float(product.get("selling_price", 0.0))
            if price < 0.0:
                raise ValueError(f"selling_price cannot be negative: {price}")
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid selling_price for product '{pid}': {exc}")

        # 2. Extract and sort chronological sales for this product
        product_sales = []
        data_assumptions = []
        notes = []

        zero_filled_count = 0

        for s in daily_sales:
            s_dict = s.to_dict() if hasattr(s, "to_dict") else dict(s)
            s_pid = str(s_dict.get("product_id", "")).strip()

            if s_pid != pid:
                continue

            s_date_str = str(s_dict.get("date", "")).strip()
            try:
                s_date = datetime.strptime(s_date_str, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError(f"Invalid date format '{s_date_str}' for product '{pid}'. Expected YYYY-MM-DD.")

            qty = s_dict.get("units_sold", 0)
            if not isinstance(qty, int) or qty < 0:
                raise ValueError(f"Invalid units_sold '{qty}' for product '{pid}' on '{s_date_str}'. Must be non-negative int.")

            rev = float(s_dict.get("revenue", qty * price))
            if rev < 0.0:
                raise ValueError(f"Invalid revenue '{rev}' for product '{pid}'. Must be non-negative.")

            is_zf = bool(s_dict.get("is_zero_filled", False))
            if is_zf:
                zero_filled_count += 1

            product_sales.append((s_date, qty, rev, is_zf))

        # Sort strictly chronologically
        product_sales.sort(key=lambda x: x[0])

        daily_units = [x[1] for x in product_sales]
        daily_revs = [x[2] for x in product_sales]
        total_days = len(daily_units)
        total_units = sum(daily_units)
        active_days = sum(1 for u in daily_units if u > 0)
        zero_days = sum(1 for u in daily_units if u == 0)

        # 3. Document explicit assumptions
        if zero_filled_count > 0:
            data_assumptions.append(
                f"{zero_filled_count} unrecorded calendar day(s) were assumed to have 0 sales based on zero-fill configuration."
            )

        # 4. Multi-Model Demand and Revenue Computation (Step 4)
        # Compute Model A (WMA), Model B (Simple Mean), Model C (Naive) for units and revenue
        wma_units = self.compute_wma(daily_units)
        mean_units = self.compute_simple_mean(daily_units)
        naive_units = self.compute_naive(daily_units)

        wma_rev = self.compute_wma(daily_revs)
        mean_rev = self.compute_simple_mean(daily_revs)
        naive_rev = self.compute_naive(daily_revs)

        # Determine Primary Method and Fallback:
        # Fallback Rule: If product-specific active observations < 3, fall back to Simple Observed Mean
        if total_days == 0:
            selected_method = "no_data"
            daily_demand = 0.0
            daily_rev = 0.0
            notes.append("No historical observations for this product.")
            is_insufficient = True
        elif active_days < 3 and total_days < 3:
            selected_method = "simple_average"
            daily_demand = mean_units
            daily_rev = mean_rev
            is_insufficient = True
            notes.append(
                f"Sparse product history ({total_days} observations < 3 threshold): "
                f"fell back from Recent-Weighted to Simple Observed Mean."
            )
        else:
            if self.method == "recent_weighted":
                selected_method = "recent_weighted"
                daily_demand = wma_units
                daily_rev = wma_rev
            elif self.method == "simple_average":
                selected_method = "simple_average"
                daily_demand = mean_units
                daily_rev = mean_rev
            elif self.method == "naive":
                selected_method = "naive"
                daily_demand = naive_units
                daily_rev = naive_rev
            elif self.method == "exponential_smoothing":
                selected_method = "exponential_smoothing"
                daily_demand = self.compute_ewma(daily_units)
                daily_rev = self.compute_ewma(daily_revs)
            else:
                selected_method = self.method
                daily_demand = wma_units
                daily_rev = wma_rev

            is_insufficient = total_days < self.insufficient_history_days
            if is_insufficient:
                notes.append(
                    f"Preliminary estimate: observed over {total_days} day(s) "
                    f"(store-wide threshold is {self.insufficient_history_days} days)."
                )

        units_forecasts = ModelForecasts(
            wma=wma_units,
            simple_mean=mean_units,
            naive=naive_units,
            selected=daily_demand,
            selected_method=selected_method
        )

        revenue_forecasts = ModelForecasts(
            wma=wma_rev,
            simple_mean=mean_rev,
            naive=naive_rev,
            selected=daily_rev,
            selected_method=selected_method
        )

        # 5. Inventory Replenishment Calculations
        if total_units == 0:
            notes.append("Zero demand observed across all recorded days.")
            stockout_runway = None
        else:
            if daily_demand > 0:
                stockout_runway = round(current_stock / daily_demand, 1)
            else:
                stockout_runway = None

        next_7_days_demand = round(daily_demand * 7.0, 2)
        next_7_days_revenue = round(daily_rev * 7.0, 2)

        is_7_day_stockout_risk = float(current_stock) < next_7_days_demand
        demand_7_day_deficit = round(max(0.0, next_7_days_demand - float(current_stock)), 2)

        if is_7_day_stockout_risk:
            notes.append(
                f"7-day demand alert: projected 7-day demand ({next_7_days_demand} units) "
                f"exceeds current stock ({current_stock} units) by {demand_7_day_deficit} units."
            )

        # Lead-Time Reorder Calculations:
        # Reorder Point = ceil(daily_demand * supplier_lead_days) + safety_stock
        lead_time_demand = daily_demand * float(lead_days)
        reorder_point = math.ceil(lead_time_demand) + safety_stock
        suggested_order = max(0, reorder_point - current_stock)
        is_at_reorder_point = (current_stock == reorder_point)
        is_restock_recommended = (current_stock < reorder_point)

        if is_restock_recommended:
            notes.append(
                f"Restock recommended: current stock ({current_stock} units) is below reorder point "
                f"({reorder_point} units). Deficit is {suggested_order} units."
            )
        elif is_at_reorder_point:
            notes.append(
                f"Stock is exactly at reorder threshold ({current_stock} == {reorder_point} units). "
                f"Deficit is 0 units; restock will trigger once stock drops below this threshold."
            )

        # Data Sufficiency Assessment
        if total_days == 0:
            tier_desc = "Tier 0 — No Historical Data"
        elif total_days < 7:
            tier_desc = "Tier 1 — Preliminary Baseline"
        elif total_days < 14:
            tier_desc = "Tier 2 — Experimental Baseline"
        elif total_days < 30:
            tier_desc = "Tier 3 — Evaluated Baseline"
        else:
            tier_desc = "Tier 4 — Local ML Eligible"

        return ProductForecastResult(
            product_id=pid,
            product_name=pname,
            current_stock=current_stock,
            safety_stock=safety_stock,
            supplier_lead_days=lead_days,
            selling_price=price,
            historical_units_sold=total_units,
            historical_active_days=active_days,
            historical_total_days=total_days,
            zero_sales_days=zero_days,
            estimated_daily_demand=daily_demand,
            estimated_next_7_days_demand=next_7_days_demand,
            forecast_method=selected_method,
            reorder_point=reorder_point,
            suggested_order_quantity=suggested_order,
            stockout_runway_days=stockout_runway,
            is_restock_recommended=is_restock_recommended,
            is_at_reorder_point=is_at_reorder_point,
            is_7_day_stockout_risk=is_7_day_stockout_risk,
            demand_7_day_deficit=demand_7_day_deficit,
            units_forecasts=units_forecasts,
            revenue_forecasts=revenue_forecasts,
            estimated_daily_revenue=daily_rev,
            estimated_next_7_days_revenue=next_7_days_revenue,
            is_insufficient_history=is_insufficient,
            data_sufficiency_tier=tier_desc,
            data_assumptions=data_assumptions,
            notes=notes,
            is_experimental=True
        )

    def generate_forecast_report(
        self,
        products: List[Dict[str, Any]],
        aggregated_sales: List[Union[DailyProductSale, Dict[str, Any]]],
        date_metadata: Optional[Dict[str, Any]] = None
    ) -> ForecastReport:
        """
        Generate complete store forecast report across all products with model comparisons.

        Args:
            products: List of product metadata dicts.
            aggregated_sales: Daily sales records (e.g. from SalesDataPreparation).
            date_metadata: Optional metadata dict from SalesDataPreparation.

        Returns:
            ForecastReport object containing product-level forecasts, comparison summaries, and disclaimers.
        """
        results: List[ProductForecastResult] = []

        global_assumptions = [
            f"Primary baseline method applied: '{self.method}'.",
            "Models compared: Recent-Weighted Moving Average (WMA), Simple Observed Mean, Naive Baseline.",
            "All projections are statistical baseline estimates; not trained machine learning predictions."
        ]

        if date_metadata and date_metadata.get("zero_fill_applied"):
            global_assumptions.append(
                f"Missing calendar dates ({date_metadata.get('missing_calendar_days', 0)} days) were zero-filled."
            )

        for p in products:
            res = self.calculate_product_forecast(p, aggregated_sales)
            results.append(res)

        # Compute store-wide aggregated metrics
        tot_daily_units = round(sum(p.estimated_daily_demand for p in results), 2)
        tot_7d_units = round(sum(p.estimated_next_7_days_demand for p in results), 2)
        tot_daily_rev = round(sum(p.estimated_daily_revenue for p in results), 2)
        tot_7d_rev = round(sum(p.estimated_next_7_days_revenue for p in results), 2)

        store_wma_u = round(sum(p.units_forecasts.wma for p in results if p.units_forecasts), 2)
        store_mean_u = round(sum(p.units_forecasts.simple_mean for p in results if p.units_forecasts), 2)
        store_naive_u = round(sum(p.units_forecasts.naive for p in results if p.units_forecasts), 2)

        store_wma_r = round(sum(p.revenue_forecasts.wma for p in results if p.revenue_forecasts), 2)
        store_mean_r = round(sum(p.revenue_forecasts.simple_mean for p in results if p.revenue_forecasts), 2)
        store_naive_r = round(sum(p.revenue_forecasts.naive for p in results if p.revenue_forecasts), 2)

        min_d = date_metadata.get("min_date") if date_metadata else None
        max_d = date_metadata.get("max_date") if date_metadata else None
        total_days = date_metadata.get("total_calendar_days", 0) if date_metadata else 0
        tier = date_metadata.get("data_sufficiency_tier", "Tier 1 — Preliminary Baseline") if date_metadata else "Tier 1 — Preliminary Baseline"

        return ForecastReport(
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            total_products=len(results),
            date_range_start=min_d,
            date_range_end=max_d,
            total_calendar_days=total_days,
            forecast_method=self.method,
            products_forecast=results,
            global_assumptions=global_assumptions,
            estimated_daily_revenue=tot_daily_rev,
            estimated_next_7_days_revenue=tot_7d_rev,
            estimated_daily_units=tot_daily_units,
            estimated_next_7_days_units=tot_7d_units,
            store_wma_revenue=store_wma_r,
            store_simple_mean_revenue=store_mean_r,
            store_naive_revenue=store_naive_r,
            store_wma_units=store_wma_u,
            store_simple_mean_units=store_mean_u,
            store_naive_units=store_naive_u,
            data_sufficiency_tier=tier
        )

    @staticmethod
    def evaluate_chronological_backtest(
        series: List[float],
        min_train_observations: int = 14
    ) -> Dict[str, Any]:
        """
        Perform rolling one-step-ahead chronological backtesting on a time series.

        Enforces strict temporal order (no random splitting, no future-data leakage).
        Compares WMA and Simple Mean against the Naive baseline.

        Args:
            series: Chronological sequence of observed values.
            min_train_observations: Minimum historical depth required before evaluation is valid.

        Returns:
            Dictionary with MAE, RMSE, zero-safe MAPE, and comparison metrics, or explicit notice
            if sample size is below the statistical threshold.
        """
        n = len(series)
        if n <= min_train_observations:
            return {
                "is_eligible": False,
                "reason": (
                    f"Insufficient observations for statistically valid backtesting "
                    f"({n} available; minimum {min_train_observations + 1} required). "
                    "Evaluation metrics withheld to prevent misleading precision."
                ),
                "metrics": None
            }

        wma_errors = []
        mean_errors = []
        naive_errors = []

        wma_sq_errors = []
        mean_sq_errors = []
        naive_sq_errors = []

        wma_pct_errors = []
        mean_pct_errors = []
        naive_pct_errors = []

        # Chronological rolling evaluation
        for t in range(min_train_observations, n):
            train = series[:t]
            actual = float(series[t])

            pred_wma = ForecastEngine.compute_wma(train)
            pred_mean = ForecastEngine.compute_simple_mean(train)
            pred_naive = ForecastEngine.compute_naive(train)

            # Absolute errors
            err_wma = abs(actual - pred_wma)
            err_mean = abs(actual - pred_mean)
            err_naive = abs(actual - pred_naive)

            wma_errors.append(err_wma)
            mean_errors.append(err_mean)
            naive_errors.append(err_naive)

            # Squared errors
            wma_sq_errors.append(err_wma ** 2)
            mean_sq_errors.append(err_mean ** 2)
            naive_sq_errors.append(err_naive ** 2)

            # Percentage errors (Zero-safe: only compute when actual > 0)
            if actual > 0:
                wma_pct_errors.append(abs((actual - pred_wma) / actual) * 100.0)
                mean_pct_errors.append(abs((actual - pred_mean) / actual) * 100.0)
                naive_pct_errors.append(abs((actual - pred_naive) / actual) * 100.0)

        eval_points = len(wma_errors)
        mae_wma = round(sum(wma_errors) / eval_points, 2)
        mae_mean = round(sum(mean_errors) / eval_points, 2)
        mae_naive = round(sum(naive_errors) / eval_points, 2)

        rmse_wma = round(math.sqrt(sum(wma_sq_errors) / eval_points), 2)
        rmse_mean = round(math.sqrt(sum(mean_sq_errors) / eval_points), 2)
        rmse_naive = round(math.sqrt(sum(naive_sq_errors) / eval_points), 2)

        mape_wma = round(sum(wma_pct_errors) / len(wma_pct_errors), 1) if wma_pct_errors else None
        mape_mean = round(sum(mean_pct_errors) / len(mean_pct_errors), 1) if mean_pct_errors else None
        mape_naive = round(sum(naive_pct_errors) / len(naive_pct_errors), 1) if naive_pct_errors else None

        # Check if WMA outperforms Naive
        wma_beats_naive = mae_wma < mae_naive

        return {
            "is_eligible": True,
            "test_sample_size": eval_points,
            "min_train_observations": min_train_observations,
            "metrics": {
                "wma": {"mae": mae_wma, "rmse": rmse_wma, "mape": mape_wma},
                "simple_mean": {"mae": mae_mean, "rmse": rmse_mean, "mape": mape_mean},
                "naive": {"mae": mae_naive, "rmse": rmse_naive, "mape": mape_naive}
            },
            "wma_beats_naive": wma_beats_naive,
            "zero_actual_days_excluded_from_mape": eval_points - len(wma_pct_errors)
        }
