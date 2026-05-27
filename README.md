# AI Stock — Kiwoom REST API + Telegram 자동매매

키움 Open API(REST)와 텔레그램 봇을 연동한 국내 주식 자동매매 프로젝트입니다.

## 요구 사항

- Python 3.10+
- [키움 Open API](https://openapi.kiwoom.com) 앱 키 (모의/실전)
- 텔레그램 봇 토큰 및 채팅 ID

## 설치

```bash
pip install -r requirements.txt
copy config\config.example.py config\config.py
copy config\local_secrets.example.py config\local_secrets.py
# local_secrets.py 에 API 키·텔레그램 정보 입력 (Git 제외)
```

## 실행

| 명령 | 설명 |
|------|------|
| `python main.py` | API 연결·토큰·순위 조회 테스트 |
| `python auto_trade.py` | 텔레그램 자동매매 봇 |
| `python send-test.py` | 텔레그램 발송 테스트 |
| `python chat-test.py` | 텔레그램 에코 봇 |

## 텔레그램 명령 (요약)

`/help`, `/status`, `/balance`, `/rank`, `/strategy`, `/news`, `/report`, `/buy`, `/sell`, `/auto on|off`, `/trend`, `/trendbuy`

자동매매 알림은 체결·매수·매도 등 **이벤트만** 전송됩니다. 주기 리포트는 `/report` 로 조회합니다.

## 프로젝트 구조

```
auto_trade.py      # 메인 진입점
kiwoom/            # REST API 클라이언트
trading/           # 전략, 봇, 뉴스, 트렌드 스캔
telegram/          # 메시지 발송
config/            # 설정 (config.py는 Git 제외)
data/              # 포지션 추적 JSON
```

## 보안

`config/local_secrets.py`, `.env*`, `*_appkey.txt`, `*_secretkey.txt` 는 Git에 포함되지 않습니다. GitHub에 올리기 전에 저장소가 **private** 인지 확인하세요.
