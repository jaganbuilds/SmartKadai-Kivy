# SmartKadai AI Sales Forecasting — Data Quality & Preparation Report
**Generated:** 2026-10-18 19:36:54
**Database Source:** `smartkadai.db` (SQLite Strict Read-Only)
**Data Sufficiency Assessment:** Tier 1 — Preliminary Baseline Only (4 active days; ML prohibited)

---

## 1. Executive Summary
- **Total Catalog Products:** 5
- **Total Raw Sales Rows:** 20 (20 valid, 0 invalid)
- **Total Units Sold:** 74 units
- **Total Recorded Revenue:** ₹4,470.00
- **Observed Date Span:** `2026-10-10` to `2026-10-14` (5 calendar days)
- **Confirmed Trading Days:** 4 days
- **Internal Unrecorded Gap Days:** 1 days
- **Elapsed Post-Data Days:** 4 days
- **Aggregation Pipeline Mode:** `active_trading_days_primary`

## 2. Historical Date Policy & Assumptions
- **Category 1 (Confirmed Trading Days):** Dates with observed retail transactions. Used as primary demand rate basis.
- **Category 2 (Confirmed Closed Days):** Excluded from store trading demand calculations when explicit closure records exist.
- **Category 3 (Unknown Internal Gaps):** 1 day(s) detected: `['2026-10-12']`.
  > [!NOTE]
  > **Active Trading Days Basis (Primary Default):** Internal gaps without confirmed store closure are omitted from daily demand rates, avoiding arbitrary demand dilution.
- **Category 4 (Elapsed Post-Data Days):** 4 day(s) elapsed after last sale. Step-2 policy strictly prohibits filling post-data dates with synthetic zeroes.

## 3. Data Integrity & Validation Findings
- **Date Format Consistency:** [PASS] Valid YYYY-MM-DD
- **Referential Integrity:** [PASS] All product IDs exist in catalog
- **Quantity Boundary Check (`quantity_sold > 0`):** [PASS] All positive
- **Price Boundary Check (`selling_price >= 0`):** [PASS] All valid
- **Missing `bill_id`:** 13 of 20 records (65.0%)
  - *Impact:* Product-level sales are intact; bill grouping uses individual transaction IDs where bill_id is NULL.
- **Missing `timestamp`:** 11 of 20 records (55.0%)
  - *Impact:* Daily aggregation uses the verified `date` column; missing timestamps do not block daily forecasting.
- **Timestamp Format Distribution:**
  - `Missing / NULL`: 11 records
  - `ISO 8601 (T-separator)`: 4 records
  - `SQL Datetime (space-separator)`: 5 records
- **Rapid Sequential Transactions Flagged:** 1 cluster(s) detected (preserved without deletion)

## 4. Product Sales Aggregation Summary
| Product ID | Product Name | Total Units Sold | Total Revenue | Active Sales Days | Avg Daily Units (Active Days) | Lead Days | Safety Stock |
|---|---|---:|---:|---:|---:|---:|---:|
| P001 | Rice | 22 units | ₹1,320.00 | 4 | 5.5 | 3d | 5 |
| P002 | Sugar | 16 units | ₹720.00 | 3 | 5.3 | 2d | 5 |
| P003 | Milk | 23 units | ₹690.00 | 3 | 7.7 | 1d | 5 |
| P004 | Toor Dal | 7 units | ₹840.00 | 2 | 3.5 | 4d | 4 |
| P005 | Cooking Oil | 6 units | ₹900.00 | 3 | 2.0 | 3d | 3 |

## 5. Audit Warnings
- NOTICE: 4 post-data calendar day(s) have elapsed since last sale (2026-10-14). In accordance with Step-2 policy, these dates were NOT backfilled with synthetic zeroes into the sales demand series.

## 6. AI/ML Forecasting Readiness & Recommendation
- **Current Volume Tier:** Tier 1 — Preliminary Baseline Only (4 active days; ML prohibited)
- **Prohibited Action:** Do NOT train a stand-alone neural network or regression model on this 4-day sample.
- **Recommended Baseline:** Use Recent-Weighted Moving Average (WMA) or Simple Observed Mean on confirmed trading days.