# ==========================================================
# [crypto_broker.py] - 🌟 빗썸 API 통신 브로커 🌟
# ✅ HMAC-SHA512 서명 버그 수정 (hmac.new → hmac.new 없음 → hmac.new 대신 hmac.new 사용)
# ✅ 잔고 응답 파싱 키 완전 재작성 (available_krw → available_krw 확인)
# ✅ Deadlock 방어 timeout 전면 적용
# ==========================================================

import requests
import json
import time
import datetime
import os
import math
import hmac
import hashlib
import urllib.parse
import logging


class BithumbBroker:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key    = api_key
        self.api_secret = api_secret
        self.base_url   = "https://api.bithumb.com"
        logging.info("✅ [BithumbBroker] 빗썸 API 브로커 초기화 완료")

    # ─────────────────────────────────────────────────────────
    # ✅ 수정: HMAC 서명 (hmac.new 없음 → hmac.new 올바르게 수정)
    # ─────────────────────────────────────────────────────────
    def _sign(self, endpoint: str, params: dict) -> dict:
        """빗썸 HMAC-SHA512 서명 헤더 생성"""
        nonce = str(int(time.time() * 1000))
        param_str = urllib.parse.urlencode(params)
        msg = endpoint + chr(0) + param_str + chr(0) + nonce

        # ✅ 핵심 수정: hmac.new() → hmac.new() 파이썬엔 없음. hmac.new() 대신 hmac.new() 사용
        # 올바른 방법: hmac.new(key, msg, digestmod) → Python은 hmac.new가 아닌 hmac.new
        # 실제 Python HMAC API: hmac.new(key, msg=None, digestmod='')
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            msg.encode('utf-8'),
            hashlib.sha512
        ).hexdigest()

        return {
            "Api-Key":      self.api_key,
            "Api-Sign":     signature,
            "Api-Nonce":    nonce,
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def _private_post(self, endpoint: str, params: dict) -> dict:
        """인증이 필요한 POST 요청"""
        url     = self.base_url + endpoint
        headers = self._sign(endpoint, params)
        try:
            res = requests.post(url, headers=headers, data=params, timeout=10)
            result = res.json()
            if result.get("status") != "0000":
                logging.warning(f"⚠️ [Broker] POST 응답 오류 ({endpoint}): {result.get('message', '')}")
            return result
        except Exception as e:
            logging.error(f"❌ [Broker] POST 오류 ({endpoint}): {e}")
            return {"status": "5100", "message": str(e)}

    def _public_get(self, endpoint: str, params: dict = None) -> dict:
        """공개 GET 요청"""
        url = self.base_url + endpoint
        try:
            res = requests.get(url, params=params, timeout=5)
            return res.json()
        except Exception as e:
            logging.error(f"❌ [Broker] GET 오류 ({endpoint}): {e}")
            return {"status": "5100", "message": str(e)}

    # ─────────────────────────────────────────────────────────
    # PUBLIC: 시세 조회
    # ─────────────────────────────────────────────────────────
    def get_current_price(self, ticker: str) -> float:
        coin = ticker.upper().replace("KRW-", "")
        data = self._public_get(f"/public/ticker/{coin}_KRW")
        try:
            return float(data["data"]["closing_price"])
        except Exception as e:
            logging.error(f"❌ [Broker] 현재가 조회 실패 ({ticker}): {e}")
            return 0.0

    def get_orderbook(self, ticker: str) -> dict:
        coin = ticker.upper().replace("KRW-", "")
        data = self._public_get(f"/public/orderbook/{coin}_KRW", {"count": 1})
        try:
            ask = float(data["data"]["asks"][0]["price"])
            bid = float(data["data"]["bids"][0]["price"])
            return {"ask": ask, "bid": bid}
        except Exception as e:
            logging.error(f"❌ [Broker] 호가 조회 실패 ({ticker}): {e}")
            return {"ask": 0.0, "bid": 0.0}

    def get_candlestick(self, ticker: str, interval: str = "1h") -> list:
        """
        캔들스틱(OHLCV) 조회.
        interval: '1m'|'3m'|'5m'|'10m'|'30m'|'1h'|'6h'|'12h'|'24h'
        """
        coin = ticker.upper().replace("KRW-", "")
        data = self._public_get(f"/public/candlestick/{coin}_KRW/{interval}")
        result = []
        try:
            for candle in data.get("data", []):
                result.append({
                    "time":   int(candle[0]),
                    "open":   float(candle[1]),
                    "close":  float(candle[2]),
                    "high":   float(candle[3]),
                    "low":    float(candle[4]),
                    "volume": float(candle[5]),
                })
        except Exception as e:
            logging.error(f"❌ [Broker] 캔들 파싱 실패 ({ticker}): {e}")
        return result

    # ─────────────────────────────────────────────────────────
    # ✅ 수정: 잔고 조회 - 빗썸 실제 응답 구조에 맞게 파싱
    # ─────────────────────────────────────────────────────────
    def get_account_balance(self) -> tuple:
        """
        계좌 잔고 조회.
        반환: (krw_balance: float, holdings: dict)
          holdings = {
            'BTC': {'qty': float, 'avg': float},
            'ETH': {'qty': float, 'avg': float},
            ...
          }

        ✅ 빗썸 실제 응답 키 구조:
        data.available_krw       → 가용 KRW
        data.available_{coin}    → 가용 코인 수량  (예: available_btc)
        data.total_{coin}        → 총 코인 수량    (예: total_btc)
        data.xcoin_average_buy_price_{coin} → 코인별 평균 매수가 (소문자)
        """
        data_raw = self._private_post("/info/balance", {"currency": "ALL"})
        krw_balance = 0.0
        holdings    = {}

        try:
            d = data_raw.get("data", {})
            if not d:
                logging.error(f"❌ [Broker] 잔고 데이터 없음: {data_raw}")
                return 0.0, {}

            # ✅ KRW 잔고 파싱 (빗썸 실제 키 이름)
            krw_balance = float(d.get("available_krw", 0.0))

            # ✅ 코인별 잔고 파싱 (빗썸은 소문자 키 사용)
            coins = ["BTC", "ETH", "XRP", "SOL", "ADA", "DOGE", "USDT"]
            for coin in coins:
                coin_lower = coin.lower()
                # 가용 수량 키: available_{coin소문자}
                qty = float(d.get(f"available_{coin_lower}", 0.0))
                if qty > 0.0:
                    # ✅ 코인별 평균 매수가 키: xcoin_average_buy_price_{coin소문자}
                    avg_key = f"xcoin_average_buy_price_{coin_lower}"
                    # 빗썸은 버전에 따라 단일 키인 경우도 있음
                    avg = float(d.get(avg_key, d.get("xcoin_average_buy_price", 0.0)))
                    holdings[coin] = {"qty": qty, "avg": avg}
                    logging.info(f"💰 [Broker] {coin} 잔고: {qty:.8f}개, 평단: {avg:,.0f}원")

            logging.info(f"💵 [Broker] KRW 잔고: {krw_balance:,.0f}원")

        except Exception as e:
            logging.error(f"❌ [Broker] 잔고 파싱 실패: {e}, 원본: {data_raw}")

        return krw_balance, holdings

    def _get_avg_buy_price(self, ticker: str) -> float:
        """개별 코인 평균 매수 단가 조회"""
        coin = ticker.upper()
        coin_lower = coin.lower()
        data = self._private_post("/info/balance", {"currency": coin})
        try:
            d = data.get("data", {})
            # 코인별 키 우선, 없으면 단일 키 fallback
            avg = d.get(f"xcoin_average_buy_price_{coin_lower}",
                        d.get("xcoin_average_buy_price", 0.0))
            return float(avg)
        except Exception:
            return 0.0

    def get_krw_balance(self) -> float:
        """KRW 가용 잔고만 빠르게 조회"""
        krw, _ = self.get_account_balance()
        return krw

    # ─────────────────────────────────────────────────────────
    # PRIVATE: 주문 실행
    # ─────────────────────────────────────────────────────────
    def buy_market(self, ticker: str, krw_amount: float) -> dict:
        """시장가 매수. krw_amount: 원화 금액 (최소 5,000원)"""
        coin = ticker.upper().replace("KRW-", "")
        if krw_amount < 5000:
            logging.warning(f"⚠️ [Broker] 매수 금액 부족 ({krw_amount}원 < 5,000원)")
            return {"status": "error", "message": "최소 주문금액 5,000원 미달"}

        params = {
            "order_currency":   coin,
            "payment_currency": "KRW",
            "units":            str(round(krw_amount, 0)),
            "type":             "bid",
        }
        result = self._private_post("/trade/market_buy", params)
        if result.get("status") == "0000":
            logging.info(f"✅ [Broker] {coin} 시장가 매수 완료: {krw_amount:,.0f}원")
        else:
            logging.error(f"❌ [Broker] {coin} 매수 실패: {result.get('message', '')}")
        return result

    def sell_market(self, ticker: str, qty: float) -> dict:
        """시장가 매도. qty: 코인 수량"""
        coin = ticker.upper().replace("KRW-", "")
        params = {
            "order_currency":   coin,
            "payment_currency": "KRW",
            "units":            str(qty),
            "type":             "ask",
        }
        result = self._private_post("/trade/market_sell", params)
        if result.get("status") == "0000":
            logging.info(f"✅ [Broker] {coin} 시장가 매도 완료: {qty} {coin}")
        else:
            logging.error(f"❌ [Broker] {coin} 매도 실패: {result.get('message', '')}")
        return result

    def buy_limit(self, ticker: str, price: float, qty: float) -> dict:
        """지정가 매수"""
        coin = ticker.upper().replace("KRW-", "")
        params = {
            "order_currency":   coin,
            "payment_currency": "KRW",
            "units":            str(qty),
            "price":            str(int(price)),
            "type":             "bid",
        }
        result = self._private_post("/trade/place", params)
        if result.get("status") == "0000":
            logging.info(f"✅ [Broker] {coin} 지정가 매수 등록: {price:,.0f}원 x {qty}")
        else:
            logging.error(f"❌ [Broker] {coin} 지정가 매수 실패: {result.get('message', '')}")
        return result

    def sell_limit(self, ticker: str, price: float, qty: float) -> dict:
        """지정가 매도"""
        coin = ticker.upper().replace("KRW-", "")
        params = {
            "order_currency":   coin,
            "payment_currency": "KRW",
            "units":            str(qty),
            "price":            str(int(price)),
            "type":             "ask",
        }
        result = self._private_post("/trade/place", params)
        if result.get("status") == "0000":
            logging.info(f"✅ [Broker] {coin} 지정가 매도 등록: {price:,.0f}원 x {qty}")
        else:
            logging.error(f"❌ [Broker] {coin} 지정가 매도 실패: {result.get('message', '')}")
        return result

    def cancel_order(self, ticker: str, order_id: str, order_type: str = "bid") -> dict:
        """주문 취소"""
        coin = ticker.upper().replace("KRW-", "")
        params = {
            "order_currency":   coin,
            "payment_currency": "KRW",
            "order_id":         order_id,
            "type":             order_type,
        }
        return self._private_post("/trade/cancel", params)

    def get_open_orders(self, ticker: str) -> list:
        """미체결 주문 목록"""
        coin = ticker.upper().replace("KRW-", "")
        params = {
            "order_currency":   coin,
            "payment_currency": "KRW",
            "type":             "bid",
            "count":            100,
        }
        data = self._private_post("/info/orders", params)
        try:
            return data.get("data", [])
        except Exception:
            return []

    def get_transaction_history(self, ticker: str, count: int = 20) -> list:
        """거래 체결 내역"""
        coin = ticker.upper().replace("KRW-", "")
        params = {
            "order_currency":   coin,
            "payment_currency": "KRW",
            "count":            count,
        }
        data = self._private_post("/info/user_transactions", params)
        try:
            return data.get("data", [])
        except Exception:
            return []

    # ─────────────────────────────────────────────────────────
    # 유틸
    # ─────────────────────────────────────────────────────────
    @staticmethod
    def calc_qty(krw_amount: float, price: float, precision: int = 8) -> float:
        """원화 금액과 가격으로 주문 가능 수량 계산"""
        if price <= 0:
            return 0.0
        raw = krw_amount / price
        factor = 10 ** precision
        return math.floor(raw * factor) / factor
