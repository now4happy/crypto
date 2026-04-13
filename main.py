# ==========================================================
# [main.py] - 🌟 빗썸 크립토 자동매매 봇 🌟
# 💡 원본 KIS 주식 봇(앱솔루트 스노우볼)의 아키텍처를 100% 계승
# 💡 빗썸 API + 텔레그램 봇 기반 BTC/ETH 자동매매 시스템
# 💡 무한매수법(V14) + V-REV 역추세 + AVWAP 스나이퍼 전술 크립토 포팅
# ==========================================================

import os
import logging
import datetime
import pytz
import asyncio
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from dotenv import load_dotenv

from crypto_config import CryptoConfigManager
from crypto_broker import BithumbBroker
from crypto_strategy import CryptoInfiniteStrategy
from crypto_telegram_bot import CryptoTelegramController
from crypto_scheduler import (
    scheduled_token_check,
    scheduled_force_reset,
    scheduled_regular_trade,
    scheduled_sniper_monitor,
    scheduled_self_cleaning,
    scheduled_volatility_scan,
)

if not os.path.exists('data'):
    os.makedirs('data')
if not os.path.exists('logs'):
    os.makedirs('logs')

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
try:
    ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID")) if os.getenv("ADMIN_CHAT_ID") else None
except ValueError:
    ADMIN_CHAT_ID = None

BITHUMB_API_KEY    = os.getenv("BITHUMB_API_KEY")
BITHUMB_API_SECRET = os.getenv("BITHUMB_API_SECRET")

if not all([TELEGRAM_TOKEN, BITHUMB_API_KEY, BITHUMB_API_SECRET]):
    print("❌ [치명적 오류] .env 파일에 필수 키가 누락되었습니다.")
    print("   필요: TELEGRAM_TOKEN, ADMIN_CHAT_ID, BITHUMB_API_KEY, BITHUMB_API_SECRET")
    exit(1)

log_filename = f"logs/crypto_bot_{datetime.datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

def main():
    cfg     = CryptoConfigManager()
    broker  = BithumbBroker(BITHUMB_API_KEY, BITHUMB_API_SECRET)
    strategy = CryptoInfiniteStrategy(cfg)

    if ADMIN_CHAT_ID:
        cfg.set_chat_id(ADMIN_CHAT_ID)

    tx_lock = asyncio.Lock()
    bot = CryptoTelegramController(cfg, broker, strategy, tx_lock)

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .connect_timeout(30.0)
        .pool_timeout(30.0)
        .connection_pool_size(128)
        .build()
    )

    for cmd, handler in [
        ("start",      bot.cmd_start),
        ("record",     bot.cmd_record),
        ("history",    bot.cmd_history),
        ("sync",       bot.cmd_sync),
        ("seed",       bot.cmd_seed),
        ("ticker",     bot.cmd_ticker),
        ("mode",       bot.cmd_mode),
        ("reset",      bot.cmd_reset),
        ("balance",    bot.cmd_balance),
        ("version",    bot.cmd_version),
    ]:
        app.add_handler(CommandHandler(cmd, handler))

    app.add_handler(CallbackQueryHandler(bot.handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))

    if cfg.get_chat_id():
        jq = app.job_queue
        kst = pytz.timezone('Asia/Seoul')

        app_data = {
            'cfg':      cfg,
            'broker':   broker,
            'strategy': strategy,
            'bot':      bot,
            'tx_lock':  tx_lock,
        }

        # ─── 시스템 관리 스케줄 ───────────────────────────
        # 토큰 갱신: 매 6시간 (빗썸 API key는 만료 없으나 상태 체크용)
        for hh in [0, 6, 12, 18]:
            jq.run_daily(
                scheduled_token_check,
                time=datetime.time(hh, 0, tzinfo=kst),
                days=tuple(range(7)),
                chat_id=cfg.get_chat_id(),
                data=app_data
            )

        # 일일 초기화: 매일 09:00 KST
        jq.run_daily(
            scheduled_force_reset,
            time=datetime.time(9, 0, tzinfo=kst),
            days=tuple(range(7)),
            chat_id=cfg.get_chat_id(),
            data=app_data
        )

        # 변동성 스캔: 매일 10:00 KST
        jq.run_daily(
            scheduled_volatility_scan,
            time=datetime.time(10, 0, tzinfo=kst),
            days=tuple(range(7)),
            chat_id=cfg.get_chat_id(),
            data=app_data
        )

        # 정규 매매 (무한매수법 LOC 장전): 매일 10:05 KST
        jq.run_daily(
            scheduled_regular_trade,
            time=datetime.time(10, 5, tzinfo=kst),
            days=tuple(range(7)),
            chat_id=cfg.get_chat_id(),
            data=app_data
        )

        # 스나이퍼 감시: 60초 간격 실시간
        jq.run_repeating(
            scheduled_sniper_monitor,
            interval=60,
            chat_id=cfg.get_chat_id(),
            data=app_data
        )

        # 자정 청소: 매일 03:00 KST
        jq.run_daily(
            scheduled_self_cleaning,
            time=datetime.time(3, 0, tzinfo=kst),
            days=tuple(range(7)),
            chat_id=cfg.get_chat_id(),
            data=app_data
        )

    latest_version = cfg.get_latest_version()
    print("=" * 60)
    print(f"🚀 크립토 스노우볼 퀀트 엔진 {latest_version}")
    print(f"🪙 운용 코인: {', '.join(cfg.get_active_tickers())}")
    print(f"📡 빗썸 API 연결 완료")
    print(f"🤖 텔레그램 봇 대기 중...")
    print("=" * 60)

    app.run_polling()

if __name__ == "__main__":
    main()
