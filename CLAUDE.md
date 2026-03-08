# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Streamlit-based portfolio visualization app displaying asset allocation treemaps and USD/KRW exchange rate charts. Data source is Google Sheets via service account credentials.

## Key Technologies

- **Framework**: Streamlit + `streamlit-js-eval` (viewport detection)
- **Visualization**: Plotly Express (treemap, line chart)
- **Data Source**: Google Sheets via `gspread`
- **Auth**: Google OAuth2 service account (app) + personal OAuth2 (monthly snapshot script)
- **External Data**: `yfinance` (USD/KRW exchange rate, market trading days)

## Development Commands

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run app
streamlit run app.py

# Test Google Sheets connection
python google_sheets_test.py

# Monthly snapshot (월말 실행)
python monthly_snapshot.py               # 스냅샷 생성
python monthly_snapshot.py --dry-run     # 원본 수정 없이 복사본만 생성
python monthly_snapshot.py --setup       # '설정' 시트 초기 생성 (1회성)
python monthly_snapshot.py --fix-refs    # raw 시트 참조 수식을 설정 시트로 교체
```

## Architecture

### Application (`app.py`)

Single-file Streamlit app with these layers:

1. **Auth** (`check_password()`): Session-state-based password gate using `st.secrets["password"]`. Bypassed if key absent (local dev).
2. **Viewport detection**: Uses `streamlit_js_eval` to read `screen.width` and set `default_treemap_height` (800px desktop / 600px mobile). Calls `st.stop()` until JS returns a value.
3. **Data** (`load_data()`, TTL=600s): Reads "종목별 현황" worksheet. Credential fallback: Streamlit secrets → `service_account.json` file.
4. **Visualization**: Plotly treemap with 3 selectable hierarchy levels; Plotly line chart for USD/KRW (`get_exchange_rate()`, TTL=3600s).
5. **Sidebar controls**: Color metric, color range, text wrap width, treemap height, hierarchy level, exchange rate period.

### Monthly Snapshot Script (`monthly_snapshot.py`)

Standalone CLI script for end-of-month portfolio archiving. Uses **two** credential types:
- **Service account** (`service_account.json`): Sheets read/write via gspread
- **Personal OAuth2** (`client_secret_*.json` → cached in `token.json`): Drive `files.copy` (file ownership stays with personal account)

Workflow:
1. Copies spreadsheet via Drive API
2. Freezes all sheet formulas to values (prevents `#REF` from unloaded `GOOGLEFINANCE`)
3. Freezes specific cells in "월별 수익률" and "자산배분현황"
4. Appends new month rows to "월별 수익률", "월별 수익률 지수비교", "월별 누적"
5. Updates "설정" sheet with current exchange rate and last trading dates

### Data Transformations

Google Sheets "종목별 현황" worksheet → 9 columns:

| 원본 | 변환 컬럼 | 형태 |
|---|---|---|
| 금액(₩) | `금액_숫자` | `int` (₩, 콤마 제거) |
| 비중(%) | `비중_숫자` | `float` |
| 변동_1d/MTD_local/MTD_KRW/1y | `{col}_숫자` | `float` |

Treemap color uses weighted-average of `비중_숫자` for aggregated levels (구분, 자산종류).

### Credential Files (gitignored)

- `service_account.json`: GCP service account key
- `.streamlit/secrets.toml`: App secrets (password, SHEET_URL, gcp_service_account)
- `token.json`: Personal OAuth2 cached token (monthly_snapshot.py)
- `client_secret_*.json`: OAuth2 client secret (monthly_snapshot.py)

The Google Sheet must have a worksheet named **"종목별 현황"** and the service account email must have editor access.

## Configuration

### `.streamlit/secrets.toml` structure

```toml
password = "..."
SHEET_URL = "https://docs.google.com/spreadsheets/d/.../edit"

[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "...@....iam.gserviceaccount.com"
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
```

### Google Sheets expected worksheets

| 시트명 | 용도 |
|---|---|
| 종목별 현황 | app.py 메인 데이터 |
| 설정 | 월별 스냅샷 설정값 (B2: 한국MTD기준일, B3: 미국MTD기준일, B4: 전월환율) |
| 월별 수익률 | 스냅샷 대상 |
| 월별 수익률 지수비교 | 스냅샷 대상 |
| 월별 누적 | 스냅샷 대상 |
| 자산배분현황 | 환율 셀(J4, K5) 고정 대상 |
