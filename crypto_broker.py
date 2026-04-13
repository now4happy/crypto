# ==========================================================
# [crypto_broker.py] - 🌟 빗썸 API 통신 브로커 🌟
# 💡 원본 KoreaInvestmentBroker의 구조를 계승하여 빗썸 REST API로 포팅
# 💡 잔고 조회 / 시세 조회 / 매수 / 매도 / 체결 내역 조회
# 💡 Deadlock 방어 timeout 전면 적용
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
    # 내부 서명 유틸
    # ─────────────────────────────────────────────────────────
    def _sign(self, endpoint: str, params: dict) -> dict:
        """빗썸 HMAC-SHA512 서명 헤더 생성"""
        nonce = str(int(time.time() * 1000))
        param_str = urllib.parse.urlencode(params)
        msg = endpoint + chr(0) + param_str + chr(0) + nonce
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            msg.encode('utf-8'),
            hashlib.sha512
        ).hexdigest()
        return {
            "Api-Key":       self.api_key,
            "Api-Sign":      signature,
            "Api-Nonce":     nonce,
            "Content-Type":  "application/x-www-form-urlencoded",
        }

    def _private_post(self, endpoint: str, params: dict) -> dict:
        """인증이 필요한 POST 요청 (잔고, 매매 등)"""
        url     = self.base_url + endpoint
        headers = self._sign(endpoint, params)
        try:
            res = requests.post(url, headers=headers, data=params, timeout=10)
            return res.json()
        except Exception as e:
            logging.error(f"❌ [Broker] POST 오류 ({endpoint}): {e}")
            return {"status": "5100", "message": str(e)}

    def _public_get(self, endpoint: str, params: dict = None) -> dict:
        """공개 GET 요청 (시세 등)"""
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
        """
        현재가 조회.  ticker = "BTC" | "ETH" 등
        """
        coin = ticker.upper().replace("KRW-", "")
        data = self._public_get(f"/public/ticker/{coin}_KRW")
        try:
            return float(data["data"]["closing_price"])
        except Exception as e:
            logging.error(f"❌ [Broker] 현재가 조회 실패 ({ticker}): {e}")
            return 0.0

    def get_orderbook(self, ticker: str) -> dict:
        """호가 조회 → {'ask': float, 'bid': float}"""
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
        interval: '1m' | '3m' | '5m' | '10m' | '30m' | '1h' | '6h' | '12h' | '24h'
        반환: [{'open','high','low','close','volume','time'}, ...]
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
    # PRIVATE: 잔고 조회
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
        """
        data = self._private_post("/info/balance", {"currency": "ALL"})
        krw_balance = 0.0
        holdings    = {}

        try:
            d = data.get("data", {})
            krw_balance = float(d.get("available_krw", 0.0))

            # 빗썸 잔고 응답 키 패턴: available_{coin}, total_{coin}, xcoin_average_buy_price
            coins = ["BTC", "ETH", "XRP", "SOL", "ADA"]
            for coin in coins:
                qty_key = f"available_{coin.lower()}"
                avg_key = f"xcoin_average_buy_price"   # 빗썸은 통합 단일 키로 반환
                qty = float(d.get(qty_key, 0.0))
                if qty > 0:
                    # 평균 매수가는 별도 API로 조회 필요 (아래 함수 참조)
                    avg = self._get_avg_buy_price(coin)
                    holdings[coin] = {"qty": qty, "avg": avg}

        except Exception as e:
            logging.error(f"❌ [Broker] 잔고 파싱 실패: {e}")

        return krw_balance, holdings

    def _get_avg_buy_price(self, ticker: str) -> float:
        """평균 매수 단가 조회"""
        coin = ticker.upper()
        data = self._private_post("/info/balance", {"currency": coin})
        try:
            return float(data["data"].get("xcoin_average_buy_price", 0.0))
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
        """
        시장가 매수.
        ticker: "BTC" | "ETH"
        krw_amount: 원화 금액 (최소 5,000원)
        """
        coin = ticker.upper().replace("KRW-", "")
        if krw_amount < 5000:
            logging.warning(f"⚠️ [Broker] 매수 금액 부족 ({krw_amount}원 < 5,000원)")
            return {"status": "error", "message": "최소 주문금액 5,000원 미달"}

        params = {
            "order_currency":   coin,
            "payment_currency": "KRW",
            "units":            str(round(krw_amount, 0)),  # 원화 금액으로 매수
            "type":             "bid",
        }
        result = self._private_post("/trade/market_buy", params)
        if result.get("status") == "0000":
            logging.info(f"✅ [Broker] {coin} 시장가 매수 완료: {krw_amount:,.0f}원")
        else:
            logging.error(f"❌ [Broker] {coin} 매수 실패: {result.get('message', '')}")
        return result

    def sell_market(self, ticker: str, qty: float) -> dict:
        """
        시장가 매도.
        ticker: "BTC" | "ETH"
        qty: 코인 수량
        """
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
        """
        지정가 매수.
        price: 원화 가격
        qty: 코인 수량
        """
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
        """
        지정가 매도.
        price: 원화 가격
        qty: 코인 수량
        """
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
        """주문 취소. order_type: 'bid' | 'ask'"""
        coin = ticker.upper().replace("KRW-", "")
        params = {
            "order_currency":   coin,
            "payment_currency": "KRW",
            "order_id":         order_id,
            "type":             order_type,
        }
        return self._private_post("/trade/cancel", params)

    def get_open_orders(self, ticker: str) -> list:
        """미체결 주문 목록 조회"""
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
        """거래 체결 내역 조회"""
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
    # 유틸: KRW 단위 반올림 (코인 최소 주문 단위 적용)
    # ─────────────────────────────────────────────────────────
    @staticmethod
    def calc_qty(krw_amount: float, price: float, precision: int = 8) -> float:
        """원화 금액과 가격으로 주문 가능 수량 계산"""
        if price <= 0:
            return 0.0
        raw = krw_amount / price
        factor = 10 ** precision
        return math.floor(raw * factor) / factor
