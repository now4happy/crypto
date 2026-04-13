# ==========================================================
# [crypto_scheduler.py] - 🌟 크립토 스케줄러 🌟
# ✅ 라오어 무한매수법 자동 실행:
#    - 평단매수 지정가 주문 자동 실행
#    - 별값매도 목표가 달성 시 전량 시장가 익절
#    - AVWAP 스나이퍼 60초 감시
# ✅ 24/7 코인 시장: 장중/장외 구분 없음
# ==========================================================

import logging
import datetime
import asyncio
import glob
import os
import time
import pytz


# ─────────────────────────────────────────────────────────
# 🧹 자정 청소
# ─────────────────────────────────────────────────────────
async def scheduled_self_cleaning(context):
    """7일 초과 로그/백업 파일 자동 삭제"""
    try:
        now_ts    = time.time()
        seven_days = 7 * 24 * 3600
        for pattern in ["logs/*.log", "data/*.bak_*"]:
            for f in glob.glob(pattern):
                if os.path.isfile(f) and os.stat(f).st_mtime < now_ts - seven_days:
                    try:
                        os.remove(f)
                    except Exception:
                        pass
        logging.info("🧹 [자정 청소] 오래된 파일 소각 완료")
    except Exception as e:
        logging.error(f"🧹 [자정 청소] 에러: {e}")


# ─────────────────────────────────────────────────────────
# 🔑 API 헬스체크
# ─────────────────────────────────────────────────────────
async def scheduled_token_check(context):
    """빗썸 API 연결 상태 + KRW 잔고 확인"""
    try:
        broker = context.job.data['broker']
        chat_id = context.job.chat_id

        krw, holdings = await asyncio.to_thread(broker.get_account_balance)
        hold_str = ", ".join([
            f"{coin}: {info['qty']:.6f}개"
            for coin, info in holdings.items()
        ]) if holdings else "없음"

        logging.info(f"🔑 [API 헬스체크] KRW: {krw:,.0f}원 | 보유: {hold_str}")

        # 잔고 0원이면 경고 메시지
        if krw == 0.0 and not holdings:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "⚠️ <b>[API 헬스체크 경고]</b>\n"
                    "KRW 잔고 0원 + 코인 미보유 감지\n"
                    "빗썸 API 키/IP 화이트리스트를 확인하세요."
                ),
                parse_mode='HTML'
            )
    except Exception as e:
        logging.error(f"❌ [API 헬스체크] 에러: {e}")


# ─────────────────────────────────────────────────────────
# 🔓 일일 초기화
# ─────────────────────────────────────────────────────────
async def scheduled_force_reset(context):
    """매일 09:00 KST: 거래 잠금 해제 및 일일 초기화"""
    app_data = context.job.data
    cfg      = app_data['cfg']
    chat_id  = context.job.chat_id

    cfg.reset_locks()

    msg = (
        "🔓 <b>[09:00 KST] 일일 시스템 초기화 완료</b>\n"
        "▫️ 모든 거래 잠금 해제\n"
        "▫️ 오늘도 무한매수 칼같이 실행합니다 🚀"
    )
    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')
    logging.info("🔓 [일일 초기화] 잠금 해제 완료")


# ─────────────────────────────────────────────────────────
# 📊 변동성 브리핑 (10:00 KST)
# ─────────────────────────────────────────────────────────
async def scheduled_volatility_scan(context):
    """공포탐욕지수 + HV 기반 일일 브리핑"""
    app_data = context.job.data
    cfg      = app_data['cfg']
    broker   = app_data['broker']
    strategy = app_data['strategy']
    chat_id  = context.job.chat_id

    tickers = cfg.get_active_tickers()
    lines   = ["📊 <b>[10:00 변동성 브리핑]</b>\n"]

    for ticker in tickers:
        try:
            candles_daily = await asyncio.to_thread(broker.get_candlestick, ticker, "24h")
            vol_data = await asyncio.to_thread(strategy.scan_volatility, ticker, candles_daily)
            fg  = vol_data["fear_greed"]
            hv  = vol_data["hv"]
            wt  = vol_data["weight"]
            rec = "✅ 매수 권장" if wt >= 1.0 else "⚠️ 자제 권장"
            lines.append(
                f"<b>{ticker}</b>: 공포탐욕={fg['value']}({fg['classification']}) "
                f"| HV={hv:.1f}% | 가중치={wt:.2f} {rec}"
            )
        except Exception as e:
            lines.append(f"<b>{ticker}</b>: 스캔 실패 ({e})")

    await context.bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode='HTML')


# ─────────────────────────────────────────────────────────
# ✅ 정규 매매 - 라오어 무한매수법 자동 실행 (10:05 KST)
# ─────────────────────────────────────────────────────────
async def scheduled_regular_trade(context):
    """
    10:05 KST: 무한매수법 플랜 연산 후 자동 주문 실행
    - SELL: 목표 수익률 달성 → 전량 시장가 매도
    - BUY: 평단매수 지정가 주문 실행
    """
    app_data = context.job.data
    cfg      = app_data['cfg']
    broker   = app_data['broker']
    strategy = app_data['strategy']
    tx_lock  = app_data['tx_lock']
    chat_id  = context.job.chat_id

    tickers = cfg.get_active_tickers()

    for ticker in tickers:
        if cfg.get_trade_lock(ticker):
            logging.info(f"[{ticker}] 거래 잠금 상태 - 정규 매매 스킵")
            continue

        try:
            async with tx_lock:
                curr_p     = await asyncio.to_thread(broker.get_current_price, ticker)
                krw, _     = await asyncio.to_thread(broker.get_account_balance)
                candles_1h = await asyncio.to_thread(broker.get_candlestick, ticker, "1h")

            if curr_p <= 0:
                continue

            plan = strategy.get_plan(ticker, curr_p, krw, candles_1h)
            action = plan.get('action', 'HOLD')

            # ── 익절 실행 ────────────────────────────────────
            if action == 'SELL':
                pos = cfg.get_position(ticker)
                sell_qty = plan.get('star_sell_qty', pos['qty'])

                if sell_qty <= 0:
                    continue

                async with tx_lock:
                    result = await asyncio.to_thread(broker.sell_market, ticker, sell_qty)

                if broker.is_ok(result):
                    avg = pos['avg']
                    realized     = (curr_p - avg) * sell_qty if avg > 0 else 0
                    realized_pct = (curr_p - avg) / avg * 100 if avg > 0 else 0

                    cfg.add_ledger(ticker, "SELL", sell_qty, curr_p, note="목표 익절 자동 매도")
                    cfg.add_history(ticker, realized, realized_pct, note="무한매수법 목표 수익률 달성")
                    cfg.set_trade_lock(ticker, False)

                    msg = (
                        f"💰 <b>[{ticker}] 무한매수 목표 익절!</b>\n"
                        f"▫️ 매도가: <b>{curr_p:,.0f}원</b>\n"
                        f"▫️ 수량: <b>{sell_qty:.6f}개</b>\n"
                        f"▫️ 실현손익: <b>{realized:+,.0f}원 ({realized_pct:+.2f}%)</b>\n"
                        f"▫️ 이유: {plan.get('reason', '')}\n"
                        f"✨ 새출발 준비 완료!"
                    )
                    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')
                    logging.info(f"✅ [{ticker}] 익절 완료: {realized:+,.0f}원")

            # ── 평단매수 지정가 주문 ─────────────────────────
            elif action == 'BUY':
                avg_buy_price = plan.get('avg_buy_price', 0)
                avg_buy_qty   = plan.get('avg_buy_qty', 0)

                if avg_buy_price <= 0 or avg_buy_qty <= 0:
                    continue

                async with tx_lock:
                    result = await asyncio.to_thread(
                        broker.buy_limit, ticker, avg_buy_price, avg_buy_qty
                    )

                if broker.is_ok(result):
                    cfg.set_trade_lock(ticker, True)
                    cfg.add_ledger(
                        ticker, "BUY", avg_buy_qty, avg_buy_price,
                        note=f"무한매수 평단매수 (진행도: {plan.get('progress_t', 0):.4f}T)"
                    )
                    state = plan.get('state', '')
                    msg = (
                        f"📥 <b>[{ticker}] 무한매수 평단매수 완료</b>\n"
                        f"▫️ 타점: <b>{avg_buy_price:,.0f}원</b>\n"
                        f"▫️ 수량: <b>{avg_buy_qty:.8f}개</b>\n"
                        f"▫️ 진행도: {plan.get('progress_t', 0):.4f}T / "
                        f"{cfg.get_split_count(ticker):.0f}분할\n"
                        f"▫️ 상태: {state}"
                    )
                    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')
                    logging.info(f"✅ [{ticker}] 평단매수 완료: {avg_buy_price:,.0f}원")
                else:
                    logging.error(f"❌ [{ticker}] 평단매수 실패: {result.get('message', '')}")

            # HOLD
            else:
                logging.info(
                    f"[{ticker}] HOLD - {plan.get('reason', '')} "
                    f"(진행도: {plan.get('progress_t', 0):.4f}T)"
                )

        except Exception as e:
            logging.error(f"❌ [{ticker}] 정규 매매 에러: {e}", exc_info=True)


# ─────────────────────────────────────────────────────────
# ✅ 익절 모니터 - 60초마다 목표가 실시간 체크
# ─────────────────────────────────────────────────────────
async def scheduled_profit_monitor(context):
    """
    60초마다: 목표가 달성 여부 실시간 감시
    → 달성 시 즉시 전량 시장가 익절
    """
    app_data = context.job.data
    cfg      = app_data['cfg']
    broker   = app_data['broker']
    strategy = app_data['strategy']
    tx_lock  = app_data['tx_lock']
    chat_id  = context.job.chat_id

    tickers = cfg.get_active_tickers()

    for ticker in tickers:
        try:
            pos = cfg.get_position(ticker)
            qty = pos.get("qty", 0.0)
            avg = pos.get("avg", 0.0)
            if qty <= 0 or avg <= 0:
                continue

            target_pct = cfg.get_target_profit(ticker)
            target_price = avg * (1 + target_pct / 100.0)

            curr_p = await asyncio.to_thread(broker.get_current_price, ticker)
            if curr_p <= 0:
                continue

            if curr_p >= target_price:
                # 익절 조건 달성
                async with tx_lock:
                    result = await asyncio.to_thread(broker.sell_market, ticker, qty)

                if broker.is_ok(result):
                    realized     = (curr_p - avg) * qty
                    realized_pct = (curr_p - avg) / avg * 100

                    cfg.add_ledger(ticker, "SELL", qty, curr_p, note="실시간 목표가 달성 익절")
                    cfg.add_history(ticker, realized, realized_pct, note="실시간 익절 모니터")
                    cfg.set_trade_lock(ticker, False)

                    msg = (
                        f"🎉 <b>[{ticker}] 실시간 익절 완료!</b>\n"
                        f"▫️ 현재가: <b>{curr_p:,.0f}원</b> (목표: {target_price:,.0f}원)\n"
                        f"▫️ 실현손익: <b>{realized:+,.0f}원 ({realized_pct:+.2f}%)</b>\n"
                        f"▫️ 수량: {qty:.8f}개\n"
                        f"✨ 새출발 준비 완료!"
                    )
                    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')
                    logging.info(f"🎉 [{ticker}] 실시간 익절: {realized:+,.0f}원")

        except Exception as e:
            logging.error(f"❌ [{ticker}] 익절 모니터 에러: {e}")


# ─────────────────────────────────────────────────────────
# 🔫 AVWAP 스나이퍼 감시 (60초 반복)
# ─────────────────────────────────────────────────────────
async def scheduled_sniper_monitor(context):
    """
    60초마다: AVWAP 스나이퍼 감시
    - 보유 중 → 손절/익절 타점 도달 시 즉시 청산
    - 미보유 → VWAP -2% 딥바운스 타점 도달 시 즉시 매수
    """
    app_data = context.job.data
    cfg      = app_data['cfg']
    broker   = app_data['broker']
    strategy = app_data['strategy']
    tx_lock  = app_data['tx_lock']
    chat_id  = context.job.chat_id

    tickers = cfg.get_active_tickers()

    for ticker in tickers:
        avwap_state = cfg.get_avwap_state(ticker)
        if not avwap_state.get("is_enabled", False):
            continue
        if avwap_state.get("is_shutdown", False):
            continue

        try:
            candles_1h = await asyncio.to_thread(broker.get_candlestick, ticker, "1h")
            curr_p     = await asyncio.to_thread(broker.get_current_price, ticker)
            krw, _     = await asyncio.to_thread(broker.get_account_balance)

            avwap_qty = avwap_state.get("qty", 0.0)
            avwap_avg = avwap_state.get("avg_price", 0.0)
            seed      = cfg.get_seed(ticker)
            alloc_krw = seed * 0.3  # AVWAP 전용 예산 30%

            vwap     = strategy.avwap.calc_daily_vwap(candles_1h)
            decision = strategy.avwap.get_decision(
                ticker, curr_p, vwap,
                avwap_avg, avwap_qty, alloc_krw, candles_1h
            )

            if decision['action'] == 'BUY':
                async with tx_lock:
                    result = await asyncio.to_thread(
                        broker.buy_market, ticker, decision['qty'] * curr_p
                    )
                if broker.is_ok(result):
                    import datetime as _dt
                    new_state = {
                        **avwap_state,
                        "qty":        decision['qty'],
                        "avg_price":  curr_p,
                        "entry_time": _dt.datetime.now().strftime("%H:%M:%S"),
                    }
                    cfg.set_avwap_state(ticker, new_state)
                    msg = (
                        f"🎯 <b>[AVWAP 스나이퍼] {ticker} 딥매수!</b>\n"
                        f"▫️ 진입가: <b>{curr_p:,.0f}원</b>\n"
                        f"▫️ 수량: <b>{decision['qty']:.8f}개</b>\n"
                        f"▫️ VWAP: {vwap:,.0f}원\n"
                        f"▫️ 사유: {decision['reason']}"
                    )
                    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')

            elif decision['action'] == 'SELL' and avwap_qty > 0:
                async with tx_lock:
                    result = await asyncio.to_thread(broker.sell_market, ticker, avwap_qty)
                if broker.is_ok(result):
                    realized     = (curr_p - avwap_avg) * avwap_qty
                    realized_pct = (curr_p - avwap_avg) / avwap_avg * 100 if avwap_avg > 0 else 0
                    new_state    = {**avwap_state, "qty": 0.0, "avg_price": 0.0, "entry_time": ""}
                    cfg.set_avwap_state(ticker, new_state)
                    emoji = "💰" if realized >= 0 else "🔴"
                    msg = (
                        f"{emoji} <b>[AVWAP 스나이퍼] {ticker} 청산!</b>\n"
                        f"▫️ 매도가: <b>{curr_p:,.0f}원</b>\n"
                        f"▫️ 실현손익: <b>{realized:+,.0f}원 ({realized_pct:+.2f}%)</b>\n"
                        f"▫️ 사유: {decision['reason']}"
                    )
                    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')

            elif decision['action'] == 'SHUTDOWN':
                new_state = {**avwap_state, "is_shutdown": True}
                cfg.set_avwap_state(ticker, new_state)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⛔ <b>[AVWAP {ticker}] {decision['reason']}</b>",
                    parse_mode='HTML'
                )

        except Exception as e:
            logging.error(f"❌ [{ticker}] 스나이퍼 감시 에러: {e}")
