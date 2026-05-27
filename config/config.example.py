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
auto_max_buys_per_day = 10
fill_poll_wait_sec = 30
fill_poll_interval_sec = 2

strategy_mode = "scalping"  # "scalping" | "swing"

strategy_scan_rank_top = 15
strategy_max_positions = 10
strategy_min_score = 18.0
strategy_take_profit_pct = 4.5
strategy_take_profit_partial_pct = 2.5
strategy_partial_sell_ratio = 0.5
strategy_stop_loss_pct = 1.8
strategy_trailing_activate_pct = 2.0
strategy_trailing_drawdown_pct = 1.2
strategy_breakeven_activate_pct = 1.0
strategy_breakeven_floor_pct = 0.3
strategy_min_flu_rt = 1.0
strategy_max_flu_rt = 6.5
strategy_optimal_flu_rt = 3.0
strategy_min_rank_improve = 2
strategy_min_bullish_count = 4
strategy_min_holding_score = 18.0
strategy_buy_morning_start = "09:15"
strategy_buy_morning_end = "11:30"
strategy_buy_afternoon_start = "13:00"
strategy_buy_afternoon_end = "14:00"
strategy_eod_cut_loss_time = "15:10"
strategy_eod_sell_time = "15:20"
strategy_eod_sell_enabled = True
strategy_portfolio_heat_limit = 2
strategy_portfolio_heat_pct = -1.0

news_enabled = True
news_cache_minutes = 20
news_max_headlines = 24
news_block_buy_sentiment = -0.35
news_block_buy_risk_score = 0.70
news_defensive_sell_sentiment = -0.45
news_force_reduce_risk_score = 0.75
news_score_boost_positive = 3.0
news_score_penalty_negative = -4.0
news_defensive_loss_pct = -0.5

news_override_when_market_bullish = True
news_override_max_risk_score = 0.25
news_override_disable_defensive_mode = True
news_override_disable_buy_block = True

notify_on_auto_events_only = True

trend_auto_buy_enabled = True
trend_min_theme_hits = 2
trend_dip_min_flu_rt = -4.0
trend_dip_max_flu_rt = 2.0
trend_min_pick_score = 12.0
trend_news_cache_minutes = 25
trend_use_fallback_themes = True
trend_fallback_theme_count = 3

scalping_auto_interval_sec = 30
scalping_max_buys_per_day = 20
scalping_max_positions = 5
scalping_scan_rank_top = 20
scalping_min_score = 20.0
scalping_take_profit_pct = 0.9
scalping_quick_profit_pct = 0.45
scalping_stop_loss_pct = 0.45
scalping_trailing_activate_pct = 0.55
scalping_trailing_drawdown_pct = 0.3
scalping_breakeven_activate_pct = 0.4
scalping_breakeven_floor_pct = 0.08
scalping_momentum_stall_min_peak_pct = 0.35
scalping_momentum_stall_drop_pct = 0.25
scalping_min_flu_rt = 0.5
scalping_max_flu_rt = 5.0
scalping_optimal_flu_rt = 1.8
scalping_min_rank_improve = 2
scalping_min_bullish_count = 5
scalping_max_hold_minutes = 25
scalping_min_hold_minutes_for_quick_exit = 2
scalping_buy_morning_start = "09:00"
scalping_buy_morning_end = "11:00"
scalping_buy_afternoon_start = "13:00"
scalping_buy_afternoon_end = "14:50"
scalping_eod_cut_loss_time = "15:08"
scalping_eod_sell_time = "15:15"
scalping_portfolio_heat_limit = 2
scalping_portfolio_heat_pct = -0.5
scalping_disable_trend_buy = False

scalping_reentry_cooldown_minutes = 7
scalping_trend_max_buys_per_day = 1
