"""키움 API 연결 테스트 (토큰 + 거래대금 상위)."""

import json

from kiwoom.client import KiwoomClient


def main() -> None:
    client = KiwoomClient()
    items = client.get_trade_value_rank(top_n=5)

    print("=== 거래대금 상위 5 ===")
    for item in items:
        code = client.normalize_stock_code(item["stk_cd"])
        print(
            f"{item['now_rank']}. {item['stk_nm']}({code}) "
            f"현재가 {item['cur_prc']} 거래대금 {item['trde_prica']}"
        )

    deposit = client.get_deposit()
    print()
    print("=== 예수금 ===")
    print(json.dumps(
        {
            "entr": client.format_amount(deposit.get("entr", "0")),
            "ord_alow_amt": client.format_amount(deposit.get("ord_alow_amt", "0")),
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
