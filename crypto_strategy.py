# ==========================================================
# [crypto_strategy.py] - 🌟 크립토 전략 연산 엔진 🌟
# ✅ 라오어 무한매수법 완전 구현:
#    - 진행도(T) 산출
#    - 평단매수 / 별값매수 / 별값매도 타점
#    - 좁줍(분할 지정가) 플랜
#    - 새출발 / 전반전 / 후반전 상태 구분
#    - 목표 수익률 달성 시 전량 시장가 익절
# ✅ AVWAP 스나이퍼 유지
# ✅ 변동성 스캔 유지
# ==========================================================

import math
import logging
import datetime
import pytz
import requests


# ─────────────────────────────────────────────────────────
# 수학 유틸 (모듈 전역)
# ─────────────────────────────────────────────────────────
class BithumbBrokerUtils:
    @staticmethod
    def calc_qty(krw_amount: float, price: float, precision: int = 8) -> float:
        if price <= 0:
            return 0.0
        raw = krw_amount / price
        factor = 10 ** precision
        return math.floor(raw * factor) / factor

    @staticmethod
    def round_price(price: float) -> float:
        """빗썸 가격 단위 처리 (100원 단위 이상은 1원 단위로)"""
        return round(price, 0)


# ─────────────────────────────────────────────────────────
# ✅ 라오어 무한매수법 V14 코어
# ─────────────────────────────────────────────────────────
class CryptoV14Strategy:
    """
    라오어 무한매수법 V14 - 크립토 버전

    핵심 개념:
    - 시드를 N분할하여 매일 1포션씩 매수
    - 진행도(T) = 현재매수횟수 / 총분할수  (예: 0.8638T = 34.55/40)
    - 평단매수: 현재 평단가 이하 지정가 (LOC)
    - 별값매수: 전일 고가 기준 추가 매수 타점
    - 별값매도: 목표가(평단 × (1 + target%)) 도달 시 전량 매도
    - 좁줍: 분할 지정가 하락 매수 (5개 타점)
    - 새출발: qty=0 첫 진입
    - 전반전: 목표가 미달성 보유 중 추가매수 가능 상태
    - 후반전: 포션이 부족하거나 KRW 부족, 목표가 대기 상태
    """

    def get_plan(self, ticker: str, current_price: float,
                 avg_price: float, qty: float,
                 available_krw: float, seed: float,
                 split_count: float, target_pct: float,
                 daily_high: float = 0.0, daily_low: float = 0.0,
                 is_simulation: bool = False) -> dict:
        """
        무한매수법 전체 지시서 생성.

        반환:
        {
          'state':         '새출발' | '전반전' | '후반전',
          'progress_t':    float,          # 진행도 (예: 0.8638)
          'progress_n':    float,          # 현재 투자 포션 수
          'action':        'BUY'|'SELL'|'HOLD',

          # 매수 플랜
          'avg_buy_price':   float,        # 평단매수 타점
          'avg_buy_qty':     float,
          'star_buy_price':  float,        # 별값매수 타점
          'star_buy_qty':    float,
          'one_portion_krw': float,        # 1포션 금액

          # 매도 플랜
          'star_sell_price': float,        # 별값매도(목표가)
          'star_sell_qty':   float,
          'target_sell_price': float,      # 최종 익절 목표가

          # 좁줍 플랜 (5개 타점)
          'joob_joob': [
            {'price': float, 'qty': float, 'drop_pct': float},
            ...
          ],

          'reason': str,
        }
        """
        if split_count <= 0:
            split_count = 20.0
        if seed <= 0:
            seed = 500_000.0

        one_portion = seed / split_count

        # ── 진행도 계산 ──────────────────────────────────────
        total_invested = qty * avg_price if qty > 0 and avg_price > 0 else 0.0
        n_portions = total_invested / one_portion if one_portion > 0 else 0.0
        progress_t = n_portions / split_count   # 0.0 ~ 1.0

        # ── 목표가 계산 ──────────────────────────────────────
        target_sell_price = 0.0
        star_sell_price   = 0.0
        if qty > 0 and avg_price > 0:
            target_sell_price = BithumbBrokerUtils.round_price(avg_price * (1 + target_pct / 100.0))
            # 별값매도 = 목표가 (라오어: 전일 고가 × 1.005 또는 목표가 중 낮은 것)
            if daily_high > 0:
                star_sell_price = BithumbBrokerUtils.round_price(
                    min(target_sell_price, daily_high * 1.005)
                )
            else:
                star_sell_price = target_sell_price

        # ── 익절 조건 체크 ───────────────────────────────────
        if qty > 0 and avg_price > 0 and current_price >= target_sell_price:
            curr_ret = (current_price - avg_price) / avg_price * 100.0
            return self._make_sell_plan(
                state='전반전' if progress_t < 0.5 else '후반전',
                progress_t=progress_t,
                progress_n=n_portions,
                current_price=current_price,
                qty=qty,
                avg_price=avg_price,
                target_sell_price=target_sell_price,
                star_sell_price=star_sell_price,
                reason=f'목표 수익률 달성 ({curr_ret:.2f}%)',
                one_portion=one_portion,
            )

        # ── 매수 타점 계산 ───────────────────────────────────
        # 평단매수: 현재 평단가 이하 지정가 (평단가 × 0.999)
        if avg_price > 0:
            avg_buy_price = BithumbBrokerUtils.round_price(avg_price * 0.999)
        else:
            # 새출발: 현재가 × 0.999 (소폭 아래 지정가)
            avg_buy_price = BithumbBrokerUtils.round_price(current_price * 0.999)

        avg_buy_qty = BithumbBrokerUtils.calc_qty(one_portion, avg_buy_price)

        # 별값매수: 전일 고가 × 1.001 이상 돌파 시 모멘텀 추가 매수
        star_buy_price = 0.0
        star_buy_qty   = 0.0
        if daily_high > 0 and avg_price > 0:
            star_buy_price = BithumbBrokerUtils.round_price(daily_high * 1.001)
            # 별값매수는 2포션
            star_buy_qty = BithumbBrokerUtils.calc_qty(one_portion * 2, star_buy_price)

        # ── 좁줍 (분할 지정가 하락 5개 타점) ──────────────────
        # 현재가 또는 평단가 기준으로 3%씩 하락하는 5개 타점
        base_price = avg_price if avg_price > 0 else current_price
        joob_joob = []
        for i in range(1, 6):
            drop_pct    = i * 3.0  # 3%, 6%, 9%, 12%, 15%
            jj_price    = BithumbBrokerUtils.round_price(base_price * (1 - drop_pct / 100.0))
            jj_qty      = BithumbBrokerUtils.calc_qty(one_portion, jj_price)
            joob_joob.append({
                "price":    jj_price,
                "qty":      jj_qty,
                "drop_pct": drop_pct,
            })

        # ── 상태 판별 ────────────────────────────────────────
        if qty == 0 or avg_price == 0:
            state = '새출발'
        elif progress_t < 0.5:
            state = '전반전'
        else:
            state = '후반전'

        # ── KRW 부족 체크 ────────────────────────────────────
        if available_krw < one_portion * 0.9:
            return {
                'state':            state,
                'progress_t':       progress_t,
                'progress_n':       n_portions,
                'action':           'HOLD',
                'avg_buy_price':    avg_buy_price,
                'avg_buy_qty':      0.0,
                'star_buy_price':   star_buy_price,
                'star_buy_qty':     0.0,
                'star_sell_price':  star_sell_price,
                'star_sell_qty':    qty,
                'target_sell_price': target_sell_price,
                'one_portion_krw':  one_portion,
                'joob_joob':        joob_joob,
                'reason':           f'KRW 부족 ({available_krw:,.0f}원 < {one_portion:,.0f}원)',
            }

        return {
            'state':            state,
            'progress_t':       progress_t,
            'progress_n':       n_portions,
            'action':           'BUY',
            'avg_buy_price':    avg_buy_price,
            'avg_buy_qty':      avg_buy_qty,
            'star_buy_price':   star_buy_price,
            'star_buy_qty':     star_buy_qty,
            'star_sell_price':  star_sell_price,
            'star_sell_qty':    qty,
            'target_sell_price': target_sell_price,
            'one_portion_krw':  one_portion,
            'joob_joob':        joob_joob,
            'reason':           f'분할 매수 타점 ({avg_buy_price:,.0f}원)',
        }

    def _make_sell_plan(self, state, progress_t, progress_n, current_price, qty,
                        avg_price, target_sell_price, star_sell_price, reason, one_portion):
        return {
            'state':            state,
            'progress_t':       progress_t,
            'progress_n':       progress_n,
            'action':           'SELL',
            'avg_buy_price':    0.0,
            'avg_buy_qty':      0.0,
            'star_buy_price':   0.0,
            'star_buy_qty':     0.0,
            'star_sell_price':  star_sell_price,
            'star_sell_qty':    qty,
            'target_sell_price': target_sell_price,
            'one_portion_krw':  one_portion,
            'joob_joob':        [],
            'reason':           reason,
        }


# ─────────────────────────────────────────────────────────
# AVWAP 스나이퍼 (기존 유지)
# ─────────────────────────────────────────────────────────
class CryptoAvwapSniper:
    """
    AVWAP 스나이퍼 - 크립토 버전
    24시간 VWAP 기반 딥매수(−2%) 및 스퀴즈 익절(+3%)
    """

    def __init__(self):
        self.dip_buy_pct   = 0.020
        self.target_pct    = 0.030
        self.stop_loss_pct = 0.030

    def calc_daily_vwap(self, candles: list) -> float:
        if not candles:
            return 0.0
        kst = pytz.timezone('Asia/Seoul')
        now_kst = datetime.datetime.now(kst)
        today_midnight = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
        today_ts = int(today_midnight.timestamp() * 1000)

        cum_vol = 0.0
        cum_vol_price = 0.0
        for c in candles:
            if c.get("time", 0) < today_ts:
                continue
            tp = (c["high"] + c["low"] + c["close"]) / 3.0
            v  = c["volume"]
            cum_vol += v
            cum_vol_price += tp * v

        if cum_vol <= 0:
            return 0.0
        return cum_vol_price / cum_vol

    def get_decision(self, ticker, current_price, vwap, avg_price, qty, alloc_krw, candles):
        if vwap <= 0:
            vwap = self.calc_daily_vwap(candles)
        if vwap <= 0:
            return {'action': 'WAIT', 'qty': 0, 'price': 0, 'reason': 'VWAP 산출 불가', 'vwap': 0}

        if qty > 0 and avg_price > 0:
            curr_ret = (current_price - avg_price) / avg_price

            if curr_ret <= -self.stop_loss_pct:
                return {
                    'action': 'SELL', 'qty': qty, 'price': current_price,
                    'reason': f'HARD_STOP ({curr_ret*100:.2f}%)', 'vwap': vwap
                }

            if current_price >= vwap * (1 + self.target_pct):
                return {
                    'action': 'SELL', 'qty': qty, 'price': current_price,
                    'reason': f'SQUEEZE_TARGET (VWAP+{self.target_pct*100:.0f}%)', 'vwap': vwap
                }

            return {'action': 'HOLD', 'qty': qty, 'price': current_price, 'reason': '보유 관망', 'vwap': vwap}

        if current_price <= vwap * (1 - self.dip_buy_pct):
            buy_qty = BithumbBrokerUtils.calc_qty(alloc_krw, current_price)
            if buy_qty > 0:
                return {
                    'action': 'BUY', 'qty': buy_qty, 'price': current_price,
                    'reason': f'VWAP_BOUNCE (VWAP−{self.dip_buy_pct*100:.0f}%)', 'vwap': vwap
                }
            else:
                return {'action': 'WAIT', 'qty': 0, 'price': 0, 'reason': 'KRW 부족', 'vwap': vwap}

        return {'action': 'WAIT', 'qty': 0, 'price': 0, 'reason': '타점 대기', 'vwap': vwap}


# ─────────────────────────────────────────────────────────
# 변동성 엔진 (기존 유지 + 일봉 고저가 추출 추가)
# ─────────────────────────────────────────────────────────
class CryptoVolatilityEngine:
    """공포탐욕지수 + HV 기반 변동성 스캔"""

    def get_fear_greed_index(self) -> dict:
        try:
            res = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5)
            data = res.json()["data"][0]
            return {
                "value":          int(data["value"]),
                "classification": data["value_classification"],
            }
        except Exception as e:
            logging.error(f"❌ [VolEngine] 공포탐욕지수 조회 실패: {e}")
            return {"value": 50, "classification": "Neutral"}

    def calc_hv(self, candles: list, period: int = 20) -> float:
        if len(candles) < period + 1:
            return 0.0
        closes = [c["close"] for c in candles]
        log_rets = [math.log(closes[i] / closes[i-1]) for i in range(1, len(closes))]
        recent = log_rets[-period:]
        mean = sum(recent) / len(recent)
        variance = sum((r - mean) ** 2 for r in recent) / len(recent)
        hv_daily = math.sqrt(variance)
        return round(hv_daily * math.sqrt(365) * 100, 2)

    def get_daily_high_low(self, candles: list) -> tuple:
        """당일 캔들에서 고가/저가 추출"""
        if not candles:
            return 0.0, 0.0
        kst = pytz.timezone('Asia/Seoul')
        now_kst = datetime.datetime.now(kst)
        today_midnight = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
        today_ts = int(today_midnight.timestamp() * 1000)

        today_candles = [c for c in candles if c.get("time", 0) >= today_ts]
        if not today_candles:
            # 당일 데이터 없으면 가장 최근 캔들 사용
            today_candles = candles[-1:]

        daily_high = max(c["high"] for c in today_candles)
        daily_low  = min(c["low"]  for c in today_candles)
        return daily_high, daily_low

    def get_weight(self, ticker: str, candles_daily: list) -> float:
        fg = self.get_fear_greed_index()
        fg_val = fg["value"]

        if fg_val <= 25:
            return 1.3
        elif fg_val <= 45:
            return 1.1
        elif fg_val <= 55:
            return 1.0
        elif fg_val <= 75:
            return 0.9
        else:
            return 0.8


# ─────────────────────────────────────────────────────────
# 중앙 라우팅 엔진
# ─────────────────────────────────────────────────────────
class CryptoInfiniteStrategy:
    """모든 전략 플러그인 통합 라우터"""

    def __init__(self, cfg):
        self.cfg        = cfg
        self.v14        = CryptoV14Strategy()
        self.avwap      = CryptoAvwapSniper()
        self.vol_engine = CryptoVolatilityEngine()

    def get_plan(self, ticker: str, current_price: float,
                 available_krw: float, candles_1h: list = None) -> dict:
        """
        전략 플랜 생성.
        candles_1h: 1시간봉 데이터 (당일 고저가 추출용)
        """
        version  = self.cfg.get_version(ticker)
        position = self.cfg.get_position(ticker)
        qty      = position["qty"]
        avg_price = position["avg"]
        seed     = self.cfg.get_seed(ticker)
        split    = self.cfg.get_split_count(ticker)
        target   = self.cfg.get_target_profit(ticker)

        # 당일 고가/저가
        daily_high, daily_low = 0.0, 0.0
        if candles_1h:
            daily_high, daily_low = self.vol_engine.get_daily_high_low(candles_1h)

        if version in ("V14", "CRYPTO_V14"):
            return self.v14.get_plan(
                ticker=ticker,
                current_price=current_price,
                avg_price=avg_price,
                qty=qty,
                available_krw=available_krw,
                seed=seed,
                split_count=split,
                target_pct=target,
                daily_high=daily_high,
                daily_low=daily_low,
            )

        if version == "V_AVWAP":
            avwap_state = self.cfg.get_avwap_state(ticker)
            avwap_qty   = avwap_state.get("qty", 0.0)
            avwap_avg   = avwap_state.get("avg_price", 0.0)
            vwap = self.avwap.calc_daily_vwap(candles_1h or [])
            alloc = seed * 0.3

            return self.avwap.get_decision(
                ticker=ticker,
                current_price=current_price,
                vwap=vwap,
                avg_price=avwap_avg,
                qty=avwap_qty,
                alloc_krw=alloc,
                candles=candles_1h or [],
            )

        # fallback
        return self.v14.get_plan(
            ticker=ticker,
            current_price=current_price,
            avg_price=avg_price,
            qty=qty,
            available_krw=available_krw,
            seed=seed,
            split_count=split,
            target_pct=target,
            daily_high=daily_high,
            daily_low=daily_low,
        )

    def scan_volatility(self, ticker: str, candles_daily: list) -> dict:
        fg = self.vol_engine.get_fear_greed_index()
        hv = self.vol_engine.calc_hv(candles_daily)
        wt = self.vol_engine.get_weight(ticker, candles_daily)
        return {"fear_greed": fg, "hv": hv, "weight": wt}
