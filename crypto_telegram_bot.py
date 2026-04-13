# ==========================================================
# [crypto_telegram_bot.py] - 🌟 크립토 텔레그램 컨트롤러 🌟
# ✅ /sync 출력: 라오어 무한매수법 지시서 형식 완전 구현
#    - 진행도(T), 총 시드, 당일 예산
#    - 평단매수/별값매수/별값매도/좁줍 타점 표시
#    - 전반전/후반전/새출발 상태 표시
# ==========================================================

import logging
import asyncio
import datetime
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes


class CryptoTelegramController:

    SUPPORTED_COINS = ["BTC", "ETH", "XRP", "SOL", "ADA", "DOGE"]

    def __init__(self, cfg, broker, strategy, tx_lock):
        self.cfg         = cfg
        self.broker      = broker
        self.strategy    = strategy
        self.tx_lock     = tx_lock
        self.user_states = {}

    def _is_admin(self, update: Update) -> bool:
        admin_id = self.cfg.get_chat_id()
        return admin_id is None or update.effective_chat.id == admin_id

    # ─────────────────────────────────────────────────────────
    # /start
    # ─────────────────────────────────────────────────────────
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update):
            return
        tickers = self.cfg.get_active_tickers()
        version = self.cfg.get_latest_version()
        msg = (
            f"🚀 <b>크립토 무한매수 봇 {version}</b>\n\n"
            f"🪙 운용 코인: <b>{', '.join(tickers)}</b>\n\n"
            "📋 <b>명령어 목록</b>\n"
            "▫️ /balance - 잔고 및 포지션 조회\n"
            "▫️ /sync - 통합 지시서 (무한매수 플랜)\n"
            "▫️ /record - 장부 조회\n"
            "▫️ /history - 실현손익 히스토리\n"
            "▫️ /seed - 시드머니 설정\n"
            "▫️ /split - 분할 수 설정\n"
            "▫️ /target - 목표 수익률 설정\n"
            "▫️ /ticker - 운용 코인 변경\n"
            "▫️ /mode - 전략 모드 설정\n"
            "▫️ /reset - 비상 초기화\n"
            "▫️ /version - 버전 정보\n"
        )
        await update.message.reply_text(msg, parse_mode='HTML')

    # ─────────────────────────────────────────────────────────
    # /balance
    # ─────────────────────────────────────────────────────────
    async def cmd_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update):
            return
        try:
            async with self.tx_lock:
                krw, holdings = await asyncio.to_thread(self.broker.get_account_balance)

            tickers = self.cfg.get_active_tickers()
            lines = [f"💵 <b>KRW 가용 잔고:</b> {krw:,.0f}원\n"]

            for ticker in tickers:
                curr_p = await asyncio.to_thread(self.broker.get_current_price, ticker)
                pos    = self.cfg.get_position(ticker)
                qty    = pos["qty"]
                avg    = pos["avg"]

                # API 실제 보유량도 표시
                api_holding = holdings.get(ticker, {})
                api_qty = api_holding.get("qty", 0.0)
                api_avg = api_holding.get("avg", 0.0)

                if qty > 0 and avg > 0:
                    ret_pct   = (curr_p - avg) / avg * 100
                    valuation = curr_p * qty
                    pnl       = valuation - avg * qty
                    lines.append(
                        f"🪙 <b>{ticker}</b>\n"
                        f"  📒 장부 수량: {qty:.8f}개 | 평단: {avg:,.0f}원\n"
                        f"  📡 API 수량: {api_qty:.8f}개 | API 평단: {api_avg:,.0f}원\n"
                        f"  현재가: {curr_p:,.0f}원 | 수익률: {ret_pct:+.2f}%\n"
                        f"  평가금: {valuation:,.0f}원 | 손익: {pnl:+,.0f}원"
                    )
                elif api_qty > 0:
                    lines.append(
                        f"🪙 <b>{ticker}</b> (장부 없음 - API만 감지)\n"
                        f"  API 수량: {api_qty:.8f}개 | 현재가: {curr_p:,.0f}원"
                    )
                else:
                    lines.append(f"🪙 <b>{ticker}</b>: 미보유 (현재가 {curr_p:,.0f}원)")

            await update.message.reply_text("\n".join(lines), parse_mode='HTML')
        except Exception as e:
            logging.error(f"❌ [cmd_balance] {e}")
            await update.message.reply_text(f"❌ 잔고 조회 실패: {e}")

    # ─────────────────────────────────────────────────────────
    # ✅ /sync - 라오어 무한매수법 통합 지시서
    # ─────────────────────────────────────────────────────────
    async def cmd_sync(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update):
            return
        try:
            kst = pytz.timezone('Asia/Seoul')
            now_kst = datetime.datetime.now(kst)
            now_str = now_kst.strftime("%H:%M")

            async with self.tx_lock:
                krw, _ = await asyncio.to_thread(self.broker.get_account_balance)

            tickers = self.cfg.get_active_tickers()
            lines   = [f"🔄 <b>[ 통합 지시서 ]</b> {now_str}\n"
                       f"💵 주문가능금액: {krw:,.0f}원\n"]

            for ticker in tickers:
                curr_p     = await asyncio.to_thread(self.broker.get_current_price, ticker)
                candles_1h = await asyncio.to_thread(self.broker.get_candlestick, ticker, "1h")
                candles_24h = await asyncio.to_thread(self.broker.get_candlestick, ticker, "24h")

                # 당일 고가/저가
                daily_high, daily_low = 0.0, 0.0
                if candles_1h:
                    from crypto_strategy import CryptoVolatilityEngine
                    ve = CryptoVolatilityEngine()
                    daily_high, daily_low = ve.get_daily_high_low(candles_1h)

                pos     = self.cfg.get_position(ticker)
                qty     = pos["qty"]
                avg     = pos["avg"]
                seed    = self.cfg.get_seed(ticker)
                split   = self.cfg.get_split_count(ticker)
                target  = self.cfg.get_target_profit(ticker)
                version = self.cfg.get_version(ticker)

                plan = self.strategy.get_plan(ticker, curr_p, krw, candles_1h)

                state      = plan.get('state', '새출발')
                progress_t = plan.get('progress_t', 0.0)
                progress_n = plan.get('progress_n', 0.0)
                one_portion = plan.get('one_portion_krw', seed / split)
                action     = plan.get('action', 'HOLD')

                # 상태 이모지
                if state == '새출발':
                    state_emoji = "✨"
                elif state == '전반전':
                    state_emoji = "🔵"
                else:
                    state_emoji = "🟠"

                # 수익률
                ret_pct = 0.0
                if qty > 0 and avg > 0:
                    ret_pct = (curr_p - avg) / avg * 100.0

                lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━")
                lines.append(
                    f"💎 <b>[{ticker}] 무한매수</b> [{version}]\n"
                    f"📈 진행: <b>{progress_t:.4f}T</b> / {split:.0f}분할\n"
                    f"💰 총 시드: {seed:,.0f}원\n"
                    f"🛒 당일 예산: {one_portion:,.0f}원"
                )

                if qty > 0 and avg > 0:
                    lines.append(
                        f"💲 현재 {curr_p:,.0f}원 / 평단 {avg:,.0f}원 ({qty:.6f}개)\n"
                        f"📊 수익: {ret_pct:+.2f}%"
                    )
                    if daily_high > 0:
                        dh_pct = (daily_high - curr_p) / curr_p * 100
                        dl_pct = (daily_low  - curr_p) / curr_p * 100
                        lines.append(
                            f"🔺 금일 고가: {daily_high:,.0f}원 ({dh_pct:+.2f}%)\n"
                            f"🔻 금일 저가: {daily_low:,.0f}원 ({dl_pct:+.2f}%)"
                        )
                else:
                    lines.append(f"💲 현재 {curr_p:,.0f}원 | 미보유")

                # 수익률 목표 진행도
                target_price = plan.get('target_sell_price', 0.0)
                lines.append(
                    f"🎯 {target:.1f}% | ⭐ {target:.2f}% | 🎯감시: {'ON' if self.cfg.get_avwap_state(ticker).get('is_enabled') else 'OFF'}"
                )

                # 주문 계획
                lines.append(f"\n📋 <b>[주문 계획 - {state_emoji}{state}]</b>")

                if action == 'SELL':
                    star_sell = plan.get('star_sell_price', 0)
                    sell_qty  = plan.get('star_sell_qty', qty)
                    lines.append(f"🔵 ⭐별값매도: <b>{star_sell:,.0f}원</b> x {sell_qty:.6f}개")
                    if target_price > 0:
                        lines.append(f"🎯 목표매도: <b>{target_price:,.0f}원</b>")

                elif action in ('BUY', 'HOLD'):
                    # 평단매수
                    avg_buy_p = plan.get('avg_buy_price', 0)
                    avg_buy_q = plan.get('avg_buy_qty', 0)
                    if avg_buy_p > 0:
                        lines.append(
                            f"🔴 ⚓평단매수: <b>{avg_buy_p:,.0f}원</b> x {avg_buy_q:.6f}개 (LOC)"
                        )

                    # 별값매수
                    star_buy_p = plan.get('star_buy_price', 0)
                    star_buy_q = plan.get('star_buy_qty', 0)
                    if star_buy_p > 0 and daily_high > 0:
                        lines.append(
                            f"🔴 ⭐별값매수: <b>{star_buy_p:,.0f}원</b> x {star_buy_q:.6f}개 (LOC)"
                        )

                    # 별값매도 (보유 중일 때)
                    if qty > 0 and target_price > 0:
                        star_sell = plan.get('star_sell_price', target_price)
                        lines.append(
                            f"🔵 ⭐별값매도: <b>{star_sell:,.0f}원</b> x {qty:.6f}개 (LOC)"
                        )
                        if target_price != star_sell:
                            lines.append(
                                f"🔵 🎯목표매도: <b>{target_price:,.0f}원</b> x {qty:.6f}개"
                            )

                    # 좁줍 플랜
                    joob = plan.get('joob_joob', [])
                    if joob:
                        jj_str = " ~ ".join([f"{j['price']:,.0f}원" for j in [joob[0], joob[-1]]])
                        lines.append(
                            f"🔑 좁줍({len(joob)}개): {jj_str} (LOC)"
                        )

                    if action == 'HOLD':
                        lines.append(f"⏸ <i>{plan.get('reason', '')}</i>")

                # AVWAP 상태
                avwap_state = self.cfg.get_avwap_state(ticker)
                if avwap_state.get("is_enabled"):
                    avwap_qty = avwap_state.get("qty", 0.0)
                    status = "활성" if not avwap_state.get("is_shutdown") else "동결"
                    candles_for_vwap = candles_1h or []
                    vwap = self.strategy.avwap.calc_daily_vwap(candles_for_vwap)
                    lines.append(
                        f"\n🎯 <b>AVWAP 스나이퍼</b>: {status} | "
                        f"VWAP={vwap:,.0f}원 | 보유={avwap_qty:.6f}개"
                    )

            lines.append("\n⚠️ <i>장마감/장전 주문 가능 (24/7)</i>")
            await update.message.reply_text("\n".join(lines), parse_mode='HTML')

        except Exception as e:
            logging.error(f"❌ [cmd_sync] {e}", exc_info=True)
            await update.message.reply_text(f"❌ 지시서 조회 실패: {e}")

    # ─────────────────────────────────────────────────────────
    # /record - 장부 조회
    # ─────────────────────────────────────────────────────────
    async def cmd_record(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update):
            return
        tickers = self.cfg.get_active_tickers()
        lines   = ["📒 <b>[ 거래 장부 ]</b>\n"]
        for ticker in tickers:
            records = self.cfg.get_ledger(ticker)
            pos     = self.cfg.get_position(ticker)
            if not records:
                lines.append(f"<b>{ticker}</b>: 거래 없음")
                continue
            lines.append(
                f"<b>{ticker}</b> | 누적 {pos['qty']:.6f}개 @ {pos['avg']:,.0f}원 "
                f"(최근 5건):"
            )
            for r in records[-5:]:
                side_emoji = "📥" if r.get("side") == "BUY" else "📤"
                lines.append(
                    f"  {side_emoji} {r.get('date','')[:16]} | "
                    f"{r.get('qty',0):.6f}개 @ {r.get('price',0):,.0f}원"
                )
        await update.message.reply_text("\n".join(lines), parse_mode='HTML')

    # ─────────────────────────────────────────────────────────
    # /history - 실현손익 히스토리
    # ─────────────────────────────────────────────────────────
    async def cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update):
            return
        history = self.cfg.get_history()
        if not history:
            await update.message.reply_text("📭 아직 실현된 수익이 없습니다.")
            return
        total_pnl = sum(h.get("realized_pnl", 0) for h in history)
        lines = [f"🏆 <b>[ 명예의 전당 ]</b> (총 {len(history)}건)\n"]
        for h in history[-10:]:
            emoji = "✅" if h.get("realized_pnl", 0) >= 0 else "❌"
            lines.append(
                f"{emoji} {h.get('date','')[:10]} [{h.get('ticker','')}] "
                f"{h.get('realized_pnl',0):+,.0f}원 ({h.get('realized_pnl_pct',0):+.2f}%)"
            )
        lines.append(f"\n💵 <b>누적 실현손익: {total_pnl:+,.0f}원</b>")
        await update.message.reply_text("\n".join(lines), parse_mode='HTML')

    # ─────────────────────────────────────────────────────────
    # /seed - 시드머니 설정
    # ─────────────────────────────────────────────────────────
    async def cmd_seed(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update):
            return
        tickers  = self.cfg.get_active_tickers()
        keyboard = [[InlineKeyboardButton(
            f"💰 {t} ({self.cfg.get_seed(t):,.0f}원)",
            callback_data=f"SEED_INPUT:{t}"
        )] for t in tickers]
        await update.message.reply_text(
            "💵 <b>[ 시드머니 설정 ]</b>\n변경할 코인을 선택하세요:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    # ─────────────────────────────────────────────────────────
    # /split - 분할 수 설정
    # ─────────────────────────────────────────────────────────
    async def cmd_split(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update):
            return
        tickers  = self.cfg.get_active_tickers()
        keyboard = [[InlineKeyboardButton(
            f"📊 {t} ({self.cfg.get_split_count(t):.0f}분할)",
            callback_data=f"SPLIT_INPUT:{t}"
        )] for t in tickers]
        await update.message.reply_text(
            "📊 <b>[ 분할 수 설정 ]</b>\n변경할 코인을 선택하세요:\n"
            "<i>(권장: 20~40분할)</i>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    # ─────────────────────────────────────────────────────────
    # /target - 목표 수익률 설정
    # ─────────────────────────────────────────────────────────
    async def cmd_target(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update):
            return
        tickers  = self.cfg.get_active_tickers()
        keyboard = [[InlineKeyboardButton(
            f"🎯 {t} ({self.cfg.get_target_profit(t):.1f}%)",
            callback_data=f"TARGET_INPUT:{t}"
        )] for t in tickers]
        await update.message.reply_text(
            "🎯 <b>[ 목표 수익률 설정 ]</b>\n변경할 코인을 선택하세요:\n"
            "<i>(라오어 권장: BTC 8%, ETH 10%)</i>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    # ─────────────────────────────────────────────────────────
    # /ticker - 운용 코인 변경
    # ─────────────────────────────────────────────────────────
    async def cmd_ticker(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update):
            return
        current  = self.cfg.get_active_tickers()
        keyboard = [
            [InlineKeyboardButton("₿ BTC 전용",   callback_data="TICKER:BTC")],
            [InlineKeyboardButton("Ξ ETH 전용",   callback_data="TICKER:ETH")],
            [InlineKeyboardButton("₿+Ξ BTC+ETH", callback_data="TICKER:BTC_ETH")],
            [InlineKeyboardButton("🌊 XRP 전용",   callback_data="TICKER:XRP")],
            [InlineKeyboardButton("◎ SOL 전용",   callback_data="TICKER:SOL")],
        ]
        await update.message.reply_text(
            f"🔄 <b>[ 운용 코인 선택 ]</b>\n현재: <b>{', '.join(current)}</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    # ─────────────────────────────────────────────────────────
    # /mode - 전략 모드 설정
    # ─────────────────────────────────────────────────────────
    async def cmd_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update):
            return
        tickers  = self.cfg.get_active_tickers()
        keyboard = []
        for t in tickers:
            avwap_state = self.cfg.get_avwap_state(t)
            avwap_on    = "✅" if avwap_state.get("is_enabled") else "⬜"
            keyboard.append([
                InlineKeyboardButton(f"[{t}] V14 무한매수", callback_data=f"MODE_V14:{t}"),
                InlineKeyboardButton(f"{avwap_on} AVWAP",  callback_data=f"MODE_AVWAP:{t}"),
            ])
        lines = ["⚙️ <b>[ 전략 모드 설정 ]</b>\n"]
        for t in tickers:
            ver   = self.cfg.get_version(t)
            avwap = self.cfg.get_avwap_state(t)
            lines.append(
                f"<b>{t}</b>: {ver} | AVWAP={'ON' if avwap.get('is_enabled') else 'OFF'} | "
                f"목표={self.cfg.get_target_profit(t):.1f}%"
            )
        await update.message.reply_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    # ─────────────────────────────────────────────────────────
    # /reset - 비상 초기화
    # ─────────────────────────────────────────────────────────
    async def cmd_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update):
            return
        tickers  = self.cfg.get_active_tickers()
        keyboard = [[InlineKeyboardButton(
            f"⚠️ {t} 장부 초기화", callback_data=f"RESET_CONFIRM:{t}"
        )] for t in tickers]
        keyboard.append([InlineKeyboardButton("🔓 잠금만 해제", callback_data="RESET_LOCKS")])
        await update.message.reply_text(
            "🚨 <b>[ 비상 초기화 ]</b>\n⚠️ 장부 초기화 시 해당 종목 데이터가 삭제됩니다!",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    # ─────────────────────────────────────────────────────────
    # /version
    # ─────────────────────────────────────────────────────────
    async def cmd_version(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update):
            return
        from crypto_config import VERSION_HISTORY
        lines = ["📌 <b>[ 업데이트 내역 ]</b>\n"]
        for v in VERSION_HISTORY[-5:]:
            lines.append(f"▫️ {v}")
        await update.message.reply_text("\n".join(lines), parse_mode='HTML')

    # ─────────────────────────────────────────────────────────
    # Callback 핸들러
    # ─────────────────────────────────────────────────────────
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data  = query.data

        # 코인 변경
        if data.startswith("TICKER:"):
            key     = data.split(":")[1]
            tickers = ["BTC", "ETH"] if key == "BTC_ETH" else [key]
            self.cfg.set_active_tickers(tickers)
            await query.edit_message_text(f"✅ 운용 코인 변경: <b>{', '.join(tickers)}</b>", parse_mode='HTML')

        # 전략 모드
        elif data.startswith("MODE_V14:"):
            ticker = data.split(":")[1]
            self.cfg.set_version(ticker, "V14")
            await query.edit_message_text(f"✅ [{ticker}] V14 무한매수 모드로 전환", parse_mode='HTML')

        elif data.startswith("MODE_AVWAP:"):
            ticker = data.split(":")[1]
            is_on  = self.cfg.toggle_avwap(ticker)
            if is_on:
                state = self.cfg.get_avwap_state(ticker)
                state["is_shutdown"] = False
                self.cfg.set_avwap_state(ticker, state)
            emoji = "✅" if is_on else "⬜"
            await query.edit_message_text(
                f"{emoji} [{ticker}] AVWAP 스나이퍼 {'활성화' if is_on else '비활성화'}",
                parse_mode='HTML'
            )

        # 시드 입력 대기
        elif data.startswith("SEED_INPUT:"):
            ticker = data.split(":")[1]
            self.user_states[update.effective_chat.id] = f"SEED_{ticker}"
            await query.edit_message_text(
                f"💵 [{ticker}] 새 시드머니 금액을 입력하세요 (원화, 숫자만):\n"
                f"현재: {self.cfg.get_seed(ticker):,.0f}원"
            )

        # 분할 수 입력 대기
        elif data.startswith("SPLIT_INPUT:"):
            ticker = data.split(":")[1]
            self.user_states[update.effective_chat.id] = f"SPLIT_{ticker}"
            await query.edit_message_text(
                f"📊 [{ticker}] 분할 수를 입력하세요 (숫자만, 권장 20~40):\n"
                f"현재: {self.cfg.get_split_count(ticker):.0f}분할"
            )

        # 목표 수익률 입력 대기
        elif data.startswith("TARGET_INPUT:"):
            ticker = data.split(":")[1]
            self.user_states[update.effective_chat.id] = f"TARGET_{ticker}"
            await query.edit_message_text(
                f"🎯 [{ticker}] 목표 수익률을 입력하세요 (%, 숫자만):\n"
                f"현재: {self.cfg.get_target_profit(ticker):.1f}%"
            )

        # 비상 초기화
        elif data.startswith("RESET_CONFIRM:"):
            ticker = data.split(":")[1]
            self.cfg.clear_ledger(ticker)
            self.cfg.set_trade_lock(ticker, False)
            await query.edit_message_text(
                f"🔴 [{ticker}] 장부 초기화 완료. 새출발합니다! ✨", parse_mode='HTML'
            )

        elif data == "RESET_LOCKS":
            self.cfg.reset_locks()
            await query.edit_message_text("🔓 모든 거래 잠금 해제 완료!")

    # ─────────────────────────────────────────────────────────
    # 텍스트 메시지 핸들러
    # ─────────────────────────────────────────────────────────
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update):
            return
        chat_id = update.effective_chat.id
        text    = update.message.text.strip() if update.message.text else ""
        state   = self.user_states.get(chat_id)

        # 시드 입력 처리
        if state and state.startswith("SEED_"):
            ticker = state[5:]
            try:
                amount = float(text.replace(",", "").replace("원", ""))
                if amount < 10000:
                    await update.message.reply_text("⚠️ 최소 10,000원 이상 입력하세요.")
                    return
                self.cfg.set_seed(ticker, amount)
                del self.user_states[chat_id]
                split = self.cfg.get_split_count(ticker)
                await update.message.reply_text(
                    f"✅ [{ticker}] 시드머니 {amount:,.0f}원 설정 완료!\n"
                    f"  1포션 = {amount/split:,.0f}원 ({split:.0f}분할)"
                )
            except ValueError:
                await update.message.reply_text("⚠️ 숫자만 입력해주세요.")
            return

        # 분할 수 입력 처리
        if state and state.startswith("SPLIT_"):
            ticker = state[6:]
            try:
                count = float(text.replace(",", ""))
                if count < 5 or count > 100:
                    await update.message.reply_text("⚠️ 5~100 사이 숫자를 입력하세요.")
                    return
                self.cfg.set_split_count(ticker, count)
                del self.user_states[chat_id]
                seed = self.cfg.get_seed(ticker)
                await update.message.reply_text(
                    f"✅ [{ticker}] {count:.0f}분할 설정 완료!\n"
                    f"  1포션 = {seed/count:,.0f}원"
                )
            except ValueError:
                await update.message.reply_text("⚠️ 숫자만 입력해주세요.")
            return

        # 목표 수익률 입력 처리
        if state and state.startswith("TARGET_"):
            ticker = state[7:]
            try:
                pct = float(text.replace(",", "").replace("%", ""))
                if pct < 1 or pct > 50:
                    await update.message.reply_text("⚠️ 1~50 사이 숫자를 입력하세요.")
                    return
                self.cfg.set_target_profit(ticker, pct)
                del self.user_states[chat_id]
                await update.message.reply_text(
                    f"✅ [{ticker}] 목표 수익률 {pct:.1f}% 설정 완료!"
                )
            except ValueError:
                await update.message.reply_text("⚠️ 숫자만 입력해주세요.")
            return

        # 단축 명령
        low = text.lower()
        if "잔고" in text or "balance" in low:
            await self.cmd_balance(update, context)
        elif "지시서" in text or "sync" in low:
            await self.cmd_sync(update, context)
        elif "장부" in text:
            await self.cmd_record(update, context)
        elif "히스토리" in text or "전당" in text:
            await self.cmd_history(update, context)
        elif "종목" in text or "코인" in text:
            await self.cmd_ticker(update, context)
        elif "모드" in text or "전략" in text:
            await self.cmd_mode(update, context)
        elif "초기화" in text or "reset" in low:
            await self.cmd_reset(update, context)
        elif "분할" in text:
            await self.cmd_split(update, context)
        elif "목표" in text:
            await self.cmd_target(update, context)
