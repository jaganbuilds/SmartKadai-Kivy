"""
SmartKadai AI Sales Forecasting - Pure-Python Forecast Engine.

Provides transparent, explainable demand estimation and inventory replenishment
calculations using recent-weighted moving averages (WMA) and exponential smoothing (EWMA).

Strict Safety and Transparency Guarantees:
1. Pure Python standard library implementation (no pandas, no scikit-learn required).
2. Clearly labeled as EXPERIMENTAL BASELINE ESTIMATES, not trained ML predictions.
3. Explicitly records data assumptions (e.g., zero-fill on missing dates).
4. Strictly read-only computation; does not mutate any database or input records.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, date
import math
from typing import Dict, List, Optional, Union, Any

try:
    from .data_preparation import DailyProductSale
except ImportError:
    # Allow standalone execution
    from data_preparation import DailyProductSale


@dataclass
class ProductForecastResult:
    """Detailed forecast and inventory recommendation for a single product."""
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

    # Forecast baseline estimates
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

    # Assumptions & Transparency
    is_insufficient_history: bool
    data_assumptions: List[str]
    notes: List[str]
    is_experimental: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ForecastReport:
    """Complete store forecast report across all products."""
    generated_at: str
    total_products: int
    date_range_start: Optional[str]
    date_range_end: Optional[str]
    total_calendar_days: int
    forecast_method: str
    products_forecast: List[ProductForecastResult]
    global_assumptions: List[str]
    disclaimer: str = (
        "EXPERIMENTAL BASELINE ESTIMATES ONLY. "
        "These estimates are calculated using statistical weighted moving averages on "
        "limited historical observations. They are not trained machine learning predictions "
        "and must not be interpreted as guaranteed sales forecasts."
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "total_products": self.total_products,
            "date_range_start": self.date_range_start,
            "date_range_end": self.date_range_end,
            "total_calendar_days": self.total_calendar_days,
            "forecast_method": self.forecast_method,
            "global_assumptions": self.global_assumptions,
            "disclaimer": self.disclaimer,
            "products_forecast": [p.to_dict() for p in self.products_forecast]
        }


class ForecastEngine:
    """
    Pure-Python demand estimation and inventory replenishment engine.
    """

    SUPPORTED_METHODS = ("recent_weighted", "exponential_smoothing", "simple_average")

    def __init__(
        self,
        method: str = "recent_weighted",
        ewma_alpha: float = 0.35,
        insufficient_history_days: int = 7
    ):
        """
        Initialize the forecasting engine.

        Args:
            method: Forecasting baseline method ('recent_weighted', 'exponential_smoothing', 'simple_average').
            ewma_alpha: Smoothing factor for exponential smoothing (between 0.0 and 1.0).
            insufficient_history_days: Threshold below which history is flagged as insufficient.
        """
        if method not in self.SUPPORTED_METHODS:
            raise ValueError(f"Unsupported forecast method '{method}'. Supported: {self.SUPPORTED_METHODS}")
        if not (0.0 < ewma_alpha <= 1.0):
            raise ValueError(f"ewma_alpha must be between 0.0 and 1.0, got {ewma_alpha}")

        self.method = method
        self.ewma_alpha = ewma_alpha
        self.insufficient_history_days = insufficient_history_days

    def _calculate_daily_demand(
        self,
        daily_units: List[int]
    ) -> float:
        """
        Calculate estimated daily demand from a chronological sequence of daily units.

        Args:
            daily_units: Chronological list of units sold per day.

        Returns:
            Estimated daily units as a float rounded to 2 decimal places.
        """
        if not daily_units:
            return 0.0

        if all(u == 0 for u in daily_units):
            return 0.0

        n = len(daily_units)

        if self.method == "simple_average":
            avg = sum(daily_units) / n
            return round(avg, 2)

        elif self.method == "recent_weighted":
            # Linear weighted moving average: weights 1, 2, ..., n
            # Day n (most recent) gets highest weight
            weights = list(range(1, n + 1))
            total_weight = sum(weights)
            weighted_sum = sum(w * u for w, u in zip(weights, daily_units))
            return round(weighted_sum / total_weight, 2)

        elif self.method == "exponential_smoothing":
            # EWMA: S_1 = y_1, S_t = alpha * y_t + (1 - alpha) * S_{t-1}
            s = float(daily_units[0])
            for y in daily_units[1:]:
                s = (self.ewma_alpha * float(y)) + ((1.0 - self.ewma_alpha) * s)
            return round(max(0.0, s), 2)

        return 0.0

    def calculate_product_forecast(
        self,
        product: Dict[str, Any],
        daily_sales: List[Union[DailyProductSale, Dict[str, Any]]]
    ) -> ProductForecastResult:
        """
        Calculate demand forecast and replenishment recommendations for a single product.

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
            # Handle either DailyProductSale or dict
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

            is_zf = bool(s_dict.get("is_zero_filled", False))
            if is_zf:
                zero_filled_count += 1

            product_sales.append((s_date, qty, is_zf))

        # Sort chronologically
        product_sales.sort(key=lambda x: x[0])

        daily_units = [x[1] for x in product_sales]
        total_days = len(daily_units)
        total_units = sum(daily_units)
        active_days = sum(1 for u in daily_units if u > 0)
        zero_days = sum(1 for u in daily_units if u == 0)

        # 3. Document explicit assumptions
        if zero_filled_count > 0:
            data_assumptions.append(
                f"{zero_filled_count} unrecorded calendar day(s) were assumed to have 0 sales based on zero-fill configuration."
            )

        is_insufficient = total_days < self.insufficient_history_days
        if is_insufficient:
            notes.append(
                f"Preliminary estimate: observed over only {total_days} day(s) (threshold is {self.insufficient_history_days} days)."
            )

        # 4. Calculate estimated daily demand
        daily_demand = self._calculate_daily_demand(daily_units)

        if total_units == 0:
            notes.append("Zero demand observed across all recorded days.")
            stockout_runway = None
        else:
            if daily_demand > 0:
                stockout_runway = round(current_stock / daily_demand, 1)
            else:
                stockout_runway = None

        # Estimated 7-day demand
        next_7_days_demand = round(daily_demand * 7.0, 2)

        # 7-Day Planning Horizon Alert (reported separately from lead-time reorder decision)
        is_7_day_stockout_risk = float(current_stock) < next_7_days_demand
        demand_7_day_deficit = round(max(0.0, next_7_days_demand - float(current_stock)), 2)

        if is_7_day_stockout_risk:
            notes.append(
                f"7-day demand alert: projected 7-day demand ({next_7_days_demand} units) "
                f"exceeds current stock ({current_stock} units) by {demand_7_day_deficit} units."
            )

        # 5. Inventory Replenishment Calculations (Lead-Time Decision)
        # Policy Definition:
        # Reorder Point = ceil(daily_demand * supplier_lead_days) + safety_stock
        # Suggested Order Quantity = max(0, reorder_point - current_stock)
        # - Below Reorder Point (current_stock < reorder_point):
        #     Restock is recommended. Suggested order is positive (reorder_point - current_stock).
        # - Exactly at Reorder Point (current_stock == reorder_point):
        #     Stock is at safety boundary. Deficit to reorder level is 0. Suggested order is 0.
        #     is_restock_recommended is False (replenishment triggers on next unit sold).
        # - Above Reorder Point (current_stock > reorder_point):
        #     Stock is sufficient. Suggested order is 0. is_restock_recommended is False.
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
            forecast_method=self.method,
            reorder_point=reorder_point,
            suggested_order_quantity=suggested_order,
            stockout_runway_days=stockout_runway,
            is_restock_recommended=is_restock_recommended,
            is_at_reorder_point=is_at_reorder_point,
            is_7_day_stockout_risk=is_7_day_stockout_risk,
            demand_7_day_deficit=demand_7_day_deficit,
            is_insufficient_history=is_insufficient,
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
        Generate complete store forecast report across all products.

        Args:
            products: List of product metadata dicts.
            aggregated_sales: Continuous daily sales records.
            date_metadata: Optional metadata dict from SalesDataPreparation.

        Returns:
            ForecastReport object containing individual product forecasts and global disclaimers.
        """
        results: List[ProductForecastResult] = []

        global_assumptions = [
            f"Forecast method applied: '{self.method}' baseline.",
            "All predictions are experimental heuristic baselines; not trained machine learning models."
        ]

        if date_metadata and date_metadata.get("zero_fill_applied"):
            global_assumptions.append(
                f"Missing calendar dates ({date_metadata.get('missing_calendar_days', 0)} days) were zero-filled."
            )

        for p in products:
            res = self.calculate_product_forecast(p, aggregated_sales)
            results.append(res)

        min_d = date_metadata.get("min_date") if date_metadata else None
        max_d = date_metadata.get("max_date") if date_metadata else None
        total_days = date_metadata.get("total_calendar_days", 0) if date_metadata else 0

        return ForecastReport(
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            total_products=len(results),
            date_range_start=min_d,
            date_range_end=max_d,
            total_calendar_days=total_days,
            forecast_method=self.method,
            products_forecast=results,
            global_assumptions=global_assumptions
        )
