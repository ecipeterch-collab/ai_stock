import json
import time

import requests

from config.config import telegram_chat_id, telegram_token
from telegram.tel_send import send_message

GET_UPDATES_URL = f"https://api.telegram.org/bot{telegram_token}/getUpdates"
TARGET_CHAT_ID = int(telegram_chat_id)
POLL_TIMEOUT = 30


def _get_message(update: dict) -> dict | None:
    return update.get("message")


def _fetch_updates(offset: int | None) -> list[dict]:
    params: dict = {"timeout": POLL_TIMEOUT}
    if offset is not None:
        params["offset"] = offset

    response = requests.get(
        GET_UPDATES_URL,
        params=params,
        timeout=POLL_TIMEOUT + 10,
    )
    response.raise_for_status()

    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API 오류: {json.dumps(data, ensure_ascii=False)}")

    return data.get("result", [])


def _skip_backlog() -> int | None:
    """시작 시점 이전 메시지는 건너뛰고, 이후 들어오는 메시지만 처리한다."""
    updates = _fetch_updates(offset=None)
    if not updates:
        return None
    return updates[-1]["update_id"] + 1


def _handle_update(update: dict) -> None:
    message = _get_message(update)
    if not message:
        return

    if message.get("chat", {}).get("id") != TARGET_CHAT_ID:
        return

    sender = message.get("from") or {}
    if sender.get("is_bot"):
        return

    text = message.get("text")
    if not text:
        return

    reversed_text = text[::-1]
    print(f"수신: {text!r} -> 전송: {reversed_text!r}")
    send_message(reversed_text)


def main() -> None:
    offset = _skip_backlog()
    print(f"채팅 {TARGET_CHAT_ID} 메시지 수신 대기 중... (종료: Ctrl+C)")

    while True:
        try:
            updates = _fetch_updates(offset)
            for update in updates:
                _handle_update(update)
                offset = update["update_id"] + 1
        except KeyboardInterrupt:
            print("\n종료합니다.")
            break
        except requests.RequestException as exc:
            print(f"요청 오류, 5초 후 재시도: {exc}")
            time.sleep(5)


if __name__ == "__main__":
    main()
