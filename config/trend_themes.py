"""글로벌 트렌드 테마 ↔ 국내 관련 종목 매핑."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrendTheme:
    theme_id: str
    name: str
    keywords: tuple[str, ...]
    stocks: tuple[tuple[str, str], ...]  # (code, name)


TREND_THEMES: tuple[TrendTheme, ...] = (
    TrendTheme(
        theme_id="ai_chip",
        name="AI·반도체·HBM",
        keywords=(
            "ai", "인공지능", "hbm", "반도체", "semiconductor", "nvidia", "gpu",
            "chip", "메모리", "파운드리", "chatgpt", "데이터센터",
        ),
        stocks=(
            ("005930", "삼성전자"),
            ("000660", "SK하이닉스"),
            ("042700", "한미반도체"),
            ("403870", "HPSP"),
            ("058470", "리노공업"),
        ),
    ),
    TrendTheme(
        theme_id="ev_battery",
        name="2차전지·EV",
        keywords=(
            "ev", "전기차", "2차전지", "배터리", "battery", "리튬", "lithium",
            "테슬라", "tesla", "양극재", "음극재",
        ),
        stocks=(
            ("373220", "LG에너지솔루션"),
            ("006400", "삼성SDI"),
            ("247540", "에코프로비엠"),
            ("003670", "포스코퓨처엠"),
            ("086520", "에코프로"),
        ),
    ),
    TrendTheme(
        theme_id="bio_health",
        name="바이오·헬스케어",
        keywords=(
            "바이오", "biotech", "신약", "헬스케어", "healthcare", "제약",
            "pharma", "면역", "비만", "obesity", "glp",
        ),
        stocks=(
            ("207940", "삼성바이오로직스"),
            ("068270", "셀트리온"),
            ("326030", "SK바이오팜"),
            ("128940", "한미약품"),
            ("145020", "휴젤"),
        ),
    ),
    TrendTheme(
        theme_id="defense_space",
        name="방산·우주·드론",
        keywords=(
            "방산", "defense", "무기", "우주", "space", "드론", "drone",
            "missile", "k9", "satellite", "위성",
        ),
        stocks=(
            ("012450", "한화에어로스페이스"),
            ("047810", "한국항공우주"),
            ("272210", "한화시스템"),
            ("064350", "현대로템"),
            ("099320", "쎄트렉아이"),
        ),
    ),
    TrendTheme(
        theme_id="nuclear_energy",
        name="원전·에너지·전력",
        keywords=(
            "원전", "nuclear", "smr", "전력", "energy", "uranium", "전기",
            "power", "재생에너지", "renewable",
        ),
        stocks=(
            ("034020", "두산에너빌리티"),
            ("015760", "한국전력"),
            ("052690", "한전기술"),
            ("083650", "비에이치아이"),
            ("100840", "SNT에너지"),
        ),
    ),
    TrendTheme(
        theme_id="robot_auto",
        name="로봇·자동화·AI소프트",
        keywords=(
            "로봇", "robot", "자동화", "automation", "humanoid", "휴머노이드",
            "saas", "cloud", "소프트웨어",
        ),
        stocks=(
            ("277810", "레인보우로보틱스"),
            ("454910", "두산로보틱스"),
            ("108490", "로보티즈"),
            ("039030", "이오테크닉스"),
            ("035420", "NAVER"),
        ),
    ),
    TrendTheme(
        theme_id="display_oled",
        name="디스플레이·OLED",
        keywords=(
            "oled", "디스플레이", "display", "패널", "panel", "vision pro",
            "apple", "IT기기",
        ),
        stocks=(
            ("034220", "LG디스플레이"),
            ("000660", "SK하이닉스"),
            ("011070", "LG이노텍"),
            ("036930", "주성엔지니어링"),
            ("005930", "삼성전자"),
        ),
    ),
)
