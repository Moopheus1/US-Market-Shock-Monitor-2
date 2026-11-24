"""Moving-average panel (KING NASDAQ method, display only) - 25 Nov 2026.

For SPY, QQQ and the stocks he walks through: price, 10/20/50/100/200-day SMAs, whether
his setup is on (downtrend making lower lows, a bounce into the 10 or 20 SMA that closes
back under it), and each stock's weight in SPY and QQQ. The setup's odds are re-tested
on SPY/QQQ history (2001-today) every day and printed next to it. Not part of any score.

Usage: python3 scripts/ma_panel.py <previous published ma_panel.json or ''>
Writes data/ma_panel.json.
"""
import csv, datetime, io, json, os, sys, urllib.request, zoneinfo

NY = zoneinfo.ZoneInfo("America/New_York")
UA = {"User-Agent": "Mozilla/5.0 (compatible; MarketShockMonitor/1.0)"}
INDEXES = ["SPY", "QQQ"]
STOCKS = ["AAPL", "NVDA", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "MU", "PLTR",
          "INTC", "TSM", "SNDK", "WDC", "STX", "SMH"]
NOW = datetime.datetime.now(datetime.timezone.utc)

# His downside targets from the video of Mon 23 Nov 2026 ("QQQ 700 WITH A NVDA RALLY?!").
# These are where he says the NEXT LEG DOWN goes - not buy prices. His buy signal is the
# 10/20 SMA bullish cross after prices stop making lower lows. Logged as a forward test.
KING_SINCE = "2026-11-23"
KING = {
    "QQQ":  {"kind": "price", "value": 590, "said": "bounce toward $666, then reject down toward $590 ($570-600)"},
    "AAPL": {"kind": "sma", "value": 100, "said": "break its 20 and 50 SMAs, drop to the 100-day SMA"},
    "MSFT": {"kind": "sma", "value": 200, "said": "break its 100 SMA, drop to the 200-day SMA"},
    "AMZN": {"kind": "sma", "value": 200, "said": "break down through its 200-day SMA"},
    "MU":   {"kind": "price", "value": 380, "said": "sharp leg down toward $380"},
    "INTC": {"kind": "price", "value": 42, "said": "reject back down toward $42"},
    "NVDA": {"kind": "none", "said": "slip back under its 10 SMA for another leg lower (no price given)"},
    "GOOGL": {"kind": "none", "said": "reject off the 10 SMA, next leg lower (no price given)"},
    "PLTR": {"kind": "none", "said": "reject off the 10 SMA, next leg lower (no price given)"},
    "TSLA": {"kind": "none", "said": "break all its SMAs, another leg down (no price given)"},
    "AVGO": {"kind": "none", "said": "keep selling off with the market (no price given)"},
}


def king_status(t, B):
    k = KING.get(t)
    if not k:
        return None
    out = {"said": k["said"], "kind": k["kind"], "target": None, "reached_on": None}
    if k["kind"] == "none":
        return out
    c = [b[3] for b in B]
    for j in range(len(B)):
        if B[j][0] < KING_SINCE:
            continue
        lvl = k["value"] if k["kind"] == "price" else (sum(c[j - k["value"] + 1:j + 1]) / k["value"] if j >= k["value"] - 1 else None)
        if lvl is not None and B[j][2] <= lvl and out["reached_on"] is None:
            out["reached_on"] = B[j][0]
    i = len(B) - 1
    out["target"] = k["value"] if k["kind"] == "price" else round(sum(c[i - k["value"] + 1:i + 1]) / k["value"], 2)
    out["label"] = ("$%d" % k["value"]) if k["kind"] == "price" else "%d-day SMA" % k["value"]
    return out


def get(url, timeout=20):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def bars(t, rng="2y"):
    if rng == "max":
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{t}?interval=1d&period1=978307200&period2={int(NOW.timestamp())}"
    else:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{t}?interval=1d&range={rng}"
    r = json.loads(get(url))["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    out = []
    for i, ts in enumerate(r["timestamp"]):
        h, l, c = q["high"][i], q["low"][i], q["close"][i]
        if None not in (h, l, c):
            out.append((datetime.datetime.fromtimestamp(ts, NY).date().isoformat(), h, l, c))
    return out, r["meta"]


def smas(c, i):
    return {k: (sum(c[i - k + 1:i + 1]) / k if i >= k - 1 else None) for k in (10, 20, 50, 100, 200)}


def setup_on(h, l, c, i):
    """His setup on bar i: 10 SMA below 20, close below 50, fresh 20-day low in the last
    10 bars, and the bar reached the 10 or 20 SMA but closed back under it."""
    s = smas(c, i)
    if None in s.values():
        return False
    lo20 = min(l[i - 19:i + 1])
    down = s[10] < s[20] and c[i] < s[50] and min(l[i - 9:i + 1]) == lo20
    lvl = min(s[10], s[20])
    return down and h[i] >= lvl and c[i] < lvl


def odds(t):
    """Re-run the test shown on the page: after his setup, how often a new 20-day low comes
    within 20 sessions, vs any day in the same downtrend. 2001-today and 2015-today."""
    B, _ = bars(t, "max")
    d = [b[0] for b in B]; h = [b[1] for b in B]; l = [b[2] for b in B]; c = [b[3] for b in B]
    res = {}
    for label, start in (("since_2001", "2001-01-01"), ("since_2015", "2015-01-01")):
        ev, base, last = [], [], -99
        for i in range(220, len(B) - 20):
            if d[i] < start:
                continue
            s = smas(c, i)
            lo20 = min(l[i - 19:i + 1])
            down = s[10] < s[20] and c[i] < s[50] and min(l[i - 9:i + 1]) == lo20
            if not down:
                continue
            nl = min(l[i + 1:i + 21]) < lo20
            base.append(nl)
            if setup_on(h, l, c, i) and i - last >= 10:
                ev.append(nl); last = i
        res[label] = {"setup_n": len(ev), "setup_newlow": sum(ev) / len(ev) if ev else None,
                      "base_n": len(base), "base_newlow": sum(base) / len(base) if base else None}
    return res


def spy_weights():
    import openpyxl
    raw = get("https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx")
    ws = openpyxl.load_workbook(io.BytesIO(raw), read_only=True).active
    rows = list(ws.iter_rows(values_only=True))
    asof = next((str(r[1]) for r in rows[:6] if r and r[0] == "Holdings:"), "")
    hdr = next(i for i, r in enumerate(rows) if r and "Ticker" in r)
    ti, wi = rows[hdr].index("Ticker"), rows[hdr].index("Weight")
    w = {}
    for r in rows[hdr + 1:]:
        if r and r[ti] and isinstance(r[wi], (int, float)):
            w[str(r[ti]).replace(".", "-")] = w.get(str(r[ti]), 0) + float(r[wi])
    return w, "State Street SPY holdings file, " + asof.replace("As of ", "as of ")


def qqq_weights():
    try:  # Invesco's own daily file (exact). May refuse automated downloads.
        txt = get("https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0?audienceType=Investor&action=download&ticker=QQQ").decode("utf-8", "ignore")
        rd = list(csv.DictReader(io.StringIO(txt)))
        key = next(k for k in rd[0] if "Weight" in k)
        tk = next(k for k in rd[0] if k.strip().lower() in ("holding ticker", "ticker"))
        w = {r[tk].strip(): float(r[key]) for r in rd if r.get(tk) and r.get(key)}
        if len(w) > 90:
            return w, "Invesco QQQ holdings file", True
    except Exception as e:
        print("Invesco QQQ file unavailable:", e)
    # Fallback: Yahoo's published top-10 holdings (only the 10 largest positions).
    import yfinance as yf
    th = yf.Ticker("QQQ").funds_data.top_holdings
    w = {str(sym): float(row["Holding Percent"]) * 100 for sym, row in th.iterrows()}
    return w, "Yahoo Finance QQQ top-10 holdings (only the 10 largest are published)", False


def alphabet(w):
    """Show Alphabet as one company: class A (GOOGL) + class C (GOOG)."""
    if w.get("GOOGL") is not None or w.get("GOOG") is not None:
        w = dict(w); w["GOOGL"] = (w.get("GOOGL") or 0) + (w.get("GOOG") or 0)
    return w


prev = {}
if len(sys.argv) > 1 and sys.argv[1] and os.path.exists(sys.argv[1]):
    try:
        prev = json.load(open(sys.argv[1]))
    except Exception:
        prev = {}

out = {"_lastUpdated": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"), "rows": [], "failed": [], "king_since": KING_SINCE}
for t in INDEXES + STOCKS:
    try:
        B, meta = bars(t)
        h = [b[1] for b in B]; l = [b[2] for b in B]; c = [b[3] for b in B]; i = len(B) - 1
        s = smas(c, i)
        recent = [B[j][0] for j in range(i - 2, i + 1) if setup_on(h, l, c, j)]
        cross_up = next((B[j][0] for j in range(i - 4, i + 1)
                         if smas(c, j)[10] > smas(c, j)[20] and smas(c, j - 1)[10] <= smas(c, j - 1)[20]), None)
        out["rows"].append({"ticker": t, "price": c[i], "bar_date": B[i][0], "high": h[i], "low": l[i],
                            "sma": {str(k): (round(v, 2) if v else None) for k, v in s.items()},
                            "setup_dates": recent, "cross_up_date": cross_up,
                            "low20": min(l[i - 19:i + 1]), "king": king_status(t, B),
                            "is_etf": t in ("SPY", "QQQ", "SMH")})
        print(f"OK  {t} {c[i]:.2f}")
    except Exception as e:
        out["failed"].append(t); print(f"FAIL {t}: {e}")

# Weights and odds change slowly: refresh once a day, otherwise carry the last good ones.
fresh = (prev.get("_weightsDate") == NOW.date().isoformat()
         and set(STOCKS) <= set((((prev.get("weights") or {}).get("SPY")) or {}).get("w", {})))  # re-fetch when a stock is added
if fresh:
    for k in ("weights", "odds", "_weightsDate"):
        if k in prev:
            out[k] = prev[k]
else:
    W = {}
    try:
        sw, src = spy_weights(); sw = alphabet(sw); W["SPY"] = {"source": src, "complete": True, "w": {t: sw.get(t) for t in STOCKS}}
    except Exception as e:
        print("SPY weights failed:", e); W["SPY"] = (prev.get("weights") or {}).get("SPY")
    try:
        qw, src, complete = qqq_weights(); qw = alphabet(qw); W["QQQ"] = {"source": src, "complete": complete, "w": {t: qw.get(t) for t in STOCKS}}
    except Exception as e:
        print("QQQ weights failed:", e); W["QQQ"] = (prev.get("weights") or {}).get("QQQ")
    out["weights"] = W
    try:
        out["odds"] = {t: odds(t) for t in INDEXES}
    except Exception as e:
        print("odds failed:", e); out["odds"] = prev.get("odds")
    out["_weightsDate"] = NOW.date().isoformat()

if len(out["failed"]) > len(INDEXES + STOCKS) // 2:
    raise SystemExit("too many tickers failed - not writing")
os.makedirs("data", exist_ok=True)
json.dump(out, open("data/ma_panel.json", "w"), indent=1)
print("weights:", {k: (v or {}).get("source") for k, v in (out.get("weights") or {}).items()})
