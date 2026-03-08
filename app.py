import streamlit as st
import pandas as pd
import gspread
import plotly.express as px
import plotly.graph_objects as go
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

# --- Viewport 감지 (모바일/데스크탑 기본 높이 자동 설정) ---
from streamlit_js_eval import streamlit_js_eval
if 'viewport_width' not in st.session_state:
    vw = streamlit_js_eval(js_expressions="screen.width", key="screen_width")
    if vw is None:
        st.stop()  # JS 결과 오기 전까지 데이터 로딩 안 함
    st.session_state.viewport_width = vw

default_treemap_height = 800 if st.session_state.viewport_width > 768 else 600
# -------------------------------------------------------

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
    selected_color_label = st.sidebar.selectbox("색상 기준", list(color_options.keys()), index=2)
    color_num_col, color_raw_col, default_range = color_options[selected_color_label]
    
    # 색상 범위 커스텀 조절
    color_range = st.sidebar.slider(
        "🎚️ 색상 범위 (±%)", min_value=1, max_value=50, value=default_range
    )
    
    # 화면 크기에 따라 사용자가 직접 조절할 수 있도록 슬라이더 추가
    wrap_width = st.sidebar.slider("텍스트 줄바꿈 기준 (글자수)", min_value=5, max_value=30, value=10)

    # 트리맵 높이 조절 슬라이더
    treemap_height = st.sidebar.slider("📏 트리맵 높이 (px)", min_value=400, max_value=1200, value=default_treemap_height, step=50)

    # 트리맵 레벨 선택
    level_options = {
        '3단계: 구분 → 자산종류 → 종목': [px.Constant("전체"), '구분', '자산종류', '종목명_display'],
        '2단계: 구분 → 자산종류': [px.Constant("전체"), '구분', '자산종류'],
        '1단계: 구분': [px.Constant("전체"), '구분'],
    }
    selected_level_label = st.sidebar.radio("🗂️ 트리맵 레벨", list(level_options.keys()), index=0)

    # --- 시장 차트 설정 ---
    st.sidebar.markdown("---")
    st.sidebar.header("📈 시장 차트 설정")

    period_options = {
        '1개월': '1mo',
        '3개월': '3mo',
        '6개월': '6mo',
        '1년': '1y',
        '5년': '5y',
        '10년': '10y'
    }
    selected_period_label = st.sidebar.selectbox("조회 기간", list(period_options.keys()), index=1)
    selected_period = period_options[selected_period_label]

    interval_options = {'일봉': '1d', '주봉': '1wk', '월봉': '1mo'}
    selected_interval_label = st.sidebar.radio("봉 단위", list(interval_options.keys()), index=0)
    selected_interval = interval_options[selected_interval_label]
    
    # 설정한 글자수 기준으로 줄바꿈 처리
    df['종목명_display'] = df['종목명'].apply(lambda x: "<br>".join(textwrap.wrap(str(x), width=wrap_width)))

    # 레벨별 가중평균 변동값 사전 계산 (1/2단계에서 (?) 방지)
    for group_col in ['구분', '자산종류']:
        grouped = df.groupby(group_col).apply(
            lambda x: (x[color_num_col] * x['비중_숫자']).sum() / x['비중_숫자'].sum()
            if x['비중_숫자'].sum() > 0 else 0.0,
            include_groups=False
        ).reset_index(name=f'{group_col}_변동_숫자')
        df = df.merge(grouped, on=group_col, how='left')
        df[f'{group_col}_변동_str'] = df[f'{group_col}_변동_숫자'].apply(lambda v: f"{v:+.1f}%")

    level_change_col = {
        '3단계: 구분 → 자산종류 → 종목': color_raw_col,
        '2단계: 구분 → 자산종류': '자산종류_변동_str',
        '1단계: 구분': '구분_변동_str',
    }
    display_change_col = level_change_col[selected_level_label]

    # 모바일 최적화: 트리맵만 크게 표시
    fig_tree = px.treemap(
        df,
        path=level_options[selected_level_label],
        values='비중_숫자',
        color=color_num_col,
        color_continuous_scale=[[0, '#FF0000'], [0.5, '#000000'], [1, '#00FF00']],
        range_color=[-color_range, color_range],
        hover_data=['종목명', display_change_col],
    )
    fig_tree.update_traces(
        texttemplate="<b>%{label}</b><br>%{value:.1f}% | %{customdata[1]}",
        textposition='middle center',
        textfont_size=16,
        hoverinfo='skip',
        hovertemplate=None,
    )

    fig_tree.update_layout(
        margin=dict(t=10, l=10, r=10, b=10),
        height=treemap_height,
        coloraxis_showscale=False,
        hovermode=False,
    )
    
    # Plotly 모드바 설정: Plotly 내장 전체화면 버튼 사용
    # 불필요한 버튼들은 제거하고 유용한 기능만 남김
    plotly_config = {
        'displayModeBar': True,  # 모드바 표시 (전체화면 버튼 포함)
        'displaylogo': False,  # Plotly 로고 숨김
        'modeBarButtonsToRemove': ['select2d', 'lasso2d', 'autoScale2d'],  # 불필요한 버튼 제거
    }

    st.plotly_chart(fig_tree, width='stretch', config=plotly_config)
    st.markdown(f"<div style='text-align:right; color:gray; font-size:12px; margin-top:-34px; padding-right:10px;'>색상 기준: {selected_color_label} | ±{color_range}%</div>", unsafe_allow_html=True)

    # 시장 차트 추가
    st.markdown("---")
    st.subheader(f"📈 시장 차트 ({selected_period_label} · {selected_interval_label})")

    tick_format = "%m-%d" if selected_period in ['1mo', '3mo', '6mo'] else "%y-%m"

    @st.cache_data(ttl=3600)
    def get_market_data(ticker_symbol, period_str, interval_str):
        import yfinance as yf
        hist = yf.Ticker(ticker_symbol).history(period=period_str, interval=interval_str)
        if hist.empty:
            return hist
        return hist[['Open', 'High', 'Low', 'Close']]

    def make_candlestick_fig(ohlc_df, tick_fmt):
        fig = go.Figure(data=[go.Candlestick(
            x=ohlc_df.index,
            open=ohlc_df['Open'],
            high=ohlc_df['High'],
            low=ohlc_df['Low'],
            close=ohlc_df['Close'],
            increasing_line_color='#00CC44',
            decreasing_line_color='#FF3333',
            increasing_fillcolor='#00CC44',
            decreasing_fillcolor='#FF3333',
        )])
        fig.update_layout(
            xaxis_rangeslider_visible=False,
            xaxis=dict(tickformat=tick_fmt, nticks=6, tickangle=0),
            xaxis_title="",
            yaxis_title="",
            margin=dict(t=5, l=10, r=10, b=10),
            height=220,
        )
        return fig

    chart_config = {'displayModeBar': False}

    def render_chart(symbol):
        try:
            data = get_market_data(symbol, selected_period, selected_interval)
            if not data.empty:
                st.plotly_chart(make_candlestick_fig(data, tick_format), use_container_width=True, config=chart_config)
            else:
                st.warning("데이터를 가져올 수 없습니다.")
        except Exception as e:
            st.error(f"오류: {e}")

    with st.spinner('시장 데이터를 불러오는 중...'):
        st.markdown("**💱 USD/KRW 환율**")
        render_chart("USDKRW=X")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**🇺🇸 S&P 500**")
            render_chart("^GSPC")
        with col2:
            st.markdown("**🇺🇸 NASDAQ 100**")
            render_chart("^NDX")

        col3, col4 = st.columns(2)
        with col3:
            st.markdown("**🇰🇷 KOSPI**")
            render_chart("^KS11")
        with col4:
            st.markdown("**🇰🇷 KOSDAQ**")
            render_chart("^KQ11")

        # 기준금리 차트
        st.markdown("**📊 기준금리 (미국 · 한국)**")

        @st.cache_data(ttl=86400)
        def get_interest_rates(period_str, interval_str):
            import requests, io
            from datetime import date, timedelta
            period_days = {
                '1mo': 30, '3mo': 90, '6mo': 180,
                '1y': 365, '5y': 365 * 5, '10y': 365 * 10,
            }
            start = (date.today() - timedelta(days=period_days.get(period_str, 90))).strftime('%Y-%m-%d')

            def fetch_fred(series_id):
                url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
                resp = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
                if resp.status_code != 200:
                    return pd.Series(dtype=float, name=series_id)
                df = pd.read_csv(io.StringIO(resp.text), index_col=0, parse_dates=True)
                series = pd.to_numeric(df.iloc[:, 0], errors='coerce')
                series.name = series_id
                return series[series.index >= pd.Timestamp(start)]

            # 미국: DFF (일별 실효기준금리), 한국: IR3TIB01KRM156N (3개월 은행간금리, 월별)
            # 미국 10년물: DGS10 (일별), 한국 10년물: IRLTLT01KRM156N (월별)
            us_base = fetch_fred('DFF')
            kr_base = fetch_fred('IR3TIB01KRM156N')
            us_10y  = fetch_fred('DGS10')
            kr_10y  = fetch_fred('IRLTLT01KRM156N')
            combined = pd.DataFrame({
                '미국 기준금리': us_base,
                '한국 기준금리': kr_base,
                '미국 10년물':   us_10y,
                '한국 10년물':   kr_10y,
            })
            # 월별 시리즈 앞값 채움
            for col in ['한국 기준금리', '한국 10년물']:
                combined[col] = combined[col].ffill()
            if interval_str == '1wk':
                combined = combined.resample('W').last()
            elif interval_str == '1mo':
                combined = combined.resample('ME').last()
            return combined.dropna(how='all')

        try:
            rate_df = get_interest_rates(selected_period, selected_interval)
            if not rate_df.empty:
                fig_rate = go.Figure()
                traces = [
                    ('미국 기준금리', '#4488FF', 'solid'),
                    ('한국 기준금리', '#FF6644', 'solid'),
                    ('미국 10년물',   '#44CCFF', 'dot'),
                    ('한국 10년물',   '#FFAA44', 'dot'),
                ]
                for col, color, dash in traces:
                    if col in rate_df.columns:
                        fig_rate.add_trace(go.Scatter(
                            x=rate_df.index, y=rate_df[col],
                            mode='lines', name=col,
                            line=dict(color=color, shape='hv', width=2, dash=dash),
                        ))
                fig_rate.update_layout(
                    xaxis=dict(tickformat=tick_format, nticks=6, tickangle=0),
                    xaxis_title="", yaxis_title="%",
                    margin=dict(t=25, l=10, r=10, b=10),
                    height=250,
                    legend=dict(orientation='h', yanchor='bottom', y=1.0, xanchor='left', x=0),
                )
                st.plotly_chart(fig_rate, use_container_width=True, config=chart_config)
            else:
                st.warning("금리 데이터를 가져올 수 없습니다.")
        except Exception as e:
            st.error(f"기준금리 데이터 오류: {e}")

except Exception as e:
    st.error(f"오류가 발생했습니다: {e}")