# ==========================================================
# [crypto_scheduler.py] - 🌟 크립토 스케줄러 🌟
# 💡 원본 scheduler_core.py + scheduler_trade.py 통합 포팅
# 💡 24/7 코인 시장: 주식 장중/장외 구분 없이 24시간 상시 작동
# 🚨 [V1.1 패치] BUY_MARKET / BUY_LIMIT 분기 처리 수술
# 🚨 [V1.1 패치] 코인별 소수점 정밀도(precision) 표시 수술
# ==========================================================

import logging
import datetime
import asyncio
import glob
import os
import time

from crypto_strategy import floor_qty, get_precision


def _fmt_qty(qty: float, ticker: str) -> str:
    """코인 정밀도에 맞는 수량 포맷 문자열 반환"""
    p = get_precision(ticker)
    return f"{qty:.{p}f}"


# ─────────────────────────────────────────────────────────
# 🧹 자정 청소
# ─────────────────────────────────────────────────────────
async def scheduled_self_cleaning(context):
    """7일 초과 로그/백업 파일 자동 삭제"""
    try:
        now_ts     = time.time()
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
    """빗썸 API 연결 상태 확인 (정기 헬스체크)"""
    try:
        broker = context.job.data['broker']
        krw    = await asyncio.to_thread(broker.get_krw_balance)
        logging.info(f"🔑 [API 헬스체크] KRW 잔고: {krw:,.0f}원 (정상)")
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
        "▫️ 오늘도 칼같이 실행합니다 🚀"
    )
    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')
    logging.info("🔓 [일일 초기화] 잠금 해제 완료")


# ─────────────────────────────────────────────────────────
# 📈 변동성 스캔 (10:00 KST)
# ─────────────────────────────────────────────────────────
async def scheduled_volatility_scan(context):
    """공포탐욕지수 + HV 기반 일일 브리핑"""
    app_data = context.job.data
    cfg      = app_data['cfg']
    broker   = app_data['broker']
    strategy = app_data['strategy']
    chat_id  = context.job.chat_id

    tickers = cfg.get_active_tickers()
    lines   = []

    for ticker in tickers:
        try:
            candles_daily = await asyncio.to_thread(
                broker.get_candlestick, ticker, "24h"
            )
            vol_data = await asyncio.to_thread(
                strategy.scan_volatility, ticker, candles_daily
            )
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

    msg = "📊 <b>[10:00 변동성 브리핑]</b>\n" + "\n".join(lines)
    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')


# ─────────────────────────────────────────────────────────
# 🎯 정규 매매 (10:05 KST)
# ─────────────────────────────────────────────────────────
async def scheduled_regular_trade(context):
    """
    10:05 KST: 무한매수법 플랜 연산 후 매수 실행.

    [action 분기]
    BUY_MARKET → 즉시 시장가 매수 (첫 매수 or 급락 시)
    BUY_LIMIT  → 현재가 -3% 타점에 지정가 등록 (추가 매수 대기)
    SELL       → 목표 수익률 도달 시 시장가 전량 익절
    HOLD       → 조건 미충족 (KRW 부족 or 최소 수량 미달)
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
                curr_p = await asyncio.to_thread(broker.get_current_price, ticker)
                krw, _ = await asyncio.to_thread(broker.get_account_balance)

            if curr_p <= 0:
                logging.warning(f"[{ticker}] 현재가 조회 실패 - 스킵")
                continue

            plan   = strategy.get_plan(ticker, curr_p, krw)
            action = plan.get('action', 'HOLD')

            # ── 시장가 즉시 매수 ────────────────────────────────
            if action == 'BUY_MARKET' and plan.get('buy_qty', 0) > 0:
                async with tx_lock:
                    result = await asyncio.to_thread(
                        broker.buy_market, ticker, plan['buy_krw']
                    )
                if result.get("status") == "0000":
                    cfg.set_trade_lock(ticker, True)
                    cfg.add_ledger(
                        ticker, "BUY",
                        plan['buy_qty'], curr_p,
                        note="정규 매매 시장가 매수"
                    )
                    qty_str = _fmt_qty(plan['buy_qty'], ticker)
                    msg = (
                        f"📥 <b>[{ticker}] 시장가 매수 완료</b>\n"
                        f"▫️ 진입가: <b>{curr_p:,.0f}원</b>\n"
                        f"▫️ 수량: <b>{qty_str} {ticker}</b>\n"
                        f"▫️ 투입: {plan['buy_krw']:,.0f}원\n"
                        f"▫️ 사유: {plan.get('reason', '')}\n"
                        f"▫️ 다음 추가매수: <b>{plan.get('next_buy_at', 0):,.0f}원</b> (현재가 −3%)"
                    )
                    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')
                else:
                    err = result.get('message', '알 수 없는 오류')
                    logging.error(f"❌ [{ticker}] 시장가 매수 실패: {err}")
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"❌ <b>[{ticker}] 시장가 매수 실패:</b> {err}",
                        parse_mode='HTML'
                    )

            # ── 지정가 추가 매수 등록 ────────────────────────────
            elif action == 'BUY_LIMIT' and plan.get('buy_qty', 0) > 0:
                async with tx_lock:
                    result = await asyncio.to_thread(
                        broker.buy_limit,
                        ticker,
                        plan['buy_price'],
                        plan['buy_qty']
                    )
                if result.get("status") == "0000":
                    qty_str  = _fmt_qty(plan['buy_qty'], ticker)
                    pos      = cfg.get_position(ticker)
                    curr_ret = (curr_p - pos['avg']) / pos['avg'] * 100 if pos['avg'] > 0 else 0
                    msg = (
                        f"📋 <b>[{ticker}] 추가매수 지정가 등록</b>\n"
                        f"▫️ 타점: <b>{plan['buy_price']:,.0f}원</b> (현재가 −3%)\n"
                        f"▫️ 수량: <b>{qty_str} {ticker}</b>\n"
                        f"▫️ 현재가: {curr_p:,.0f}원 | 현재 수익률: {curr_ret:+.2f}%\n"
                        f"▫️ 익절 목표: {plan.get('sell_price', 0):,.0f}원"
                    )
                    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')
                else:
                    err = result.get('message', '알 수 없는 오류')
                    logging.error(f"❌ [{ticker}] 지정가 등록 실패: {err}")

            # ── 익절 매도 ────────────────────────────────────────
            elif action == 'SELL' and plan.get('sell_qty', 0) > 0:
                position = cfg.get_position(ticker)
                async with tx_lock:
                    result = await asyncio.to_thread(
                        broker.sell_market, ticker, plan['sell_qty']
                    )
                if result.get("status") == "0000":
                    realized     = (curr_p - position['avg']) * plan['sell_qty']
                    realized_pct = (curr_p - position['avg']) / position['avg'] * 100 if position['avg'] > 0 else 0
                    cfg.add_ledger(
                        ticker, "SELL",
                        plan['sell_qty'], curr_p,
                        note="목표 익절 자동 매도"
                    )
                    cfg.add_history(ticker, realized, realized_pct, note="목표 수익률 달성")
                    cfg.set_trade_lock(ticker, False)
                    qty_str = _fmt_qty(plan['sell_qty'], ticker)
                    msg = (
                        f"💰 <b>[{ticker}] 목표 익절 완료!</b>\n"
                        f"▫️ 매도가: <b>{curr_p:,.0f}원</b>\n"
                        f"▫️ 수량: {qty_str} {ticker}\n"
                        f"▫️ 실현손익: <b>{realized:+,.0f}원 ({realized_pct:+.2f}%)</b>"
                    )
                    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')

            # ── 대기 (조용히 로그만) ─────────────────────────────
            else:
                logging.info(f"[{ticker}] HOLD - {plan.get('reason', '')}")

        except Exception as e:
            logging.error(f"❌ [{ticker}] 정규 매매 에러: {e}")


# ─────────────────────────────────────────────────────────
# 🔫 스나이퍼 감시 (60초 반복)
# ─────────────────────────────────────────────────────────
async def scheduled_sniper_monitor(context):
    """
    60초마다: AVWAP 스나이퍼 감시
    - 보유 중 → 손절/익절 타점 도달 시 즉시 시장가 청산
    - 미보유 → VWAP −2% 딥바운스 타점 도달 시 즉시 시장가 매수
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

            avwap_qty  = float(avwap_state.get("qty", 0.0))
            avwap_avg  = float(avwap_state.get("avg_price", 0.0))
            seed       = cfg.get_seed(ticker)
            alloc_krw  = seed * 0.3  # AVWAP 전용 예산 30%

            vwap     = strategy.avwap.calc_daily_vwap(candles_1h)
            decision = strategy.avwap.get_decision(
                ticker, curr_p, vwap,
                avwap_avg, avwap_qty, alloc_krw, candles_1h
            )

            if decision['action'] == 'BUY' and decision.get('qty', 0) > 0:
                buy_qty    = floor_qty(decision['qty'], ticker)
                if buy_qty <= 0:
                    continue
                krw_needed = buy_qty * curr_p
                async with tx_lock:
                    result = await asyncio.to_thread(
                        broker.buy_market, ticker, krw_needed
                    )
                if result.get("status") == "0000":
                    new_state = {
                        **avwap_state,
                        "qty":         buy_qty,
                        "avg_price":   curr_p,
                        "entry_time":  datetime.datetime.now().strftime("%H:%M:%S"),
                        "is_shutdown": False,
                    }
                    cfg.set_avwap_state(ticker, new_state)
                    qty_str = _fmt_qty(buy_qty, ticker)
                    msg = (
                        f"🎯 <b>[AVWAP 스나이퍼] {ticker} 딥매수!</b>\n"
                        f"▫️ 진입가: <b>{curr_p:,.0f}원</b>\n"
                        f"▫️ 수량: <b>{qty_str} {ticker}</b>\n"
                        f"▫️ VWAP: {vwap:,.0f}원 | 이격: {(curr_p/vwap-1)*100:.2f}%\n"
                        f"▫️ 사유: {decision['reason']}"
                    )
                    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')

            elif decision['action'] == 'SELL' and avwap_qty > 0:
                sell_qty = floor_qty(avwap_qty, ticker)
                async with tx_lock:
                    result = await asyncio.to_thread(broker.sell_market, ticker, sell_qty)
                if result.get("status") == "0000":
                    realized     = (curr_p - avwap_avg) * sell_qty
                    realized_pct = (curr_p - avwap_avg) / avwap_avg * 100 if avwap_avg > 0 else 0
                    new_state    = {**avwap_state, "qty": 0.0, "avg_price": 0.0, "entry_time": ""}
                    cfg.set_avwap_state(ticker, new_state)
                    qty_str = _fmt_qty(sell_qty, ticker)
                    emoji   = "💰" if realized >= 0 else "🔴"
                    msg = (
                        f"{emoji} <b>[AVWAP 스나이퍼] {ticker} 청산!</b>\n"
                        f"▫️ 매도가: <b>{curr_p:,.0f}원</b>\n"
                        f"▫️ 수량: {qty_str} {ticker}\n"
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
