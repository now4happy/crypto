# ==========================================================
# [crypto_strategy.py] - 🌟 크립토 전략 연산 엔진 🌟
# 💡 무한매수법(V14) + AVWAP 스나이퍼를 크립토 24/7 시장에 맞게 재설계
# 💡 핵심 차이점: 주식 장중 시간 제한 없음 → 24시간 실행
# 💡 BTC/ETH 변동성 기반 동적 타점 산출
# 🚨 [V1.1 패치] 첫 매수 타점 현재가 즉시 적용 및 코인별 소수점 정밀도 수술
# 🚨 [V1.1 패치] 추가매수 타점을 평단가 기준 → 현재가 기준으로 교정 (대기 고착 버그 수정)
# ==========================================================

import math
import logging
import datetime
import pytz
import requests


# ─────────────────────────────────────────────────────────────────
# 코인별 주문 정밀도 테이블
# 빗썸 최소 주문 단위: BTC=소수점8, ETH=소수점6, XRP/SOL/ADA=소수점4
# ─────────────────────────────────────────────────────────────────
COIN_PRECISION = {
    "BTC":  8,
    "ETH":  6,
    "XRP":  4,
    "SOL":  4,
    "ADA":  4,
    "DOGE": 4,
    "AVAX": 4,
}

def get_precision(ticker: str) -> int:
    """코인 심볼로 소수점 자릿수 반환. 미등록 코인은 기본 4자리."""
    return COIN_PRECISION.get(ticker.upper().replace("KRW-", ""), 4)

def floor_qty(qty: float, ticker: str) -> float:
    """코인 정밀도에 맞게 수량을 내림(floor) 처리"""
    precision = get_precision(ticker)
    factor = 10 ** precision
    return math.floor(qty * factor) / factor

def round_price(price: float, ticker: str) -> float:
    """
    빗썸 가격 단위 규칙에 맞게 반올림.
    BTC/ETH(고가 코인): 1원 단위
    XRP/ADA 등(저가 코인): 소수점 2자리
    """
    ticker = ticker.upper().replace("KRW-", "")
    if ticker in ("BTC", "ETH", "SOL", "AVAX"):
        return round(price, 0)     # 1원 단위
    else:
        return round(price, 2)     # 소수점 2자리 (저가 코인)


class CryptoV14Strategy:
    """
    무한매수법 V14 코어 - 크립토 버전
    분할 매수 → 목표 수익률 도달 시 전량 익절

    [매수 타점 설계]
    ① 첫 매수(qty=0): 현재가로 즉시 시장가 매수
    ② 추가 매수(qty>0): 현재가 대비 -3% 지점에 지정가 대기
       → 평단가 기준이 아닌 현재가 기준으로 타점 계산
       → 현재가가 이미 타점 이하라면 즉시 시장가 매수
    """

    def get_plan(self, ticker, current_price, avg_price, qty,
                 available_krw, seed, split_count, target_pct,
                 is_simulation=False):
        """
        매수/매도 지시서 생성.
        반환: {
          'action':       'BUY_MARKET' | 'BUY_LIMIT' | 'SELL' | 'HOLD',
          'buy_price':    float,   # 지정가 타점 (BUY_MARKET 시에는 current_price)
          'sell_price':   float,   # 목표 익절 타점
          'buy_krw':      float,   # 1회 투입 원화 금액
          'buy_qty':      float,   # 매수 수량 (소수점 정밀도 적용)
          'sell_qty':     float,   # 매도 수량
          'reason':       str,
          'next_buy_at':  float,   # 다음 추가 매수 예정 타점 (정보 표시용)
        }
        """
        if split_count <= 0:
            split_count = 20
        if seed <= 0:
            seed = 500000.0

        one_portion      = seed / split_count        # 1회 투입 금액
        target_sell_price = avg_price * (1 + target_pct / 100.0) if avg_price > 0 else 0.0

        # ── 익절 조건 ──────────────────────────────────────────
        if qty > 0 and avg_price > 0:
            curr_ret = (current_price - avg_price) / avg_price * 100.0
            if curr_ret >= target_pct:
                return {
                    'action':      'SELL',
                    'sell_price':  current_price,
                    'sell_qty':    qty,
                    'buy_price':   0.0,
                    'buy_krw':     0.0,
                    'buy_qty':     0.0,
                    'sell_qty':    qty,
                    'reason':      f'목표 수익률 달성 ({curr_ret:.2f}%)',
                    'next_buy_at': 0.0,
                }

        # ── KRW 잔고 부족 체크 ─────────────────────────────────
        if available_krw < one_portion * 0.9:
            next_buy_at = round_price(current_price * 0.970, ticker)
            return {
                'action':      'HOLD',
                'buy_price':   next_buy_at,
                'sell_price':  target_sell_price,
                'buy_krw':     0.0,
                'buy_qty':     0.0,
                'sell_qty':    0.0,
                'reason':      f'KRW 부족 ({available_krw:,.0f}원 < {one_portion:,.0f}원)',
                'next_buy_at': next_buy_at,
            }

        # ── 첫 매수: 미보유 상태 → 현재가로 즉시 시장가 매수 ─────
        if qty <= 0 or avg_price <= 0:
            buy_qty = floor_qty(one_portion / current_price, ticker)
            if buy_qty <= 0:
                return {
                    'action':      'HOLD',
                    'buy_price':   current_price,
                    'sell_price':  0.0,
                    'buy_krw':     one_portion,
                    'buy_qty':     0.0,
                    'sell_qty':    0.0,
                    'reason':      f'최소 수량 미달 (1포션={one_portion:,.0f}원 / 현재가={current_price:,.0f}원)',
                    'next_buy_at': current_price,
                }
            return {
                'action':      'BUY_MARKET',   # ← 즉시 시장가 매수
                'buy_price':   current_price,
                'sell_price':  current_price * (1 + target_pct / 100.0),
                'buy_krw':     one_portion,
                'buy_qty':     buy_qty,
                'sell_qty':    0.0,
                'reason':      f'최초 매수 (시장가 즉시 진입)',
                'next_buy_at': round_price(current_price * 0.970, ticker),
            }

        # ── 추가 매수: 현재가 기준 -3% 타점 ─────────────────────
        # 🚨 핵심 수정: 평단가가 아닌 현재가 대비 -3% 타점
        # 이렇게 해야 현재가 아래에서만 추가 매수가 트리거됨
        next_buy_price = round_price(current_price * 0.970, ticker)
        buy_qty        = floor_qty(one_portion / next_buy_price, ticker)

        # 현재가가 이미 추가 매수 타점 이하라면 즉시 시장가 매수
        # (예: 자정에 급락하여 -3% 이상 이미 빠진 경우)
        # current_price * 0.97 = next_buy_price 이므로 current_price <= next_buy_price는 불가
        # 대신 평단가 대비 -3% 이하로 현재가가 떨어진 경우를 급락으로 판단
        if avg_price > 0 and current_price <= avg_price * 0.970:
            buy_qty = floor_qty(one_portion / current_price, ticker)
            return {
                'action':      'BUY_MARKET',
                'buy_price':   current_price,
                'sell_price':  target_sell_price,
                'buy_krw':     one_portion,
                'buy_qty':     buy_qty,
                'sell_qty':    0.0,
                'reason':      f'추가 매수 즉시 진입 (현재가 타점 이하)',
                'next_buy_at': round_price(current_price * 0.970, ticker),
            }

        if buy_qty <= 0:
            return {
                'action':      'HOLD',
                'buy_price':   next_buy_price,
                'sell_price':  target_sell_price,
                'buy_krw':     one_portion,
                'buy_qty':     0.0,
                'sell_qty':    0.0,
                'reason':      f'최소 수량 미달',
                'next_buy_at': next_buy_price,
            }

        return {
            'action':      'BUY_LIMIT',        # ← 타점 지정가 대기
            'buy_price':   next_buy_price,
            'sell_price':  target_sell_price,
            'buy_krw':     one_portion,
            'buy_qty':     buy_qty,
            'sell_qty':    0.0,
            'reason':      f'추가 매수 대기 (현재가 −3% = {next_buy_price:,.0f}원)',
            'next_buy_at': next_buy_price,
        }


class CryptoAvwapSniper:
    """
    AVWAP 스나이퍼 - 크립토 버전
    24시간 VWAP 기반 딥매수(−2%) 및 스퀴즈 익절(+3%) 전술
    코인 시장은 24/7이므로 '당일 00:00 KST ~ 현재' 누적 VWAP 사용
    """

    def __init__(self):
        self.dip_buy_pct  = 0.020   # VWAP 대비 −2% 진입
        self.target_pct   = 0.030   # VWAP 대비 +3% 익절
        self.stop_loss_pct = 0.030  # 진입가 대비 −3% 손절

    def calc_daily_vwap(self, candles: list) -> float:
        """
        당일 00:00 KST 이후 1분봉 기준 누적 VWAP 계산.
        candles: get_candlestick() 결과 (1m 또는 1h)
        """
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
            v = c["volume"]
            cum_vol += v
            cum_vol_price += tp * v

        if cum_vol <= 0:
            return 0.0
        return cum_vol_price / cum_vol

    def get_decision(self, ticker, current_price, vwap, avg_price, qty, alloc_krw, candles):
        """
        AVWAP 스나이퍼 의사결정.
        반환: {'action': str, 'qty': float, 'price': float, 'reason': str, 'vwap': float}
        """
        if vwap <= 0:
            vwap = self.calc_daily_vwap(candles)
        if vwap <= 0:
            return {'action': 'WAIT', 'qty': 0, 'price': 0, 'reason': 'VWAP 산출 불가', 'vwap': 0}

        # ── 보유 중 청산 시퀀스 ──────────────────────────────
        if qty > 0 and avg_price > 0:
            curr_ret = (current_price - avg_price) / avg_price

            # 하드스탑 −3%
            if curr_ret <= -self.stop_loss_pct:
                return {
                    'action': 'SELL', 'qty': qty, 'price': current_price,
                    'reason': f'HARD_STOP ({curr_ret*100:.2f}%)', 'vwap': vwap
                }

            # 스퀴즈 익절: VWAP +3% 이상
            if current_price >= vwap * (1 + self.target_pct):
                return {
                    'action': 'SELL', 'qty': qty, 'price': current_price,
                    'reason': f'SQUEEZE_TARGET (VWAP+{self.target_pct*100:.0f}%)', 'vwap': vwap
                }

            return {'action': 'HOLD', 'qty': qty, 'price': current_price, 'reason': '보유 관망', 'vwap': vwap}

        # ── 신규 진입 시퀀스 ─────────────────────────────────
        # VWAP 대비 −2% 이하 딥매수
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


class CryptoVolatilityEngine:
    """
    크립토 변동성 스캔 - 24/7 HV(역사적 변동성) 기반
    공포지수(Crypto Fear & Greed Index) 병용
    """

    def get_fear_greed_index(self) -> dict:
        """
        Alternative.me의 Crypto Fear & Greed Index 조회
        반환: {'value': int, 'classification': str}
        """
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
        """
        20일 역사적 변동성(HV) 계산.
        candles: 일봉 데이터 list
        """
        if len(candles) < period + 1:
            return 0.0
        import math
        closes = [c["close"] for c in candles]
        log_rets = [math.log(closes[i] / closes[i-1]) for i in range(1, len(closes))]
        recent = log_rets[-period:]
        mean = sum(recent) / len(recent)
        variance = sum((r - mean) ** 2 for r in recent) / len(recent)
        hv_daily = math.sqrt(variance)
        hv_annual = hv_daily * math.sqrt(365) * 100
        return round(hv_annual, 2)

    def get_weight(self, ticker: str, candles_daily: list) -> float:
        """
        공포탐욕지수 + HV 조합으로 매매 강도 가중치 반환.
        가중치 < 1.0 → 공격적 매수 자제 권장
        가중치 > 1.0 → 적극 매수 권장
        """
        fg = self.get_fear_greed_index()
        hv = self.calc_hv(candles_daily)
        fg_val = fg["value"]

        # 공포(0~30) → 기회 → 가중치 높임
        # 탐욕(70~100) → 주의 → 가중치 낮춤
        if fg_val <= 25:
            fg_weight = 1.3
        elif fg_val <= 45:
            fg_weight = 1.1
        elif fg_val <= 55:
            fg_weight = 1.0
        elif fg_val <= 75:
            fg_weight = 0.9
        else:
            fg_weight = 0.8

        return round(fg_weight, 2)


class CryptoInfiniteStrategy:
    """중앙 라우팅 엔진 - 모든 전략 플러그인 통합"""

    def __init__(self, cfg):
        self.cfg            = cfg
        self.v14            = CryptoV14Strategy()
        self.avwap          = CryptoAvwapSniper()
        self.vol_engine     = CryptoVolatilityEngine()

    def get_plan(self, ticker, current_price, available_krw, candles_1h=None):
        version   = self.cfg.get_version(ticker)
        position  = self.cfg.get_position(ticker)
        qty       = position["qty"]
        avg_price = position["avg"]
        seed      = self.cfg.get_seed(ticker)
        split     = self.cfg.get_split_count(ticker)
        target    = self.cfg.get_target_profit(ticker)

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
            )

        # AVWAP 스나이퍼 모드
        if version == "V_AVWAP":
            avwap_state = self.cfg.get_avwap_state(ticker)
            avwap_qty   = avwap_state.get("qty", 0.0)
            avwap_avg   = avwap_state.get("avg_price", 0.0)
            vwap = self.avwap.calc_daily_vwap(candles_1h or [])
            alloc = seed * 0.3  # AVWAP 전용 자본 30%

            return self.avwap.get_decision(
                ticker=ticker,
                current_price=current_price,
                vwap=vwap,
                avg_price=avwap_avg,
                qty=avwap_qty,
                alloc_krw=alloc,
                candles=candles_1h or [],
            )

        # 기본 fallback
        return self.v14.get_plan(
            ticker=ticker,
            current_price=current_price,
            avg_price=avg_price,
            qty=qty,
            available_krw=available_krw,
            seed=seed,
            split_count=split,
            target_pct=target,
        )

    def scan_volatility(self, ticker, candles_daily):
        fg  = self.vol_engine.get_fear_greed_index()
        hv  = self.vol_engine.calc_hv(candles_daily)
        wt  = self.vol_engine.get_weight(ticker, candles_daily)
        return {"fear_greed": fg, "hv": hv, "weight": wt}


class BithumbBrokerUtils:
    """브로커 없이 사용할 수 있는 수학 유틸"""
    @staticmethod
    def calc_qty(krw_amount: float, price: float, precision: int = 8) -> float:
        if price <= 0:
            return 0.0
        raw = krw_amount / price
        factor = 10 ** precision
        return math.floor(raw * factor) / factor
