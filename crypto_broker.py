# ==========================================================
# [crypto_broker.py] - 빗썸 API 브로커 V2.0
# ✅ 빗썸 신버전 API (2024년 7월 오픈 API 2.0) 완전 재작성
# ✅ 인증 방식: 구버전 HMAC-Sign → 신버전 JWT (HS256)
# ✅ 잔고: GET  /v1/accounts
# ✅ 주문: POST /v2/orders
# ✅ 취소: DEL  /v2/orders
# ==========================================================

import requests
import hashlib
import uuid
import time
import math
import logging
import jwt          # pip install PyJWT
import urllib.parse


class BithumbBroker:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key    = api_key
        self.api_secret = api_secret
        self.base_url   = "https://api.bithumb.com"
        logging.info("✅ [BithumbBroker] 빗썸 JWT API 브로커 V2.0 초기화 완료")

    # ─────────────────────────────────────────────────────────
    # ✅ 신버전 JWT 인증 (HS256, Bearer)
    # ─────────────────────────────────────────────────────────
    def _make_jwt_token(self, query_string: str = "") -> str:
        payload = {
            "access_key": self.api_key,
            "nonce":       str(uuid.uuid4()),
            "timestamp":   int(time.time() * 1000),
        }
        if query_string:
            h = hashlib.sha512()
            h.update(query_string.encode("utf-8"))
            payload["query_hash"]     = h.hexdigest()
            payload["query_hash_alg"] = "SHA512"

        token = jwt.encode(payload, self.api_secret, algorithm="HS256")
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        return token

    def _auth_headers(self, query_string: str = "") -> dict:
        return {
            "Authorization": f"Bearer {self._make_jwt_token(query_string)}",
            "Content-Type":  "application/json; charset=utf-8",
        }

    def _private_get(self, endpoint: str, params: dict = None) -> dict | list:
        url = self.base_url + endpoint
        qs  = urllib.parse.urlencode(params) if params else ""
        try:
            res = requests.get(url, params=params, headers=self._auth_headers(qs), timeout=10)
            if res.status_code == 200:
                return res.json()
            logging.error(f"❌ [Broker] GET {endpoint} {res.status_code}: {res.text[:300]}")
            return {"error": {"name": str(res.status_code), "message": res.text[:200]}}
        except Exception as e:
            logging.error(f"❌ [Broker] GET {endpoint}: {e}")
            return {"error": {"name": "exception", "message": str(e)}}

    def _private_post(self, endpoint: str, body: dict = None) -> dict:
        url  = self.base_url + endpoint
        body = body or {}
        qs   = "&".join(f"{k}={v}" for k, v in body.items())
        try:
            res = requests.post(url, json=body, headers=self._auth_headers(qs), timeout=10)
            if res.status_code in (200, 201):
                return res.json()
            logging.error(f"❌ [Broker] POST {endpoint} {res.status_code}: {res.text[:300]}")
            return {"error": {"name": str(res.status_code), "message": res.text[:200]}}
        except Exception as e:
            logging.error(f"❌ [Broker] POST {endpoint}: {e}")
            return {"error": {"name": "exception", "message": str(e)}}

    def _private_delete(self, endpoint: str, params: dict = None) -> dict:
        url = self.base_url + endpoint
        qs  = urllib.parse.urlencode(params) if params else ""
        try:
            res = requests.delete(url, params=params, headers=self._auth_headers(qs), timeout=10)
            if res.status_code == 200:
                return res.json()
            logging.error(f"❌ [Broker] DEL {endpoint} {res.status_code}: {res.text[:300]}")
            return {"error": {"name": str(res.status_code), "message": res.text[:200]}}
        except Exception as e:
            logging.error(f"❌ [Broker] DEL {endpoint}: {e}")
            return {"error": {"name": "exception", "message": str(e)}}

    def _public_get(self, endpoint: str, params: dict = None) -> dict:
        url = self.base_url + endpoint
        try:
            res = requests.get(url, params=params, timeout=5)
            return res.json()
        except Exception as e:
            logging.error(f"❌ [Broker] Public GET {endpoint}: {e}")
            return {"status": "5100", "message": str(e)}

    # ─────────────────────────────────────────────────────────
    # ✅ 잔고 조회 - GET /v1/accounts
    # 응답: [{"currency":"KRW","balance":"100000","locked":"0","avg_buy_price":"0"}, ...]
    # ─────────────────────────────────────────────────────────
    def get_account_balance(self) -> tuple:
        data = self._private_get("/v1/accounts")
        krw_balance = 0.0
        holdings    = {}

        if isinstance(data, list):
            for item in data:
                currency = item.get("currency", "").upper()
                balance  = float(item.get("balance", 0.0))
                locked   = float(item.get("locked",  0.0))
                avg      = float(item.get("avg_buy_price", 0.0))

                if currency == "KRW":
                    krw_balance = balance
                    logging.info(f"💵 [Broker] KRW 가용: {krw_balance:,.0f}원 | 잠금: {locked:,.0f}원")
                elif balance > 0 or locked > 0:
                    holdings[currency] = {"qty": balance + locked, "avg": avg}
                    logging.info(f"🪙 [Broker] {currency}: {balance+locked:.8f}개 | 평단: {avg:,.0f}원")
        else:
            err = data.get("error", {}) if isinstance(data, dict) else {}
            err_name = err.get("name", "")
            err_msg  = err.get("message", "")
            logging.error(f"❌ [Broker] 잔고 조회 실패: {err_name} - {err_msg}")
            if "NotAllowIP" in err_name or "NotAllowIP" in err_msg:
                logging.error("🚨 빗썸 API 관리 페이지에서 이 서버의 IP를 화이트리스트에 추가하세요!")
            elif "401" in str(err_name):
                logging.error("🚨 API KEY 또는 SECRET KEY가 잘못되었습니다! .env 파일을 확인하세요.")

        return krw_balance, holdings

    def get_krw_balance(self) -> float:
        krw, _ = self.get_account_balance()
        return krw

    # ─────────────────────────────────────────────────────────
    # PUBLIC: 시세 조회 (구버전 public API 유지)
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
            return {
                "ask": float(data["data"]["asks"][0]["price"]),
                "bid": float(data["data"]["bids"][0]["price"]),
            }
        except Exception as e:
            logging.error(f"❌ [Broker] 호가 조회 실패 ({ticker}): {e}")
            return {"ask": 0.0, "bid": 0.0}

    def get_candlestick(self, ticker: str, interval: str = "1h") -> list:
        coin = ticker.upper().replace("KRW-", "")
        data = self._public_get(f"/public/candlestick/{coin}_KRW/{interval}")
        result = []
        try:
            for c in data.get("data", []):
                result.append({
                    "time":   int(c[0]),
                    "open":   float(c[1]),
                    "close":  float(c[2]),
                    "high":   float(c[3]),
                    "low":    float(c[4]),
                    "volume": float(c[5]),
                })
        except Exception as e:
            logging.error(f"❌ [Broker] 캔들 파싱 실패 ({ticker}): {e}")
        return result

    # ─────────────────────────────────────────────────────────
    # ✅ 주문 실행 - POST /v2/orders (신버전)
    # market 형식: "KRW-BTC"
    # ─────────────────────────────────────────────────────────
    def buy_market(self, ticker: str, krw_amount: float) -> dict:
        """시장가 매수 (원화 금액)"""
        market = f"KRW-{ticker.upper().replace('KRW-', '')}"
        if krw_amount < 5000:
            logging.warning(f"⚠️ 최소 5,000원 미달 ({krw_amount}원)")
            return {"error": {"name": "min_order", "message": "최소 주문금액 5,000원 미달"}}
        body   = {"market": market, "side": "bid", "ord_type": "price", "price": str(int(krw_amount))}
        result = self._private_post("/v2/orders", body)
        if self.is_ok(result):
            logging.info(f"✅ {market} 시장가 매수: {krw_amount:,.0f}원")
        else:
            logging.error(f"❌ {market} 매수 실패: {result.get('error', {})}")
        return result

    def sell_market(self, ticker: str, qty: float) -> dict:
        """시장가 매도 (코인 수량)"""
        market = f"KRW-{ticker.upper().replace('KRW-', '')}"
        body   = {"market": market, "side": "ask", "ord_type": "market", "volume": str(qty)}
        result = self._private_post("/v2/orders", body)
        if self.is_ok(result):
            logging.info(f"✅ {market} 시장가 매도: {qty}개")
        else:
            logging.error(f"❌ {market} 매도 실패: {result.get('error', {})}")
        return result

    def buy_limit(self, ticker: str, price: float, qty: float) -> dict:
        """지정가 매수"""
        market = f"KRW-{ticker.upper().replace('KRW-', '')}"
        body   = {"market": market, "side": "bid", "ord_type": "limit",
                  "price": str(int(price)), "volume": str(qty)}
        result = self._private_post("/v2/orders", body)
        if self.is_ok(result):
            logging.info(f"✅ {market} 지정가 매수: {price:,.0f}원 x {qty}")
        else:
            logging.error(f"❌ {market} 지정가 매수 실패: {result.get('error', {})}")
        return result

    def sell_limit(self, ticker: str, price: float, qty: float) -> dict:
        """지정가 매도"""
        market = f"KRW-{ticker.upper().replace('KRW-', '')}"
        body   = {"market": market, "side": "ask", "ord_type": "limit",
                  "price": str(int(price)), "volume": str(qty)}
        result = self._private_post("/v2/orders", body)
        if self.is_ok(result):
            logging.info(f"✅ {market} 지정가 매도: {price:,.0f}원 x {qty}")
        else:
            logging.error(f"❌ {market} 지정가 매도 실패: {result.get('error', {})}")
        return result

    def cancel_order(self, order_id: str, ticker: str = "") -> dict:
        """주문 취소"""
        params = {"order_id": order_id}
        if ticker:
            params["market"] = f"KRW-{ticker.upper().replace('KRW-', '')}"
        return self._private_delete("/v2/orders", params)

    def get_open_orders(self, ticker: str) -> list:
        """미체결 주문 목록"""
        params = {"market": f"KRW-{ticker.upper().replace('KRW-', '')}", "state": "wait", "limit": 100}
        data   = self._private_get("/v1/orders", params)
        return data if isinstance(data, list) else []

    # ─────────────────────────────────────────────────────────
    # 유틸
    # ─────────────────────────────────────────────────────────
    def is_ok(self, result: dict) -> bool:
        """주문 성공 여부 (uuid 필드 존재 여부로 판단)"""
        return isinstance(result, dict) and "uuid" in result and "error" not in result

    @staticmethod
    def calc_qty(krw_amount: float, price: float, precision: int = 8) -> float:
        if price <= 0:
            return 0.0
        raw    = krw_amount / price
        factor = 10 ** precision
        return math.floor(raw * factor) / factor
