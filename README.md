# 🛒 SmartKadai — Offline Smart Billing & Inventory Management App

SmartKadai is an offline-first billing and inventory management application designed for small retail shops, grocery stores, and provision stores. It helps shop owners manage products, process bills, monitor stock, review sales, and estimate future revenue using baseline forecasting methods.

## 🚀 Features

- **Billing Management** — Create bills and calculate sales totals.
- **Product Management** — Add and manage products and selling prices.
- **Stock Management** — Track inventory and update stock levels.
- **Sales Reports** — View sales summaries for today, the last 7 days, and all time.
- **CSV Export** — Export sales reports for further analysis.
- **AI Forecasting Baseline** — Estimate next-day and 7-day revenue and unit demand using historical sales data.
- **Local Database** — Store application data using SQLite.
- **Offline-First Design** — Core billing and inventory features are designed to work locally without requiring a cloud server.
- **Automated Testing** — Includes tests for forecasting, data preparation, and application workflows.

## 🧰 Technology Stack

- **Language:** Python
- **User Interface:** Kivy
- **Database:** SQLite
- **Data Processing:** Python standard library and project-specific forecasting modules
- **Testing:** pytest / Python test scripts
- **Packaging:** PyInstaller and Android packaging workflow, where applicable

## 🧠 Forecasting Module

SmartKadai includes a baseline forecasting module that uses historical sales data to estimate future business activity.

Current forecasting methods include:

- Recent-Weighted Moving Average
- Simple Observed Mean
- Naive Baseline

The forecasts are intended to support basic business planning. Their accuracy depends on the amount and quality of historical sales data. They are baseline estimates, not guaranteed predictions.

## 📂 Project Structure

```text
SmartKadai-Kivy/
├── main.py
├── smartkadaui.cmd
├── run_test_ui.py
├── test_e2e_workflows.py
├── forecasting/
│   ├── __init__.py
│   ├── data_preparation.py
│   ├── forecast_engine.py
│   ├── test_data_preparation.py
│   ├── test_forecast_engine.py
│   └── output/
│       └── data_quality_report.md
├── core.md
├── full.md
└── README.md
```

## ⚙️ Getting Started

### Prerequisites

- Python compatible with the project's dependencies
- Git
- Windows for the supplied Windows launcher

### Clone the Repository

```bash
git clone https://github.com/jaganbuilds/SmartKadai-Kivy.git
cd SmartKadai-Kivy
```

### Set Up a Virtual Environment

**Windows PowerShell:**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Install Dependencies

Install the dependencies required by the project. If a `requirements.txt` file is available, run:

```powershell
pip install -r requirements.txt
```

### Run the Application

Check the project's launcher and application configuration for the supported startup command. On Windows, the supplied `smartkadaui.cmd` may be used if configured for your environment.

## 🧪 Testing

Run the forecasting tests from the project root:

```powershell
python -m pytest forecasting/
```

Run the end-to-end workflow test script, if its dependencies and configuration are available:

```powershell
python test_e2e_workflows.py
```

## 🔒 Data & Privacy

- The application is designed around local data storage.
- Database files, authentication files, secrets, virtual environments, and local backups should not be committed to the public repository.
- Do not store passwords or API keys directly in source code.
- Back up important shop data separately and securely.

## 🎯 Project Goals

- Simplify billing and inventory management for small shops.
- Support local-first operation.
- Provide useful sales reporting.
- Explore practical baseline forecasting for small-business demand planning.

## 🛠️ Future Improvements

- Improve forecast evaluation with additional historical data.
- Add product-level demand forecasting.
- Improve reporting and data visualization.
- Streamline Android APK packaging and installation.
- Add documentation and screenshots for key workflows.

## 👨‍💻 Developer

**Jagan M.**

- GitHub: [@jaganbuilds](https://github.com/jaganbuilds)
- LinkedIn: [Jagan M.](https://www.linkedin.com/in/jagan-m-a42457343/)
- Portfolio: [jaganaiengineer.vercel.app](https://jaganaiengineer.vercel.app/)

---

*Built to make everyday retail operations simpler with Python, local data storage, and practical forecasting.*

