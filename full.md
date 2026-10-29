# SmartKadai — Full Application Completion & Verification

Act as a senior Python, Kivy, SQLite, QA automation, and AI/ML engineer. Continue my existing SmartKadai project and bring it to a stable, tested, release-ready state.

## 1. Project Details

- Project folder: `D:\SmartKadai_Kivy`
- Main application: `main.py`
- Python virtual environment: `.venv`
- Live database: `smartkadai.db`
- Test template: `smartkadai_test.db`
- Existing test launcher: `run_test_ui.py`
- Existing automated tests: `test_e2e_workflows.py`
- Forecasting modules: `forecasting\`
- Separate Streamlit project: `D:\smartkadai_aiproject` — DO NOT modify or mix it with this project.

## 2. Critical Safety Rules

1. Inspect the entire project structure, main application, database schema, forecasting modules, and tests before making changes.
2. Never modify, delete, overwrite, reset, or insert test data into `smartkadai.db`.
3. Never copy a test database back to the live database.
4. Preserve all existing working features and backups.
5. Use only isolated test databases for tests and manual verification.
6. Use read-only SQLite connections when inspecting database contents.
7. Before modifying source code, create a timestamped backup of each source file that will be changed.
8. Do not run destructive migrations, delete files, or alter database schemas without explaining the reason and requesting approval.
9. Do not invent successful test results. Run tests and report actual results.
10. Do not launch multiple Kivy instances or overwrite an existing test session.
11. Use the project's virtual environment Python: `.venv\Scripts\python.exe`.
12. If a change may affect the live database or existing bills, STOP and request approval.

## 3. Phase One — Read-Only Audit

Inspect:
- All project files and folders.
- `main.py` navigation and module structure.
- Product, billing, stock, sales report, dashboard, and forecasting implementations.
- SQLite tables, columns, constraints, indexes, and relationships.
- Existing unit and end-to-end tests.
- Existing backup files and current test launcher behavior.

Known database tables include:
- `products(product_id, product_name, selling_price, current_stock, supplier_lead_days, safety_stock)`
- `sales(sale_id, bill_id, timestamp, date, product_id, quantity_sold, selling_price)`

Verify the actual schema before relying on these column names.

Inspect these test session files without modifying them:
- `smartkadai_ui_session_20261016_185136.db`
- `smartkadai_ui_session_20261016_185203.db`

The second session previously contained a Rice sale of quantity 3 at ₹60, total ₹180, with stock changing from 18 to 15.

Report:
- Current implementation status.
- Confirmed bugs versus unverified behavior.
- Test results and failures.
- Risks and proposed fixes.
- A prioritized completion checklist.

Do not edit files during this audit phase.

## 4. Phase Two — Billing and POS

After reporting the audit, proceed with low-risk fixes only after identifying the relevant code and backup.

Verify:
- Product selection and price display.
- Quantity increment/decrement.
- Correct line totals and grand total.
- Multiple products in one bill.
- Empty-cart handling.
- Invalid, zero, and negative quantity prevention.
- Insufficient-stock prevention.
- Confirm & Save Bill.
- Receipt details and bill ID.
- Prevention of accidental duplicate submissions.
- Safe cancellation before saving.

Expected example:
Rice price = ₹60, quantity = 2, total = ₹120.
If starting stock is 18, successful sale must leave stock = 16 and create the correct sales record.

Use a fresh isolated test database copied from `smartkadai_test.db`. Never use the live database for testing.

## 5. Phase Three — Stock Management and SQLite Safety

Verify:
- Stock reduces exactly once after a successful sale.
- Restocking updates the correct product.
- Invalid stock changes are rejected.
- Sales beyond available stock are blocked.
- Related database updates succeed or fail together.
- Transactions roll back correctly after an error.
- Foreign-key enforcement is enabled on every appropriate SQLite connection.
- Database failures show understandable errors without corrupting data.

Do not perform a schema migration unless necessary and approved.

## 6. Phase Four — Sales Report

Verify:
- Saved bills appear in reports.
- Daily totals and bill totals are correct.
- Date filters and history work.
- CSV export contains correct data.
- Report calculations match the database.
- Empty reports and malformed dates are handled safely.

Test using isolated databases with known sample sales.

## 7. Phase Five — AI Sales Forecasting

Inspect the existing `forecasting\` implementation before replacing or redesigning anything.

Verify:
- Historical sales aggregation.
- Missing dates and zero-sales days.
- 7-day demand forecast.
- Stockout runway and risk labels.
- Reorder point and suggested restock quantity.
- Supplier lead time and safety stock handling.
- Search and risk filters.
- New products and products with insufficient history.
- Zero stock and no-sales edge cases.
- Invalid or missing database values.

The current baseline uses recent-weighted average/EWMA-style forecasting. Keep it as a baseline unless testing shows a justified reason to change it.

Implement chronological backtesting against actual sales data where sufficient data exists. Compare the baseline against a simple naive forecast and report suitable error metrics. Never claim forecast accuracy without evidence.

Keep forecasts read-only; generating a forecast must not modify stock or sales records.

## 8. Phase Six — Automated and Manual Verification

Use `.venv\Scripts\python.exe` for Python commands.

Run the existing tests, including `test_e2e_workflows.py` and the forecasting test suite. Discover the actual test files before running commands.

Add or update tests for:
- Billing calculations.
- Stock deduction.
- Restocking.
- Duplicate submission.
- Transaction rollback.
- Sales report totals.
- Forecast calculations and edge cases.

Distinguish mocked tests from tests that actually use SQLite or launch the Kivy UI.

For each test, report:
- Exact command.
- Pass/fail result.
- Error details if any.
- Whether the live database was untouched.

Do not claim manual UI tests passed unless they were actually performed.

## 9. Phase Seven — UI, Packaging, and Release

After core tests pass:
- Review dashboard and navigation.
- Review Tamil and English labels.
- Check layout consistency and error messages.
- Verify app startup from the project virtual environment.
- Document dependencies and installation steps.
- Assess Windows executable packaging.
- Build and test a distributable package only after the application is stable.

Do not remove existing backups or unrelated project files.

## 10. Required Working Method

Work in small, reviewable steps.

At the end of each phase, provide:
1. What you inspected or changed.
2. Files changed and backups created.
3. Tests executed and actual results.
4. Any unresolved issues.
5. The next recommended action.

**Start with Phase One only. Do a read-only audit and report findings before editing code.** Then wait for my approval before implementing changes.

Explain technical findings in simple Tanglish where practical. Do not claim the application is complete until the tests and release checks actually pass.