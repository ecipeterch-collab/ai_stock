import json

import requests

from config.config import telegram_chat_id, telegram_token

SEND_MESSAGE_URL = f"https://api.telegram.org/bot{telegram_token}/sendMessage"


def send_message(
    message: str,
    *,
    parse_mode: str | None = None,
    disable_notification: bool = False,
    timeout: float = 10,
) -> dict:
    """config.config의 telegram_chat_id, telegram_token으로 메시지를 전송한다.

    Args:
        message: 전송할 텍스트.
        parse_mode: Telegram parse_mode (예: "HTML", "MarkdownV2").
        disable_notification: True이면 무음 알림으로 전송.
        timeout: HTTP 요청 타임아웃(초).

    Returns:
        Telegram API 응답 JSON.

    Raises:
        requests.HTTPError: HTTP 오류 시.
        RuntimeError: Telegram API가 ok=False를 반환할 때.
    """
    if not message:
        raise ValueError("message는 비어 있을 수 없습니다.")

    payload: dict = {
        "chat_id": telegram_chat_id,
        "text": message,
        "disable_notification": disable_notification,
    }
    if parse_mode is not None:
        payload["parse_mode"] = parse_mode

    response = requests.post(SEND_MESSAGE_URL, json=payload, timeout=timeout)
    response.raise_for_status()

    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API 오류: {json.dumps(data, ensure_ascii=False)}")

    return data


def main() -> None:
    result = send_message("텔레그램 전송 테스트")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
