"""Gold (GC=F) and Bitcoin (BTC-USD) reference cards for v2 (24 Nov 2026).

Same calculation and JSON schema as v1's fetch-gold.yml / fetch-crypto.yml, which run on
a twice-daily GitHub cron that GitHub has been skipping (24 Nov: both cards still showed
the previous day at 11pm SGT). v2 runs this every 15 min inside the pulse loop and
publishes to the pulse-data branch; the page takes the newer of v2's and v1's file.
Reference only - not scored in Part I or Part II.
"""
import datetime
import json
import os
import urllib.request

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MarketShockMonitor/1.0)"}
JOBS = [("GC=F", "data/gold.json", "Yahoo Finance (GC=F, COMEX gold futures)"),
        ("BTC-USD", "data/bitcoin.json", "Yahoo Finance (BTC-USD)")]
os.makedirs("data", exist_ok=True)
ok = 0
for ticker, path, source in JOBS:
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1mo"
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=15) as r:
            res = json.load(r)["chart"]["result"][0]
        pts = [(t, c) for t, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]) if c is not None]
        if len(pts) < 2:
            raise ValueError("not enough data points returned")
        cur, prev = pts[-1][1], pts[-2][1]

        def back(n):
            return None if len(pts) <= n else (cur - pts[-1 - n][1]) / pts[-1 - n][1] * 100

        out = {"price": cur, "prevClose": prev, "changePct": (cur - prev) / prev * 100,
               "change5d": back(5), "change20d": back(20), "_lastUpdated": now,
               "_source": source, "_fetchFailed": False}
        json.dump(out, open(path, "w"), indent=2)
        ok += 1
        print(f"OK  {ticker} = {cur:.2f}, day {out['changePct']:+.2f}%")
    except Exception as e:
        # keep the last good file rather than publishing a failure over it
        print(f"FAIL {ticker}: {e}")
if ok == 0:
    raise SystemExit("both reference fetches failed")
