import json

import requests

from config.config import telegram_token

GET_UPDATES_URL = f"https://api.telegram.org/bot{telegram_token}/getUpdates"


def get_latest_chat_id() -> int | None:
    """봇이 수신한 최신 메시지에서 chat_id를 반환한다."""
    response = requests.get(GET_UPDATES_URL, timeout=10)
    response.raise_for_status()

    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API 오류: {json.dumps(data, ensure_ascii=False)}")

    updates = data.get("result", [])
    if not updates:
        print("수신된 메시지가 없습니다. 텔레그램 봇에게 먼저 메시지를 보내주세요.")
        return None

    latest_update = updates[-1]
    message = (
        latest_update.get("message")
        or latest_update.get("edited_message")
        or latest_update.get("channel_post")
    )
    if not message:
        print("최신 업데이트에서 메시지를 찾을 수 없습니다.")
        return None

    return message["chat"]["id"]


def main() -> None:
    chat_id = get_latest_chat_id()
    if chat_id is not None:
        print(f"chat_id: {chat_id}")


if __name__ == "__main__":
    main()
