"""매도 문의는 사용자가 지정한 종목만. 나머지는 자동 매도."""

from __future__ import annotations

import json

import pytest

from trading.bot import TelegramTradingBot


def test_sell_ask_list_round_trip(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import trading.mode_settings as ms

    path = tmp_path / "runtime_settings.json"
    path.write_text(
        json.dumps({"strategy_mode": "swing", "auto_trading_enabled": True}),
        encoding="utf-8",
    )
    monkeypatch.setattr(ms, "SETTINGS_FILE", path)

    assert ms.get_sell_ask_codes() == []
    assert ms.is_sell_ask_code("005930") is False

    added = ms.add_sell_ask_code("A005930")
    assert added == ["005930"]
    assert ms.is_sell_ask_code("005930") is True
    assert ms.add_sell_ask_code("005930") == ["005930"]

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["strategy_mode"] == "swing"
    assert saved["auto_trading_enabled"] is True
    assert saved["sell_ask_codes"] == ["005930"]

    left = ms.remove_sell_ask_code("005930")
    assert left == []
    assert ms.is_sell_ask_code("005930") is False


def test_sell_ask_rejects_bad_code(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import trading.mode_settings as ms

    monkeypatch.setattr(ms, "SETTINGS_FILE", tmp_path / "runtime_settings.json")
    with pytest.raises(ValueError):
        ms.add_sell_ask_code("삼성")


def test_sellask_command_adds_lists_and_removes(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import trading.mode_settings as ms

    monkeypatch.setattr(ms, "SETTINGS_FILE", tmp_path / "runtime_settings.json")
    bot = TelegramTradingBot.__new__(TelegramTradingBot)

    empty = bot._cmd_sellask([])
    assert "없음" in empty

    added = bot._cmd_sellask(["105560"])
    assert "105560" in added

    listed = bot._cmd_sellask([])
    assert "105560" in listed

    removed = bot._cmd_sellask(["off", "105560"])
    assert "제외" in removed
    assert ms.get_sell_ask_codes() == []


def test_sellask_lists_holding_names(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import trading.mode_settings as ms

    monkeypatch.setattr(ms, "SETTINGS_FILE", tmp_path / "runtime_settings.json")
    bot = TelegramTradingBot.__new__(TelegramTradingBot)

    class _Holding:
        def __init__(self, code: str, name: str) -> None:
            self.code = code
            self.name = name

    class _Strategy:
        def _parse_holdings(self):
            return [_Holding("005930", "삼성전자")]

        def holding_code_menu(self) -> str:
            return "보유 종목코드\n- 삼성전자 005930"

    bot.strategy = _Strategy()
    ms.add_sell_ask_code("005930")
    listed = bot._cmd_sellask([])
    assert "삼성전자 005930" in listed
    assert "보유 종목코드" in bot._cmd_buy([])
    assert "005930" in bot._cmd_sell([])
