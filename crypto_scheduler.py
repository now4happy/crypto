# ==========================================================
# [crypto_scheduler.py] - 크립토 스케줄러
# ✅ 매일 06:05 KST 1회 매수 실행
#    - 새출발(qty=0): 시장가 즉시 매수 (무조건 체결)
#    - 보유 중(qty>0): 전날 미체결 취소 후 지정가 매수
# ✅ 60초마다 목표가 감시 → 즉시 시장가 익절
# ✅ 하루 1번 매수 → 다음날 그 값으로 다음 타점 계산
# ==========================================================

import logging
import datetime
import asyncio
import glob
import os
import time
import pytz


# ─────────────────────────────────────────────────────────
# 🧹 자정 청소 (03:00 KST)
# ─────────────────────────────────────────────────────────
async def scheduled_self_cleaning(context):
    """7일 초과 로그/백업 파일 자동 삭제"""
    try:
        now_ts     = time.time()
        seven_days = 7 * 24 * 3600
        base_dir   = os.path.dirname(os.path.abspath(__file__))
        for pattern in [
            os.path.join(base_dir, "logs/*.log"),
            os.path.join(base_dir, "data/*.bak_*"),
        ]:
            for f in glob.glob(pattern):
                if os.path.isfile(f) and os.stat(f).st_mtime < now_ts - seven_days:
                    try:
                        os.remove(f)
                    except Exception:
                        pass
        logging.info("🧹 [자정 청소] 완료")
    except Exception as e:
        logging.error(f"🧹 [자정 청소] 에러: {e}")


# ─────────────────────────────────────────────────────────
# 🔑 API 헬스체크 (6시간마다)
# ─────────────────────────────────────────────────────────
async def scheduled_token_check(context):
    """빗썸 API 연결 상태 + KRW 잔고 확인"""
    try:
        broker  = context.job.data['broker']
        chat_id = context.job.chat_id

        krw, holdings = await asyncio.to_thread(broker.get_account_balance)
        hold_str = ", ".join([
            f"{coin}: {info['qty']:.6f}개"
            for coin, info in holdings.items()
        ]) if holdings else "없음"

        logging.info(f"🔑 [헬스체크] KRW: {krw:,.0f}원 | 보유: {hold_str}")

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
        logging.error(f"❌ [헬스체크] 에러: {e}")


# ─────────────────────────────────────────────────────────
# 🔓 일일 초기화 (06:00 KST) - 매매 직전 잠금 해제
# ─────────────────────────────────────────────────────────
async def scheduled_force_reset(context):
    """매일 06:00 KST: 거래 잠금 해제"""
    cfg     = context.job.data['cfg']
    chat_id = context.job.chat_id

    cfg.reset_locks()
    logging.info("🔓 [06:00] 거래 잠금 해제 완료")


# ─────────────────────────────────────────────────────────
# 📊 변동성 브리핑 (06:00 KST)
# ─────────────────────────────────────────────────────────
async def scheduled_volatility_scan(context):
    """공포탐욕지수 + HV 기반 일일 브리핑"""
    app_data = context.job.data
    cfg      = app_data['cfg']
    broker   = app_data['broker']
    strategy = app_data['strategy']
    chat_id  = context.job.chat_id

    tickers = cfg.get_active_tickers()
    lines   = ["📊 <b>[06:00 변동성 브리핑]</b>\n"]

    for ticker in tickers:
        try:
            candles_daily = await asyncio.to_thread(broker.get_candlestick, ticker, "24h")
            vol_data      = await asyncio.to_thread(strategy.scan_volatility, ticker, candles_daily)
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
# ✅ 핵심: 일일 매수 실행 (06:05 KST)
#
# [새출발] qty = 0 → 시장가 즉시 매수 (무조건 체결)
# [보유 중] qty > 0 → 미체결 취소 후 지정가 매수
# ─────────────────────────────────────────────────────────
async def scheduled_regular_trade(context):
    """
    매일 06:05 KST: 하루 1회 매수 실행
    - 새출발(첫 주문): 시장가로 즉시 체결
    - 보유 중(2회차~): 전날 미체결 취소 후 지정가 등록
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
            logging.info(f"[{ticker}] 거래 잠금 상태 - 오늘 이미 매수 완료")
            continue

        try:
            async with tx_lock:
                curr_p     = await asyncio.to_thread(broker.get_current_price, ticker)
                krw, _     = await asyncio.to_thread(broker.get_account_balance)
                candles_1h = await asyncio.to_thread(broker.get_candlestick, ticker, "1h")

            if curr_p <= 0:
                logging.error(f"❌ [{ticker}] 현재가 조회 실패")
                continue

            pos       = cfg.get_position(ticker)
            qty       = pos.get("qty", 0.0)
            avg       = pos.get("avg", 0.0)
            plan      = strategy.get_plan(ticker, curr_p, krw, candles_1h)
            action    = plan.get('action', 'HOLD')
            seed      = cfg.get_seed(ticker)
            split     = cfg.get_split_count(ticker)
            one_portion = seed / split

            # ── 익절 조건 먼저 체크 ──────────────────────────
            if action == 'SELL':
                sell_qty = plan.get('star_sell_qty', qty)
                if sell_qty <= 0:
                    continue

                async with tx_lock:
                    result = await asyncio.to_thread(broker.sell_market, ticker, sell_qty)

                if broker.is_ok(result):
                    realized     = (curr_p - avg) * sell_qty if avg > 0 else 0
                    realized_pct = (curr_p - avg) / avg * 100 if avg > 0 else 0
                    cfg.add_ledger(ticker, "SELL", sell_qty, curr_p, note="목표 익절 자동 매도")
                    cfg.add_history(ticker, realized, realized_pct, note="무한매수법 목표 수익률 달성")
                    cfg.set_trade_lock(ticker, False)
                    msg = (
                        f"💰 <b>[{ticker}] 목표 익절!</b>\n"
                        f"▫️ 매도가: <b>{curr_p:,.0f}원</b>\n"
                        f"▫️ 실현손익: <b>{realized:+,.0f}원 ({realized_pct:+.2f}%)</b>\n"
                        f"✨ 새출발 준비 완료!"
                    )
                    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')
                continue

            # ── HOLD (KRW 부족 등) ───────────────────────────
            if action == 'HOLD':
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"⏸ <b>[{ticker}] 오늘 매수 대기</b>\n"
                        f"▫️ 사유: {plan.get('reason', '')}\n"
                        f"▫️ KRW 잔고: {krw:,.0f}원 | 1포션: {one_portion:,.0f}원"
                    ),
                    parse_mode='HTML'
                )
                continue

            # ── 새출발: qty=0 → 시장가 즉시 매수 ────────────
            if qty == 0 or avg == 0:
                if krw < one_portion * 0.9:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            f"⚠️ <b>[{ticker}] 새출발 실패 - KRW 부족</b>\n"
                            f"▫️ 필요: {one_portion:,.0f}원 | 보유: {krw:,.0f}원"
                        ),
                        parse_mode='HTML'
                    )
                    continue

                # 시장가 매수 (무조건 즉시 체결)
                async with tx_lock:
                    result = await asyncio.to_thread(
                        broker.buy_market, ticker, one_portion
                    )

                if broker.is_ok(result):
                    # 체결 후 실제 평단가 확인 (시장가라 curr_p 기준)
                    buy_qty = round(one_portion / curr_p, 8)
                    cfg.add_ledger(
                        ticker, "BUY", buy_qty, curr_p,
                        note=f"새출발 시장가 매수 (1포션: {one_portion:,.0f}원)"
                    )
                    cfg.set_trade_lock(ticker, True)
                    msg = (
                        f"🚀 <b>[{ticker}] 새출발 매수 완료!</b>\n"
                        f"▫️ 체결가: <b>약 {curr_p:,.0f}원</b> (시장가)\n"
                        f"▫️ 금액: <b>{one_portion:,.0f}원</b>\n"
                        f"▫️ 예상 수량: {buy_qty:.8f}개\n"
                        f"▫️ 목표가: {curr_p * (1 + cfg.get_target_profit(ticker)/100):,.0f}원\n"
                        f"📊 내일부터 무한매수법 진행!"
                    )
                    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')
                    logging.info(f"🚀 [{ticker}] 새출발 시장가 매수: {one_portion:,.0f}원")
                else:
                    logging.error(f"❌ [{ticker}] 새출발 매수 실패: {result}")

            # ── 보유 중: 전날 미체결 취소 후 지정가 등록 ─────
            else:
                # 1. 미체결 주문 전부 취소
                try:
                    open_orders = await asyncio.to_thread(broker.get_open_orders, ticker)
                    cancelled = 0
                    for order in open_orders:
                        order_id = order.get("uuid") or order.get("order_id", "")
                        if order_id:
                            await asyncio.to_thread(broker.cancel_order, order_id, ticker)
                            cancelled += 1
                    if cancelled > 0:
                        logging.info(f"🗑️ [{ticker}] 미체결 주문 {cancelled}건 취소 완료")
                except Exception as e:
                    logging.warning(f"⚠️ [{ticker}] 미체결 취소 실패 (무시하고 진행): {e}")

                # 2. 지정가 매수 등록 (평단 × 0.999)
                avg_buy_price = plan.get('avg_buy_price', 0)
                avg_buy_qty   = plan.get('avg_buy_qty', 0)

                if avg_buy_price <= 0 or avg_buy_qty <= 0:
                    logging.warning(f"⚠️ [{ticker}] 매수 타점 계산 실패")
                    continue

                async with tx_lock:
                    result = await asyncio.to_thread(
                        broker.buy_limit, ticker, avg_buy_price, avg_buy_qty
                    )

                if broker.is_ok(result):
                    cfg.set_trade_lock(ticker, True)
                    cfg.add_ledger(
                        ticker, "BUY", avg_buy_qty, avg_buy_price,
                        note=f"무한매수 지정가 ({plan.get('progress_t', 0):.4f}T)"
                    )
                    target_price = plan.get('target_sell_price', 0)
                    msg = (
                        f"📥 <b>[{ticker}] 지정가 매수 등록</b>\n"
                        f"▫️ 타점: <b>{avg_buy_price:,.0f}원</b>\n"
                        f"▫️ 수량: <b>{avg_buy_qty:.8f}개</b>\n"
                        f"▫️ 진행도: {plan.get('progress_t', 0):.4f}T / "
                        f"{cfg.get_split_count(ticker):.0f}분할\n"
                        f"▫️ 목표 익절가: {target_price:,.0f}원\n"
                        f"▫️ 상태: {plan.get('state', '')}"
                    )
                    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')
                    logging.info(f"📥 [{ticker}] 지정가 매수 등록: {avg_buy_price:,.0f}원")
                else:
                    logging.error(f"❌ [{ticker}] 지정가 매수 실패: {result}")

        except Exception as e:
            logging.error(f"❌ [{ticker}] 정규 매매 에러: {e}", exc_info=True)


# ─────────────────────────────────────────────────────────
# ✅ 익절 모니터 - 60초마다 목표가 실시간 체크
# ─────────────────────────────────────────────────────────
async def scheduled_profit_monitor(context):
    """
    60초마다: 목표가 달성 여부 감시
    → 달성 시 즉시 전량 시장가 익절 → 장부 초기화 → 내일 새출발
    """
    app_data = context.job.data
    cfg      = app_data['cfg']
    broker   = app_data['broker']
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

            target_pct   = cfg.get_target_profit(ticker)
            target_price = avg * (1 + target_pct / 100.0)

            curr_p = await asyncio.to_thread(broker.get_current_price, ticker)
            if curr_p <= 0 or curr_p < target_price:
                continue

            # 목표가 달성 → 즉시 전량 시장가 매도
            async with tx_lock:
                result = await asyncio.to_thread(broker.sell_market, ticker, qty)

            if broker.is_ok(result):
                realized     = (curr_p - avg) * qty
                realized_pct = (curr_p - avg) / avg * 100

                cfg.add_ledger(ticker, "SELL", qty, curr_p, note="실시간 목표가 익절")
                cfg.add_history(ticker, realized, realized_pct, note="실시간 익절 모니터")
                cfg.set_trade_lock(ticker, False)   # 잠금 해제 → 내일 새출발

                msg = (
                    f"🎉 <b>[{ticker}] 익절 완료!</b>\n"
                    f"▫️ 체결가: <b>{curr_p:,.0f}원</b>\n"
                    f"▫️ 평단가: {avg:,.0f}원\n"
                    f"▫️ 실현손익: <b>{realized:+,.0f}원 ({realized_pct:+.2f}%)</b>\n"
                    f"▫️ 수량: {qty:.8f}개\n"
                    f"✨ 장부 초기화 완료 — 내일 06:05 새출발!"
                )
                await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')
                logging.info(f"🎉 [{ticker}] 익절: {realized:+,.0f}원 ({realized_pct:+.2f}%)")

        except Exception as e:
            logging.error(f"❌ [{ticker}] 익절 모니터 에러: {e}")


# ─────────────────────────────────────────────────────────
# 🔫 AVWAP 스나이퍼 감시 (60초)
# ─────────────────────────────────────────────────────────
async def scheduled_sniper_monitor(context):
    """60초마다: AVWAP 스나이퍼 감시"""
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
            alloc_krw = seed * 0.3

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
                    cfg.set_avwap_state(ticker, {
                        **avwap_state,
                        "qty":        decision['qty'],
                        "avg_price":  curr_p,
                        "entry_time": _dt.datetime.now().strftime("%H:%M:%S"),
                    })
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            f"🎯 <b>[AVWAP] {ticker} 딥매수!</b>\n"
                            f"▫️ 진입가: <b>{curr_p:,.0f}원</b>\n"
                            f"▫️ 수량: {decision['qty']:.8f}개\n"
                            f"▫️ VWAP: {vwap:,.0f}원"
                        ),
                        parse_mode='HTML'
                    )

            elif decision['action'] == 'SELL' and avwap_qty > 0:
                async with tx_lock:
                    result = await asyncio.to_thread(broker.sell_market, ticker, avwap_qty)
                if broker.is_ok(result):
                    realized     = (curr_p - avwap_avg) * avwap_qty
                    realized_pct = (curr_p - avwap_avg) / avwap_avg * 100 if avwap_avg > 0 else 0
                    cfg.set_avwap_state(ticker, {**avwap_state, "qty": 0.0, "avg_price": 0.0, "entry_time": ""})
                    emoji = "💰" if realized >= 0 else "🔴"
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            f"{emoji} <b>[AVWAP] {ticker} 청산!</b>\n"
                            f"▫️ 매도가: <b>{curr_p:,.0f}원</b>\n"
                            f"▫️ 실현손익: <b>{realized:+,.0f}원 ({realized_pct:+.2f}%)</b>"
                        ),
                        parse_mode='HTML'
                    )

            elif decision['action'] == 'SHUTDOWN':
                cfg.set_avwap_state(ticker, {**avwap_state, "is_shutdown": True})
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⛔ <b>[AVWAP {ticker}] {decision['reason']}</b>",
                    parse_mode='HTML'
                )

        except Exception as e:
            logging.error(f"❌ [{ticker}] 스나이퍼 에러: {e}")
