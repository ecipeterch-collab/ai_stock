# Kiwoom Open API URLs
real_host_url = "https://api.kiwoom.com"
real_socket_url = "wss://api.kiwoom.com:10000"
paper_host_url = "https://mockapi.kiwoom.com"
paper_socket_url = "wss://mockapi.kiwoom.com:10000"

# Copy this file to config.py.
# Secrets are loaded from environment variables or config/local_secrets.py (not committed).
real_app_key = ""
real_app_secret = ""
paper_app_key = ""
paper_app_secret = ""
telegram_chat_id = ""
telegram_token = ""

use_paper = True
dmst_stex_tp = "KRX"
default_order_qty = 1
auto_interval_sec = 300
auto_max_buys_per_day = 3
fill_poll_wait_sec = 30
fill_poll_interval_sec = 2

strategy_mode = "swing"  # "scalping" | "swing" — /mode 로 런타임 변경 가능

strategy_scan_rank_top = 15
strategy_max_positions = 5
strategy_min_score = 19.0  # 진입 품질 강화 (17→19)
top_volume_rank_n = 30

# 포지션 사이징: 1주 고정 대신 종목당 목표 금액으로 수량 산정
position_sizing_enabled = True
position_target_krw = 500_000  # 종목당 목표 투입 금액(원)
position_min_qty = 1
position_max_qty = 100

strategy_stop_loss_pct = 3.0  # 손실 꼬리 축소 (5→3)
# 본전스탑/수익보호: 1주 포지션도 작동 (부분익절 게이트 없음)
strategy_swing_breakeven_activate_pct = 3.0
strategy_swing_breakeven_floor_pct = 0.5
strategy_swing_protect_trailing_activate_pct = 5.0
strategy_swing_protect_trailing_drawdown_pct = 1.5
strategy_swing_take_profit_pct = 10.0
strategy_swing_top_volume_tp1_pct = 15.0
strategy_swing_top_volume_tp2_pct = 20.0
strategy_swing_trailing_activate_pct = 12.0
strategy_swing_trailing_drawdown_pct = 2.0
strategy_exit_use_limit_orders = True
strategy_exit_limit_price_ticks = 2
strategy_take_profit_pct = 10.0
strategy_take_profit_partial_pct = 10.0
strategy_partial_sell_ratio = 0.5
strategy_trailing_activate_pct = 12.0
strategy_trailing_drawdown_pct = 2.0
strategy_breakeven_activate_pct = 12.0
strategy_breakeven_floor_pct = 5.0
# 눌림목 구간 집중 (flu -3~+1%, optimal 0.0) — 대형주 횡보·과열추격 차단
strategy_min_flu_rt = -3.0
strategy_max_flu_rt = 1.0
strategy_optimal_flu_rt = 0.0
strategy_min_rank_improve = 1
strategy_min_bullish_count = 3
strategy_weak_market_sentiment = -0.50
strategy_weak_market_min_bullish_count = 3
strategy_block_leveraged_etf = True
strategy_defensive_min_hold_minutes = 45
strategy_defensive_trailing_min_peak_pct = 3.0
strategy_reentry_cooldown_minutes = 45
strategy_trend_max_buys_per_day = 1

# 하락장 우량주 급락 매수 (스윙 전용, 약세장에서만)
strategy_crash_buy_enabled = True
strategy_crash_scan_rank_top = 30
strategy_crash_max_rank = 12
strategy_crash_min_flu_rt = -12.0
strategy_crash_max_flu_rt = -5.0
strategy_crash_optimal_flu_rt = -7.0
strategy_crash_min_score = 20.0
strategy_crash_max_buys_per_day = 1
strategy_crash_max_bullish_count = 2
strategy_crash_max_news_risk = 0.50
strategy_crash_reentry_cooldown_minutes = 90
strategy_circuit_recent_sells = 5
strategy_circuit_max_losses = 4
strategy_circuit_consecutive_losses = 3
strategy_circuit_cooldown_minutes = 60
strategy_circuit_stop_for_day_consecutive_losses = 5
strategy_buy_morning_start = "09:15"
strategy_buy_morning_end = "11:30"
strategy_buy_afternoon_start = "13:00"
strategy_buy_afternoon_end = "14:45"
strategy_eod_cut_loss_time = "15:10"
strategy_eod_sell_time = "15:20"
strategy_eod_sell_enabled = True
strategy_swing_eod_sell_all = False
strategy_swing_eod_sell_if_below_pct = 0.0
strategy_position_sync_grace_minutes = 15
strategy_portfolio_heat_limit = 2
strategy_portfolio_heat_pct = -1.0

news_enabled = True
news_cache_minutes = 20
news_max_headlines = 24
# 복합 뉴스 필터: 고위험·극단부정·(부정+리스크) 동반 시 차단
news_block_buy_sentiment = -0.70
news_block_buy_sentiment_hard = -0.90
news_block_buy_risk_floor = 0.20
news_block_buy_risk_score = 0.70
news_defensive_sell_sentiment = -0.45
news_force_reduce_risk_score = 0.75
news_score_boost_positive = 3.0
news_score_penalty_negative = -4.0
news_defensive_loss_pct = -0.5

news_override_when_market_bullish = True
news_override_max_risk_score = 0.40
news_override_min_bullish_ratio = 0.25
news_override_allow_buy_sentiment_floor = -0.75
news_override_disable_defensive_mode = True
news_override_disable_buy_block = True

notify_on_auto_events_only = True

# Web dashboard (run_web.py) — 외부 접속 시 반드시 강한 비밀번호·HTTPS/VPN 사용
# Tailscale Serve / Caddy 사용 시 127.0.0.1 권장 (docs/REMOTE_ACCESS.md)
web_host = "127.0.0.1"
web_port = 8080
web_token_expire_hours = 24

trend_auto_buy_enabled = True
trend_min_theme_hits = 2
trend_dip_min_flu_rt = -5.0
trend_dip_max_flu_rt = 3.0
trend_min_pick_score = 12.0
trend_news_cache_minutes = 25
trend_use_fallback_themes = True
trend_fallback_theme_count = 3

scalping_auto_interval_sec = 30
scalping_max_buys_per_day = 10
scalping_max_positions = 5
scalping_scan_rank_top = 30
scalping_min_score = 15.0
scalping_take_profit_pct = 0.9
scalping_quick_profit_pct = 0.45
scalping_stop_loss_pct = 1.0
hard_stop_loss_pct = 5.0
daily_loss_stop_pct = 5.0
scalping_trailing_activate_pct = 0.55
scalping_trailing_drawdown_pct = 0.3
scalping_breakeven_activate_pct = 0.4
scalping_breakeven_floor_pct = 0.08
scalping_momentum_stall_min_peak_pct = 0.35
scalping_momentum_stall_drop_pct = 0.25
scalping_min_flu_rt = 0.3
scalping_max_flu_rt = 7.0
scalping_optimal_flu_rt = 2.2
scalping_min_rank_improve = 1
scalping_min_bullish_count = 3
scalping_max_hold_minutes = 25
scalping_min_hold_minutes_for_quick_exit = 2
scalping_min_hold_seconds_for_stop_loss = 60
scalping_emergency_stop_loss_multiple = 3.0
scalping_buy_morning_start = "09:00"
scalping_buy_morning_end = "11:30"
scalping_buy_afternoon_start = "13:00"
scalping_buy_afternoon_end = "15:00"
scalping_eod_cut_loss_time = "15:08"
scalping_eod_sell_time = "15:15"
scalping_portfolio_heat_limit = 3
scalping_portfolio_heat_pct = -1.0
scalping_disable_trend_buy = False

scalping_reentry_cooldown_minutes = 8
scalping_trend_max_buys_per_day = 1

scalping_circuit_recent_sells = 5
scalping_circuit_max_losses = 5
scalping_circuit_consecutive_losses = 5
scalping_circuit_cooldown_minutes = 15
scalping_circuit_stop_for_day_consecutive_losses = 8

scalping_exit_use_limit_orders = True
scalping_exit_limit_price_ticks = 2
