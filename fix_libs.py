import sys
import subprocess
import streamlit as st

st.title("🛠️ 라이브러리 자동 설치 도구")

st.write(f"현재 Streamlit이 사용하는 파이썬 경로:\n`{sys.executable}`")
st.info("아래 버튼을 누르면 현재 환경에 필요한 라이브러리가 설치됩니다.")

if st.button("필수 라이브러리 설치하기 (클릭)"):
    with st.spinner("설치 중입니다... 잠시만 기다려주세요."):
        try:
            # 필요한 라이브러리 목록 (gspread, pandas, plotly 등)
            pkgs = ["gspread", "google-auth", "pandas", "plotly"]
            subprocess.check_call([sys.executable, "-m", "pip", "install"] + pkgs)
            st.success("✅ 설치 완료! 이제 이 탭을 닫고 'streamlit run app.py'를 실행하세요.")
        except Exception as e:
            st.error(f"설치 실패: {e}")