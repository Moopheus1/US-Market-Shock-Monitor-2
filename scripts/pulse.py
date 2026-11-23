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

        out[key] = {"ticker": ticker, "current": current, "previous": previous}
        print(f"OK  {ticker} -> current={current} previous={previous}")
    except Exception as e:
        failures.append(ticker)
        print(f"FAIL {ticker}: {e}")

out["_lastUpdated"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
out["_failedSymbols"] = failures

os.makedirs("data", exist_ok=True)
with open("data/pulse.json", "w") as f:
    json.dump(out, f, indent=2)

print(f"\n{len(out) - 2}/{len(SYMBOLS)} symbols fetched OK. Failed: {failures}")

# Fail the job loudly if EVERYTHING failed - a partial-failure commit is fine
# (stale-but-real data beats nothing), but a full failure means Yahoo blocked us
# or the endpoint changed, and you want that surfaced in the Actions tab, not
# silently committed as an empty file.
if len(failures) == len(SYMBOLS):
    raise SystemExit("All symbols failed - not committing an empty pulse.json")
