"""키움 REST API + 텔레그램 연동 자동매매 프로그램."""

from trading.bot import TelegramTradingBot


def main() -> None:
    bot = TelegramTradingBot()
    bot.run()


if __name__ == "__main__":
    main()
