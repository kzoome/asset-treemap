import gspread
from google.oauth2.service_account import Credentials

# 1. 설정: 서비스 계정 키 파일과 대상 시트 URL
# 다운로드 받은 JSON 키 파일명을 여기에 입력하세요.
SERVICE_ACCOUNT_FILE = 'service_account.json'
# 접근하려는 다른 계정의 구글 시트 URL을 여기에 입력하세요.
SHEET_URL = 'YOUR_SHEET_URL_HERE'

# 2. 인증 범위 설정
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def check_sheet_access():
    try:
        print("🔄 인증 정보 로드 중...")
        credentials = Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=scopes
        )
        gc = gspread.authorize(credentials)

        print("🔄 구글 시트 연결 시도 중...")
        # URL로 시트 열기
        doc = gc.open_by_url(SHEET_URL)
        
        # 첫 번째 워크시트 선택
        worksheet = doc.worksheet("종목별 현황")
        
        # 데이터 읽기 (헤더 포함 상위 5행)
        data = worksheet.get_all_values()
        
        print(f"\n✅ 성공! 문서 제목: {doc.title}")
        print(f"📊 데이터 미리보기 (총 {len(data)}행):")
        for row in data[:5]:
            print(row)
            
    except FileNotFoundError:
        print(f"\n❌ 오류: '{SERVICE_ACCOUNT_FILE}' 파일을 찾을 수 없습니다. 프로젝트 폴더에 JSON 키 파일을 넣어주세요.")
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        print("💡 팁: 타겟 구글 시트의 '공유' 설정에서 서비스 계정 이메일을 추가했는지 확인해주세요.")

if __name__ == "__main__":
    check_sheet_access()