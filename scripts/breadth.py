"""Buy/sell volume proxy for v2 (moved here from v1's fetch-breadth.yml on 24 Nov 2026).

v1's version runs on a */15 GitHub cron, which GitHub throttles: on 24 Nov its newest
file was Monday's data, written 08:31 SGT, still shown 20+ min after Tuesday's open.
v2 now runs this inside the 5-min pulse loop (fetch-pulse.yml) and publishes to the
pulse-data branch. Same method as v1 (1-min bar direction, SPY/QQQ/DIA/IWM, Yahoo),
except bars are limited to the first 4 trading hours (9:30am-1:30pm ET), as the page
label says, so a later run can't change the number. Context only - not scored.
"""
import datetime
import json
import os
import urllib.request
import zoneinfo

NY = zoneinfo.ZoneInfo("America/New_York")
SYMBOLS = {"SPY": "S&P 500", "QQQ": "NASDAQ 100", "DIA": "Dow 30", "IWM": "Russell 2000"}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MarketShockMonitor/1.0)"}


def classify_volume(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range=1d"
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=15) as r:
        res = json.load(r)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    closes, volumes, ts = q["close"], q["volume"], res["timestamp"]
    up = down = flat = used = 0
    last = None
    for i in range(1, len(closes)):
        c, v, pc = closes[i], volumes[i], closes[i - 1]
        if c is None or v is None or pc is None:
            continue
        t = datetime.datetime.fromtimestamp(ts[i], NY)
        if (t.hour, t.minute) > (13, 30):  # first 4 trading hours only
            continue
        used += 1
        last = ts[i]
        if c > pc:
            up += v
        elif c < pc:
            down += v
        else:
            flat += v
    return {"upVolume": up, "downVolume": down, "flatVolume": flat, "barsUsed": used, "lastBarTimestamp": last}


out, failures, tu, td = {"symbols": {}}, [], 0, 0
for t, label in SYMBOLS.items():
    try:
        r = classify_volume(t)
        out["symbols"][t] = {"label": label, **r}
        tu += r["upVolume"]; td += r["downVolume"]
        print(f"OK  {t}: up={r['upVolume']} down={r['downVolume']} bars={r['barsUsed']}")
    except Exception as e:
        failures.append(t)
        print(f"FAIL {t}: {e}")

out["totalUpVolume"], out["totalDownVolume"] = tu, td
out["upDownRatio"] = round(tu / td, 3) if td > 0 else None
out["_lastUpdated"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
out["_failedSymbols"] = failures
out["_methodology"] = ("Bar-direction proxy (1-min bar volume classified by close vs prior close, first 4 trading "
                       "hours), NOT tick-level aggressor-side (Lee-Ready) volume - that requires paid NBBO quote data.")
if len(failures) == len(SYMBOLS):
    raise SystemExit("All symbols failed - not writing breadth.json")
os.makedirs("data", exist_ok=True)
json.dump(out, open("data/breadth.json", "w"), indent=2)
print(f"ratio={out['upDownRatio']} failed={failures}")
