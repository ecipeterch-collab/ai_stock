from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from typing import Any

import requests

from config.config import (
    paper_app_key,
    paper_app_secret,
    paper_host_url,
    real_app_key,
    real_app_secret,
    real_host_url,
    use_paper,
    dmst_stex_tp,
    kiwoom_chart_exchange,
    kiwoom_execution_stex_tp,
    kiwoom_paper_min_request_interval_sec,
    kiwoom_rank_stex_tp,
    kiwoom_real_min_request_interval_sec,
)

TOKEN_ENDPOINT = "/oauth2/token"
TOKEN_REVOKE_ENDPOINT = "/oauth2/revoke"
ACNT_ENDPOINT = "/api/dostk/acnt"
RANK_ENDPOINT = "/api/dostk/rkinfo"
CHART_ENDPOINT = "/api/dostk/chart"
ORDER_ENDPOINT = "/api/dostk/ordr"


class KiwoomAPIError(RuntimeError):
    pass


# 키움 서버 일시 처리 실패. HTTP 429와 달리 return_code로 오며 재시도하면 곧잘 성공한다.
_TRANSIENT_RETURN_CODES = {4007, "4007"}
_TRANSIENT_RETRY_COUNT = 2


def _is_transient_kiwoom_error(body: dict) -> bool:
    if body.get("return_code") in _TRANSIENT_RETURN_CODES:
        return True
    msg = str(body.get("return_msg") or "")
    return "[4007]" in msg


def _is_invalid_token_error(body: dict) -> bool:
    """다른 프로세스가 토큰을 재발급하면 만료 전에도 8005/8001이 난다."""
    msg = str(body.get("return_msg") or "")
    if "Token이 유효하지 않습니다" in msg:
        return True
    return "[8005" in msg or "8005:" in msg or "[8001]" in msg


_clients: dict[bool, "KiwoomClient"] = {}
_clients_lock = threading.Lock()


def get_shared_client(paper: bool | None = None) -> "KiwoomClient":
    """프로세스당 모의/실전 각 1개 클라이언트 (토큰·호출 제한 공유)."""
    key = use_paper if paper is None else paper
    with _clients_lock:
        client = _clients.get(key)
        if client is None:
            client = KiwoomClient(paper=key)
            _clients[key] = client
        return client


class KiwoomClient:
    """키움 REST API 클라이언트 (모의/실전, KRX·NXT·SOR·통합 시세)."""

    def __init__(self, paper: bool | None = None) -> None:
        self.paper = use_paper if paper is None else paper
        if self.paper:
            self.host = paper_host_url
            self.app_key = paper_app_key
            self.app_secret = paper_app_secret
            self._min_request_interval_sec = float(kiwoom_paper_min_request_interval_sec)
        else:
            self.host = real_host_url
            self.app_key = real_app_key
            self.app_secret = real_app_secret
            self._min_request_interval_sec = float(kiwoom_real_min_request_interval_sec)

        self._token: str | None = None
        self._token_expires_at: datetime | None = None
        self._lock = threading.Lock()
        self._last_request_at: float = 0.0

    def close(self) -> None:
        """접근토큰 폐기(au10002) — 세션 종료 시 호출 권장."""
        self.revoke_token()

    def __enter__(self) -> KiwoomClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _issue_token(self) -> str:
        last_error: Exception | None = None
        for attempt in range(4):
            response = requests.post(
                self.host + TOKEN_ENDPOINT,
                headers={"Content-Type": "application/json;charset=UTF-8"},
                json={
                    "grant_type": "client_credentials",
                    "appkey": self.app_key,
                    "secretkey": self.app_secret,
                },
                timeout=15,
            )
            if response.status_code == 429:
                last_error = requests.HTTPError(
                    f"토큰 발급 제한(429), {2 ** attempt}초 후 재시도",
                    response=response,
                )
                time.sleep(2**attempt)
                continue

            response.raise_for_status()
            body = response.json()
            if body.get("return_code") != 0:
                raise KiwoomAPIError(f"토큰 발급 실패: {body.get('return_msg')}")

            self._token = body["token"]
            expires_dt = body.get("expires_dt")
            if expires_dt and len(expires_dt) >= 14:
                self._token_expires_at = datetime.strptime(expires_dt[:14], "%Y%m%d%H%M%S")
            else:
                self._token_expires_at = datetime.now() + timedelta(hours=12)
            return self._token

        if last_error:
            raise last_error
        raise KiwoomAPIError("토큰 발급에 실패했습니다.")

    def revoke_token(self) -> None:
        """접근토큰 폐기(au10002). 토큰 발급 한도 절약."""
        token = self._token
        if not token:
            return
        with self._lock:
            self._throttle()
            try:
                response = requests.post(
                    self.host + TOKEN_REVOKE_ENDPOINT,
                    headers={
                        "Content-Type": "application/json;charset=UTF-8",
                        "api-id": "au10002",
                    },
                    json={
                        "appkey": self.app_key,
                        "secretkey": self.app_secret,
                        "token": token,
                    },
                    timeout=15,
                )
                if response.status_code == 429:
                    return
                response.raise_for_status()
            except requests.RequestException:
                return
            finally:
                self._token = None
                self._token_expires_at = None

    def _ensure_token(self) -> str:
        if self._token and self._token_expires_at and datetime.now() < self._token_expires_at:
            return self._token
        return self._issue_token()

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._min_request_interval_sec:
            time.sleep(self._min_request_interval_sec - elapsed)

    def post(
        self,
        endpoint: str,
        api_id: str,
        data: dict | None = None,
        *,
        cont_yn: str = "N",
        next_key: str = "",
    ) -> tuple[dict, dict]:
        with self._lock:
            last_exc: Exception | None = None
            token: str | None = None
            transient_attempts = 0
            token_reissued = False
            while True:
                self._throttle()
                if token is None:
                    token = self._ensure_token()
                for attempt in range(5):
                    response = requests.post(
                        self.host + endpoint,
                        headers={
                            "Content-Type": "application/json;charset=UTF-8",
                            "authorization": f"Bearer {token}",
                            "cont-yn": cont_yn,
                            "next-key": next_key,
                            "api-id": api_id,
                        },
                        json=data or {},
                        timeout=30,
                    )
                    if response.status_code == 429:
                        wait = min(2 ** attempt, 8)
                        last_exc = requests.HTTPError(
                            f"{api_id} 호출 제한(429), {wait}초 후 재시도",
                            response=response,
                        )
                        time.sleep(wait)
                        if attempt >= 2:
                            token = self._issue_token()
                        continue
                    break
                else:
                    if last_exc:
                        raise last_exc
                    raise KiwoomAPIError(f"{api_id} 호출 제한(429)")
                self._last_request_at = time.monotonic()
                response.raise_for_status()
                body = response.json()
                headers = {
                    "cont-yn": response.headers.get("cont-yn", "N"),
                    "next-key": response.headers.get("next-key", ""),
                    "api-id": response.headers.get("api-id", api_id),
                }
                if body.get("return_code", 0) != 0:
                    if (
                        _is_transient_kiwoom_error(body)
                        and transient_attempts < _TRANSIENT_RETRY_COUNT
                    ):
                        transient_attempts += 1
                        time.sleep(min(2 ** (transient_attempts - 1), 4))
                        continue
                    if _is_invalid_token_error(body) and not token_reissued:
                        token_reissued = True
                        self._token = None
                        self._token_expires_at = None
                        token = self._issue_token()
                        continue
                    raise KiwoomAPIError(
                        f"{api_id} 오류: {body.get('return_msg')} "
                        f"({json.dumps(body, ensure_ascii=False)})"
                    )
                return body, headers

    def post_all(self, endpoint: str, api_id: str, data: dict | None = None) -> dict:
        merged: dict[str, Any] = {}
        cont_yn = "N"
        next_key = ""

        while True:
            body, headers = self.post(
                endpoint,
                api_id,
                data,
                cont_yn=cont_yn,
                next_key=next_key,
            )
            for key, value in body.items():
                if isinstance(value, list) and isinstance(merged.get(key), list):
                    merged[key].extend(value)
                else:
                    merged[key] = value
            merged["return_code"] = body.get("return_code", 0)
            merged["return_msg"] = body.get("return_msg", "")

            if headers.get("cont-yn") != "Y":
                break
            cont_yn = "Y"
            next_key = headers.get("next-key", "")

        return merged

    @staticmethod
    def normalize_stock_code(stk_cd: str) -> str:
        """API 응답 종목코드 → 주문/조회용 6자리 코드 (예: A005930 → 005930, 039490_AL → 039490)."""
        code = stk_cd.split("_")[0].strip().upper()
        if len(code) == 7 and code[0] == "A":
            body = code[1:]
            if len(body) == 6 and body.isalnum():
                return body
        base = code
        for suffix in ("_AL", "_NX"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        return base

    @staticmethod
    def format_stock_code_for_exchange(
        stk_cd: str,
        exchange: str | None = None,
    ) -> str:
        """차트·시세 조회용 거래소별 종목코드 (KRX 6자리 / NXT _NX / 통합 _AL)."""
        code = KiwoomClient.normalize_stock_code(stk_cd)
        ex = (exchange or kiwoom_chart_exchange or "KRX").upper()
        if ex in ("SOR", "AL", "통합", "3", "ALL"):
            return f"{code}_AL"
        if ex in ("NXT", "2"):
            return f"{code}_NX"
        return code

    @staticmethod
    def parse_price(value: str) -> int:
        cleaned = value.strip().lstrip("+-")
        return int(cleaned) if cleaned else 0

    @staticmethod
    def parse_percent(value: str) -> float:
        cleaned = value.strip().replace("%", "").lstrip("+")
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    @staticmethod
    def parse_qty(value: str) -> int:
        cleaned = value.strip().replace(",", "")
        if not cleaned:
            return 0
        try:
            return int(cleaned)
        except ValueError:
            return 0

    @staticmethod
    def format_amount(value: str) -> str:
        cleaned = value.strip().lstrip("0") or "0"
        try:
            return f"{int(cleaned):,}"
        except ValueError:
            return value

    def get_trade_value_rank(
        self,
        *,
        market: str = "001",
        top_n: int = 10,
    ) -> list[dict]:
        """거래대금 상위 종목 조회 (ka10032)."""
        params = {
            "mrkt_tp": market,
            "mang_stk_incls": "1",
            "stex_tp": kiwoom_rank_stex_tp,
        }
        body, headers = self.post(RANK_ENDPOINT, "ka10032", params)
        items = list(body.get("trde_prica_upper", []))

        while len(items) < top_n and headers.get("cont-yn") == "Y":
            body, headers = self.post(
                RANK_ENDPOINT,
                "ka10032",
                params,
                cont_yn="Y",
                next_key=headers.get("next-key", ""),
            )
            items.extend(body.get("trde_prica_upper", []))

        return items[:top_n]

    def get_deposit(self) -> dict:
        """예수금 상세 현황 (kt00001)."""
        body, _ = self.post(ACNT_ENDPOINT, "kt00001", {"qry_tp": "3"})
        return body

    def _resolve_execution_stex(self, stex_tp: str | None = None) -> str:
        """체결조회 거래소. 모의는 KRX(1)만, 실전은 config 또는 명시값."""
        if self.paper:
            return "1"
        if stex_tp:
            return stex_tp
        return kiwoom_execution_stex_tp

    def get_executions(
        self,
        *,
        stk_cd: str = "",
        ord_no: str = "",
        qry_tp: str = "0",
        sell_tp: str = "0",
        stex_tp: str | None = None,
    ) -> list[dict]:
        """체결 내역 조회 (ka10076). stex_tp: 0=통합, 1=KRX, 2=NXT. 모의는 KRX 고정."""
        resolved_stex = self._resolve_execution_stex(stex_tp)
        params = {
            "stk_cd": self.normalize_stock_code(stk_cd) if stk_cd else "",
            "qry_tp": qry_tp,
            "sell_tp": sell_tp,
            "ord_no": ord_no,
            "stex_tp": resolved_stex,
        }
        body, headers = self.post(ACNT_ENDPOINT, "ka10076", params)
        items = list(body.get("cntr", []))

        while headers.get("cont-yn") == "Y":
            body, headers = self.post(
                ACNT_ENDPOINT,
                "ka10076",
                params,
                cont_yn="Y",
                next_key=headers.get("next-key", ""),
            )
            items.extend(body.get("cntr", []))

        return items

    def get_daily_chart(
        self,
        stk_cd: str,
        *,
        base_dt: str | None = None,
        upd_stkpc_tp: str = "1",
        exchange: str | None = None,
    ) -> list[dict]:
        """일봉 차트 (ka10081). 첫 페이지만 (약 600봉)."""
        code = self.format_stock_code_for_exchange(stk_cd, exchange)
        dt = base_dt or datetime.now().strftime("%Y%m%d")
        body, _ = self.post(
            CHART_ENDPOINT,
            "ka10081",
            {"stk_cd": code, "base_dt": dt, "upd_stkpc_tp": upd_stkpc_tp},
        )
        return list(body.get("stk_dt_pole_chart_qry", []))

    def get_minute_chart(
        self,
        stk_cd: str,
        *,
        tic_scope: str = "5",
        base_dt: str | None = None,
        upd_stkpc_tp: str = "1",
        exchange: str | None = None,
    ) -> list[dict]:
        """분봉 차트 (ka10080). 첫 페이지만 (약 900봉). tic_scope: 1/3/5/10/15/30/45/60."""
        code = self.format_stock_code_for_exchange(stk_cd, exchange)
        payload: dict[str, str] = {
            "stk_cd": code,
            "tic_scope": tic_scope,
            "upd_stkpc_tp": upd_stkpc_tp,
        }
        if base_dt:
            payload["base_dt"] = base_dt
        body, _ = self.post(
            CHART_ENDPOINT,
            "ka10080",
            payload,
        )
        return list(body.get("stk_min_pole_chart_qry", []))

    def get_holdings(
        self,
        *,
        dmst_stex: str | None = None,
    ) -> list[dict]:
        """계좌 평가 잔고 (kt00018). dmst_stex: KRX | NXT (모의는 KRX만)."""
        resolved = dmst_stex or (dmst_stex_tp if not self.paper else "KRX")
        params = {"qry_tp": "1", "dmst_stex_tp": resolved}
        body, headers = self.post(ACNT_ENDPOINT, "kt00018", params)
        items = list(body.get("acnt_evlt_remn_indv_tot", []))

        while headers.get("cont-yn") == "Y":
            body, headers = self.post(
                ACNT_ENDPOINT,
                "kt00018",
                params,
                cont_yn="Y",
                next_key=headers.get("next-key", ""),
            )
            items.extend(body.get("acnt_evlt_remn_indv_tot", []))

        return items

    def _resolve_dmst_stex(self, exchange: str | None = None) -> str:
        """주문 거래소. 모의투자는 KRX만, 실전은 config dmst_stex_tp (KRX|NXT|SOR)."""
        if exchange:
            return exchange
        if self.paper:
            return "KRX"
        return dmst_stex_tp

    def buy_market(
        self,
        stk_cd: str,
        qty: int,
        dmst_stex_tp: str | None = None,
    ) -> dict:
        """시장가 매수 (kt10000). dmst_stex_tp: KRX | NXT | SOR."""
        body, _ = self.post(
            ORDER_ENDPOINT,
            "kt10000",
            {
                "dmst_stex_tp": self._resolve_dmst_stex(dmst_stex_tp),
                "stk_cd": self.normalize_stock_code(stk_cd),
                "ord_qty": str(qty),
                "ord_uv": "",
                "trde_tp": "3",
                "cond_uv": "",
            },
        )
        return body

    def sell_market(
        self,
        stk_cd: str,
        qty: int,
        dmst_stex_tp: str | None = None,
    ) -> dict:
        """시장가 매도 (kt10001)."""
        body, _ = self.post(
            ORDER_ENDPOINT,
            "kt10001",
            {
                "dmst_stex_tp": self._resolve_dmst_stex(dmst_stex_tp),
                "stk_cd": self.normalize_stock_code(stk_cd),
                "ord_qty": str(qty),
                "ord_uv": "",
                "trde_tp": "3",
                "cond_uv": "",
            },
        )
        return body

    def buy_limit(
        self,
        stk_cd: str,
        qty: int,
        price: int,
        dmst_stex_tp: str | None = None,
    ) -> dict:
        """지정가 매수 (kt10000)."""
        body, _ = self.post(
            ORDER_ENDPOINT,
            "kt10000",
            {
                "dmst_stex_tp": self._resolve_dmst_stex(dmst_stex_tp),
                "stk_cd": self.normalize_stock_code(stk_cd),
                "ord_qty": str(qty),
                "ord_uv": str(price),
                "trde_tp": "0",
                "cond_uv": "",
            },
        )
        return body

    def sell_limit(
        self,
        stk_cd: str,
        qty: int,
        price: int,
        dmst_stex_tp: str | None = None,
    ) -> dict:
        """지정가 매도 (kt10001)."""
        body, _ = self.post(
            ORDER_ENDPOINT,
            "kt10001",
            {
                "dmst_stex_tp": self._resolve_dmst_stex(dmst_stex_tp),
                "stk_cd": self.normalize_stock_code(stk_cd),
                "ord_qty": str(qty),
                "ord_uv": str(price),
                "trde_tp": "0",
                "cond_uv": "",
            },
        )
        return body
