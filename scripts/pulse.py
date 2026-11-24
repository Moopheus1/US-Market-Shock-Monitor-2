import json
import os
import urllib.request
import datetime

# ticker -> key used in data/pulse.json (must match YAHOO_KEY_MAP in index.html)
SYMBOLS = {
    "ES=F":     "es",
    "NQ=F":     "nq",
    "YM=F":     "ym",
    "RTY=F":    "rty",
    "^VIX":     "vix_spot",
    "^TNX":     "tnx",
    "DX-Y.NYB": "dxy_spot",
    "CL=F":     "cl",
}

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MarketShockMonitor/1.0)"}
out = {}
failures = []

for ticker, key in SYMBOLS.items():
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + ticker + "?interval=1d&range=5d"
    )
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
        result = data["chart"]["result"][0]
        meta = result["meta"]
        current = meta.get("regularMarketPrice") or meta.get("previousClose") or meta.get("chartPreviousClose")
        quote = result.get("indicators", {}).get("quote", [{}])[0]; bars = [x for x in (quote.get("close") or []) if x is not None]; previous = (bars[-2] if len(bars) >= 2 else (bars[0] if bars else None)) or meta.get("chartPreviousClose") or meta.get("previousClose") or meta.get("regularMarketPreviousClose")
        # Sanity cap on the day's % move. VIX gets a wide cap: it routinely moves 15-50% on
        # shock days, and the old flat 12% cap dropped it on exactly those days (20 Nov 2026),
        # so the live score stopped matching the Edge Tracker formula, which has no cap.
        cap = 150 if ticker == "^VIX" else 12
        if current is None or previous is None or previous == 0 or abs((current - previous) / previous) * 100 > cap: raise ValueError(f"missing/implausible price (current={current}, previous={previous})")

        mt = meta.get("regularMarketTime")
        out[key] = {"ticker": ticker, "current": current, "previous": previous,
                    # time of the last actual trade/quote - the page leaves a symbol out of the
                    # score when this is 2h+ old, the same rule edge_tracker.py's backtest uses
                    "market_time_utc": datetime.datetime.fromtimestamp(mt, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if mt else None}
        print(f"OK  {ticker} -> current={current} previous={previous}")
    except Exception as e:
        failures.append(ticker)
        print(f"FAIL {ticker}: {e}")

# Overnight 10Y estimate (added 24 Nov 2026, display only - NOT scored).
# Yahoo's ^TNX does not trade before 08:20 ET, so before then the page had no 10Y number.
# The 10Y T-note future (ZN=F) trades ~23h a day. Regression of daily ^TNX change (bp)
# on ZN=F % change, Nov 2024-Nov 2026 (499 days): -15.3 bp per +1% in ZN, corr -0.98,
# residual s.d. ~1 bp. Estimate = last ^TNX close + (-15.3 x ZN % change since its last close).
# The bias score still skips the 10Y before 08:20 ET, exactly as the Edge Tracker backtest does.
BP_PER_PCT_ZN = -15.3
try:
    import zoneinfo
    ny_today = datetime.datetime.now(zoneinfo.ZoneInfo("America/New_York")).date()

    def daily(ticker):
        req = urllib.request.Request("https://query1.finance.yahoo.com/v8/finance/chart/" + ticker + "?interval=1d&range=10d", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            res = json.load(r)["chart"]["result"][0]
        closes = res["indicators"]["quote"][0]["close"]
        bars = [(datetime.datetime.fromtimestamp(t, zoneinfo.ZoneInfo("America/New_York")).date(), c)
                for t, c in zip(res["timestamp"], closes) if c is not None]
        return res["meta"], bars

    zmeta, zbars = daily("ZN=F")
    tmeta, tbars = daily("^TNX")
    zn_now = zmeta.get("regularMarketPrice")
    zn_prev = [c for d, c in zbars if d < ny_today][-1]       # last completed session's close
    tnx_close = [c for d, c in tbars if d < ny_today][-1]     # last completed 10Y close
    zn_pct = (zn_now - zn_prev) / zn_prev * 100
    if abs(zn_pct) > 3:
        raise ValueError(f"implausible ZN move {zn_pct:.2f}%")
    est = tnx_close + BP_PER_PCT_ZN * zn_pct / 100
    out["tnx_est"] = {
        "ticker": "ZN=F", "zn_current": zn_now, "zn_previous": zn_prev,
        "zn_time_utc": datetime.datetime.fromtimestamp(zmeta.get("regularMarketTime", 0), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tnx_close": round(tnx_close, 3), "estimate": round(est, 3),
        "change_bp": round(BP_PER_PCT_ZN * zn_pct, 1), "bp_per_pct": BP_PER_PCT_ZN,
    }
    print(f"OK  10Y estimate {est:.3f}% ({BP_PER_PCT_ZN * zn_pct:+.1f} bp from ZN {zn_prev} -> {zn_now})")
except Exception as e:
    print(f"WARN 10Y estimate unavailable: {e}")

# Live market move (24 Nov 2026): SPY vs yesterday's close, plus SPY at 10:30am ET - the
# page's tested "one hour after the open" check (>0.5% either way: ~9 in 10 closed that way).
# Display only, not part of the score.
try:
    import zoneinfo
    NYZ = zoneinfo.ZoneInfo("America/New_York")
    req = urllib.request.Request("https://query1.finance.yahoo.com/v8/finance/chart/SPY?interval=1m&range=1d", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10) as r:
        res = json.load(r)["chart"]["result"][0]
    m = res["meta"]
    bars = [(datetime.datetime.fromtimestamp(t, NYZ), c) for t, c in zip(res.get("timestamp") or [], res["indicators"]["quote"][0]["close"]) if c is not None]
    spy = {"price": m.get("regularMarketPrice"), "prev_close": m.get("chartPreviousClose"),
           "market_time_utc": datetime.datetime.fromtimestamp(m["regularMarketTime"], datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "session_date": bars[0][0].date().isoformat() if bars else None, "price_1030": None}
    # close of the 10:29 one-minute bar = last price of the first hour; only once 10:30 has passed
    if bars and (bars[-1][0].hour, bars[-1][0].minute) >= (10, 30):
        first_hour = [c for d, c in bars if (d.hour, d.minute) < (10, 30)]
        spy["price_1030"] = first_hour[-1] if first_hour else None
    out["spy_live"] = spy
    print(f"OK  SPY live {spy['price']} vs prev close {spy['prev_close']} (10:30 price {spy['price_1030']})")
except Exception as e:
    print(f"WARN SPY live unavailable: {e}")

out["_lastUpdated"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
out["_failedSymbols"] = failures

os.makedirs("data", exist_ok=True)
with open("data/pulse.json", "w") as f:
    json.dump(out, f, indent=2)

print(f"\n{len(SYMBOLS) - len(failures)}/{len(SYMBOLS)} symbols fetched OK. Failed: {failures}")

# Fail the job loudly if EVERYTHING failed - a partial-failure commit is fine
# (stale-but-real data beats nothing), but a full failure means Yahoo blocked us
# or the endpoint changed, and you want that surfaced in the Actions tab, not
# silently committed as an empty file.
if len(failures) == len(SYMBOLS):
    raise SystemExit("All symbols failed - not committing an empty pulse.json")
