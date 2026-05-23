import ccxt
import time
import random
import requests
from datetime import datetime
import os

# =============================================================
# CONFIG
# =============================================================

BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY", "rcCZpy9TD4f2KJ9wzvBnrtUdCaX4ny205uPTbKQmMTaiebUet5KVmHMrY9Z2wvyr")
BINANCE_SECRET     = os.getenv("BINANCE_SECRET", "I573pDLsdjhVNWsRrjfHVpRvand6yM82fhC2VnXMEJJxxTS3dX1fRuNWrt8CW65h")
# SLACK_WEBHOOK_URL  = os.getenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/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")


PKR_RATE       = 281.0          # Updated live each cycle from CoinGecko
PAIRS          = ["BNB/USDT", "USDC/USDT", "BTC/USDT"]

# ⚠️ TOTAL_CAPITAL is NOT fixed — bot reads live USDT balance each cycle
# This handles fee erosion automatically (57 → 56.8 → 56.5 etc)

ALLOCATION_RANGES = {
    "BNB/USDT":  (0.45, 0.60),
    "USDC/USDT": (0.25, 0.35),
    "BTC/USDT":  (0.10, 0.20),
}

PROFIT_TARGET    = 0.003         # +0.3% take profit
STOP_LOSS        = 0.005         # -0.5% stop loss
MIN_HOLD_MINUTES = 25            # minimum hold time
MAX_HOLD_MINUTES = 45            # maximum hold time (random each trade → 25–45 min)
POLL_INTERVAL    = 30            # price check every 30 seconds
BINANCE_FEE_RATE = 0.001         # 0.1% per trade (taker fee)

# Per-pair dip thresholds
# USDC/USDT is stable — 0.01% threshold so dip triggers fast
# BNB and BTC use the original 0.2% dip requirement
DIP_THRESHOLDS = {
    "BNB/USDT":  0.002,   # -0.2% dip required
    "USDC/USDT": 0.0001,  # -0.01% dip (stable pair — triggers immediately)
    "BTC/USDT":  0.002,   # -0.2% dip required
}

# Fee-aware minimum net profit to trigger take-profit
MIN_NET_PROFIT_USDT = 0.0005    # Must clear at least 0.05 cents net after fees

# =============================================================
# BINANCE SETUP
# =============================================================

exchange = ccxt.binance({
    "apiKey":          BINANCE_API_KEY,
    "secret":          BINANCE_SECRET,
    "enableRateLimit": True,
    "options": {
        "defaultType":      "spot",
        # Disable fetch_currencies — this stops CCXT from calling
        # /sapi/v1/capital/config/getall which is geo-restricted
        # on cloud servers. We don't need currency info for spot trading.
        "fetchCurrencies":  False,
    }
})

# =============================================================
# SLACK
# =============================================================

def send_slack(message: str):
    try:
        r = requests.post(SLACK_WEBHOOK_URL, json={"text": message}, timeout=10)
        if r.status_code != 200:
            print(f"[Slack error] {r.status_code}")
    except Exception as e:
        print(f"[Slack error] {e}")

# =============================================================
# LIVE PKR RATE — fetched from CoinGecko each cycle
# =============================================================

def get_pkr_rate() -> float:
    """Fetch live USDT/PKR rate. Falls back to 281 if fails."""
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "tether", "vs_currencies": "pkr"},
            timeout=8
        )
        data = r.json()
        rate = float(data["tether"]["pkr"])
        print(f"[PKR Rate] Live rate fetched: {rate}")
        return rate
    except Exception as e:
        print(f"[PKR Rate] Fallback to 281. Error: {e}")
        return 281.0

# =============================================================
# LIVE BALANCE — reads actual USDT from Binance each cycle
# FIX: uses /api/v3/account (unrestricted) instead of
#      /sapi/v1/capital/config/getall (geo-restricted endpoint)
# =============================================================

def get_live_capital() -> float:
    """Always reads actual free USDT — accounts for fees automatically."""
    balance = exchange.fetch_balance(params={"type": "spot"})
    usdt = float(balance["USDT"]["free"])
    print(f"[Capital] Live USDT balance: {usdt}")
    return usdt

# =============================================================
# ALLOCATION RANDOMIZER — based on live balance, not fixed 57
# =============================================================

def randomize_allocations(total: float) -> dict:
    raw          = {p: random.uniform(lo, hi) for p, (lo, hi) in ALLOCATION_RANGES.items()}
    total_weight = sum(raw.values())
    normalized   = {p: w / total_weight for p, w in raw.items()}
    amounts      = {}
    allocated    = 0.0
    pairs        = list(normalized.keys())
    for i, pair in enumerate(pairs):
        if i == len(pairs) - 1:
            amounts[pair] = round(total - allocated, 2)
        else:
            amounts[pair]  = round(normalized[pair] * total, 2)
            allocated     += amounts[pair]
    return amounts

# =============================================================
# PRICE HELPERS
# =============================================================

def get_price(symbol: str) -> float:
    ticker = exchange.fetch_ticker(symbol)
    return float(ticker["last"])

def get_recent_prices(symbol: str, limit: int = 10) -> list:
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe="1m", limit=limit)
    return [candle[4] for candle in ohlcv]

def detect_dip(symbol: str) -> tuple:
    prices      = get_recent_prices(symbol, limit=10)
    recent_high = max(prices[:-1])           # highest close from candles 1–9
    current     = get_price(symbol)          # live ticker price, not stale candle close
    threshold   = DIP_THRESHOLDS.get(symbol, 0.002)
    dip_pct     = (recent_high - current) / recent_high
    return dip_pct >= threshold, round(dip_pct * 100, 4)

# =============================================================
# BUY & SELL — precision-safe, no quoteOrderQty
# =============================================================

def buy_market(symbol: str, usdt_amount: float) -> dict:
    """Convert USDT → base asset qty with Binance precision rules."""
    price    = get_price(symbol)
    raw_qty  = usdt_amount / price
    quantity = float(exchange.amount_to_precision(symbol, raw_qty))
    order    = exchange.create_market_buy_order(symbol, quantity)
    return order

def sell_market(symbol: str, quantity: float) -> dict:
    qty   = float(exchange.amount_to_precision(symbol, quantity))
    order = exchange.create_market_sell_order(symbol, qty)
    return order

# =============================================================
# FEE CALCULATOR
# =============================================================

def calc_fees(buy_price: float, sell_price: float, quantity: float) -> dict:
    buy_value   = buy_price  * quantity
    sell_value  = sell_price * quantity
    buy_fee     = round(buy_value  * BINANCE_FEE_RATE, 6)
    sell_fee    = round(sell_value * BINANCE_FEE_RATE, 6)
    total_fee   = round(buy_fee + sell_fee, 6)
    return {
        "buy_fee_usdt":   buy_fee,
        "sell_fee_usdt":  sell_fee,
        "total_fee_usdt": total_fee,
    }

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
# SINGLE TRADE CYCLE
# =============================================================

def run_trade_cycle(symbol: str, usdt_amount: float, pkr_rate: float) -> dict:

    hold_seconds = random.randint(MIN_HOLD_MINUTES * 60, MAX_HOLD_MINUTES * 60)

    result = {
        "symbol":          symbol,
        "usdt_amount":     usdt_amount,
        "buy_price":       None,
        "sell_price":      None,
        "quantity":        None,
        "pnl_usdt":        None,
        "pnl_pct":         None,
        "fee_breakdown":   None,
        "net_pnl_usdt":    None,
        "reason":          None,
        "status":          "pending",
        "buy_time":        None,
        "sell_time":       None,
        "hold_minutes":    round(hold_seconds / 60, 1),
    }

    # ── Step 1: Wait for dip (max 5 min) ──────────────────────
    dip_detected = False
    dip_wait     = 0
    while dip_wait < 300:
        try:
            is_dip, dip_pct = detect_dip(symbol)
            if is_dip:
                print(f"[{symbol}] Dip detected: {dip_pct}% — buying!")
                dip_detected = True
                break
            else:
                print(f"[{symbol}] No dip ({dip_pct}%), waiting 20s...")
        except Exception as e:
            print(f"[{symbol}] Dip error: {e}")
        time.sleep(20)
        dip_wait += 20

    # Skip trade if no dip found — capital preserved
    if not dip_detected:
        result["status"] = "skipped"
        result["reason"] = "no_dip_detected"
        print(f"[{symbol}] ⏭️  No dip after 5 min — skipping trade. Capital preserved.")
        send_slack(f"⏭️ *{symbol}* — No dip detected after 5 min. Trade skipped. Capital preserved.")
        return result

    # ── Step 2: BUY ───────────────────────────────────────────
    try:
        buy_order = buy_market(symbol, usdt_amount)

        # fetch_order() for real fill price — avoids corrupted PnL
        buy_price = float(buy_order.get("average") or 0)
        if not buy_price:
            try:
                order_id   = buy_order["id"]
                order_info = exchange.fetch_order(order_id, symbol)
                buy_price  = float(order_info["average"])
                print(f"[{symbol}] Buy price from fetch_order: {buy_price}")
            except Exception as fe:
                buy_price = float(buy_order.get("price") or 0)
                print(f"[{symbol}] fetch_order failed, using order price: {buy_price}. Error: {fe}")

        quantity = float(
            buy_order.get("filled") or
            buy_order.get("amount")
        )
        result["buy_price"] = buy_price
        result["quantity"]  = quantity
        result["buy_time"]  = datetime.utcnow().strftime("%H:%M:%S UTC")
        result["status"]    = "bought"
        print(f"[{symbol}] ✅ Bought {quantity} @ {buy_price} | Hold: {result['hold_minutes']} min")
    except Exception as e:
        result["status"] = "buy_failed"
        result["reason"] = str(e)
        print(f"[{symbol}] ❌ BUY FAILED: {e}")
        return result

    # ── Step 3: MONITOR — profit / stop-loss / timeout ────────
    start_time = time.time()
    while True:
        elapsed = time.time() - start_time
        try:
            current_price = get_price(symbol)
            change_pct    = (current_price - buy_price) / buy_price
            print(f"[{symbol}] Price: {current_price} | Change: {round(change_pct*100,3)}% | Elapsed: {round(elapsed/60,1)}min")

            # Fee-aware take-profit — only exit if net profit clears minimum
            if change_pct >= PROFIT_TARGET:
                estimated_fees = calc_fees(buy_price, current_price, quantity)
                gross_profit   = (current_price - buy_price) * quantity
                net_profit     = gross_profit - estimated_fees["total_fee_usdt"]
                if net_profit >= MIN_NET_PROFIT_USDT:
                    result["reason"] = "take_profit"
                    break
                else:
                    print(f"[{symbol}] ⚠️  +0.3% reached but net {round(net_profit,6)} USDT < min. Holding...")

            if change_pct <= -STOP_LOSS:
                result["reason"] = "stop_loss"
                break
            if elapsed >= hold_seconds:
                result["reason"] = "timeout"
                break
        except Exception as e:
            print(f"[{symbol}] Poll error: {e}")
        time.sleep(POLL_INTERVAL)

    # ── Step 4: SELL — retry circuit breaker (3 attempts) ─────
    sell_order   = None
    sell_success = False
    for attempt in range(1, 4):
        try:
            sell_order   = sell_market(symbol, quantity)
            sell_success = True
            print(f"[{symbol}] ✅ Sell succeeded on attempt {attempt}")
            break
        except Exception as e:
            print(f"[{symbol}] ❌ Sell attempt {attempt}/3 failed: {e}")
            if attempt < 3:
                time.sleep(10)

    if not sell_success:
        critical_msg = (
            f"🚨 *CRITICAL — SELL FAILED 3x* 🚨\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"  Pair     : {symbol}\n"
            f"  Quantity : {quantity}\n"
            f"  Buy Price: {buy_price}\n"
            f"  Action   : ⚠️ MANUAL SELL REQUIRED on Binance NOW\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        send_slack(critical_msg)
        result["status"] = "sell_failed_critical"
        result["reason"] = "sell_failed_after_3_attempts"
        return result

    # fetch_order() for real sell fill price
    sell_price = float(sell_order.get("average") or 0)
    if not sell_price:
        try:
            sell_order_id   = sell_order["id"]
            sell_order_info = exchange.fetch_order(sell_order_id, symbol)
            sell_price      = float(sell_order_info["average"])
        except Exception as fe:
            sell_price = float(sell_order.get("price") or 0)
            print(f"[{symbol}] fetch_order (sell) failed: {fe}")

    fees      = calc_fees(buy_price, sell_price, quantity)
    gross_pnl = (sell_price - buy_price) * quantity
    net_pnl   = gross_pnl - fees["total_fee_usdt"]

    result["sell_price"]    = sell_price
    result["sell_time"]     = datetime.utcnow().strftime("%H:%M:%S UTC")
    result["pnl_usdt"]      = round(gross_pnl, 4)
    result["pnl_pct"]       = round((sell_price - buy_price) / buy_price * 100, 4)
    result["fee_breakdown"] = fees
    result["net_pnl_usdt"]  = round(net_pnl, 4)
    result["status"]        = "sold"
    print(f"[{symbol}] ✅ Sold @ {sell_price} | Net PnL: {round(net_pnl,4)} USDT")

    return result

# =============================================================
# SLACK REPORT
# =============================================================

def build_slack_report(
    cycle: int,
    allocations: dict,
    results: list,
    total_volume: float,
    usdt_balance: float,
    pkr_rate: float
) -> str:

    pkr_balance    = round(usdt_balance * pkr_rate, 2)
    total_gross    = round(sum(r["pnl_usdt"]     or 0 for r in results), 4)
    total_net      = round(sum(r["net_pnl_usdt"] or 0 for r in results), 4)
    total_fees     = round(sum((r["fee_breakdown"]["total_fee_usdt"] if r.get("fee_breakdown") else 0) for r in results), 6)
    total_fees_pkr = round(total_fees * pkr_rate, 2)
    net_emoji      = "🟢" if total_net >= 0 else "🔴"

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🤖 *VOLUME BOT — CYCLE #{cycle} REPORT*",
        f"🕒 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "💰 *ALLOCATION THIS CYCLE*",
    ]
    for pair, amt in allocations.items():
        pct = round(amt / usdt_balance * 100, 1)
        lines.append(f"  • {pair}: {amt} USDT  ({pct}% of balance)")

    lines += ["", "📊 *TRADE RESULTS*", ""]

    for r in results:
        sym    = r["symbol"]
        status = r["status"]

        if status == "sold":
            fees        = r["fee_breakdown"]
            gross       = r["pnl_usdt"]
            net         = r["net_pnl_usdt"]
            g_sign      = "+" if gross >= 0 else ""
            n_sign      = "+" if net   >= 0 else ""
            trade_emoji = "✅" if net >= 0 else "⚠️"

            buy_fee_pkr  = round(fees["buy_fee_usdt"]   * pkr_rate, 1)
            sell_fee_pkr = round(fees["sell_fee_usdt"]  * pkr_rate, 1)
            total_f_pkr  = round(fees["total_fee_usdt"] * pkr_rate, 1)

            reason_map = {
                "take_profit": "🎯 Take Profit (+0.3%)",
                "stop_loss":   "🛡️ Stop Loss (-0.5%)",
                "timeout":     f"⏱️ Timeout ({r['hold_minutes']} min)",
            }

            lines += [
                f"  {trade_emoji} *{sym}*",
                f"     Allocated   : {r['usdt_amount']} USDT",
                f"     Buy Price   : {r['buy_price']} USDT",
                f"     Sell Price  : {r['sell_price']} USDT",
                f"     Quantity    : {r['quantity']}",
                f"     Gross P&L   : {g_sign}{gross} USDT  ({g_sign}{r['pnl_pct']}%)",
                f"     🏦 Buy Fee  : {fees['buy_fee_usdt']} USDT  (≈ Rs{buy_fee_pkr})",
                f"     🏦 Sell Fee : {fees['sell_fee_usdt']} USDT  (≈ Rs{sell_fee_pkr})",
                f"     🏦 Total Fee: {fees['total_fee_usdt']} USDT  (≈ Rs{total_f_pkr})",
                f"     Net P&L     : {n_sign}{net} USDT",
                f"     Exit Reason : {reason_map.get(r['reason'], r['reason'])}",
                f"     Hold Time   : {r['hold_minutes']} min",
                f"     Time        : {r['buy_time']} → {r['sell_time']}",
                "",
            ]
        elif status == "buy_failed":
            lines += [f"  ❌ *{sym}* — BUY FAILED", f"     Reason: {r['reason']}", ""]
        elif status == "sell_failed_critical":
            lines += [
                f"  🚨 *{sym}* — SELL FAILED (3 ATTEMPTS) — MANUAL ACTION REQUIRED",
                f"     Quantity: {r.get('quantity','N/A')} | Buy Price: {r.get('buy_price','N/A')}",
                "",
            ]
        elif status == "skipped":
            lines += [f"  ⏭️ *{sym}* — SKIPPED (no dip detected in 5 min)", ""]
        else:
            lines += [f"  ⚪ *{sym}* — {status}", ""]

    lines += [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"💸 *TOTAL FEES PAID  :* {total_fees} USDT  (≈ Rs{total_fees_pkr})",
        f"📈 *GROSS CYCLE P&L  :* {'+' if total_gross >= 0 else ''}{total_gross} USDT",
        f"{net_emoji} *NET CYCLE P&L    :* {'+' if total_net >= 0 else ''}{total_net} USDT",
        f"📊 *TOTAL VOLUME     :* {round(total_volume, 2)} USDT",
        f"💵 *USDT BALANCE     :* {round(usdt_balance, 2)} USDT",
        f"🇵🇰 *PKR BALANCE      :* Rs{pkr_balance:,.2f}",
        f"💱 *LIVE PKR RATE    :* 1 USDT = Rs{pkr_rate}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    return "\n".join(lines)

# =============================================================
# MAIN LOOP
# =============================================================

def run_bot():

    send_slack(
        "🚀 *Volume Bot v4 — LIVE*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Pairs    : BNB/USDT | USDC/USDT | BTC/USDT\n"
        "Strategy : Buy Dip (-0.2%) → Sell +0.3% profit\n"
        "Stop Loss: -0.5% per trade\n"
        "Hold Time: Random 25–45 min per trade\n"
        "Capital  : Live balance (auto-adjusts for fees)\n"
        "PKR Rate : Live from CoinGecko\n"
        "Fix      : Balance endpoint geo-restriction resolved ✅\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    cycle_count = 0

    while True:
        cycle_count += 1

        try:
            pkr_rate     = get_pkr_rate()
            live_capital = get_live_capital()
        except Exception as e:
            send_slack(f"❌ Could not fetch balance/PKR rate: {e}")
            time.sleep(60)
            continue

        pkr_total = round(live_capital * pkr_rate, 2)

        send_slack(
            f"🔄 *Cycle #{cycle_count} Starting*\n"
            f"💵 Live Capital : {live_capital} USDT\n"
            f"🇵🇰 In PKR       : Rs{pkr_total:,.2f}\n"
            f"💱 PKR Rate     : 1 USDT = Rs{pkr_rate}"
        )

        allocations = randomize_allocations(live_capital)
        alloc_lines = "\n".join(
            f"  • {p}: {a} USDT  ({round(a/live_capital*100,1)}%)"
            for p, a in allocations.items()
        )
        send_slack(f"💰 *Allocations — Cycle #{cycle_count}*\n{alloc_lines}")

        results = []
        for pair in PAIRS:
            amt = allocations[pair]
            send_slack(f"⏳ *{pair}* — Entering with {amt} USDT...")
            result = run_trade_cycle(pair, amt, pkr_rate)
            results.append(result)

            pause = random.randint(60, 180)
            print(f"[Bot] Pausing {pause}s before next pair...")
            time.sleep(pause)

        try:
            total_volume = calculate_total_volume()
            usdt_balance = get_live_capital()
        except Exception as e:
            total_volume = 0.0
            usdt_balance = live_capital
            print(f"[Stats error] {e}")

        report = build_slack_report(
            cycle        = cycle_count,
            allocations  = allocations,
            results      = results,
            total_volume = total_volume,
            usdt_balance = usdt_balance,
            pkr_rate     = pkr_rate
        )
        send_slack(report)

        cooldown = random.randint(480, 900)
        cd_min   = round(cooldown / 60, 1)
        send_slack(f"😴 *Cycle #{cycle_count} complete. Cooldown: {cd_min} min...*")
        time.sleep(cooldown)


if __name__ == "__main__":
    run_bot()
