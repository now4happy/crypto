# 🪙 크립토 스노우볼 퀀트 봇 (빗썸 API)

원본 KIS 주식 자동매매 봇(앱솔루트 스노우볼)의 아키텍처를 그대로 계승하여
빗썸 API 기반 BTC/ETH 코인 자동매매 시스템으로 포팅한 코드입니다.

---

## ✨ 주요 기능

| 기능 | 설명 |
|------|------|
| **V14 무한매수법** | 분할 매수 → 목표 수익률 달성 시 전량 익절 |
| **AVWAP 스나이퍼** | 당일 VWAP −2% 딥바운스 매수 → +3% 스퀴즈 익절 / −3% 하드스탑 |
| **공포탐욕지수 스캔** | Alternative.me Fear & Greed Index 기반 매수 강도 가중치 |
| **24/7 스나이퍼 감시** | 60초마다 AVWAP 타점/청산 자동 감시 |
| **텔레그램 봇 제어** | /balance /sync /record /seed /ticker /mode /reset |
| **장부 시스템** | 매수/매도 내역 JSON 저장, 실현손익 히스토리 |
| **일일 변동성 브리핑** | 매일 10:00 KST 공포탐욕지수 + HV 브리핑 |

---

## 📂 파일 구조

```
crypto_bot/
├── main.py                  ← 메인 진입점 (스케줄러 등록)
├── crypto_broker.py         ← 빗썸 API 통신 브로커
├── crypto_config.py         ← 설정/장부 관리자 (JSON 영구 저장)
├── crypto_strategy.py       ← V14 + AVWAP + 변동성 엔진
├── crypto_scheduler.py      ← 모든 스케줄 작업 (자동 매매)
├── crypto_telegram_bot.py   ← 텔레그램 봇 컨트롤러
├── .env.example             ← 환경변수 템플릿
└── data/                    ← 자동 생성 (장부, 설정 저장)
```

---

## 🛠️ 설치 및 실행

### 1. 패키지 설치
```bash
pip install requests python-telegram-bot[job-queue] python-dotenv pytz
```

### 2. 환경변수 설정
```bash
cp .env.example .env
# .env 파일을 열어서 본인의 API 키 입력
nano .env
```

### 3. 빗썸 API 발급
- https://www.bithumb.com 로그인 → 마이페이지 → API 관리
- API Key + API Secret 발급 후 .env에 입력

### 4. 실행
```bash
python main.py
```

### 5. 서버 백그라운드 실행 (Google Cloud SSH)
```bash
# systemd 서비스 등록 (KST 타임존 고정)
sudo cat << 'EOF' > /etc/systemd/system/cryptobot.service
[Unit]
Description=Crypto Snowball Quant Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/home/YOUR_USERNAME/crypto_bot
Environment="TZ=Asia/Seoul"
ExecStart=/usr/bin/python3 /home/YOUR_USERNAME/crypto_bot/main.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable cryptobot
sudo systemctl start cryptobot

# 로그 확인
sudo journalctl -u cryptobot -f
```

---

## 📱 텔레그램 명령어

| 명령어 | 설명 |
|--------|------|
| `/start` | 봇 시작 및 명령어 목록 |
| `/balance` | 현재 KRW 잔고 + 코인 포지션 |
| `/sync` | 통합 지시서 (매수/매도 타점 확인) |
| `/record` | 최근 거래 장부 조회 |
| `/history` | 실현손익 히스토리 (명예의 전당) |
| `/seed` | 코인별 시드머니 설정 |
| `/ticker` | 운용 코인 변경 (BTC/ETH/XRP/SOL 등) |
| `/mode` | 전략 모드 설정 (V14/AVWAP) |
| `/reset` | 비상 초기화 (잠금 해제/장부 초기화) |
| `/version` | 버전 및 업데이트 내역 |

---

## ⚙️ 스케줄 타임테이블 (KST 기준)

| 시간 | 작업 |
|------|------|
| 매일 03:00 | 🧹 자정 청소 (7일 초과 로그 삭제) |
| 매일 06:00 / 12:00 / 18:00 / 00:00 | 🔑 API 헬스체크 |
| 매일 09:00 | 🔓 일일 거래 잠금 해제 |
| 매일 10:00 | 📊 변동성 브리핑 (공포탐욕지수 + HV) |
| 매일 10:05 | 📥 정규 매매 (무한매수법 V14) |
| 60초마다 | 🔫 AVWAP 스나이퍼 실시간 감시 |

---

## ⚠️ 주의사항

- 빗썸 API 최소 주문 금액: **5,000원**
- 코인 시장은 24/7이므로 주식 봇과 달리 장중/장외 구분 없음
- 첫 실행 전 반드시 소액으로 테스트 후 사용
- 모든 투자 손실에 대한 책임은 사용자 본인에게 있습니다

---

## 🔗 원본 출처

본 코드는 라오어님의 무한매수법 아이디어를 기반으로 하며,
원본 KIS 주식 봇(앱솔루트 스노우볼)의 아키텍처를 크립토 시장에 맞게 포팅한 교육용 예제입니다.
