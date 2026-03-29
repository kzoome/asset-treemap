#!/usr/bin/env python3
"""
월간 포트폴리오 스냅샷 자동화 스크립트

사용법:
  python monthly_snapshot.py            # 월말 스냅샷 생성 (Phase 1)
  python monthly_snapshot.py --setup    # '설정' 시트 생성 (Phase 0, 1회성)
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from google.oauth2.credentials import Credentials as UserCredentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import yfinance as yf

# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

SA_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
# Drive copy에만 사용하는 개인 계정 OAuth2 스코프
USER_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]

SERVICE_ACCOUNT_FILE = "service_account.json"
OAUTH_CLIENT_FILE = "client_secret_927371341361-csuca07n15scqbloadbji1iog7nrflac.apps.googleusercontent.com.json"
TOKEN_FILE = "token.json"  # 첫 인증 후 저장되는 토큰 (gitignore에 추가할 것)
SECRETS_FILE = ".streamlit/secrets.toml"

# '월별 수익률' 마지막 행에서 고정할 열 목록
MONTHLY_COLS_TO_FREEZE = ["A", "F", "H", "K", "L", "M", "N", "O", "Z", "AA"]

# '자산배분현황'에서 고정할 환율 셀
ALLOC_PREV_RATE_CELL = "J4"   # 전월환율
ALLOC_CURR_RATE_CELL = "K5"   # 현재환율


# ---------------------------------------------------------------------------
# 유틸 함수
# ---------------------------------------------------------------------------

def col_num_to_letter(n: int) -> str:
    """1-based 열 번호 → 열 문자 (예: 1→A, 26→Z, 27→AA)"""
    result = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result


def get_file_id_from_url(url: str) -> str:
    """Google Sheets URL에서 파일 ID 추출"""
    parts = url.split("/")
    try:
        d_idx = parts.index("d")
        return parts[d_idx + 1]
    except (ValueError, IndexError):
        raise ValueError(f"URL에서 파일 ID를 추출할 수 없습니다: {url}")


def get_last_data_row(ws: gspread.Worksheet) -> int:
    """A열 기준으로 마지막 비어있지 않은 행 번호(1-indexed) 반환"""
    col_a = ws.col_values(1)
    for i in range(len(col_a) - 1, -1, -1):
        if col_a[i].strip():
            return i + 1
    return 1


def get_recent_last_trading_day(market: str, as_of: date | None = None) -> date:
    """yfinance로 as_of 날짜(기본: 오늘) 기준 가장 최근 거래일 반환.

    market: 'KR' (KOSPI) 또는 'US' (S&P 500)
    """
    as_of = as_of or date.today()
    start_date = as_of - timedelta(days=10)
    end_date = as_of + timedelta(days=1)  # yfinance end는 exclusive

    ticker = "^KS11" if market == "KR" else "^GSPC"
    df = yf.download(
        ticker,
        start=start_date.strftime("%Y-%m-%d"),
        end=end_date.strftime("%Y-%m-%d"),
        progress=False,
        auto_adjust=True,
    )
    if df.empty:
        raise ValueError(
            f"{market} 시장 {as_of} 기준 최근 거래일 데이터를 가져올 수 없습니다."
        )

    last_trading = df.index[-1]
    return last_trading.date() if hasattr(last_trading, "date") else last_trading


def prev_month_of(today: date) -> tuple[int, int]:
    """오늘 날짜 기준 전월 (year, month) 반환"""
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


# ---------------------------------------------------------------------------
# 인증
# ---------------------------------------------------------------------------

def authenticate():
    """gspread 클라이언트(서비스 계정)와 개인 계정 Drive API 서비스 반환"""
    # Sheets 조작: 서비스 계정
    sa_creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SA_SCOPES)
    gc = gspread.authorize(sa_creds)

    # Drive files.copy: 개인 계정 OAuth2 (파일 소유자 = 개인 계정)
    user_creds = _get_user_credentials()
    drive_service = build("drive", "v3", credentials=user_creds)

    return gc, drive_service


def _get_user_credentials() -> UserCredentials:
    """개인 계정 OAuth2 토큰 로드 또는 최초 인증 수행"""
    creds = None
    token_path = Path(TOKEN_FILE)

    if token_path.exists():
        creds = UserCredentials.from_authorized_user_file(TOKEN_FILE, USER_DRIVE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(OAUTH_CLIENT_FILE, USER_DRIVE_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
        print(f"    OAuth2 토큰 저장: {TOKEN_FILE}")

    return creds


# ---------------------------------------------------------------------------
# 설정값 로드
# ---------------------------------------------------------------------------

def load_sheet_url() -> str:
    """SHEET_URL을 secrets.toml 또는 사용자 입력에서 읽기"""
    secrets_path = Path(SECRETS_FILE)
    if secrets_path.exists():
        # Python 3.11+ tomllib (stdlib)
        try:
            import tomllib
            with open(secrets_path, "rb") as f:
                secrets = tomllib.load(f)
            url = secrets.get("SHEET_URL", "")
            if url and "YOUR_DEFAULT" not in url:
                return url
        except Exception:
            pass

    url = input("Google Sheet URL을 입력하세요: ").strip()
    return url


# ---------------------------------------------------------------------------
# Phase 0: '설정' 시트 생성 (1회성)
# ---------------------------------------------------------------------------

def setup_settings_sheet(doc: gspread.Spreadsheet) -> gspread.Worksheet:
    """'설정' 시트가 없으면 생성하고 초기 구조를 세팅한다.

    raw 시트에서 읽을 수 있는 값(E60, E61, K60)을 자동으로 채우려 시도하며,
    실패하면 빈칸으로 남겨 수동 입력을 유도한다.
    """
    # 이미 있으면 종료
    try:
        ws = doc.worksheet("설정")
        print("'설정' 시트가 이미 존재합니다.")
        return ws
    except gspread.WorksheetNotFound:
        pass

    print("'설정' 시트를 생성합니다...")
    ws = doc.add_worksheet(title="설정", rows=20, cols=5)

    # 헤더 + 항목명 설정
    ws.update(
        [["항목명", "값"]],
        "A1:B1",
        value_input_option="RAW",
    )
    ws.update(
        [["한국주식MTD기준일"], ["미국주식MTD기준일"], ["전월환율"]],
        "A2:A4",
        value_input_option="RAW",
    )

    # raw 시트에서 기존 값 읽기 시도
    kr_mtd, us_mtd, prev_rate = "", "", ""
    try:
        raw_ws = doc.worksheet("종목별 현황(raw)")
        kr_mtd = raw_ws.acell("E60", value_render_option="FORMATTED_VALUE").value or ""
        us_mtd = raw_ws.acell("E61", value_render_option="FORMATTED_VALUE").value or ""
        prev_rate = raw_ws.acell("K60", value_render_option="FORMATTED_VALUE").value or ""
        print(f"  raw 시트 값 읽기 성공: E60={kr_mtd}, E61={us_mtd}, K60={prev_rate}")
    except Exception as e:
        print(f"  raw 시트에서 값 읽기 실패 (수동 입력 필요): {e}")

    ws.update(
        [[kr_mtd], [us_mtd], [prev_rate]],
        "B2:B4",
        value_input_option="RAW",
    )

    print(
        "\n✅ '설정' 시트 생성 완료.\n"
        "   다음 후속 작업을 수동으로 진행하세요:\n"
        "   1. '설정' 시트 B2~B4 값이 올바른지 확인\n"
        "   2. raw 시트에서 E60, E61, K60을 참조하는 수식을 '설정'!B2~B4로 변경\n"
        "   3. raw 시트 60행 이하 삭제\n"
    )
    return ws


# ---------------------------------------------------------------------------
# Phase 0-b: raw 시트 참조 수식 → '설정' 시트 참조로 일괄 변경
# ---------------------------------------------------------------------------

import re

# raw 시트 셀 → 설정 시트 셀 매핑
RAW_REF_MAP = {
    "E60": "설정!B2",   # 한국주식MTD기준일
    "E61": "설정!B3",   # 미국주식MTD기준일
    "K60": "설정!B4",   # 전월환율
}
RAW_SHEET_NAME = "종목별 현황(raw)"


def _make_ref_pattern(col: str, row: str) -> re.Pattern:
    """열·행 문자열로 셀 참조 패턴 생성 ($ 기호 optional, 대소문자 무시)."""
    return re.compile(
        r"\$?" + re.escape(col) + r"\$?" + re.escape(row) + r"(?!\d)",
        re.IGNORECASE,
    )


def fix_raw_references(doc: gspread.Spreadsheet) -> None:
    """모든 시트를 순회하며 raw 시트 60행 참조를 설정 시트로 교체."""

    # 각 raw 셀마다 (패턴, 교체값) 쌍을 준비
    # 다른 시트에서 참조: '종목별 현황'!E60  또는  종목별 현황!E60
    other_sheet_patterns: list[tuple[re.Pattern, str]] = []
    raw_local_patterns: list[tuple[re.Pattern, str]] = []

    for raw_cell, settings_ref in RAW_REF_MAP.items():
        col, row = re.match(r"([A-Z]+)(\d+)", raw_cell, re.IGNORECASE).groups()

        # 다른 시트에서 오는 외부 참조 패턴
        # e.g. '종목별 현황'!$E$60  또는  종목별 현황!E60
        ext_pat = re.compile(
            r"'?" + re.escape(RAW_SHEET_NAME) + r"'?!\$?" + re.escape(col) + r"\$?" + re.escape(row) + r"(?!\d)",
            re.IGNORECASE,
        )
        other_sheet_patterns.append((ext_pat, settings_ref))

        # raw 시트 내부 로컬 참조 패턴
        local_pat = _make_ref_pattern(col, row)
        raw_local_patterns.append((local_pat, settings_ref))

    total_changes = 0

    for ws in doc.worksheets():
        ws_title = ws.title
        print(f"  검사 중: '{ws_title}'", end="", flush=True)

        # FORMULA 렌더링으로 전체 값 읽기
        try:
            all_formulas = ws.get_all_values(value_render_option="FORMULA")
        except Exception as e:
            print(f" → 읽기 실패: {e}")
            continue

        changed_cells: list[tuple[int, int, str]] = []  # (row, col, new_formula)

        for r_idx, row_data in enumerate(all_formulas):
            for c_idx, cell_val in enumerate(row_data):
                if not isinstance(cell_val, str) or not cell_val.startswith("="):
                    continue

                original = cell_val
                new_val = cell_val

                if ws_title == RAW_SHEET_NAME:
                    # raw 시트 내부: 로컬 참조 교체
                    for pat, replacement in raw_local_patterns:
                        new_val = pat.sub(replacement, new_val)
                else:
                    # 다른 시트: 외부 참조 패턴으로 교체
                    for pat, replacement in other_sheet_patterns:
                        new_val = pat.sub(replacement, new_val)

                if new_val != original:
                    changed_cells.append((r_idx + 1, c_idx + 1, new_val))

        if not changed_cells:
            print(" → 변경 없음")
            continue

        print(f" → {len(changed_cells)}셀 변경")
        for row_num, col_num, new_formula in changed_cells:
            cell_a1 = gspread.utils.rowcol_to_a1(row_num, col_num)
            try:
                ws.update([[new_formula]], cell_a1, value_input_option="USER_ENTERED")
                print(f"    {cell_a1}: {new_formula[:80]}")
                total_changes += 1
            except Exception as e:
                print(f"    경고: {cell_a1} 업데이트 실패: {e}")

    print(f"\n✅ 완료: 총 {total_changes}셀 수식 변경")


# ---------------------------------------------------------------------------
# Phase 1: 스냅샷 생성
# ---------------------------------------------------------------------------

def copy_spreadsheet(drive_service, file_id: str, title: str) -> str:
    """개인 계정 Drive API로 문서 전체 복사, 복사본 ID 반환.

    drive_service는 개인 계정 OAuth2 자격증명으로 생성된 서비스.
    복사본 소유자 = 개인 계정 → 개인 Drive 용량 사용.
    복사 후 서비스 계정에 편집 권한 부여하여 gspread로 접근 가능하게 함.
    """
    import json as _json

    copy_id = (
        drive_service.files()
        .copy(fileId=file_id, body={"name": title})
        .execute()
    )["id"]

    # 서비스 계정에 편집 권한 부여 (gspread로 복사본 접근하기 위해)
    sa_email = _json.load(open(SERVICE_ACCOUNT_FILE))["client_email"]
    drive_service.permissions().create(
        fileId=copy_id,
        body={"type": "user", "role": "writer", "emailAddress": sa_email},
    ).execute()
    print(f"    서비스 계정 편집 권한 부여: {sa_email}")

    return copy_id


def freeze_sheet_values(src_ws: gspread.Worksheet, dst_ws: gspread.Worksheet) -> None:
    """src_ws의 현재 표시값을 읽어 dst_ws에 RAW로 덮어써서 수식을 값으로 고정.

    복사본 생성 직후 GOOGLEFINANCE 등 외부 함수가 아직 로딩되지 않아
    #REF/#N/A가 찍히는 문제를 방지하기 위해 원본(src)에서 값을 읽는다.
    """
    all_values = src_ws.get_all_values(value_render_option="FORMATTED_VALUE")
    if not all_values:
        return
    last_row = len(all_values)
    last_col = max((len(r) for r in all_values), default=1)
    end_cell = col_num_to_letter(last_col) + str(last_row)
    dst_ws.update(all_values, f"A1:{end_cell}", value_input_option="RAW")


def freeze_cells(ws: gspread.Worksheet, cells: list[str]) -> dict:
    """지정 셀 목록의 값을 UNFORMATTED_VALUE로 읽어 RAW로 덮어쓰고, 값 dict 반환

    UNFORMATTED_VALUE를 사용해 숫자/날짜를 그대로 보존한다.
    """
    result = {}
    for cell_ref in cells:
        try:
            val = ws.acell(cell_ref, value_render_option="UNFORMATTED_VALUE").value
            result[cell_ref] = val
            if val is not None:
                ws.update([[val]], cell_ref, value_input_option="RAW")
        except Exception as e:
            print(f"   경고: {cell_ref} 처리 중 오류: {e}")
    return result


def detect_loading_errors(values: dict) -> list[str]:
    """값 dict에서 에러/로딩 중인 셀을 찾아 설명 목록 반환.

    Google Sheets 에러값(#N/A, #REF! 등), Loading..., None을 감지한다.
    """
    problems = []
    for cell_ref, val in values.items():
        if val is None:
            problems.append(f"{cell_ref}: 값 없음(None)")
        elif isinstance(val, str) and (
            val.startswith("#") or "Loading" in val or val.strip() == ""
        ):
            problems.append(f"{cell_ref}: {val!r}")
    return problems


def read_cells(ws: gspread.Worksheet, cells: list[str]) -> dict:
    """지정 셀 목록의 UNFORMATTED_VALUE를 읽어 dict 반환 (덮어쓰기 없음)"""
    result = {}
    for cell_ref in cells:
        try:
            val = ws.acell(cell_ref, value_render_option="UNFORMATTED_VALUE").value
            result[cell_ref] = val
        except Exception as e:
            print(f"   경고: {cell_ref} 읽기 중 오류: {e}")
    return result


def adjust_row_refs(formula: str, old_row: int, new_row: int) -> str:
    """수식 내 열 참조 행 번호를 조정한다.

    old_row → new_row, old_row-1 → old_row 로 치환.
    예: adjust_row_refs("=C93-C92-B93", 93, 94) → "=C94-C93-B94"
    절대 참조($4 등)는 변경하지 않는다.
    """
    if not isinstance(formula, str) or not formula.startswith("="):
        return formula

    def replacer(m: re.Match) -> str:
        prefix = m.group(1)   # '$' or ''
        num = int(m.group(2))
        if num == old_row:
            return prefix + str(new_row)
        elif num == old_row - 1:
            return prefix + str(old_row)
        return m.group(0)

    return re.sub(r"(?<=[A-Z])(\$?)(\d+)", replacer, formula)


def add_new_month_row(
    ws: gspread.Worksheet,
    date_str: str,
    ref_row: int,
    copy_formulas: bool = False,
    zero_col_letters: list[str] | None = None,
    format_end_col: str | None = None,
) -> int:
    """마지막 데이터 행 다음에 새 행을 추가하고, 새 행 번호 반환.

    copy_formulas=True: ref_row 수식 패턴을 복사해 새 행을 채운다.
      - 행 참조(ref_row, ref_row-1)는 새 행 번호에 맞게 자동 조정.
      - zero_col_letters에 지정된 열은 0으로 설정 (예: ["J", "N"]).
      - format_end_col: 서식 복사 마지막 열 문자 (예: "Q"). None이면 데이터 열 전체.
    copy_formulas=False: A열에 date_str만 입력 (기존 동작).
    """
    new_row = ref_row + 1

    if not copy_formulas:
        ws.update([[date_str]], f"A{new_row}", value_input_option="RAW")
        return new_row

    # 참조 행 수식 전체 읽기
    range_data = ws.get(f"{ref_row}:{ref_row}", value_render_option="FORMULA")
    formulas = range_data[0] if range_data else []
    if not formulas:
        ws.update([[date_str]], f"A{new_row}", value_input_option="RAW")
        return new_row

    # zero 처리할 열 인덱스(0-based) 계산
    zero_indices: set[int] = set()
    for col_str in (zero_col_letters or []):
        n = 0
        for ch in col_str.upper():
            n = n * 26 + (ord(ch) - ord("A") + 1)
        zero_indices.add(n - 1)

    new_row_data = []
    for i, cell_val in enumerate(formulas):
        if i in zero_indices:
            new_row_data.append(0)
        elif isinstance(cell_val, str) and cell_val.startswith("="):
            new_row_data.append(adjust_row_refs(cell_val, ref_row, new_row))
        else:
            new_row_data.append(cell_val)

    # 서식 먼저 복사 (ref_row → new_row)
    num_cols = len(new_row_data)
    fmt_cols = num_cols
    if format_end_col:
        n = 0
        for ch in format_end_col.upper():
            n = n * 26 + (ord(ch) - ord("A") + 1)
        fmt_cols = n
    ws.spreadsheet.batch_update({
        "requests": [{
            "copyPaste": {
                "source": {
                    "sheetId": ws.id,
                    "startRowIndex": ref_row - 1,
                    "endRowIndex": ref_row,
                    "startColumnIndex": 0,
                    "endColumnIndex": fmt_cols,
                },
                "destination": {
                    "sheetId": ws.id,
                    "startRowIndex": new_row - 1,
                    "endRowIndex": new_row,
                    "startColumnIndex": 0,
                    "endColumnIndex": fmt_cols,
                },
                "pasteType": "PASTE_FORMAT",
                "pasteOrientation": "NORMAL",
            }
        }]
    })

    end_col = col_num_to_letter(num_cols)
    ws.update(
        [new_row_data],
        f"A{new_row}:{end_col}{new_row}",
        value_input_option="USER_ENTERED",
    )
    return new_row


def read_settings(doc: gspread.Spreadsheet) -> tuple[dict, gspread.Worksheet]:
    """'설정' 시트에서 설정값 읽기"""
    try:
        ws = doc.worksheet("설정")
    except gspread.WorksheetNotFound:
        raise RuntimeError(
            "'설정' 시트가 없습니다. 먼저 --setup 옵션으로 설정 시트를 생성하세요."
        )
    data = ws.get_all_values()
    settings = {}
    for row in data[1:]:  # 헤더 행 스킵
        if len(row) >= 2 and row[0].strip():
            settings[row[0].strip()] = row[1].strip()
    return settings, ws


def run_snapshot(gc: gspread.Client, drive_service, sheet_url: str, dry_run: bool = False) -> None:
    """메인 스냅샷 실행 (Phase 1)

    dry_run=True: 복사본 생성·고정까지만 실제 실행, 원본 수정(6~10단계)은 출력만.
    """
    today = date.today()
    prev_year, prev_month = prev_month_of(today)
    snapshot_title = f"포트폴리오 {prev_year}-{prev_month:02d} 스냅샷"

    mode = "[DRY-RUN] " if dry_run else ""
    # 15일 이후면 당월, 15일 이전이면 전월 기준으로 자동 선택
    if today.day > 15:
        snap_year, snap_month = today.year, today.month
    else:
        snap_year, snap_month = prev_year, prev_month
    snapshot_title = f"포트폴리오 {snap_year}-{snap_month:02d} 스냅샷"

    print(f"\n{mode}{snapshot_title}을 생성합니다.")
    if dry_run:
        print("※ dry-run 모드: 복사본 생성·고정까지만 실행, 원본은 변경하지 않습니다.")

    # ── 1. 원본 열기 ────────────────────────────────────────────────────────
    print("\n[1] 원본 스프레드시트 열기...")
    file_id = get_file_id_from_url(sheet_url)
    doc = gc.open_by_url(sheet_url)
    _, settings_ws = read_settings(doc)

    # ── 2. Drive API로 문서 복사 ────────────────────────────────────────────
    print(f"[2] 문서 복사 중: '{snapshot_title}'...")
    copy_id = copy_spreadsheet(drive_service, file_id, snapshot_title)
    copy_url = f"https://docs.google.com/spreadsheets/d/{copy_id}/edit"
    print(f"    복사본: {copy_url}")
    copy_doc = gc.open_by_key(copy_id)

    # ── 3. 복사본 전체 시트 값 고정 (원본에서 읽어서 복사본에 씀) ─────────────
    # 복사 직후 GOOGLEFINANCE 등이 로딩 전이라 #NUM/#REF가 찍히는 문제 방지
    print("[3] 복사본 전체 시트 값 고정 중...")
    orig_sheets = {ws.title: ws for ws in doc.worksheets()}
    copy_sheets = {ws.title: ws for ws in copy_doc.worksheets()}
    for title, orig_ws in orig_sheets.items():
        if title not in copy_sheets:
            print(f"    경고: 복사본에 '{title}' 시트 없음, 스킵")
            continue
        print(f"    {title}...", end=" ", flush=True)
        freeze_sheet_values(orig_ws, copy_sheets[title])
        print("완료")

    # ── 4. 복사본 '월별 수익률' 마지막 행 특정 셀 고정 ──────────────────────
    # 원본에서 값을 읽어 복사본에 씀 (타이밍 문제 방지)
    print("[4] 복사본 '월별 수익률' 마지막 행 고정 중...")
    snapshot_values: dict = {}
    monthly_last_row: int | None = None
    try:
        monthly_orig_ws = doc.worksheet("월별 수익률")
        monthly_copy = copy_doc.worksheet("월별 수익률")
        monthly_last_row = get_last_data_row(monthly_orig_ws)
        cells_to_freeze = [f"{c}{monthly_last_row}" for c in MONTHLY_COLS_TO_FREEZE]
        # 원본에서 읽기, 복사본에 쓰기
        snapshot_values = read_cells(monthly_orig_ws, cells_to_freeze)
        for cell_ref, val in snapshot_values.items():
            if val is not None:
                monthly_copy.update([[val]], cell_ref, value_input_option="RAW")
        print(f"    {monthly_last_row}행 고정 완료 ({len(snapshot_values)}셀)")

        # 마지막 행 서식을 바로 위 행에서 전체 복사
        if monthly_last_row > 1:
            copy_doc.batch_update({"requests": [{"copyPaste": {
                "source": {
                    "sheetId": monthly_copy.id,
                    "startRowIndex": monthly_last_row - 2,
                    "endRowIndex": monthly_last_row - 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": 1000,
                },
                "destination": {
                    "sheetId": monthly_copy.id,
                    "startRowIndex": monthly_last_row - 1,
                    "endRowIndex": monthly_last_row,
                    "startColumnIndex": 0,
                    "endColumnIndex": 1000,
                },
                "pasteType": "PASTE_FORMAT",
                "pasteOrientation": "NORMAL",
            }}]})
            print(f"    {monthly_last_row}행 서식 복원 완료 (전체 열)")
    except gspread.WorksheetNotFound:
        print("    경고: 복사본 '월별 수익률' 시트를 찾을 수 없습니다.")

    # ── 5. 복사본 '자산배분현황' 환율 셀 고정 ──────────────────────────────
    print("[5] 복사본 '자산배분현황' 환율 셀 고정 중...")
    current_rate = None
    try:
        alloc_orig = doc.worksheet("자산배분현황")
        alloc_copy = copy_doc.worksheet("자산배분현황")
        alloc_values = read_cells(alloc_orig, [ALLOC_PREV_RATE_CELL, ALLOC_CURR_RATE_CELL])
        for cell_ref, val in alloc_values.items():
            if val is not None:
                alloc_copy.update([[val]], cell_ref, value_input_option="RAW")
        current_rate = alloc_values.get(ALLOC_CURR_RATE_CELL)
        print(
            f"    전월환율({ALLOC_PREV_RATE_CELL}): {alloc_values.get(ALLOC_PREV_RATE_CELL)}, "
            f"현재환율({ALLOC_CURR_RATE_CELL}): {current_rate}"
        )
    except gspread.WorksheetNotFound:
        print("    경고: 복사본 '자산배분현황' 시트를 찾을 수 없습니다.")

    # ── 5-b. 스냅샷 값 유효성 검사 ──────────────────────────────────────────
    # 에러/로딩 중인 값이 있으면 복사본 삭제 후 작업 중단 (원본 보존)
    essential_cells = {
        k: v for k, v in snapshot_values.items()
        if any(k.startswith(c) for c in ["F", "H", "K", "O"])
    }
    if current_rate is not None:
        essential_cells[ALLOC_CURR_RATE_CELL] = current_rate
    problems = detect_loading_errors(essential_cells)
    if problems:
        print("\n❌ 스냅샷 값에 에러/로딩 중인 셀이 감지되었습니다:")
        for p in problems:
            print(f"   {p}")
        print("   원본 파일을 보존하고 작업을 중단합니다.")
        print("   복사본 삭제 중...")
        try:
            drive_service.files().delete(fileId=copy_id).execute()
            print("   복사본 삭제 완료.")
        except Exception as e:
            print(f"   경고: 복사본 삭제 실패 ({e}). 수동 삭제 필요: {copy_url}")
        return

    # ── 6~10. 원본 수정 (dry-run이면 출력만) ────────────────────────────────
    monthly_orig = None
    orig_monthly_last_row: int | None = None
    try:
        monthly_orig = doc.worksheet("월별 수익률")
        orig_monthly_last_row = get_last_data_row(monthly_orig)
    except gspread.WorksheetNotFound:
        pass

    # 원본 마지막 행에 덮어쓸 값 미리 계산
    orig_updates = {}
    if orig_monthly_last_row is not None:
        for col in MONTHLY_COLS_TO_FREEZE:
            val = snapshot_values.get(f"{col}{monthly_last_row}")
            if val is not None:
                orig_updates[f"{col}{orig_monthly_last_row}"] = val

    # MTD 거래일 계산 (dry-run이어도 조회는 함)
    kr_last = us_last = None
    try:
        kr_last = get_recent_last_trading_day("KR", as_of=today)
    except Exception as e:
        print(f"    경고: 한국 마지막 거래일 조회 실패: {e}")
    try:
        us_last = get_recent_last_trading_day("US", as_of=today)
    except Exception as e:
        print(f"    경고: 미국 마지막 거래일 조회 실패: {e}")

    if dry_run:
        print("\n[DRY-RUN] 원본에 적용할 변경 내용 (실제로는 실행하지 않음):")
        print(f"  [6] 원본 '월별 수익률' {orig_monthly_last_row}행 고정 ({len(orig_updates)}셀):")
        for cell, val in orig_updates.items():
            print(f"      {cell} = {val}")
        new_row_num = (orig_monthly_last_row or 0) + 1
        print(f"  [7] 원본 '월별 수익률' {new_row_num}행 추가 (날짜: {today})")
        print(f"  [8] 원본 '월별 수익률 지수비교' 새 행 추가 (날짜: {today})")
        print(f"  [9] 원본 '월별 누적' 새 행 추가 (날짜: {today})")
        print(f"  [10] 설정 시트:")
        print(f"      전월환율(B4) → {current_rate}")
        print(f"      한국주식MTD기준일(B2) → {kr_last}")
        print(f"      미국주식MTD기준일(B3) → {us_last}")
        print(f"\n✅ dry-run 완료. 복사본 URL: {copy_url}")
        print("   복사본을 확인 후 Drive에서 삭제하세요.")
        return

    # ── 실제 원본 수정 ────────────────────────────────────────────────────
    print("[6] 원본 '월별 수익률' 마지막 행 고정 중...")
    if monthly_orig and orig_updates:
        batch = [{"range": cell, "values": [[val]]} for cell, val in orig_updates.items()]
        monthly_orig.batch_update(batch, value_input_option="RAW")
        print(f"    {orig_monthly_last_row}행 고정 완료 ({len(batch)}셀)")

    print("[7] 원본 '월별 수익률' 새 행 추가 중...")
    if monthly_orig and orig_monthly_last_row:
        new_row = add_new_month_row(
            monthly_orig, today.strftime("%Y-%m-%d"), orig_monthly_last_row,
            copy_formulas=True, zero_col_letters=["J", "N"], format_end_col="Q",
        )
        print(f"    {new_row}행 추가 완료")

    print("[8] 원본 '월별 수익률 지수비교' 새 행 추가 중...")
    try:
        idx_orig = doc.worksheet("월별 수익률 지수비교")
        new_row = add_new_month_row(
            idx_orig, today.strftime("%Y-%m-%d"), get_last_data_row(idx_orig),
            copy_formulas=True,
        )
        print(f"    {new_row}행 추가 완료")
    except gspread.WorksheetNotFound:
        print("    경고: '월별 수익률 지수비교' 시트를 찾을 수 없습니다.")

    print("[9] 원본 '월별 누적' 새 행 추가 중...")
    try:
        cum_orig = doc.worksheet("월별 누적")
        new_row = add_new_month_row(
            cum_orig, today.strftime("%Y-%m-%d"), get_last_data_row(cum_orig),
            copy_formulas=True,
        )
        print(f"    {new_row}행 추가 완료")
    except gspread.WorksheetNotFound:
        print("    경고: '월별 누적' 시트를 찾을 수 없습니다.")

    print("[10] '설정' 시트 업데이트 중...")
    if current_rate is not None:
        settings_ws.update([[current_rate]], "B4", value_input_option="RAW")
        print(f"    전월환율 → {current_rate}")
    if kr_last:
        settings_ws.update([[kr_last.strftime("%Y-%m-%d")]], "B2", value_input_option="RAW")
        print(f"    한국주식MTD기준일 → {kr_last}")
    if us_last:
        settings_ws.update([[us_last.strftime("%Y-%m-%d")]], "B3", value_input_option="RAW")
        print(f"    미국주식MTD기준일 → {us_last}")

    print(f"\n✅ 완료!")
    print(f"   스냅샷: {snapshot_title}")
    print(f"   복사본 URL: {copy_url}")
    return copy_url


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------

def main():
    setup_only = "--setup" in sys.argv
    fix_refs   = "--fix-refs" in sys.argv
    dry_run    = "--dry-run" in sys.argv

    sheet_url = load_sheet_url()
    if not sheet_url:
        print("❌ SHEET_URL이 설정되지 않았습니다.")
        sys.exit(1)

    print("인증 중...")
    gc, drive_service = authenticate()
    doc = gc.open_by_url(sheet_url)

    if setup_only:
        print("\n[Phase 0] '설정' 시트 생성")
        setup_settings_sheet(doc)
    elif fix_refs:
        print("\n[Phase 0-b] raw 시트 참조 수식 → '설정' 시트 참조로 변경")
        fix_raw_references(doc)
    else:
        run_snapshot(gc, drive_service, sheet_url, dry_run=dry_run)


if __name__ == "__main__":
    main()
