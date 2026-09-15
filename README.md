# 🤖 Binance Spot Trading Agent

A Python-based Binance Spot trading automation project built with
[CCXT](https://github.com/ccxt/ccxt).

The agent monitors selected trading pairs, detects configured price dips,
allocates the available USDT balance dynamically, executes Spot market orders,
tracks fees and P&L, and sends cycle reports through Slack.

> ⚠️ This project can place real Binance Spot orders with valid API credentials

---

## ✨ Features

- Live Binance USDT balance detection
- Dynamic balance allocation
- BNB/USDT, USDC/USDT and BTC/USDT monitoring
- Pair-specific dip detection
- Market buy and sell execution
- Take-profit and stop-loss handling
- Randomized 25–45 minute maximum holding period
- Binance trading-fee estimation
- Gross and net P&L reporting
- Trade-volume calculation
- Slack notifications and cycle reports
- Railway/Nixpacks deployment configuration

---

## 🚦 Deployment Status

### ✅ Local execution

The application has been successfully tested locally.

Local execution can retrieve the Binance balance, obtain the live
USDT/PKR conversion rate, calculate allocations, monitor configured trading
pairs, detect price movements and produce Slack cycle reports.

### ⚠️ Railway deployment

The project can be deployed to Railway, but Binance API requests from the
currently tested Railway cloud environment are rejected because of the
outbound server IP/location.

Railway response:

```text
451 Service unavailable from a restricted location
```

Binance message:

```text
Service unavailable from a restricted location according to 'b. Eligibility'.
```

---

## 📁 Project Structure

```text
.
├── main.py
├── requirements.txt
├── nixpacks.toml
├── Procfile
└── README.md
```

---

## 🔐 Environment Variables

Never commit real API keys, secrets, or Slack webhook URLs to Git.

Required Binance variables:

```env
BINANCE_API_KEY=YOUR_BINANCE_API_KEY
BINANCE_SECRET=YOUR_BINANCE_SECRET
```

Optional Slack integration:

```env
SLACK_WEBHOOK_URL=YOUR_SLACK_WEBHOOK_URL
```

---

## 💻 Run Locally

### 1. Clone the repository

```bash
git clone https://github.com/AhmxAli07/Railway-Trading-Agent.git
cd Railway-Trading-Agent
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

On Windows Git Bash:

```bash
source .venv/Scripts/activate
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Set environment variables

Windows Git Bash:

```bash
export BINANCE_API_KEY="YOUR_BINANCE_API_KEY"
export BINANCE_SECRET="YOUR_BINANCE_SECRET"
export SLACK_WEBHOOK_URL="YOUR_SLACK_WEBHOOK_URL"
```

### 5. Start the agent

```bash
python main.py
```

---

## 🧪 Example Local Run

Example output from a successful local monitoring cycle:

```text
Pairs     : BNB/USDT | USDC/USDT | BTC/USDT
Strategy  : Buy Dip → Sell at configured profit target
Stop Loss : -0.5% per trade
Hold Time : Random 25–45 min per trade
Capital   : Live Binance USDT balance
PKR Rate  : Live from CoinGecko

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔄 Cycle #1 Starting

💵 Live Capital : 55.86236595 USDT
🇵🇰 In PKR       : Rs15,519.12
💱 PKR Rate      : 1 USDT = Rs277.81

💰 Allocations
• BNB/USDT: 31.98 USDT
• USDC/USDT: 15.74 USDT
• BTC/USDT: 8.14 USDT

⏭️ BNB/USDT — No dip detected. Trade skipped.
⏭️ USDC/USDT — No dip detected. Trade skipped.
⏭️ BTC/USDT — No dip detected. Trade skipped.

🤖 VOLUME BOT — CYCLE #1 REPORT

💸 Total Fees : 0 USDT
📈 Gross P&L  : +0 USDT
🟢 Net P&L    : +0 USDT
💵 Balance    : 55.86 USDT
🇵🇰 PKR        : Rs15,519.12
```

---

## 🚂 Railway Configuration

The repository includes Nixpacks configuration:

```toml
[phases.build]
cmds = ["pip install -r requirements.txt"]

[start]
cmd = "python main.py"
```

Configure the following variables through the Railway project dashboard:

```text
BINANCE_API_KEY
BINANCE_SECRET
SLACK_WEBHOOK_URL
```

---

## ⚙️ Current Strategy Configuration

| Setting | Configuration |
|---|---|
| Trading pairs | BNB/USDT, USDC/USDT, BTC/USDT |
| BNB allocation | 45–60% |
| USDC allocation | 25–35% |
| BTC allocation | 10–20% |
| BNB dip threshold | -0.2% |
| USDC dip threshold | -0.01% |
| BTC dip threshold | -0.2% |
| Take profit | +0.3% |
| Stop loss | -0.5% |
| Hold duration | Random 25–45 minutes |
| Price polling | Every 30 seconds |
| Estimated trading fee | 0.1% |
| Cycle cooldown | Random 8–15 minutes |

---

## 🔑 Binance API Permissions

For live trading, the API key requires the permissions needed to read account
information and place Spot orders.

Recommended:

```text
✅ Read account information
✅ Spot trading
❌ Withdrawals
```

Withdrawal permission is not required by this project and should remain
disabled.

---

## 📲 Slack Reporting

The agent can report:

- Cycle start
- Current USDT and PKR balance
- Dip detection results
- Buy and sell results
- Fees
- Gross P&L
- Net P&L
- Trading volume
- Cycle cooldown

If Slack is not configured, the application can be configured to print these
messages to the local terminal instead.

---

## ⚠️ Risk & Usage Notice

This project is provided for educational purposes.

Users are responsible for:

- Understanding the trading logic
- Securing their API credentials
- Testing changes before live execution
- Following Binance API and regional eligibility requirements
- Complying with applicable laws and exchange terms

No profitability is guaranteed.

---

## 🛠️ Technologies

- Python
- CCXT
- Binance Spot API
- Slack Incoming Webhooks
- Railway
- Nixpacks
