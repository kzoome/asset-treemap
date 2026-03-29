#!/usr/bin/env python3
"""
후잉 가계부 계좌 잔액 동기화 스크립트

스냅샷 복사본의 '계좌별 합계' 탭에서 계좌별 금액을 읽어
후잉 가계부의 해당 계좌 잔액과 차이를 거래내역으로 등록합니다.

사용법:
  python whooing_sync.py <snapshot_spreadsheet_url>
"""

import sys
import tomllib
from datetime import date
from pathlib import Path

import gspread
import requests
from google.oauth2.service_account import Credentials

# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

SECRETS_PATH = Path("/Users/al02633347/workspace-p/asset-treemap/.streamlit/secrets.toml")
WHOOING_SECRETS_PATH = Path("/Users/al02633347/.claude-personal/secrets.toml")

SA_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

WHOOING_API_BASE = "https://whooing.com/api"
WHOOING_SECTION_ID = "s12152"

# 후잉 금융수익 계좌 (income)
INCOME_ACCOUNT = ("income", "x73")

# 계좌명별 후잉 거래 아이템명 오버라이드 (기본값: "{계좌명}투자")
ITEM_NAME_OVERRIDE: dict[str, str] = {
    "업비트": "코인투자",
}

# 계좌명(시트) → (후잉 account_type, 후잉 account_id)
# 후잉 자산 계좌 ID는 API로 확인된 값
ACCOUNT_MAP: dict[str, tuple[str, str]] = {
    "은희미래":   ("assets", "x208"),
    "신한금투":   ("assets", "x190"),
    "키움증권":   ("assets", "x175"),
    "미래연금":   ("assets", "x158"),
    "신한ISA":    ("assets", "x194"),
    "업비트":     ("assets", "x221"),
    "은희ISA":    ("assets", "x211"),
    "미래IRP":    ("assets", "x171"),
    "해외비과세": ("assets", "x159"),
}

# ---------------------------------------------------------------------------
# 인증
# ---------------------------------------------------------------------------

def load_secrets() -> tuple[dict, dict]:
    """GCP 서비스 계정 시크릿과 후잉 시크릿을 반환"""
    with open(SECRETS_PATH, "rb") as f:
        gcp_secrets = tomllib.load(f)
    with open(WHOOING_SECRETS_PATH, "rb") as f:
        whooing_secrets = tomllib.load(f)
    return gcp_secrets, whooing_secrets


def build_whooing_headers(whooing_cfg: dict) -> dict:
    """후잉 API 인증 헤더 생성"""
    return {"X-API-KEY": whooing_cfg["x_api_key"]}


def build_gc(gcp_secrets: dict) -> gspread.Client:
    """gspread 클라이언트 반환"""
    creds = Credentials.from_service_account_info(
        gcp_secrets["gcp_service_account"], scopes=SA_SCOPES
    )
    return gspread.authorize(creds)


# ---------------------------------------------------------------------------
# 스프레드시트 읽기
# ---------------------------------------------------------------------------

def read_account_totals(gc: gspread.Client, snapshot_url: str) -> dict[str, int]:
    """스냅샷 복사본 '계좌별 합계' 탭에서 계좌명 → 금액(원) 매핑 반환"""
    doc = gc.open_by_url(snapshot_url)
    try:
        ws = doc.worksheet("계좌별 합계")
    except gspread.WorksheetNotFound:
        raise RuntimeError("스냅샷에 '계좌별 합계' 시트가 없습니다.")

    rows = ws.get_all_values()
    # 헤더 행 탐색: '계좌' 또는 '계좌명' 열 찾기
    header_row_idx = None
    acct_col = None
    amt_col = None
    for i, row in enumerate(rows):
        for j, cell in enumerate(row):
            if cell.strip() in ("계좌", "계좌명"):
                header_row_idx = i
                acct_col = j
                break
        if header_row_idx is not None:
            break

    if header_row_idx is None:
        raise RuntimeError("'계좌별 합계' 시트에서 '계좌' 열을 찾을 수 없습니다.")

    header = rows[header_row_idx]
    # '금액' 또는 '합계' 열 찾기
    for j, cell in enumerate(header):
        if cell.strip() in ("금액", "합계", "금액(원)", "총액"):
            amt_col = j
            break

    if amt_col is None:
        # 계좌 열 다음 열을 금액으로 간주
        amt_col = acct_col + 1

    totals: dict[str, int] = {}
    for row in rows[header_row_idx + 1:]:
        if len(row) <= max(acct_col, amt_col):
            continue
        acct_name = row[acct_col].strip()
        amt_raw = row[amt_col].strip().replace(",", "").replace("₩", "").replace(" ", "")
        if not acct_name or not amt_raw:
            continue
        try:
            totals[acct_name] = int(float(amt_raw))
        except ValueError:
            continue

    return totals


# ---------------------------------------------------------------------------
# 후잉 API
# ---------------------------------------------------------------------------

def get_whooing_balance(account_type: str, account_id: str, headers: dict) -> int:
    """후잉 계좌의 현재 잔액 반환"""
    url = f"{WHOOING_API_BASE}/bs/{account_type}/{account_id}.json"
    params = {"section_id": WHOOING_SECTION_ID}
    resp = requests.get(url, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", 0)
    # results가 숫자 직접 또는 dict인 경우 처리
    if isinstance(results, (int, float)):
        return int(results)
    if isinstance(results, dict):
        return int(results.get("balance", results.get("total", 0)))
    return 0


def post_whooing_entry(
    l_account_type: str,
    l_account_id: str,
    r_account_type: str,
    r_account_id: str,
    money: int,
    item: str,
    entry_date: date,
    headers: dict,
) -> dict:
    """후잉 거래내역 등록"""
    url = f"{WHOOING_API_BASE}/entries.json"
    payload = {
        "section_id": WHOOING_SECTION_ID,
        "date": entry_date.strftime("%Y%m%d"),
        "item": item,
        "l_account": l_account_type,
        "l_account_id": l_account_id,
        "r_account": r_account_type,
        "r_account_id": r_account_id,
        "money": str(money),
    }
    resp = requests.post(url, headers=headers, data=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# 메인 동기화
# ---------------------------------------------------------------------------

def sync_accounts(snapshot_url: str) -> None:
    """스냅샷 잔액과 후잉 잔액을 비교해 차이를 거래내역으로 등록"""
    gcp_secrets, whooing_secrets = load_secrets()
    whooing_cfg = whooing_secrets["whooing"]
    headers = build_whooing_headers(whooing_cfg)
    gc = build_gc(gcp_secrets)

    print("\n[후잉] 스냅샷 '계좌별 합계' 탭 읽는 중...")
    try:
        totals = read_account_totals(gc, snapshot_url)
    except Exception as e:
        print(f"  ❌ 오류: {e}")
        return

    if not totals:
        print("  ❌ 계좌별 합계 데이터를 읽을 수 없습니다.")
        return

    print(f"  읽은 계좌 수: {len(totals)}")

    today = date.today()
    synced = 0
    skipped = 0

    for acct_name, snapshot_amount in totals.items():
        if acct_name not in ACCOUNT_MAP:
            print(f"  ⚠  '{acct_name}' 은 ACCOUNT_MAP에 없어 건너뜁니다.")
            skipped += 1
            continue

        acct_type, acct_id = ACCOUNT_MAP[acct_name]

        try:
            whooing_balance = get_whooing_balance(acct_type, acct_id, headers)
        except Exception as e:
            print(f"  ❌ '{acct_name}' 후잉 잔액 조회 실패: {e}")
            skipped += 1
            continue

        diff = snapshot_amount - whooing_balance

        print(
            f"  {acct_name:<10} 스냅샷={snapshot_amount:>12,}  "
            f"후잉={whooing_balance:>12,}  차이={diff:>+12,}"
        )

        if diff == 0:
            continue

        # 거래내역 등록: 항상 l=계좌(assets), r=금융수익(income)
        # diff > 0: 자산 증가(양수), diff < 0: 자산 감소(음수 money)
        item = ITEM_NAME_OVERRIDE.get(acct_name, f"{acct_name}투자")
        l_type, l_id = acct_type, acct_id
        r_type, r_id = INCOME_ACCOUNT

        try:
            post_whooing_entry(
                l_account_type=l_type,
                l_account_id=l_id,
                r_account_type=r_type,
                r_account_id=r_id,
                money=diff,
                item=item,
                entry_date=today,
                headers=headers,
            )
            print(f"    ✅ 거래 등록: {item} {diff:+,}원")
            synced += 1
        except Exception as e:
            print(f"    ❌ 거래 등록 실패: {e}")
            skipped += 1

    print(f"\n[후잉] 완료: 등록 {synced}건, 건너뜀 {skipped}건")


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("사용법: python whooing_sync.py <snapshot_spreadsheet_url>")
        sys.exit(1)

    snapshot_url = sys.argv[1]
    sync_accounts(snapshot_url)


if __name__ == "__main__":
    main()
