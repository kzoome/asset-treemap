import streamlit as st
import pandas as pd
import gspread
import plotly.express as px
from google.oauth2.service_account import Credentials
import textwrap
import streamlit.components.v1 as components

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

@st.cache_data(ttl=600)  # 600초(10분)마다 캐시를 만료시키고 데이터를 새로 가져옵니다.
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

    # 모든 변동 컬럼을 숫자로 변환
    for col in ['변동_1d', '변동_MTD_local', '변동_MTD_KRW', '변동_1y']:
        if col in df.columns:
            df[f'{col}_숫자'] = df[col].apply(clean_percentage)

    return df

# 3. 메인 화면 구성
st.title("Treemap")

try:
    with st.spinner('구글 시트에서 데이터를 불러오는 중...'):
        df = load_data()
    
    # 사이드바 설정
    st.sidebar.header("🎨 시각화 설정")

    # 데이터 새로고침 버튼
    if st.sidebar.button("🔄 데이터 새로고침"):
        st.cache_data.clear()
        st.rerun()
    
    # 색상 기준 선택
    color_options = {
        '1D (일간)': ('변동_1d_숫자', '변동_1d', 3),
        'MTD Local': ('변동_MTD_local_숫자', '변동_MTD_local', 10),
        'MTD KRW (원화)': ('변동_MTD_KRW_숫자', '변동_MTD_KRW', 10),
        '1Y (연간)': ('변동_1y_숫자', '변동_1y', 30),
    }
    selected_color_label = st.sidebar.selectbox("색상 기준", list(color_options.keys()), index=0)
    color_num_col, color_raw_col, default_range = color_options[selected_color_label]
    
    # 색상 범위 커스텀 조절
    color_range = st.sidebar.slider(
        "🎚️ 색상 범위 (±%)", min_value=1, max_value=50, value=default_range
    )
    
    # 화면 크기에 따라 사용자가 직접 조절할 수 있도록 슬라이더 추가
    wrap_width = st.sidebar.slider("텍스트 줄바꿈 기준 (글자수)", min_value=5, max_value=30, value=10)

    # 트리맵 높이 조절 슬라이더
    treemap_height = st.sidebar.slider("📏 트리맵 높이 (px)", min_value=400, max_value=1200, value=600, step=50)

    # --- 환율 차트 설정 ---
    st.sidebar.markdown("---")
    st.sidebar.header("📈 환율 차트 설정")
    
    # 기간 선택 드롭다운 (1개월 ~ 10년)
    period_options = {
        '1개월': '1mo',
        '3개월': '3mo',
        '6개월': '6mo',
        '1년': '1y',
        '5년': '5y',
        '10년': '10y'
    }
    
    # 기본값을 '3개월'로 설정 (index 1)
    selected_period_label = st.sidebar.selectbox("조회 기간", list(period_options.keys()), index=1)
    selected_period = period_options[selected_period_label]
    
    # 설정한 글자수 기준으로 줄바꿈 처리
    df['종목명_display'] = df['종목명'].apply(lambda x: "<br>".join(textwrap.wrap(str(x), width=wrap_width)))

    # 모바일 최적화: 트리맵만 크게 표시
    fig_tree = px.treemap(
        df,
        path=[px.Constant("전체"), '구분', '자산종류', '종목명_display'],
        values='비중_숫자',
        color=color_num_col,
        color_continuous_scale=[[0, '#FF0000'], [0.5, '#000000'], [1, '#00FF00']],
        range_color=[-color_range, color_range],
        hover_data=['종목명', color_raw_col],
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
        height=treemap_height,
        coloraxis_showscale=False,  # UI를 깔끔하게 하기 위해 색상 바 숨김
        hovermode=False            # 차트 전체의 호버 모드 비활성화
    )
    
    # Plotly 모드바 설정: Plotly 내장 전체화면 버튼 사용
    # 불필요한 버튼들은 제거하고 유용한 기능만 남김
    plotly_config = {
        'displayModeBar': True,  # 모드바 표시 (전체화면 버튼 포함)
        'displaylogo': False,  # Plotly 로고 숨김
        'modeBarButtonsToRemove': ['select2d', 'lasso2d', 'autoScale2d'],  # 불필요한 버튼 제거
    }

    st.plotly_chart(fig_tree, use_container_width=True, config=plotly_config)

    # 환율 차트 추가
    st.markdown("---")
    st.subheader(f"📈 USD/KRW 환율 ({selected_period_label})")
    
    @st.cache_data(ttl=3600)  # 1시간마다 환율 데이터 갱신
    def get_exchange_rate(period_str):
        import yfinance as yf
        ticker = yf.Ticker("USDKRW=X")
        hist = ticker.history(period=period_str)
        return hist[['Close']]
        
    try:
        with st.spinner('환율 데이터를 불러오는 중...'):
            exchange_df = get_exchange_rate(selected_period)
            if not exchange_df.empty:
                # 데이터 구간에 따라 x축 눈금 및 포맷 조절
                tick_format = "%y-%m-%d"
                if selected_period in ['1mo', '3mo', '6mo']:
                    tick_format = "%m-%d" # 짧은/중간 기간이면 월/일
                else: 
                    tick_format = "%y-%m" # 1년 이상이면 년/월

                
                # st.line_chart 대신 Plotly를 사용하여 y축이 0부터 시작하지 않도록 자동 스케일링
                fig_ex = px.line(
                    exchange_df, 
                    y='Close', 
                    title=""  # 제목 중복을 피하기 위해 Plotly 차트 자체 제목은 비움
                )
                fig_ex.update_layout(
                    xaxis_title="",
                    yaxis_title="",         # 세로축 '원' 범례 제거
                    xaxis=dict(
                        tickformat=tick_format, # 동적으로 포맷 설정
                        nticks=6,               # x축에 표시할 눈금(tick)의 최대 개수를 제한하여 빽빽하지 않게 설정
                        tickangle=0             # 날짜가 똑바로 보이게 (0도)
                    ),
                    margin=dict(t=10, l=10, r=10, b=10), # 상단 여백(t)을 줄여서 공간 확보
                    height=250 # 높이도 모바일에 맞게 약간 축소
                )
                fig_ex.update_yaxes(autorange=True) # 데이터 범위에 맞게 자동 조절
                
                st.plotly_chart(fig_ex, use_container_width=True, config={'displayModeBar': False})
            else:
                st.warning("환율 데이터를 가져올 수 없습니다.")
    except Exception as e:
        st.error(f"환율 데이터를 가져오는데 실패했습니다: {e}")

except Exception as e:
    st.error(f"오류가 발생했습니다: {e}")