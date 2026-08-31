"""시총 대형 유니버스 — 매도 규칙 분기용 고정 리스트."""

from __future__ import annotations

DEFAULT_MEGA_CAP_CODES = frozenset(
    {
        "005930",  # 삼성전자
        "005935",  # 삼성전자우
        "000660",  # SK하이닉스
        "005380",  # 현대차
        "000270",  # 기아
        "035420",  # NAVER
        "068270",  # 셀트리온
        "105560",  # KB금융
        "055550",  # 신한지주
        "373220",  # LG에너지솔루션
    }
)


def normalize_krx_code(code: str) -> str:
    raw = (code or "").strip().upper()
    if raw.startswith("A") and len(raw) == 7:
        raw = raw[1:]
    return raw


def mega_cap_universe() -> frozenset[str]:
    try:
        from config.config import mega_cap_codes

        return frozenset(normalize_krx_code(c) for c in mega_cap_codes)
    except (ImportError, AttributeError, TypeError):
        return DEFAULT_MEGA_CAP_CODES


def is_mega_cap(code: str) -> bool:
    return normalize_krx_code(code) in mega_cap_universe()
