from __future__ import annotations

# 스윙 전략에서 변동성·추적오차가 큰 상품 제외
_LEVERAGED_NAME_MARKERS = (
    "레버리지",
    "인버스",
    "곱버스",
    "단일종목",  # 단일종목 레버리지/선물 추종형
    "선물",
    "2X",
    "3X",
    "1.5X",
    "2.0X",
    "SHORT",
    "BULL",
    "BEAR",
    "ETN",
)

_ETF_NAME_PREFIXES = (
    "KODEX",
    "TIGER",
    "ARIRANG",
    "KOSEF",
    "ACE",
    "SOL",
    "RISE",
    "HANARO",
    "TIMEFOLIO",
)


def is_etf(name: str, code: str = "") -> bool:
    """개별주가 아닌 ETF/ETN류 (우량주 급락 매수 대상에서 제외)."""
    if is_leveraged_etf(name, code):
        return True
    label = (name or "").strip().upper()
    if not label:
        return False
    return any(label.startswith(prefix) for prefix in _ETF_NAME_PREFIXES)


def is_leveraged_etf(name: str, code: str = "") -> bool:
    """KODEX/TIGER 등 레버리지·인버스 ETF 여부 (종목명 기준)."""
    label = (name or "").strip()
    if not label:
        return False
    upper = label.upper()
    for marker in _LEVERAGED_NAME_MARKERS:
        if marker.upper() in upper or marker in label:
            return True
    return False
