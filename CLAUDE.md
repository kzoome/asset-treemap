# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Streamlit-based portfolio visualization application that displays asset allocation using interactive treemaps and USD/KRW exchange rate charts. Data is fetched from Google Sheets and visualized using Plotly.

## Key Technologies

- **Framework**: Streamlit (web application framework)
- **Data Processing**: Pandas
- **Visualization**: Plotly Express
- **Data Source**: Google Sheets via gspread library
- **Authentication**: Google OAuth2 service account
- **External Data**: yfinance (for exchange rate data)

## Development Commands

### Setup
```bash
# Create virtual environment
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate  # macOS/Linux
# or
.venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
```

### Running the Application
```bash
# Run locally (default port 8501)
streamlit run app.py

# Run with specific configuration
streamlit run app.py --server.enableCORS false --server.enableXsrfProtection false
```

### Testing Google Sheets Connection
```bash
# Test Google Sheets authentication and data access
python google_sheets_test.py
```

## Architecture

### Single-File Application Structure

The application is contained in `app.py` with the following key sections:

1. **Authentication Layer** (`check_password()`): Password protection using Streamlit secrets
2. **Data Layer** (`load_data()`): Google Sheets integration with caching (10-minute TTL)
3. **Visualization Layer**:
   - Treemap visualization (asset allocation by category and performance)
   - Exchange rate chart (USD/KRW historical data)
4. **Configuration**: Sidebar controls for customizing visualizations

### Data Flow

```
Google Sheets → gspread → Pandas DataFrame → Data Cleaning → Plotly Visualization
                                                             ↓
                                                    Streamlit UI
```

### Key Data Transformations

The app expects Google Sheets data with columns:
- `구분` (Category), `자산종류` (Asset Type), `종목명` (Name)
- `금액` (Amount in ₩), `비중` (Weight %)
- `변동_1d`, `변동_MTD_local`, `변동_MTD_KRW`, `변동_1y` (Performance metrics)

Data cleaning functions:
- `clean_currency()`: Converts "₩81,643,700" → 81643700
- `clean_percentage()`: Converts "5.2%" → 5.2

### Caching Strategy

- `@st.cache_data(ttl=600)` on `load_data()`: Refreshes Google Sheets data every 10 minutes
- `@st.cache_data(ttl=3600)` on `get_exchange_rate()`: Refreshes exchange rate data every hour

## Configuration

### Required Secrets

Create `.streamlit/secrets.toml` (excluded from git) with:

```toml
# Password protection
password = "your_password_here"

# Google Sheets URL
SHEET_URL = "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit"

# Google service account credentials
[gcp_service_account]
type = "service_account"
project_id = "your-project-id"
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "your-service-account@your-project.iam.gserviceaccount.com"
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
# ... other fields
```

### Local Development

For local development, you can use `service_account.json` file instead of secrets. The app falls back to file-based credentials if Streamlit secrets are not available.

### Google Sheets Setup

1. Create a service account in Google Cloud Console
2. Download the JSON credentials
3. Share your Google Sheet with the service account email (found in credentials)
4. Ensure the sheet has a worksheet named "종목별 현황"

## Deployment

The app is configured for deployment on Streamlit Cloud or similar platforms:
- Uses `.devcontainer/devcontainer.json` for GitHub Codespaces
- Environment-aware credential loading (secrets vs. file-based)
- Mobile-optimized UI with responsive layouts

### Streamlit Cloud Deployment

1. Push code to GitHub (ensure `service_account.json` and `secrets.toml` are gitignored)
2. Connect repository to Streamlit Cloud
3. Add secrets via Streamlit Cloud UI (paste contents of `secrets.toml`)
4. Deploy

## UI Features

### Treemap Visualization
- Multi-level hierarchy: 전체 → 구분 → 자산종류 → 종목명
- Color-coded by performance (red = negative, green = positive)
- Customizable color ranges via sidebar slider
- Text wrapping control for long asset names
- Hover interactions disabled for mobile optimization

### Exchange Rate Chart
- Displays USD/KRW historical data
- Period selection: 1 month, 3 months, 6 months, 1 year, 5 years, 10 years
- Auto-scaling y-axis (doesn't start from zero)
- Dynamic x-axis formatting based on period

## Code Style Notes

- Korean language UI (titles, labels, error messages)
- Mobile-first design considerations
- Minimal margins and optimized heights for small screens
- Display mode bar disabled for cleaner mobile experience
