# 포트폴리오 트리맵 시각화

Google Sheets에 기록된 자산 현황을 인터랙티브 트리맵으로 시각화하는 Streamlit 앱입니다.
USD/KRW 환율 차트와 월말 스냅샷 자동화 기능도 포함되어 있습니다.

---

## 주요 기능

- **자산 트리맵**: 구분 → 자산종류 → 종목명 계층으로 포트폴리오 비중을 시각화
- **성과 색상**: 1D / MTD / 1Y 수익률 기준으로 빨강(-)~검정(0)~초록(+) 색상 표시
- **환율 차트**: USD/KRW 실시간 데이터 (yfinance), 기간 선택 가능
- **월별 스냅샷**: 월말 포트폴리오 상태를 Google Drive에 자동 복사·보존
- **모바일 최적화**: 화면 크기에 따라 트리맵 높이 자동 조정

---

## 로컬 실행

### 1. 환경 설정

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 인증 파일 준비

**Google Cloud 서비스 계정 설정:**

1. [Google Cloud Console](https://console.cloud.google.com/)에서 서비스 계정 생성
2. JSON 키 파일 다운로드 → `service_account.json`으로 저장 (프로젝트 루트)
3. Google Sheet를 서비스 계정 이메일에 **편집자** 권한으로 공유

**Streamlit secrets 설정:**

`.streamlit/secrets.toml` 파일 생성:

```toml
password = "접속_비밀번호"
SHEET_URL = "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit"

[gcp_service_account]
type = "service_account"
project_id = "your-project-id"
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "your-sa@your-project.iam.gserviceaccount.com"
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
```

> `secrets.toml`과 `service_account.json`은 `.gitignore`에 포함되어 있습니다.

### 3. 앱 실행

```bash
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 접속 후 비밀번호를 입력합니다.

---

## Google Sheets 구조

앱이 읽는 워크시트: **"종목별 현황"**

| 열 | 내용 |
|---|---|
| 구분 | 자산 대분류 (예: 국내주식, 해외주식) |
| 자산종류 | 중분류 (예: ETF, 개별주식) |
| 종목명 | 개별 종목 이름 |
| 금액 | 평가금액 (₩ 형식, 예: ₩1,234,567) |
| 비중(%) | 포트폴리오 내 비중 (예: 5.2%) |
| 변동(1d) | 일간 수익률 |
| 변동(MTD)로컬 | MTD 현지 통화 수익률 |
| 변동(MTD)원화 | MTD 원화 환산 수익률 |
| 변동(1y) | 1년 수익률 |

---

## 사이드바 설정

| 설정 | 설명 |
|---|---|
| 색상 기준 | 트리맵 색상에 사용할 수익률 지표 선택 (1D / MTD / 1Y) |
| 색상 범위 | 색상 스케일 ±% 범위 조정 |
| 텍스트 줄바꿈 | 종목명 줄바꿈 기준 글자 수 |
| 트리맵 높이 | 차트 세로 크기 (px) |
| 트리맵 레벨 | 1~3단계 계층 선택 |
| 환율 조회 기간 | 1개월 / 3개월 / 6개월 / 1년 / 5년 / 10년 |
| 데이터 새로고침 | 캐시 초기화 후 Google Sheets 재조회 |

---

## 월별 스냅샷 (`monthly_snapshot.py`)

월말에 포트폴리오 스프레드시트 전체를 Google Drive에 복사하고, 수식을 값으로 고정하여 기록을 보존합니다.

### 초기 설정 (최초 1회)

```bash
# 1. '설정' 시트 생성
python monthly_snapshot.py --setup

# 2. OAuth2 개인 계정 인증 (브라우저 팝업 → 권한 허용)
#    token.json이 생성되면 이후 자동 갱신됨
python monthly_snapshot.py --dry-run
```

`client_secret_*.json` 파일 (OAuth2 클라이언트 시크릿)이 프로젝트 루트에 있어야 합니다.

### 월말 실행

```bash
# 실제 스냅샷 생성
python monthly_snapshot.py

# 원본 수정 없이 복사본만 생성 (검증용)
python monthly_snapshot.py --dry-run
```

실행 시 전월/당월 중 스냅샷 대상 월을 선택할 수 있습니다.

### 스냅샷 동작 순서

1. 원본 스프레드시트를 Drive에 복사 (`포트폴리오 YYYY-MM 스냅샷`)
2. 복사본 전체 시트의 수식을 값으로 고정
3. "월별 수익률" 마지막 행의 주요 셀 고정
4. "자산배분현황" 환율 셀(전월/현재) 고정
5. 원본 "월별 수익률", "월별 수익률 지수비교", "월별 누적"에 새 월 행 추가
6. "설정" 시트의 전월환율·MTD 기준일 업데이트

---

## Streamlit Cloud 배포

1. GitHub 저장소에 코드 푸시 (`service_account.json`, `secrets.toml` 제외)
2. [Streamlit Cloud](https://streamlit.io/cloud)에서 저장소 연결
3. **App settings → Secrets**에 `secrets.toml` 내용 붙여넣기
4. 배포

---

## GitHub Codespaces

저장소를 Codespaces에서 열면 자동으로 의존성이 설치되고 앱이 실행됩니다 (포트 8501 자동 포워딩).
단, `secrets.toml`과 `service_account.json`은 Codespaces Secrets 또는 직접 생성이 필요합니다.
