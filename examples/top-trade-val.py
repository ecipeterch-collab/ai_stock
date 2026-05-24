import requests
import json

# 거래대금상위요청
def fn_ka10032(token, data, cont_yn='N', next_key=''):
	# 1. 요청할 API URL
	#host = 'https://mockapi.kiwoom.com' # 모의투자
	host = 'https://api.kiwoom.com' # 실전투자
	endpoint = '/api/dostk/rkinfo'
	url =  host + endpoint

	# 2. header 데이터
	headers = {
		'Content-Type': 'application/json;charset=UTF-8', # 컨텐츠타입
		'authorization': f'Bearer {token}', # 접근토큰
		'cont-yn': cont_yn, # 연속조회여부
		'next-key': next_key, # 연속조회키
		'api-id': 'ka10032', # TR명
	}

	# 3. http POST 요청
	response = requests.post(url, headers=headers, json=data)

	# 4. 응답 상태 코드와 데이터 출력
	print('Code:', response.status_code)
	print('Header:', json.dumps({key: response.headers.get(key) for key in ['next-key', 'cont-yn', 'api-id']}, indent=4, ensure_ascii=False))
	print('Body:', json.dumps(response.json(), indent=4, ensure_ascii=False))  # JSON 응답을 파싱하여 출력

# 실행 구간
if __name__ == '__main__':
	# 1. 토큰 설정
	MY_ACCESS_TOKEN = '사용자 AccessToken' # 접근토큰

	# 2. 요청 데이터
	params = {
		'mrkt_tp': '001', # 시장구분 000:전체, 001:코스피, 101:코스닥
		'mang_stk_incls': '1', # 관리종목포함 0:관리종목 미포함, 1:관리종목 포함
		'stex_tp': '3', # 거래소구분 1:KRX, 2:NXT 3.통합
	}

	# 3. API 실행
	fn_ka10032(token=MY_ACCESS_TOKEN, data=params)

	# next-key, cont-yn 값이 있을 경우
	# fn_ka10032(token=MY_ACCESS_TOKEN, data=params, cont_yn='Y', next_key='nextkey..')