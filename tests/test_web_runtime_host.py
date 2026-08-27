from web.app import dashboard, health, runtime_host


def test_runtime_host_uses_gethostname(monkeypatch):
    monkeypatch.setattr("web.app.socket.gethostname", lambda: "jhunnet-stock")
    assert runtime_host() == "jhunnet-stock"


def test_health_includes_ok_and_host(monkeypatch):
    monkeypatch.setattr("web.app.socket.gethostname", lambda: "jhunnet-stock")
    body = health()
    assert body["ok"] is True
    assert body["host"] == "jhunnet-stock"


def test_dashboard_payload_sets_runtime_host(monkeypatch):
    monkeypatch.setattr("web.app.socket.gethostname", lambda: "jhunnet-stock")
    monkeypatch.setattr(
        "web.app.build_dashboard_snapshot",
        lambda: {"trade_mode_label": "모의투자"},
    )
    data = dashboard(_user="admin")
    assert data["runtime_host"] == "jhunnet-stock"
    assert data["trade_mode_label"] == "모의투자"
