import ccxt
import time
import random
import requests
from datetime import datetime

# =============================================================
# CONFIG — SET YOUR ENV VARIABLES ON RAILWAY
# =============================================================

import os

BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY", "rcCZpy9TD4f2KJ9wzvBnrtUdCaX4ny205uPTbKQmMTaiebUet5KVmHMrY9Z2wvyr")
BINANCE_SECRET     = os.getenv("BINANCE_SECRET", "I573pDLsdjhVNWsRrjfHVpRvand6yM82fhC2VnXMEJJxxTS3dX1fRuNWrt8CW65h")
SLACK_WEBHOOK_URL  = os.getenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/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")

# PKR conversion rate (update if needed)
PKR_RATE = 281.0

# Trading pairs in PRIORITY order
PAIRS = ["BNB/USDT", "USDC/USDT", "BTC/USDT"]

# Total capital in USDT
TOTAL_CAPITAL = 57.0

# Priority allocation ranges (min%, max%) — bot randomizes within
ALLOCATION_RANGES = {
    "BNB/USDT":  (0.45, 0.60),   # ~45–60% → highest priority
    "USDC/USDT": (0.25, 0.35),   # ~25–35% → mid priority
    "BTC/USDT":  (0.10, 0.20),   # ~10–20% → lowest priority
}

# Strategy params
PROFIT_TARGET    = 0.003   # +0.3% → take profit
STOP_LOSS        = 0.005   # -0.5% → cut loss
CYCLE_MINUTES    = 30      # max hold time per cycle (minutes)
CYCLE_SECONDS    = CYCLE_MINUTES * 60
POLL_INTERVAL    = 30      # check price every 30 seconds
DIP_THRESHOLD    = 0.002   # wait for at least -0.2% dip before buying

# =============================================================
# BINANCE SETUP
# =============================================================

exchange = ccxt.binance({
    "apiKey":         BINANCE_API_KEY,
    "secret":         BINANCE_SECRET,
    "enableRateLimit": True,
    "options": {
        "defaultType": "spot"
    }
})

# =============================================================
# SLACK NOTIFIER
# =============================================================

def send_slack(message: str):
    try:
        payload = {"text": message}
        r = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        if r.status_code != 200:
            print(f"[Slack error] {r.status_code}: {r.text}")
    except Exception as e:
        print(f"[Slack exception] {e}")

# =============================================================
# ALLOCATION RANDOMIZER
# =============================================================

def randomize_allocations(total: float) -> dict:
    """
    Randomize amounts within priority ranges.
    BNB gets most, USDC mid, BTC least.
    Ensures total stays within budget.
    """
    raw = {}
    for pair, (lo, hi) in ALLOCATION_RANGES.items():
        raw[pair] = random.uniform(lo, hi)

    # Normalize so they sum to 1.0
    total_weight = sum(raw.values())
    normalized = {p: w / total_weight for p, w in raw.items()}

    # Apply to capital — round to 2 decimals
    amounts = {}
    allocated = 0.0
    pairs = list(normalized.keys())
    for i, pair in enumerate(pairs):
        if i == len(pairs) - 1:
            amounts[pair] = round(total - allocated, 2)
        else:
            amounts[pair] = round(normalized[pair] * total, 2)
            allocated += amounts[pair]

    return amounts

# =============================================================
# PRICE HELPERS
# =============================================================

def get_price(symbol: str) -> float:
    ticker = exchange.fetch_ticker(symbol)
    return float(ticker["last"])

def get_recent_prices(symbol: str, limit: int = 10) -> list:
    """Returns closing prices from last `limit` 1-min candles."""
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe="1m", limit=limit)
    return [candle[4] for candle in ohlcv]

def detect_dip(symbol: str) -> tuple:
    """
    Returns (is_dip: bool, dip_pct: float)
    Dip = current price is DIP_THRESHOLD% below recent high.
    """
    prices = get_recent_prices(symbol, limit=10)
    recent_high = max(prices[:-1])   # high of last 9 candles
    current     = prices[-1]
    dip_pct     = (recent_high - current) / recent_high
    return dip_pct >= DIP_THRESHOLD, dip_pct

# =============================================================
# TRADE FUNCTIONS
# =============================================================

def buy_market(symbol: str, usdt_amount: float) -> dict:
    """Buy `usdt_amount` worth of `symbol` at market price."""
    # For BTC/BNB we pass quoteOrderQty; for USDC we pass amount directly
    order = exchange.create_order(
        symbol   = symbol,
        type     = "market",
        side     = "buy",
        amount   = None,
        params   = {"quoteOrderQty": usdt_amount}
    )
    return order

def sell_market(symbol: str, quantity: float) -> dict:
    """Sell exact `quantity` of base asset at market price."""
    order = exchange.create_market_sell_order(symbol, quantity)
    return order

# =============================================================
# VOLUME CALCULATOR
# =============================================================

def calculate_total_volume() -> float:
    total = 0.0
    for pair in PAIRS:
        try:
            trades = exchange.fetch_my_trades(pair, limit=50)
            for t in trades:
                total += float(t.get("cost", 0))
        except Exception:
            pass
    return total

# =============================================================
# BALANCE CHECKER
# =============================================================

def get_usdt_balance() -> float:
    balance = exchange.fetch_balance()
    return float(balance["USDT"]["free"])

# =============================================================
# SINGLE TRADE CYCLE
# =============================================================

def run_trade_cycle(symbol: str, usdt_amount: float) -> dict:
    """
    1. Wait for dip
    2. Buy
    3. Monitor for +0.3% profit OR -0.5% stop-loss OR timeout
    4. Sell
    Returns result dict with all trade info.
    """
    result = {
        "symbol":       symbol,
        "usdt_amount":  usdt_amount,
        "buy_price":    None,
        "sell_price":   None,
        "quantity":     None,
        "pnl_usdt":     None,
        "pnl_pct":      None,
        "reason":       None,
        "status":       "pending",
        "buy_time":     None,
        "sell_time":    None,
    }

    # ── Step 1: Wait for dip (max 5 minutes) ──────────────────
    dip_wait = 0
    while dip_wait < 300:
        try:
            is_dip, dip_pct = detect_dip(symbol)
            if is_dip:
                break
        except Exception as e:
            print(f"[{symbol}] Dip check error: {e}")
        time.sleep(20)
        dip_wait += 20

    # ── Step 2: BUY ───────────────────────────────────────────
    try:
        buy_order = buy_market(symbol, usdt_amount)
        buy_price = float(buy_order.get("average") or buy_order.get("price") or get_price(symbol))
        quantity  = float(buy_order.get("filled") or buy_order.get("amount"))

        result["buy_price"] = buy_price
        result["quantity"]  = quantity
        result["buy_time"]  = datetime.utcnow().strftime("%H:%M:%S UTC")
        result["status"]    = "bought"
    except Exception as e:
        result["status"] = "buy_failed"
        result["reason"] = str(e)
        return result

    # ── Step 3: MONITOR ───────────────────────────────────────
    start_time = time.time()
    while True:
        elapsed = time.time() - start_time

        try:
            current_price = get_price(symbol)
            change_pct    = (current_price - buy_price) / buy_price

            # Take profit
            if change_pct >= PROFIT_TARGET:
                result["reason"] = "take_profit"
                break

            # Stop loss
            if change_pct <= -STOP_LOSS:
                result["reason"] = "stop_loss"
                break

            # Timeout
            if elapsed >= CYCLE_SECONDS:
                result["reason"] = "timeout"
                break

        except Exception as e:
            print(f"[{symbol}] Price poll error: {e}")

        time.sleep(POLL_INTERVAL)

    # ── Step 4: SELL ──────────────────────────────────────────
    try:
        sell_order = sell_market(symbol, quantity)
        sell_price = float(sell_order.get("average") or sell_order.get("price") or get_price(symbol))

        pnl_usdt = (sell_price - buy_price) * quantity
        pnl_pct  = (sell_price - buy_price) / buy_price * 100

        result["sell_price"] = sell_price
        result["sell_time"]  = datetime.utcnow().strftime("%H:%M:%S UTC")
        result["pnl_usdt"]   = round(pnl_usdt, 4)
        result["pnl_pct"]    = round(pnl_pct, 4)
        result["status"]     = "sold"
    except Exception as e:
        result["status"] = "sell_failed"
        result["reason"] = str(e)

    return result

# =============================================================
# SLACK REPORT BUILDER
# =============================================================

def build_slack_report(allocations: dict, results: list, total_volume: float, usdt_balance: float) -> str:

    pkr_balance = round(usdt_balance * PKR_RATE, 2)
    total_pnl   = sum(r["pnl_usdt"] for r in results if r["pnl_usdt"] is not None)
    total_pnl   = round(total_pnl, 4)
    pnl_emoji   = "🟢" if total_pnl >= 0 else "🔴"

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━",
        "🤖 *VOLUME BOT — CYCLE REPORT*",
        f"🕒 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "💰 *ALLOCATION THIS CYCLE*",
    ]

    for pair, amt in allocations.items():
        pct = round(amt / TOTAL_CAPITAL * 100, 1)
        lines.append(f"  • {pair}: {amt} USDT ({pct}%)")

    lines += ["", "📊 *TRADE RESULTS*"]

    for r in results:
        sym    = r["symbol"]
        status = r["status"]

        if status == "sold":
            sign   = "+" if r["pnl_usdt"] >= 0 else ""
            emoji  = "✅" if r["pnl_usdt"] >= 0 else "⚠️"
            reason_map = {
                "take_profit": "🎯 Take Profit",
                "stop_loss":   "🛡 Stop Loss",
                "timeout":     "⏱ Timeout",
            }
            reason_label = reason_map.get(r["reason"], r["reason"])
            lines += [
                f"  {emoji} *{sym}*",
                f"     Allocated : {r['usdt_amount']} USDT",
                f"     Buy Price : {r['buy_price']}",
                f"     Sell Price: {r['sell_price']}",
                f"     Qty       : {r['quantity']}",
                f"     P&L       : {sign}{r['pnl_usdt']} USDT ({sign}{r['pnl_pct']}%)",
                f"     Exit Reason: {reason_label}",
                f"     Time      : {r['buy_time']} → {r['sell_time']}",
            ]
        elif status == "buy_failed":
            lines += [f"  ❌ *{sym}* — BUY FAILED: {r['reason']}"]
        elif status == "sell_failed":
            lines += [f"  ❌ *{sym}* — SELL FAILED: {r['reason']}"]
        else:
            lines += [f"  ⚪ *{sym}* — {status}"]

    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"{pnl_emoji} *CYCLE P&L     :* {'+' if total_pnl >= 0 else ''}{total_pnl} USDT",
        f"📈 *TOTAL VOLUME :* {round(total_volume, 2)} USDT",
        f"💵 *USDT BALANCE :* {round(usdt_balance, 2)} USDT",
        f"🇵🇰 *PKR BALANCE  :* {pkr_balance:,} PKR",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]

    return "\n".join(lines)

# =============================================================
# MAIN BOT LOOP
# =============================================================

def run_bot():
    send_slack("🚀 *Volume Bot Started!*\nPairs: BNB/USDT | USDC/USDT | BTC/USDT\nCapital: 57 USDT\nStrategy: Buy Dip → +0.3% Profit | -0.5% Stop Loss")

    cycle_count = 0

    while True:
        cycle_count += 1
        send_slack(f"🔄 *Cycle #{cycle_count} starting...*")

        # ── Randomize allocations ────────────────────────────
        allocations = randomize_allocations(TOTAL_CAPITAL)

        alloc_msg = "💰 *Allocations this cycle:*\n" + "\n".join(
            f"  • {p}: {a} USDT" for p, a in allocations.items()
        )
        send_slack(alloc_msg)

        # ── Run all 3 trades (sequentially) ─────────────────
        # Sequential is safer for 57 USDT — avoids splitting thin balance
        results = []
        for pair in PAIRS:
            amt = allocations[pair]
            send_slack(f"⏳ *Trading {pair}* with {amt} USDT...")
            result = run_trade_cycle(pair, amt)
            results.append(result)

            # Brief random pause between trades (looks human)
            pause = random.randint(45, 120)
            time.sleep(pause)

        # ── Fetch final stats ────────────────────────────────
        try:
            total_volume  = calculate_total_volume()
            usdt_balance  = get_usdt_balance()
        except Exception as e:
            total_volume  = 0.0
            usdt_balance  = 0.0
            print(f"[Stats error] {e}")

        # ── Send full Slack report ───────────────────────────
        report = build_slack_report(allocations, results, total_volume, usdt_balance)
        send_slack(report)

        # ── Random cooldown between cycles (8–15 min) ────────
        cooldown = random.randint(480, 900)
        send_slack(f"😴 *Cooldown:* {cooldown // 60} min before next cycle...")
        time.sleep(cooldown)


# =============================================================
# ENTRY POINT
# =============================================================

if __name__ == "__main__":
    run_bot()
