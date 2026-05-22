# 🤖 Binance Volume Bot — Deployment Guide

## Files
- `bot.py` — main bot
- `requirements.txt` — Python dependencies
- `nixpacks.toml` — Railway build config

---

## 🚀 Deploy to Railway (Step by Step)

### Step 1 — Push to GitHub
```
git init
git add .
git commit -m "volume bot v1"
git push origin main
```

### Step 2 — Railway Setup
1. Go to railway.app → New Project
2. Connect your GitHub repo
3. Railway auto-detects Python via nixpacks.toml

### Step 3 — Add ENV Variables on Railway
Go to your project → Variables tab → Add these:

| Variable           | Value                  |
|--------------------|------------------------|
| BINANCE_API_KEY    | your Binance API key   |
| BINANCE_SECRET     | your Binance secret    |
| SLACK_WEBHOOK_URL  | your Slack webhook URL |

### Step 4 — Deploy
Click Deploy — done! ✅

---

## ⚙️ Strategy Summary

| Setting           | Value                        |
|-------------------|------------------------------|
| Pairs             | BNB/USDT, USDC/USDT, BTC/USDT |
| Capital           | 57 USDT                      |
| BNB allocation    | 45–60% (randomized)          |
| USDC allocation   | 25–35% (randomized)          |
| BTC allocation    | 10–20% (randomized)          |
| Buy signal        | Dip detected (-0.2% from high) |
| Take profit       | +0.3%                        |
| Stop loss         | -0.5%                        |
| Cycle duration    | Max 30 minutes per trade     |
| Cooldown          | 8–15 minutes (randomized)    |

---

## 📲 Slack Messages Sent

- ✅ Bot started
- 🔄 Cycle start + allocations
- ⏳ Each trade start
- 📊 Full cycle report:
  - Per coin: allocated USDT, buy/sell price, qty, P&L, exit reason
  - Total cycle P&L
  - Total volume (USDT)
  - Balance in USDT and PKR

---

## ⚠️ Binance API Key Permissions Needed
- ✅ Enable: Read + Spot Trading
- ❌ Disable: Withdrawals (not needed, safer)

---

## 🔧 Tune These in bot.py

```python
TOTAL_CAPITAL    = 57.0      # your balance
PROFIT_TARGET    = 0.003     # +0.3% take profit
STOP_LOSS        = 0.005     # -0.5% stop loss
DIP_THRESHOLD    = 0.002     # -0.2% dip to trigger buy
CYCLE_MINUTES    = 30        # max hold per trade
PKR_RATE         = 281.0     # update as needed
```
