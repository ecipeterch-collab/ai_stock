"""모의 체결조회는 KRX, 키움 4007은 재시도."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from config.config import kiwoom_execution_stex_tp
from kiwoom.client import KiwoomAPIError, KiwoomClient


def _json_response(body: dict, status: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.headers = {}
    response.json.return_value = body
    response.raise_for_status.return_value = None
    return response


def test_paper_get_executions_forces_krx_even_if_config_is_unified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = KiwoomClient(paper=True)
    captured: dict[str, object] = {}

    def fake_post(endpoint, api_id, data, **kwargs):
        captured["data"] = data
        return {"cntr": [], "return_code": 0}, {"cont-yn": "N"}

    monkeypatch.setattr(client, "post", fake_post)

    client.get_executions()
    assert captured["data"]["stex_tp"] == "1"

    client.get_executions(stex_tp="0")
    assert captured["data"]["stex_tp"] == "1"


def test_real_get_executions_keeps_config_or_explicit_stex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = KiwoomClient(paper=False)
    captured: dict[str, object] = {}

    def fake_post(endpoint, api_id, data, **kwargs):
        captured["data"] = data
        return {"cntr": [], "return_code": 0}, {"cont-yn": "N"}

    monkeypatch.setattr(client, "post", fake_post)

    client.get_executions()
    assert captured["data"]["stex_tp"] == kiwoom_execution_stex_tp

    client.get_executions(stex_tp="2")
    assert captured["data"]["stex_tp"] == "2"


def test_post_retries_4007_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    client = KiwoomClient(paper=True)
    monkeypatch.setattr(client, "_ensure_token", lambda: "tok")
    monkeypatch.setattr(client, "_throttle", lambda: None)
    monkeypatch.setattr("kiwoom.client.time.sleep", lambda *_a, **_k: None)

    bodies = [
        {"return_code": 4007, "return_msg": "서비스를 처리하는 중에 오류가 발생했습니다.[4007]"},
        {"return_code": 4007, "return_msg": "서비스를 처리하는 중에 오류가 발생했습니다.[4007]"},
        {"return_code": 0, "return_msg": "ok", "cntr": [{"ord_no": "1"}]},
    ]
    monkeypatch.setattr(
        "kiwoom.client.requests.post",
        lambda *_a, **_k: _json_response(bodies.pop(0)),
    )

    body, _headers = client.post("/api/dostk/acnt", "ka10076", {})
    assert body["return_code"] == 0
    assert body["cntr"][0]["ord_no"] == "1"
    assert bodies == []


def test_post_raises_after_4007_retries_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = KiwoomClient(paper=True)
    monkeypatch.setattr(client, "_ensure_token", lambda: "tok")
    monkeypatch.setattr(client, "_throttle", lambda: None)
    monkeypatch.setattr("kiwoom.client.time.sleep", lambda *_a, **_k: None)

    monkeypatch.setattr(
        "kiwoom.client.requests.post",
        lambda *_a, **_k: _json_response(
            {
                "return_code": 4007,
                "return_msg": "서비스를 처리하는 중에 오류가 발생했습니다.[4007]",
            }
        ),
    )

    with pytest.raises(KiwoomAPIError, match=r"ka10076.*4007"):
        client.post("/api/dostk/acnt", "ka10076", {})


def test_post_does_not_retry_non_transient_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = KiwoomClient(paper=True)
    monkeypatch.setattr(client, "_ensure_token", lambda: "tok")
    monkeypatch.setattr(client, "_throttle", lambda: None)
    calls = {"n": 0}

    def fake_post(*_a, **_k):
        calls["n"] += 1
        return _json_response(
            {"return_code": 1, "return_msg": "조회 실패"}
        )

    monkeypatch.setattr("kiwoom.client.requests.post", fake_post)

    with pytest.raises(KiwoomAPIError, match="조회 실패"):
        client.post("/api/dostk/acnt", "ka10076", {})
    assert calls["n"] == 1


def test_post_reissues_token_on_8005_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime, timedelta

    client = KiwoomClient(paper=True)
    client._token = "old"
    client._token_expires_at = datetime.now() + timedelta(hours=12)
    monkeypatch.setattr(client, "_throttle", lambda: None)

    def fake_issue() -> str:
        client._token = "new"
        client._token_expires_at = datetime.now() + timedelta(hours=12)
        return "new"

    monkeypatch.setattr(client, "_issue_token", fake_issue)
    auths: list[str] = []

    def fake_post(*_a, **kwargs):
        auth = kwargs["headers"]["authorization"]
        auths.append(auth)
        if auth == "Bearer old":
            return _json_response(
                {
                    "return_code": 3,
                    "return_msg": "인증에 실패했습니다[8005:Token이 유효하지 않습니다]",
                }
            )
        return _json_response({"return_code": 0, "return_msg": "ok"})

    monkeypatch.setattr("kiwoom.client.requests.post", fake_post)

    body, _headers = client.post("/api/dostk/acnt", "ka10076", {})
    assert body["return_code"] == 0
    assert auths == ["Bearer old", "Bearer new"]


def test_post_raises_if_token_still_invalid_after_reissue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime, timedelta

    client = KiwoomClient(paper=True)
    client._token = "old"
    client._token_expires_at = datetime.now() + timedelta(hours=12)
    monkeypatch.setattr(client, "_throttle", lambda: None)
    monkeypatch.setattr(client, "_issue_token", lambda: "new")
    calls = {"n": 0}

    def fake_post(*_a, **_k):
        calls["n"] += 1
        return _json_response(
            {
                "return_code": 3,
                "return_msg": "인증에 실패했습니다[8005:Token이 유효하지 않습니다]",
            }
        )

    monkeypatch.setattr("kiwoom.client.requests.post", fake_post)

    with pytest.raises(KiwoomAPIError, match="8005"):
        client.post("/api/dostk/acnt", "ka10076", {})
    assert calls["n"] == 2


def test_post_retries_4007_when_code_is_only_in_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = KiwoomClient(paper=True)
    monkeypatch.setattr(client, "_ensure_token", lambda: "tok")
    monkeypatch.setattr(client, "_throttle", lambda: None)
    monkeypatch.setattr("kiwoom.client.time.sleep", lambda *_a, **_k: None)

    bodies = [
        {"return_code": 1, "return_msg": "서비스를 처리하는 중에 오류가 발생했습니다.[4007]"},
        {"return_code": 0, "return_msg": "ok"},
    ]
    monkeypatch.setattr(
        "kiwoom.client.requests.post",
        lambda *_a, **_k: _json_response(bodies.pop(0)),
    )

    body, _headers = client.post("/api/dostk/acnt", "ka10076", {})
    assert body["return_code"] == 0
    assert bodies == []
