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
    selected_period_label = st.sidebar.selectbox("조회 기간", list(period_options.keys()), index=3)
    selected_period = period_options[selected_period_label]

    interval_options = {'일봉': '1d', '주봉': '1wk', '월봉': '1mo'}
    selected_interval_label = st.sidebar.radio("봉 단위", list(interval_options.keys()), index=1)
    selected_interval = interval_options[selected_interval_label]

    # 기간+봉 단위 자동 조정 (yfinance 제한 대응)
    effective_interval = selected_interval
    effective_interval_label = selected_interval_label
    auto_adjusted = False
    if selected_period in ['5y', '10y'] and selected_interval == '1d':
        effective_interval = '1wk'
        effective_interval_label = '주봉'
        auto_adjusted = True
    elif selected_period == '10y' and selected_interval == '1wk':
        effective_interval = '1mo'
        effective_interval_label = '월봉'
        auto_adjusted = True
    if auto_adjusted:
        st.sidebar.caption(f"⚠️ {selected_period_label}에서 {selected_interval_label}은 데이터 제한으로 {effective_interval_label}으로 자동 변환됩니다.")

    df['종목명_display'] = df['종목명'].apply(lambda x: "<br>".join(textwrap.wrap(str(x), width=10)))

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
    st.subheader(f"📈 시장 차트 ({selected_period_label} · {effective_interval_label})")

    tick_format = "%m-%d" if selected_period in ['1mo', '3mo', '6mo'] else "%y-%m"

    @st.cache_data(ttl=3600)
    def get_market_data(ticker_symbol, period_str, interval_str):
        import yfinance as yf
        hist = yf.Ticker(ticker_symbol).history(period=period_str, interval=interval_str)
        if hist.empty:
            return hist
        return hist[['Open', 'High', 'Low', 'Close']]

    def make_candlestick_fig(ohlc_df, tick_fmt, height=220):
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
            height=height,
        )
        return fig

    chart_config = {'displayModeBar': False}

    def render_chart(symbol, label="", height=220):
        if label:
            st.markdown(f"**{label}**")
        try:
            data = get_market_data(symbol, selected_period, effective_interval)
            if not data.empty:
                st.plotly_chart(make_candlestick_fig(data, tick_format, height=height), use_container_width=True, config=chart_config)
            else:
                st.warning("데이터를 가져올 수 없습니다.")
        except Exception as e:
            st.error(f"오류: {e}")

    @st.cache_data(ttl=86400)
    def get_yield_curve_data(period_str, interval_str):
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
            df_tmp = pd.read_csv(io.StringIO(resp.text), index_col=0, parse_dates=True)
            series = pd.to_numeric(df_tmp.iloc[:, 0], errors='coerce')
            series.name = series_id
            return series[series.index >= pd.Timestamp(start)]

        dgs2   = fetch_fred('DGS2')
        dgs10  = fetch_fred('DGS10')
        spread = fetch_fred('T10Y2Y')
        infl   = fetch_fred('T10YIE')
        combined = pd.DataFrame({'미국 2년물': dgs2, '미국 10년물': dgs10, '스프레드': spread, '기대 인플레이션': infl})
        if interval_str == '1wk':
            combined = combined.resample('W').last()
        elif interval_str == '1mo':
            combined = combined.resample('ME').last()
        return combined.dropna(how='all')

    with st.spinner('시장 데이터를 불러오는 중...'):
        # 1. 주식 지수 (최상단)
        col1, col2 = st.columns(2)
        with col1:
            render_chart("^GSPC", label="🇺🇸 S&P 500")
        with col2:
            render_chart("^NDX", label="🇺🇸 NASDAQ 100")

        col3, col4, col5 = st.columns(3)
        with col3:
            render_chart("^KS11", label="🇰🇷 KOSPI")
        with col4:
            render_chart("^KQ11", label="🇰🇷 KOSDAQ")
        with col5:
            render_chart("^SOX", label="💾 SOX 반도체")

        # 2. 미국 국채 수익률 & 장단기 스프레드
        try:
            yc_df = get_yield_curve_data(selected_period, effective_interval)
            if not yc_df.empty:
                col_yield, col_spread, col_infl = st.columns([2, 2, 2])
                with col_yield:
                    st.markdown("**📈 미국 국채 수익률 (2Y · 10Y)**")
                    fig_yield = go.Figure()
                    for col_name, color in [('미국 2년물', '#FF8844'), ('미국 10년물', '#4488FF')]:
                        if col_name in yc_df.columns:
                            fig_yield.add_trace(go.Scatter(
                                x=yc_df.index, y=yc_df[col_name],
                                mode='lines', name=col_name,
                                line=dict(color=color, width=2),
                            ))
                    fig_yield.update_layout(
                        xaxis=dict(tickformat=tick_format, nticks=6, tickangle=0),
                        xaxis_title="", yaxis_title="%",
                        margin=dict(t=25, l=10, r=10, b=10),
                        height=240,
                        legend=dict(orientation='h', yanchor='bottom', y=1.0, xanchor='left', x=0),
                    )
                    st.plotly_chart(fig_yield, use_container_width=True, config=chart_config)

                with col_spread:
                    st.markdown("**📉 장단기 스프레드 (10Y - 2Y)**")
                    spread_series = yc_df['스프레드'].dropna()
                    bar_colors = ['#00CC44' if v >= 0 else '#FF3333' for v in spread_series]
                    fig_spread = go.Figure()
                    fig_spread.add_trace(go.Bar(
                        x=spread_series.index, y=spread_series.values,
                        marker_color=bar_colors, name='스프레드',
                    ))
                    fig_spread.add_hline(y=0, line_color='white', line_width=1)
                    fig_spread.update_layout(
                        xaxis=dict(tickformat=tick_format, nticks=6, tickangle=0),
                        xaxis_title="", yaxis_title="%",
                        margin=dict(t=25, l=10, r=10, b=10),
                        height=240,
                        showlegend=False,
                    )
                    st.plotly_chart(fig_spread, use_container_width=True, config=chart_config)

                with col_infl:
                    st.markdown("**🌡️ 기대 인플레이션 (10Y BEI)**")
                    infl_series = yc_df['기대 인플레이션'].dropna()
                    fig_infl = go.Figure()
                    fig_infl.add_trace(go.Scatter(
                        x=infl_series.index, y=infl_series.values,
                        mode='lines', name='기대 인플레이션',
                        line=dict(color='#FFDD44', width=2),
                        fill='tozeroy',
                        fillcolor='rgba(255,221,68,0.08)',
                    ))
                    fig_infl.update_layout(
                        xaxis=dict(tickformat=tick_format, nticks=6, tickangle=0),
                        xaxis_title="", yaxis_title="%",
                        margin=dict(t=25, l=10, r=10, b=10),
                        height=240,
                        showlegend=False,
                    )
                    st.plotly_chart(fig_infl, use_container_width=True, config=chart_config)
            else:
                st.warning("국채 수익률 데이터를 가져올 수 없습니다.")
        except Exception as e:
            st.error(f"국채 수익률 데이터 오류: {e}")

        # 3. 환율 · 달러 인덱스 · VIX (작게)
        col_fx1, col_fx2, col_vix = st.columns([1, 1, 1])
        with col_fx1:
            render_chart("USDKRW=X", label="💱 USD/KRW", height=160)
        with col_fx2:
            render_chart("DX-Y.NYB", label="💵 달러 인덱스 (DXY)", height=160)
        with col_vix:
            render_chart("^VIX", label="😱 VIX", height=160)

        # 4. 상품 & 대안자산
        col5, col6, col7, col8 = st.columns(4)
        with col5:
            render_chart("GC=F", label="🥇 금 (Gold)")
        with col6:
            render_chart("CL=F", label="🛢️ WTI 원유")
        with col7:
            render_chart("HG=F", label="🔧 구리 (Copper)")
        with col8:
            render_chart("BTC-USD", label="₿ 비트코인")

        # 5. TANKER 신조선가 (KOBC)
        @st.cache_data(ttl=86400)
        def get_kobc_tanker_data(period_str):
            import requests
            from bs4 import BeautifulSoup
            from datetime import date, timedelta
            period_days = {
                '1mo': 30, '3mo': 90, '6mo': 180,
                '1y': 365, '5y': 365 * 5, '10y': 365 * 10,
            }
            end = date.today()
            start = end - timedelta(days=period_days.get(period_str, 365))
            url = "https://www.kobc.or.kr/ebz/shippinginfo/stn/gridList.do?mId=0401000000"
            hdrs = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                'Referer': 'https://www.kobc.or.kr/ebz/shippinginfo/main.do',
                'Content-Type': 'application/x-www-form-urlencoded',
            }
            payload = {'sDay': start.strftime('%Y-%m-%d'), 'eDay': end.strftime('%Y-%m-%d')}
            session = requests.Session()
            session.get('https://www.kobc.or.kr/ebz/shippinginfo/main.do', headers=hdrs, timeout=15)
            resp = session.post(url, data=payload, headers=hdrs, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            table = soup.find('table')
            if not table:
                return pd.DataFrame()
            headers_list = [th.get_text(strip=True) for th in table.find_all('th')]
            rows = [[td.get_text(strip=True) for td in tr.find_all('td')] for tr in table.find_all('tr') if tr.find_all('td')]
            if not rows or not headers_list:
                return pd.DataFrame()
            df_kobc = pd.DataFrame(rows, columns=headers_list[:len(rows[0])])
            df_kobc['Date'] = pd.to_datetime(df_kobc['Date'])
            for col in df_kobc.columns[1:]:
                df_kobc[col] = pd.to_numeric(df_kobc[col], errors='coerce')
            return df_kobc.sort_values('Date').reset_index(drop=True)

        try:
            tanker_df = get_kobc_tanker_data(selected_period)
            if not tanker_df.empty:
                st.markdown("**🚢 TANKER 신조선가 (KOBC, 단위: $M)**")
                fig_tanker = go.Figure()
                if 'VLCC(320K)' in tanker_df.columns:
                    fig_tanker.add_trace(go.Scatter(
                        x=tanker_df['Date'], y=tanker_df['VLCC(320K)'],
                        mode='lines', name='VLCC(320K)',
                        line=dict(color='#FF6644', width=2),
                        yaxis='y1',
                    ))
                if 'SUEZMAX(160K)' in tanker_df.columns:
                    fig_tanker.add_trace(go.Scatter(
                        x=tanker_df['Date'], y=tanker_df['SUEZMAX(160K)'],
                        mode='lines', name='SUEZMAX(160K)',
                        line=dict(color='#44CCFF', width=2),
                        yaxis='y2',
                    ))
                fig_tanker.update_layout(
                    xaxis=dict(tickformat=tick_format, nticks=8, tickangle=0),
                    xaxis_title="",
                    yaxis=dict(title=dict(text='VLCC ($M)', font=dict(color='#FF6644')), tickfont=dict(color='#FF6644')),
                    yaxis2=dict(title=dict(text='SUEZMAX ($M)', font=dict(color='#44CCFF')), tickfont=dict(color='#44CCFF'), overlaying='y', side='right'),
                    margin=dict(t=10, l=10, r=60, b=10),
                    height=260,
                    legend=dict(orientation='h', yanchor='bottom', y=1.0, xanchor='left', x=0),
                )
                st.plotly_chart(fig_tanker, use_container_width=True, config=chart_config)
            else:
                st.warning("TANKER 신조선가 데이터를 가져올 수 없습니다.")
        except Exception as e:
            st.error(f"TANKER 신조선가 오류: {e}")

except Exception as e:
    st.error(f"오류가 발생했습니다: {e}")