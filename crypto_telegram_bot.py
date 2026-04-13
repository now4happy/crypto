# ==========================================================
# [crypto_telegram_bot.py] - 🌟 크립토 텔레그램 컨트롤러 🌟
# 💡 원본 TelegramController 구조 계승 → 크립토 전용 커맨드 완성
# 💡 /start /record /history /sync /seed /ticker /mode /reset /balance /version
# ==========================================================

import logging
import asyncio
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes


class CryptoTelegramController:

    SUPPORTED_COINS = ["BTC", "ETH", "XRP", "SOL", "ADA"]

    def __init__(self, cfg, broker, strategy, tx_lock):
        self.cfg      = cfg
        self.broker   = broker
        self.strategy = strategy
        self.tx_lock  = tx_lock
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
            f"🚀 <b>크립토 스노우볼 봇 {version}</b>\n\n"
            f"🪙 운용 코인: <b>{', '.join(tickers)}</b>\n\n"
            "📋 <b>명령어 목록</b>\n"
            "▫️ /balance - 잔고 및 포지션 조회\n"
            "▫️ /sync - 통합 지시서 (현재 플랜)\n"
            "▫️ /record - 장부 조회\n"
            "▫️ /history - 실현손익 히스토리\n"
            "▫️ /seed - 시드머니 설정\n"
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
            lines = [f"💵 <b>KRW 잔고:</b> {krw:,.0f}원\n"]

            for ticker in tickers:
                curr_p = await asyncio.to_thread(self.broker.get_current_price, ticker)
                pos    = self.cfg.get_position(ticker)
                qty    = pos["qty"]
                avg    = pos["avg"]

                if qty > 0 and avg > 0:
                    ret_pct  = (curr_p - avg) / avg * 100
                    valuation = curr_p * qty
                    invest    = avg * qty
                    pnl       = valuation - invest
                    lines.append(
                        f"🪙 <b>{ticker}</b>\n"
                        f"  수량: {qty:.8f} | 평단: {avg:,.0f}원\n"
                        f"  현재가: {curr_p:,.0f}원 | 수익률: {ret_pct:+.2f}%\n"
                        f"  평가금: {valuation:,.0f}원 | 손익: {pnl:+,.0f}원"
                    )
                else:
                    lines.append(f"🪙 <b>{ticker}</b>: 미보유 (현재가 {curr_p:,.0f}원)")

            await update.message.reply_text("\n".join(lines), parse_mode='HTML')
        except Exception as e:
            await update.message.reply_text(f"❌ 잔고 조회 실패: {e}")

    # ─────────────────────────────────────────────────────────
    # /sync - 통합 지시서
    # ─────────────────────────────────────────────────────────
    async def cmd_sync(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update):
            return
        try:
            async with self.tx_lock:
                krw, _ = await asyncio.to_thread(self.broker.get_account_balance)

            tickers = self.cfg.get_active_tickers()
            lines   = ["📋 <b>[ 통합 지시서 ]</b>\n"]

            for ticker in tickers:
                curr_p = await asyncio.to_thread(self.broker.get_current_price, ticker)
                pos    = self.cfg.get_position(ticker)
                plan   = self.strategy.get_plan(ticker, curr_p, krw)
                version = self.cfg.get_version(ticker)

                lines.append(f"━━━ <b>{ticker}</b> [{version}] ━━━")
                lines.append(f"현재가: {curr_p:,.0f}원")

                if pos["qty"] > 0:
                    ret_pct = (curr_p - pos['avg']) / pos['avg'] * 100
                    lines.append(f"보유: {pos['qty']:.8f}개 @ {pos['avg']:,.0f}원 ({ret_pct:+.2f}%)")
                else:
                    lines.append("보유: 없음")

                action = plan.get('action', 'HOLD')
                if action == 'BUY':
                    lines.append(f"📥 매수 타점: <b>{plan['buy_price']:,.0f}원</b>")
                    lines.append(f"   금액: {plan['buy_krw']:,.0f}원 | 수량: {plan['buy_qty']:.8f}")
                elif action == 'SELL':
                    lines.append(f"💰 익절 타점: <b>{plan.get('sell_price',0):,.0f}원</b>")
                elif action == 'HOLD':
                    lines.append(f"⏸ 대기 중 ({plan.get('reason','')})")

                # AVWAP 상태 추가 표시
                avwap_state = self.cfg.get_avwap_state(ticker)
                if avwap_state.get("is_enabled"):
                    avwap_qty = avwap_state.get("qty", 0.0)
                    status = "활성" if not avwap_state.get("is_shutdown") else "동결"
                    lines.append(f"🎯 AVWAP 스나이퍼: {status} (보유: {avwap_qty:.8f})")

            await update.message.reply_text("\n".join(lines), parse_mode='HTML')
        except Exception as e:
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
            if not records:
                lines.append(f"<b>{ticker}</b>: 거래 없음")
                continue
            lines.append(f"<b>{ticker}</b> (최근 5건):")
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
        tickers = self.cfg.get_active_tickers()
        keyboard = []
        for t in tickers:
            seed = self.cfg.get_seed(t)
            keyboard.append([InlineKeyboardButton(
                f"💵 {t} 시드 변경 (현재: {seed:,.0f}원)",
                callback_data=f"SEED_INPUT:{t}"
            )])
        await update.message.reply_text(
            "💵 <b>[ 시드머니 설정 ]</b>\n변경할 코인을 선택하세요:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    # ─────────────────────────────────────────────────────────
    # /ticker - 운용 코인 변경
    # ─────────────────────────────────────────────────────────
    async def cmd_ticker(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update):
            return
        current = self.cfg.get_active_tickers()
        keyboard = [
            [InlineKeyboardButton("₿ BTC 전용",      callback_data="TICKER:BTC")],
            [InlineKeyboardButton("Ξ ETH 전용",      callback_data="TICKER:ETH")],
            [InlineKeyboardButton("₿+Ξ BTC+ETH",    callback_data="TICKER:BTC_ETH")],
            [InlineKeyboardButton("🌊 XRP 전용",      callback_data="TICKER:XRP")],
            [InlineKeyboardButton("◎ SOL 전용",      callback_data="TICKER:SOL")],
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
        tickers = self.cfg.get_active_tickers()
        keyboard = []
        for t in tickers:
            ver = self.cfg.get_version(t)
            avwap_state = self.cfg.get_avwap_state(t)
            avwap_on = "✅" if avwap_state.get("is_enabled") else "⬜"
            keyboard.append([
                InlineKeyboardButton(f"[{t}] V14 무한매수", callback_data=f"MODE_V14:{t}"),
                InlineKeyboardButton(f"{avwap_on} AVWAP", callback_data=f"MODE_AVWAP:{t}"),
            ])
        lines = ["⚙️ <b>[ 전략 모드 설정 ]</b>\n"]
        for t in tickers:
            ver = self.cfg.get_version(t)
            avwap = self.cfg.get_avwap_state(t)
            avwap_txt = "ON" if avwap.get("is_enabled") else "OFF"
            lines.append(f"<b>{t}</b>: {ver} | AVWAP={avwap_txt}")
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
        tickers = self.cfg.get_active_tickers()
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
        data = query.data

        # ── 코인 변경 ────────────────────────────────────────
        if data.startswith("TICKER:"):
            key = data.split(":")[1]
            if key == "BTC_ETH":
                tickers = ["BTC", "ETH"]
            else:
                tickers = [key]
            self.cfg.set_active_tickers(tickers)
            await query.edit_message_text(f"✅ 운용 코인 변경: <b>{', '.join(tickers)}</b>", parse_mode='HTML')

        # ── 전략 모드 ────────────────────────────────────────
        elif data.startswith("MODE_V14:"):
            ticker = data.split(":")[1]
            self.cfg.set_version(ticker, "V14")
            await query.edit_message_text(f"✅ [{ticker}] V14 무한매수 모드로 전환", parse_mode='HTML')

        elif data.startswith("MODE_AVWAP:"):
            ticker = data.split(":")[1]
            is_on  = self.cfg.toggle_avwap(ticker)
            # AVWAP ON 시 shutdown 해제
            if is_on:
                state = self.cfg.get_avwap_state(ticker)
                state["is_shutdown"] = False
                self.cfg.set_avwap_state(ticker, state)
            emoji = "✅" if is_on else "⬜"
            await query.edit_message_text(
                f"{emoji} [{ticker}] AVWAP 스나이퍼 {'활성화' if is_on else '비활성화'}",
                parse_mode='HTML'
            )

        # ── 시드 입력 ────────────────────────────────────────
        elif data.startswith("SEED_INPUT:"):
            ticker = data.split(":")[1]
            self.user_states[update.effective_chat.id] = f"SEED_{ticker}"
            await query.edit_message_text(
                f"💵 [{ticker}] 새 시드머니 금액을 입력하세요 (원화, 숫자만):"
            )

        # ── 비상 초기화 ──────────────────────────────────────
        elif data.startswith("RESET_CONFIRM:"):
            ticker = data.split(":")[1]
            self.cfg.clear_ledger(ticker)
            self.cfg.set_trade_lock(ticker, False)
            await query.edit_message_text(
                f"🔴 [{ticker}] 장부 초기화 완료. 새출발합니다!", parse_mode='HTML'
            )

        elif data == "RESET_LOCKS":
            self.cfg.reset_locks()
            await query.edit_message_text("🔓 모든 거래 잠금 해제 완료!")

    # ─────────────────────────────────────────────────────────
    # 텍스트 메시지 핸들러 (상태 기반 입력)
    # ─────────────────────────────────────────────────────────
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update):
            return
        chat_id = update.effective_chat.id
        text    = update.message.text.strip() if update.message.text else ""
        state   = self.user_states.get(chat_id)

        # ── 시드 입력 처리 ────────────────────────────────────
        if state and state.startswith("SEED_"):
            ticker = state[5:]
            try:
                amount = float(text.replace(",", ""))
                if amount < 10000:
                    await update.message.reply_text("⚠️ 최소 10,000원 이상 입력하세요.")
                    return
                self.cfg.set_seed(ticker, amount)
                del self.user_states[chat_id]
                await update.message.reply_text(
                    f"✅ [{ticker}] 시드머니 {amount:,.0f}원으로 설정 완료!"
                )
            except ValueError:
                await update.message.reply_text("⚠️ 숫자만 입력해주세요.")
            return

        # ── 텍스트 단축 명령 ──────────────────────────────────
        if "잔고" in text or "balance" in text.lower():
            await self.cmd_balance(update, context)
        elif "지시서" in text or "sync" in text.lower():
            await self.cmd_sync(update, context)
        elif "장부" in text:
            await self.cmd_record(update, context)
        elif "히스토리" in text or "전당" in text:
            await self.cmd_history(update, context)
        elif "종목" in text or "코인" in text:
            await self.cmd_ticker(update, context)
        elif "모드" in text or "전략" in text:
            await self.cmd_mode(update, context)
        elif "초기화" in text or "reset" in text.lower():
            await self.cmd_reset(update, context)
