"""대시보드 HTML이 JS/CSS를 캐시 버스팅한다."""

import logging

from web.app import DropUnauthDashboardAccessFilter, render_index_html


def test_index_html_cache_busts_static_assets() -> None:
    html = render_index_html()
    assert 'src="/static/app.js?v=' in html
    assert 'href="/static/styles.css?v=' in html


def _access_record(msg: str) -> logging.LogRecord:
    return logging.LogRecord("uvicorn.access", logging.INFO, "", 0, msg, (), None)


def test_access_filter_hides_dashboard_401() -> None:
    filt = DropUnauthDashboardAccessFilter()
    msg = '127.0.0.1:59895 - "GET /api/dashboard HTTP/1.1" 401 Unauthorized'
    assert filt.filter(_access_record(msg)) is False


def test_access_filter_keeps_dashboard_200_and_login_401() -> None:
    filt = DropUnauthDashboardAccessFilter()
    ok = '127.0.0.1:61927 - "GET /api/dashboard HTTP/1.1" 200 OK'
    login = '127.0.0.1:61927 - "POST /api/auth/login HTTP/1.1" 401 Unauthorized'
    assert filt.filter(_access_record(ok)) is True
    assert filt.filter(_access_record(login)) is True
