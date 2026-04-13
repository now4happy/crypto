# ==========================================================
# [crypto_config.py] - 🌟 크립토 설정 및 장부 관리자 🌟
# 💡 원본 ConfigManager 구조를 계승하여 크립토 환경으로 포팅
# 💡 BTC/ETH 장부, 시드, 분할 설정, 버전, 잠금 상태 관리
# ==========================================================

import json
import os
import datetime
import time
import shutil
import tempfile

VERSION_HISTORY = [
    "V1.0 [2026] 빗썸 크립토 봇 초기 릴리즈 - BTC/ETH 무한매수법 + AVWAP 스나이퍼",
]

class CryptoConfigManager:
    def __init__(self):
        self.FILES = {
            "CHAT_ID":       "data/chat_id.dat",
            "LEDGER":        "data/ledger.json",
            "HISTORY":       "data/history.json",
            "SPLIT_CFG":     "data/split_config.json",
            "TICKER":        "data/active_tickers.json",
            "SEED_CFG":      "data/seed_config.json",
            "VERSION_CFG":   "data/version_config.json",
            "REVERSE_CFG":   "data/reverse_config.json",
            "LOCKS":         "data/trade_locks.json",
            "AVWAP_CFG":     "data/avwap_hybrid.json",
            "QUEUE_LEDGER":  "data/queue_ledger.json",
        }

        # ── 기본값 (코인 단위는 원화 기준 시드)
        self.DEFAULT_SEED     = {"BTC": 500000.0, "ETH": 500000.0}   # 50만원
        self.DEFAULT_SPLIT    = {"BTC": 20.0,     "ETH": 20.0}       # 20분할
        self.DEFAULT_TARGET   = {"BTC": 8.0,      "ETH": 10.0}       # 목표 수익률 %
        self.DEFAULT_COMPOUND = {"BTC": 70.0,     "ETH": 70.0}       # 복리율 %
        self.DEFAULT_VERSION  = {"BTC": "V14",    "ETH": "V14"}

        for f in self.FILES.values():
            d = os.path.dirname(f)
            if d and not os.path.exists(d):
                os.makedirs(d, exist_ok=True)

    # ─────────────────────────────────────────────────────────
    # 내부 JSON IO (원자적 쓰기)
    # ─────────────────────────────────────────────────────────
    def _load_json(self, filename, default=None):
        if os.path.exists(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️ [Config] 로드 에러 ({filename}): {e}")
                try:
                    shutil.copy(filename, filename + f".bak_{int(time.time())}")
                except Exception:
                    pass
        return default if default is not None else {}

    def _save_json(self, filename, data):
        try:
            d = os.path.dirname(filename)
            if d and not os.path.exists(d):
                os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=d or '.', text=True)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(fd)
            os.replace(tmp, filename)
        except Exception as e:
            print(f"❌ [Config] 저장 에러 ({filename}): {e}")

    def _load_file(self, filename, default=None):
        if os.path.exists(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    return f.read().strip()
            except Exception:
                pass
        return default

    def _save_file(self, filename, content):
        try:
            d = os.path.dirname(filename)
            if d and not os.path.exists(d):
                os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=d or '.', text=True)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(str(content))
                f.flush()
                os.fsync(fd)
            os.replace(tmp, filename)
        except Exception as e:
            print(f"❌ [Config] 파일 저장 에러 ({filename}): {e}")

    # ─────────────────────────────────────────────────────────
    # Chat ID
    # ─────────────────────────────────────────────────────────
    def get_chat_id(self):
        v = self._load_file(self.FILES["CHAT_ID"])
        try:
            return int(v) if v else None
        except Exception:
            return None

    def set_chat_id(self, chat_id):
        self._save_file(self.FILES["CHAT_ID"], str(chat_id))

    # ─────────────────────────────────────────────────────────
    # 운용 종목
    # ─────────────────────────────────────────────────────────
    def get_active_tickers(self) -> list:
        tickers = self._load_json(self.FILES["TICKER"], ["BTC", "ETH"])
        return tickers if tickers else ["BTC"]

    def set_active_tickers(self, tickers: list):
        self._save_json(self.FILES["TICKER"], tickers)

    # ─────────────────────────────────────────────────────────
    # 시드 / 분할 / 목표 수익률 / 복리율
    # ─────────────────────────────────────────────────────────
    def get_seed(self, ticker: str) -> float:
        d = self._load_json(self.FILES["SEED_CFG"], {})
        return float(d.get(ticker, self.DEFAULT_SEED.get(ticker, 500000.0)))

    def set_seed(self, ticker: str, amount: float):
        d = self._load_json(self.FILES["SEED_CFG"], {})
        d[ticker] = amount
        self._save_json(self.FILES["SEED_CFG"], d)

    def get_split_count(self, ticker: str) -> float:
        d = self._load_json(self.FILES["SPLIT_CFG"], {})
        return float(d.get(ticker, self.DEFAULT_SPLIT.get(ticker, 20.0)))

    def set_split_count(self, ticker: str, count: float):
        d = self._load_json(self.FILES["SPLIT_CFG"], {})
        d[ticker] = count
        self._save_json(self.FILES["SPLIT_CFG"], d)

    def get_target_profit(self, ticker: str) -> float:
        d = self._load_json(self.FILES["SPLIT_CFG"], {})
        return float(d.get(f"{ticker}_target", self.DEFAULT_TARGET.get(ticker, 8.0)))

    def set_target_profit(self, ticker: str, pct: float):
        d = self._load_json(self.FILES["SPLIT_CFG"], {})
        d[f"{ticker}_target"] = pct
        self._save_json(self.FILES["SPLIT_CFG"], d)

    # ─────────────────────────────────────────────────────────
    # 버전 / 모드
    # ─────────────────────────────────────────────────────────
    def get_version(self, ticker: str) -> str:
        d = self._load_json(self.FILES["VERSION_CFG"], {})
        return d.get(ticker, self.DEFAULT_VERSION.get(ticker, "V14"))

    def set_version(self, ticker: str, version: str):
        d = self._load_json(self.FILES["VERSION_CFG"], {})
        d[ticker] = version
        self._save_json(self.FILES["VERSION_CFG"], d)

    def get_latest_version(self) -> str:
        return VERSION_HISTORY[-1].split(" ")[0] if VERSION_HISTORY else "V1.0"

    # ─────────────────────────────────────────────────────────
    # 장부 (Ledger)
    # ─────────────────────────────────────────────────────────
    def get_ledger(self, ticker: str = None) -> list:
        all_records = self._load_json(self.FILES["LEDGER"], [])
        if ticker:
            return [r for r in all_records if r.get("ticker") == ticker]
        return all_records

    def add_ledger(self, ticker: str, side: str, qty: float, price: float, note: str = ""):
        all_records = self._load_json(self.FILES["LEDGER"], [])
        all_records.append({
            "ticker":    ticker,
            "side":      side,       # "BUY" | "SELL"
            "qty":       qty,
            "price":     price,
            "krw_amount": qty * price,
            "date":      datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "note":      note,
        })
        self._save_json(self.FILES["LEDGER"], all_records)

    def clear_ledger(self, ticker: str):
        all_records = self._load_json(self.FILES["LEDGER"], [])
        # 해당 종목 기록을 히스토리로 이관 후 삭제
        ticker_records = [r for r in all_records if r.get("ticker") == ticker]
        if ticker_records:
            history = self._load_json(self.FILES["HISTORY"], [])
            history.extend(ticker_records)
            self._save_json(self.FILES["HISTORY"], history)
        remaining = [r for r in all_records if r.get("ticker") != ticker]
        self._save_json(self.FILES["LEDGER"], remaining)

    def get_position(self, ticker: str) -> dict:
        """
        장부 기반 보유 포지션 계산.
        반환: {'qty': float, 'avg': float, 'total_invested': float}
        """
        records = self.get_ledger(ticker)
        total_qty = 0.0
        total_invested = 0.0
        for r in records:
            qty = float(r.get("qty", 0.0))
            price = float(r.get("price", 0.0))
            if r.get("side") == "BUY":
                total_qty += qty
                total_invested += qty * price
            elif r.get("side") == "SELL":
                if total_qty > 0:
                    ratio = min(qty / total_qty, 1.0)
                    total_invested -= total_invested * ratio
                total_qty = max(0.0, total_qty - qty)
        avg = (total_invested / total_qty) if total_qty > 0 else 0.0
        return {"qty": total_qty, "avg": avg, "total_invested": total_invested}

    # ─────────────────────────────────────────────────────────
    # 거래 잠금 (중복 주문 방지)
    # ─────────────────────────────────────────────────────────
    def get_trade_lock(self, ticker: str) -> bool:
        d = self._load_json(self.FILES["LOCKS"], {})
        return bool(d.get(ticker, False))

    def set_trade_lock(self, ticker: str, locked: bool):
        d = self._load_json(self.FILES["LOCKS"], {})
        d[ticker] = locked
        self._save_json(self.FILES["LOCKS"], d)

    def reset_locks(self):
        self._save_json(self.FILES["LOCKS"], {})

    # ─────────────────────────────────────────────────────────
    # 리버스(V-REV) 모드
    # ─────────────────────────────────────────────────────────
    def get_reverse_state(self, ticker: str) -> dict:
        d = self._load_json(self.FILES["REVERSE_CFG"], {})
        return d.get(ticker, {"is_active": False, "day_count": 0, "trigger_price": 0.0})

    def set_reverse_state(self, ticker: str, is_active: bool, day_count: int = 0, trigger_price: float = 0.0):
        d = self._load_json(self.FILES["REVERSE_CFG"], {})
        d[ticker] = {
            "is_active":     is_active,
            "day_count":     day_count,
            "trigger_price": trigger_price,
        }
        self._save_json(self.FILES["REVERSE_CFG"], d)

    # ─────────────────────────────────────────────────────────
    # AVWAP 하이브리드 상태
    # ─────────────────────────────────────────────────────────
    def get_avwap_state(self, ticker: str) -> dict:
        d = self._load_json(self.FILES["AVWAP_CFG"], {})
        return d.get(ticker, {
            "is_enabled":  False,
            "qty":         0.0,
            "avg_price":   0.0,
            "entry_time":  "",
            "is_shutdown": False,
        })

    def set_avwap_state(self, ticker: str, state: dict):
        d = self._load_json(self.FILES["AVWAP_CFG"], {})
        d[ticker] = state
        self._save_json(self.FILES["AVWAP_CFG"], d)

    def toggle_avwap(self, ticker: str) -> bool:
        state = self.get_avwap_state(ticker)
        state["is_enabled"] = not state.get("is_enabled", False)
        self.set_avwap_state(ticker, state)
        return state["is_enabled"]

    # ─────────────────────────────────────────────────────────
    # 히스토리 (명예의 전당)
    # ─────────────────────────────────────────────────────────
    def get_history(self) -> list:
        return self._load_json(self.FILES["HISTORY"], [])

    def add_history(self, ticker: str, realized_pnl: float, realized_pnl_pct: float, note: str = ""):
        history = self._load_json(self.FILES["HISTORY"], [])
        history.append({
            "ticker":           ticker,
            "realized_pnl":     realized_pnl,
            "realized_pnl_pct": realized_pnl_pct,
            "date":             datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "note":             note,
        })
        self._save_json(self.FILES["HISTORY"], history)
