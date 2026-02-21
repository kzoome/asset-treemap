import streamlit as st
import pandas as pd
import gspread
import plotly.express as px
from google.oauth2.service_account import Credentials
import socket
import textwrap

# 1. 페이지 설정
st.set_page_config(page_title="내 포트폴리오", layout="wide")

# --- 비밀번호 보호 기능 ---
def check_password():
    """비밀번호가 맞으면 True, 아니면 False 반환"""
    # 비밀번호가 설정되어 있지 않으면(로컬 개발 환경 등) 통과
    # (주의: 배포 시에는 반드시 Secrets에 'password'를 설정해야 함)
    if "password" not in st.secrets:
        return True

    def password_entered():
        if st.session_state["password"] == st.secrets["password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # 보안을 위해 입력값 삭제
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("🔒 비밀번호를 입력하세요", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("🔒 비밀번호를 입력하세요", type="password", on_change=password_entered, key="password")
        st.error("❌ 비밀번호가 틀렸습니다.")
        return False
    else:
        return True

if not check_password():
    st.stop()
# -----------------------

# 2. 구글 시트 연결 설정
SERVICE_ACCOUNT_FILE = 'service_account.json'
SHEET_URL = st.secrets.get("SHEET_URL", "https://docs.google.com/spreadsheets/d/YOUR_DEFAULT_URL/edit")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

@st.cache_data
def load_data():
    """구글 시트에서 데이터를 가져와 DataFrame으로 변환하는 함수"""
    # 배포 환경(Secrets)과 로컬 환경(파일) 모두 지원하도록 수정
    try:
        credentials = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"], scopes=SCOPES
        )
    except (FileNotFoundError, KeyError):
        credentials = Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        
    gc = gspread.authorize(credentials)
    doc = gc.open_by_url(SHEET_URL)
    worksheet = doc.worksheet("종목별 현황")
    
    # 모든 데이터 가져오기
    data = worksheet.get_all_values()
    
    # 데이터 구조에 맞춰 컬럼명 새로 정의 (중복 방지 및 편의성)
    # 원본 순서: 구분, 자산종류, 종목명, 금액(₩), 비중(%), 변동(1d), 변동(MTD)로컬, 변동(MTD)원화, 변동(1y)
    new_columns = [
        '구분', '자산종류', '종목명', '금액', '비중', 
        '변동_1d', '변동_MTD_local', '변동_MTD_KRW', '변동_1y'
    ]
    df = pd.DataFrame(data[1:], columns=new_columns)
    
    # 데이터 전처리: '금액' 컬럼을 숫자로 변환 (₩, , 제거)
    # 예: "₩81,643,700" -> 81643700
    def clean_currency(x):
        if isinstance(x, str):
            return int(x.replace('₩', '').replace(',', ''))
        return 0
        
    if '금액' in df.columns:
        df['금액_숫자'] = df['금액'].apply(clean_currency)
        
    # 데이터 전처리: 퍼센트(%) 문자열을 숫자로 변환하는 함수
    def clean_percentage(x):
        if isinstance(x, str):
            try:
                return float(x.replace('%', '').replace(',', ''))
            except ValueError:
                return 0.0
        return 0.0

    if '비중' in df.columns:
        df['비중_숫자'] = df['비중'].apply(clean_percentage)

    if '변동_1y' in df.columns:
        df['변동_숫자'] = df['변동_1y'].apply(clean_percentage)

    if '변동_MTD_KRW' in df.columns:
        df['변동_MTD_숫자'] = df['변동_MTD_KRW'].apply(clean_percentage)

    return df

# 3. 메인 화면 구성
st.title("Treemap")

# 사이드바: 자산 종류 필터
st.sidebar.header("🔍 필터")

# 모바일 접속 도우미 (QR코드)
with st.sidebar.expander("📱 모바일에서 접속하기"):
    try:
        # 현재 PC의 로컬 네트워크 IP 주소 가져오기
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_addr = s.getsockname()[0]
        s.close()
        url = f"http://{ip_addr}:8501"
        st.image(f"https://api.qrserver.com/v1/create-qr-code/?size=150x150&data={url}", caption="카메라로 스캔하세요")
        st.write(f"주소: `{url}`")
        st.info("⚠️ PC와 스마트폰이 **동일한 와이파이**에 연결되어 있어야 합니다.")
    except Exception:
        st.error("IP 주소를 확인할 수 없습니다.")

try:
    with st.spinner('구글 시트에서 데이터를 불러오는 중...'):
        df = load_data()
    
    # 필터 적용
    all_assets = df['자산종류'].unique()
    selected_assets = st.sidebar.multiselect("자산 종류 선택", all_assets, default=all_assets)
    
    # 화면 크기에 따라 사용자가 직접 조절할 수 있도록 슬라이더 추가
    wrap_width = st.sidebar.slider("텍스트 줄바꿈 기준 (글자수)", min_value=5, max_value=30, value=10)
    
    filtered_df = df[df['자산종류'].isin(selected_assets)].copy()
    
    # 설정한 글자수 기준으로 줄바꿈 처리
    filtered_df['종목명_display'] = filtered_df['종목명'].apply(lambda x: "<br>".join(textwrap.wrap(str(x), width=wrap_width)))
    
    # 모바일 최적화: 트리맵만 크게 표시
    fig_tree = px.treemap(
        filtered_df,
        path=[px.Constant("전체"), '구분', '자산종류', '종목명_display'],
        values='비중_숫자',
        color='변동_MTD_숫자',
        color_continuous_scale=[[0, '#FF0000'], [0.5, '#000000'], [1, '#00FF00']],
        range_color=[-10, 10],
        hover_data=['종목명', '변동_MTD_KRW'],
    )
    # 모바일 가독성을 위해 높이를 늘리고 텍스트 설정 최적화
    fig_tree.update_traces(
        texttemplate="<b>%{label}</b><br>%{value:.1f}% (%{customdata[1]})",
        textposition='middle center',
        textfont_size=16,
        hoverinfo='skip',  # 마우스 오버 이벤트 무시
        hovertemplate=None # 자동 생성된 호버 템플릿 제거
    )
    
    fig_tree.update_layout(
        margin=dict(t=10, l=10, r=10, b=10),
        height=600,
        coloraxis_showscale=False,  # UI를 깔끔하게 하기 위해 색상 바 숨김
        hovermode=False            # 차트 전체의 호버 모드 비활성화
    )
    
    # config={'displayModeBar': False}를 추가하여 모바일 방해 요소 제거
    st.plotly_chart(fig_tree, use_container_width=True, config={'displayModeBar': False})

    # 모바일 사용자를 위한 상세 데이터 표 추가
    with st.expander("📊 상세 데이터 보기"):
        st.dataframe(
            filtered_df[['종목명', '자산종류', '비중', '변동_MTD_KRW']],
            hide_index=True,
            use_container_width=True
        )
    
except Exception as e:
    st.error(f"오류가 발생했습니다: {e}")