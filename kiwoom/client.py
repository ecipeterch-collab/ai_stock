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
)

TOKEN_ENDPOINT = "/oauth2/token"
ACNT_ENDPOINT = "/api/dostk/acnt"
RANK_ENDPOINT = "/api/dostk/rkinfo"
ORDER_ENDPOINT = "/api/dostk/ordr"


class KiwoomAPIError(RuntimeError):
    pass


class KiwoomClient:
    """키움 REST API 클라이언트 (모의/실전 전환 지원)."""

    def __init__(self, paper: bool | None = None) -> None:
        self.paper = use_paper if paper is None else paper
        if self.paper:
            self.host = paper_host_url
            self.app_key = paper_app_key
            self.app_secret = paper_app_secret
        else:
            self.host = real_host_url
            self.app_key = real_app_key
            self.app_secret = real_app_secret

        self._token: str | None = None
        self._token_expires_at: datetime | None = None
        self._lock = threading.Lock()

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

    def _ensure_token(self) -> str:
        if self._token and self._token_expires_at and datetime.now() < self._token_expires_at:
            return self._token
        return self._issue_token()

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
            token = self._ensure_token()
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
                time.sleep(1)
                token = self._issue_token()
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
            response.raise_for_status()
            body = response.json()
            headers = {
                "cont-yn": response.headers.get("cont-yn", "N"),
                "next-key": response.headers.get("next-key", ""),
                "api-id": response.headers.get("api-id", api_id),
            }
            if body.get("return_code", 0) != 0:
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
        """API 응답 종목코드 → 주문/조회용 6자리 코드 (예: A005930 → 005930, A0193W0 → 0193W0)."""
        code = stk_cd.split("_")[0].strip().upper()
        if len(code) == 7 and code[0] == "A":
            body = code[1:]
            if len(body) == 6 and body.isalnum():
                return body
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
        cleaned = value.strip().lstrip("0") or "0"
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
            "stex_tp": "3",
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

    def get_executions(
        self,
        *,
        stk_cd: str = "",
        ord_no: str = "",
        qry_tp: str = "0",
        sell_tp: str = "0",
        stex_tp: str = "1",
    ) -> list[dict]:
        """체결 내역 조회 (ka10076)."""
        params = {
            "stk_cd": self.normalize_stock_code(stk_cd) if stk_cd else "",
            "qry_tp": qry_tp,
            "sell_tp": sell_tp,
            "ord_no": ord_no,
            "stex_tp": stex_tp,
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

    def get_holdings(self) -> list[dict]:
        """계좌 평가 잔고 (kt00018)."""
        params = {"qry_tp": "1", "dmst_stex_tp": "KRX"}
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

    def buy_market(self, stk_cd: str, qty: int, dmst_stex_tp: str = "KRX") -> dict:
        """시장가 매수 (kt10000)."""
        body, _ = self.post(
            ORDER_ENDPOINT,
            "kt10000",
            {
                "dmst_stex_tp": dmst_stex_tp,
                "stk_cd": self.normalize_stock_code(stk_cd),
                "ord_qty": str(qty),
                "ord_uv": "",
                "trde_tp": "3",
                "cond_uv": "",
            },
        )
        return body

    def sell_market(self, stk_cd: str, qty: int, dmst_stex_tp: str = "KRX") -> dict:
        """시장가 매도 (kt10001)."""
        body, _ = self.post(
            ORDER_ENDPOINT,
            "kt10001",
            {
                "dmst_stex_tp": dmst_stex_tp,
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
        dmst_stex_tp: str = "KRX",
    ) -> dict:
        """지정가 매수 (kt10000)."""
        body, _ = self.post(
            ORDER_ENDPOINT,
            "kt10000",
            {
                "dmst_stex_tp": dmst_stex_tp,
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
        dmst_stex_tp: str = "KRX",
    ) -> dict:
        """지정가 매도 (kt10001)."""
        body, _ = self.post(
            ORDER_ENDPOINT,
            "kt10001",
            {
                "dmst_stex_tp": dmst_stex_tp,
                "stk_cd": self.normalize_stock_code(stk_cd),
                "ord_qty": str(qty),
                "ord_uv": str(price),
                "trde_tp": "0",
                "cond_uv": "",
            },
        )
        return body
