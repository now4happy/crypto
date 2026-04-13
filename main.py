# ==========================================================
# [main.py] - 빗썸 크립토 무한매수 봇 V2.0
# ✅ asyncio.Lock을 post_init 훅에서 생성 (루프 불일치 버그 수정)
# ✅ 스케줄러 예외가 봇 전체를 멈추지 않도록 보호
# ✅ 명령어 응답 안 되는 문제 해결
# ==========================================================

import os
import logging
import datetime
import pytz
import asyncio
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
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
    scheduled_profit_monitor,
    scheduled_self_cleaning,
    scheduled_volatility_scan,
)

for d in ['data', 'logs']:
    os.makedirs(d, exist_ok=True)

load_dotenv()

TELEGRAM_TOKEN     = os.getenv("TELEGRAM_TOKEN")
BITHUMB_API_KEY    = os.getenv("BITHUMB_API_KEY")
BITHUMB_API_SECRET = os.getenv("BITHUMB_API_SECRET")

try:
    ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID")) if os.getenv("ADMIN_CHAT_ID") else None
except (ValueError, TypeError):
    ADMIN_CHAT_ID = None

if not all([TELEGRAM_TOKEN, BITHUMB_API_KEY, BITHUMB_API_SECRET]):
    print("❌ [치명적 오류] .env 파일에 필수 키가 누락되었습니다.")
    print("   필요: TELEGRAM_TOKEN, ADMIN_CHAT_ID, BITHUMB_API_KEY, BITHUMB_API_SECRET")
    exit(1)

log_filename = f"logs/crypto_bot_{datetime.datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
# python-telegram-bot 내부 로그 레벨 조정 (너무 많은 debug 로그 억제)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)


def main():
    cfg      = CryptoConfigManager()
    broker   = BithumbBroker(BITHUMB_API_KEY, BITHUMB_API_SECRET)
    strategy = CryptoInfiniteStrategy(cfg)

    if ADMIN_CHAT_ID:
        cfg.set_chat_id(ADMIN_CHAT_ID)

    # ✅ 핵심 수정: Application 먼저 빌드 후 post_init에서 Lock 생성
    # asyncio.Lock()은 반드시 실행 중인 이벤트 루프 안에서 생성해야 함
    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .connect_timeout(30.0)
        .pool_timeout(30.0)
        .connection_pool_size(64)
        .build()
    )

    # app.bot_data에 공유 객체 저장 (Lock은 post_init에서 생성)
    app.bot_data["cfg"]      = cfg
    app.bot_data["broker"]   = broker
    app.bot_data["strategy"] = strategy

    async def post_init(application: Application) -> None:
        """✅ 이벤트 루프 안에서 Lock 생성 및 스케줄러 등록"""
        tx_lock = asyncio.Lock()
        application.bot_data["tx_lock"] = tx_lock

        bot_ctrl = CryptoTelegramController(cfg, broker, strategy, tx_lock)
        application.bot_data["bot_ctrl"] = bot_ctrl

        # ── 명령어 핸들러 등록 ──────────────────────────────
        handlers = [
            ("start",   bot_ctrl.cmd_start),
            ("balance", bot_ctrl.cmd_balance),
            ("sync",    bot_ctrl.cmd_sync),
            ("record",  bot_ctrl.cmd_record),
            ("history", bot_ctrl.cmd_history),
            ("seed",    bot_ctrl.cmd_seed),
            ("split",   bot_ctrl.cmd_split),
            ("target",  bot_ctrl.cmd_target),
            ("ticker",  bot_ctrl.cmd_ticker),
            ("mode",    bot_ctrl.cmd_mode),
            ("reset",   bot_ctrl.cmd_reset),
            ("version", bot_ctrl.cmd_version),
        ]
        for cmd, handler in handlers:
            application.add_handler(CommandHandler(cmd, handler))

        application.add_handler(CallbackQueryHandler(bot_ctrl.handle_callback))
        application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, bot_ctrl.handle_message)
        )

        # ── 스케줄러 등록 ────────────────────────────────────
        chat_id = cfg.get_chat_id()
        if not chat_id:
            logging.warning("⚠️  ADMIN_CHAT_ID 미설정 - 스케줄러 비활성화")
            return

        kst = pytz.timezone('Asia/Seoul')
        app_data = {
            'cfg':      cfg,
            'broker':   broker,
            'strategy': strategy,
            'tx_lock':  tx_lock,
        }
        jq = application.job_queue

        # API 헬스체크: 6시간마다
        for hh in [0, 6, 12, 18]:
            jq.run_daily(
                scheduled_token_check,
                time=datetime.time(hh, 0, tzinfo=kst),
                days=tuple(range(7)),
                chat_id=chat_id,
                data=app_data,
                name=f"token_check_{hh}h",
            )

        # 일일 초기화: 09:00 KST
        jq.run_daily(
            scheduled_force_reset,
            time=datetime.time(9, 0, tzinfo=kst),
            days=tuple(range(7)),
            chat_id=chat_id,
            data=app_data,
            name="force_reset",
        )

        # 변동성 브리핑: 10:00 KST
        jq.run_daily(
            scheduled_volatility_scan,
            time=datetime.time(10, 0, tzinfo=kst),
            days=tuple(range(7)),
            chat_id=chat_id,
            data=app_data,
            name="volatility_scan",
        )

        # 정규 매매: 10:05 KST
        jq.run_daily(
            scheduled_regular_trade,
            time=datetime.time(10, 5, tzinfo=kst),
            days=tuple(range(7)),
            chat_id=chat_id,
            data=app_data,
            name="regular_trade",
        )

        # 실시간 익절 감시: 60초
        jq.run_repeating(
            scheduled_profit_monitor,
            interval=60,
            first=10,
            chat_id=chat_id,
            data=app_data,
            name="profit_monitor",
        )

        # AVWAP 스나이퍼: 60초
        jq.run_repeating(
            scheduled_sniper_monitor,
            interval=60,
            first=15,
            chat_id=chat_id,
            data=app_data,
            name="sniper_monitor",
        )

        # 자정 청소: 03:00 KST
        jq.run_daily(
            scheduled_self_cleaning,
            time=datetime.time(3, 0, tzinfo=kst),
            days=tuple(range(7)),
            chat_id=chat_id,
            data=app_data,
            name="self_cleaning",
        )

        logging.info(f"✅ [post_init] 핸들러 및 스케줄러 등록 완료 (chat_id={chat_id})")

        # 시작 알림
        tickers = cfg.get_active_tickers()
        version = cfg.get_latest_version()
        try:
            await application.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🚀 <b>크립토 무한매수 봇 {version} 시작!</b>\n"
                    f"🪙 운용 코인: <b>{', '.join(tickers)}</b>\n"
                    f"📊 실시간 익절·스나이퍼 감시 활성화\n"
                    f"/balance 로 잔고를 확인하세요."
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            logging.error(f"❌ 시작 알림 실패: {e}")

    app.post_init = post_init

    latest_version = cfg.get_latest_version()
    tickers        = cfg.get_active_tickers()
    print("=" * 60)
    print(f"🚀 크립토 무한매수 봇 {latest_version}")
    print(f"🪙 운용 코인: {', '.join(tickers)}")
    for t in tickers:
        seed  = cfg.get_seed(t)
        split = cfg.get_split_count(t)
        tgt   = cfg.get_target_profit(t)
        print(f"   {t}: 시드={seed:,.0f}원 / {split:.0f}분할 / 목표={tgt:.1f}%")
    print(f"📡 빗썸 JWT API V2.0")
    print(f"🤖 텔레그램 봇 시작 중...")
    print("=" * 60)

    app.run_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,   # ✅ 재시작 시 밀린 메시지 무시
    )


if __name__ == "__main__":
    main()
