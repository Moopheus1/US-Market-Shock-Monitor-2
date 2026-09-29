"""
Edge Tracker for the Part II pre-market bias score.

Rebuilds the score exactly as it would have read at two snapshot times, using only
hourly bars that had already CLOSED by then, and grades it against what SPY did next.

  sgt8pm : 20:00 Singapore time (08:00 ET in US summer, 07:00 ET in winter)
  et9am  : 09:00 ET, last clean hourly snapshot before the 09:30 open

Score formula = the live one: weighted mean of % change vs prior 16:00 ET value
(VIX inverted), clamped to +-3, mapped to 0..100. Same weights as index.html.
TNX is skipped before 08:20 ET (no data yet). MOO and buy/sell volume are not part
of the pre-open score (not knowable before the open).

Outcomes:
  red_day     SPY close vs prior close            (what the panel is named after)
  gap         SPY open vs prior close             (partly already visible at snapshot)
  open_close  SPY close vs open                   (the session after the gap)
  snap_close  ES at 16:00 ET vs ES at snapshot    (tradeable: acting AT the snapshot)

Rows are appended to data/edge_rows.json and never rewritten once complete, so the
history survives Yahoo's rolling 730-day window. Rows dated on/after FORWARD_START
are the live out-of-sample test - the method was frozen before those days happened.

Runs daily after the US close (edge-tracker.yml). No API keys needed.
"""
import json, os, math, bisect, time, urllib.request, datetime as dt
from zoneinfo import ZoneInfo

NY, SG = ZoneInfo("America/New_York"), ZoneInfo("Asia/Singapore")
FORWARD_START = "2026-09-30"
ROWS_PATH, SUMMARY_PATH = "data/edge_rows.json", "data/edge_summary.json"
FLOW_PATH = "data/flow_log.json"  # appended by the scheduled options-flow logger
# (yahoo ticker, weight, invert) - must match PREMARKET_SYMBOLS in index.html
SYMS = [("ES=F", 25, False), ("NQ=F", 20, False), ("YM=F", 10, False), ("RTY=F", 10, False),
        ("^VIX", 15, True), ("^TNX", 8, False), ("DX-Y.NYB", 5, False), ("CL=F", 4, False)]
HDR = {"User-Agent": "Mozilla/5.0 (compatible; MarketShockMonitor/2.0)"}


def fetch(ticker, interval, rng):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?interval={interval}&range={rng}&includePrePost=true")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=30) as r:
                return json.load(r)["chart"]["result"][0]
        except Exception as e:
            if attempt == 2: raise
            time.sleep(5)


def hourly_closed(ticker):
    r = fetch(ticker, "1h", "730d")
    q = r["indicators"]["quote"][0]
    # keyed by bar END time: only bars finished by the snapshot are usable
    return sorted((t + 3600, c) for t, c in zip(r["timestamp"], q["close"]) if c is not None)


def ny(d, h, m=0):
    return dt.datetime(d.year, d.month, d.day, h, m, tzinfo=NY)


def score(changes):
    tw = sum(w for _, w, _ in changes)
    raw = sum((-c if inv else c) * w for c, w, inv in changes) / tw
    return round((max(-3, min(3, raw)) + 3) / 6 * 100), raw


def bucket(s):
    return "bull" if s > 60 else "bear" if s < 40 else "neutral"


def build_rows():
    H = {t: hourly_closed(t) for t, _, _ in SYMS}
    K = {t: [x[0] for x in H[t]] for t in H}

    def at(t, ts):
        i = bisect.bisect_right(K[t], ts) - 1
        return H[t][i] if i >= 0 else (None, None)

    spy = fetch("SPY", "1d", "5y")
    q = spy["indicators"]["quote"][0]
    days = [(dt.datetime.fromtimestamp(t, NY).date(), o, c)
            for t, o, c in zip(spy["timestamp"], q["open"], q["close"]) if o and c]
    now_ny = dt.datetime.now(NY)
    rows = []
    for i in range(1, len(days)):
        d, o, c = days[i]
        pd_, _, pc = days[i - 1]
        if d == now_ny.date() and now_ny < ny(d, 16, 30):
            continue  # session not finished - grade it tomorrow
        rec = {"date": d.isoformat(), "red_day": c / pc - 1, "gap": o / pc - 1, "open_close": c / o - 1}
        snaps = {"sgt8pm": dt.datetime(d.year, d.month, d.day, 20, tzinfo=SG).astimezone(NY),
                 "et9am": ny(d, 9)}
        ok = True
        for name, snap in snaps.items():
            sts, prev_ts = snap.timestamp(), ny(pd_, 16).timestamp()
            ch, es_now = [], None
            for t, w, inv in SYMS:
                if t == "^TNX" and snap < ny(d, 8, 20):
                    continue
                now_end, now_v = at(t, sts)
                _, prev_v = at(t, prev_ts)
                if now_v is None or prev_v is None or sts - now_end > 7200:
                    continue
                ch.append(((now_v / prev_v - 1) * 100, w, inv))
                if t == "ES=F":
                    es_now, es_prev = now_v, prev_v
            _, es_close = at("ES=F", ny(d, 16).timestamp())
            if es_now is None or es_close is None or len(ch) < 5:
                ok = False
                break
            s, raw = score(ch)
            rec[name] = {"score": s, "raw": round(raw, 4), "es_chg": es_now / es_prev - 1,
                         "snap_close": es_close / es_now - 1, "n_inputs": len(ch)}
        if ok:
            rows.append(rec)
    return rows


def wilson(k, n, z=1.96):
    if n == 0: return [None, None]
    p = k / n; den = 1 + z * z / n; cen = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [cen - half, cen + half]


def spearman(x, y):
    n = len(x)
    if n < 3: return None
    rk = lambda v: {j: r for r, j in enumerate(sorted(range(n), key=lambda i: v[i]))}
    rx, ry = rk(x), rk(y); m = (n - 1) / 2
    num = sum((rx[i] - m) * (ry[i] - m) for i in range(n))
    den = math.sqrt(sum((rx[i] - m) ** 2 for i in range(n)) * sum((ry[i] - m) ** 2 for i in range(n)))
    return num / den if den else None


def summarize(rows):
    out = {}
    for snap in ["sgt8pm", "et9am"]:
        S = {"buckets": {b: sum(bucket(r[snap]["score"]) == b for r in rows) for b in ["bull", "neutral", "bear"]}}
        for oc in ["red_day", "gap", "open_close", "snap_close"]:
            val = (lambda r: r[snap]["snap_close"]) if oc == "snap_close" else (lambda r, k=oc: r[k])
            ys = [val(r) for r in rows]
            res = {"n": len(ys), "base_up": sum(y > 0 for y in ys) / len(ys) if ys else None,
                   "rho_score": spearman([r[snap]["score"] for r in rows], ys),
                   "rho_es_only": spearman([r[snap]["es_chg"] for r in rows], ys)}
            for b in ["bull", "bear"]:
                sel = [val(r) for r in rows if bucket(r[snap]["score"]) == b]
                k = sum((y > 0) if b == "bull" else (y < 0) for y in sel)
                res[b] = {"n": len(sel), "hit": k / len(sel) if sel else None, "ci95": wilson(k, len(sel)),
                          "avg_pct": 100 * sum(sel) / len(sel) if sel else None}
            sig = [r for r in rows if bucket(r[snap]["score"]) != "neutral"]
            if sig:
                k = sum((r[snap]["score"] > 50) == (val(r) > 0) for r in sig)
                res["signal_days"] = {"n": len(sig), "hit": k / len(sig), "ci95": wilson(k, len(sig))}
            S[oc] = res
        out[snap] = S
    return out


def grade_flow(rows):
    """Grade the options-flow forward test (data/flow_log.json).

    preopen rows  (logged ~8:40am ET): previous session's big-money SPY flow.
        Graded against that day's colour (SPY close vs prior close) and against
        the move AFTER 9am ET (ES 9am -> 4pm), i.e. what you could still trade.
    firsthour rows (logged ~10:35am ET): the first hour's flow.
        Graded against SPY from 10:30am ET to the close.
    Signal = sign of net bullish-minus-bearish premium EXCLUDING same-day (0DTE) options
    (0DTE is mostly intraday hedging/noise); the all-expiry sign is graded too.
    """
    if not os.path.exists(FLOW_PATH):
        return None
    try:
        log = json.load(open(FLOW_PATH))
    except Exception:
        return None
    by_date = {r["date"]: r for r in rows}
    spy_h = fetch("SPY", "1h", "730d")
    q = spy_h["indicators"]["quote"][0]
    at1030 = {}
    for t, c in zip(spy_h["timestamp"], q["close"]):
        d = dt.datetime.fromtimestamp(t, NY)
        if c is not None and d.strftime("%H:%M") == "09:30":
            at1030[d.date().isoformat()] = c  # close of the 9:30-10:30 bar
    spy_d = fetch("SPY", "1d", "2y")
    qd = spy_d["indicators"]["quote"][0]
    close = {dt.datetime.fromtimestamp(t, NY).date().isoformat(): c for t, c in zip(spy_d["timestamp"], qd["close"]) if c}

    res = {"preopen": {"colour": [], "after": [], "colour_all": []}, "firsthour": {"rest": [], "rest_all": []}}
    recent = []
    for r in log:
        if r.get("ticker") != "SPY" or r.get("net_ex0dte") is None:
            continue
        target = dt.datetime.fromisoformat(r["logged_at_utc"].replace("Z", "+00:00")).astimezone(NY).date().isoformat()
        sig, sig_all = r["net_ex0dte"] > 0, (r.get("net") or 0) > 0
        row = by_date.get(target)
        item = {"session": target, "run": r["run"], "net_ex0dte": r["net_ex0dte"], "truncated": r.get("truncated")}
        if r["run"] == "preopen" and row:
            green = row["red_day"] > 0
            res["preopen"]["colour"].append(sig == green)
            res["preopen"]["colour_all"].append(sig_all == green)
            res["preopen"]["after"].append(sig == (row["et9am"]["snap_close"] > 0))
            item.update(outcome=row["red_day"], right=sig == green)
        elif r["run"] == "firsthour" and target in at1030 and target in close:
            rest = close[target] / at1030[target] - 1
            if dt.datetime.now(NY).date().isoformat() == target and dt.datetime.now(NY).hour < 16:
                continue  # session not finished
            res["firsthour"]["rest"].append(sig == (rest > 0))
            res["firsthour"]["rest_all"].append(sig_all == (rest > 0))
            item.update(outcome=rest, right=sig == (rest > 0))
        else:
            item.update(outcome=None, right=None)  # not graded yet
        recent.append(item)

    def pack(v):
        k = sum(v)
        return {"n": len(v), "hit": k / len(v) if v else None, "ci95": wilson(k, len(v))}
    return {
        "first_logged": min((r["logged_at_utc"] for r in log), default=None),
        "rows_logged": len(log),
        "preopen": {k: pack(v) for k, v in res["preopen"].items()},
        "firsthour": {k: pack(v) for k, v in res["firsthour"].items()},
        "recent": recent[-12:][::-1],
    }


def main():
    stored = {}
    if os.path.exists(ROWS_PATH):
        stored = {r["date"]: r for r in json.load(open(ROWS_PATH))}
    fresh = build_rows()
    added = 0
    for r in fresh:
        if r["date"] not in stored:  # complete rows are frozen, never rewritten
            stored[r["date"]] = r; added += 1
    rows = [stored[k] for k in sorted(stored)]
    json.dump(rows, open(ROWS_PATH, "w"), separators=(",", ":"))

    ins = [r for r in rows if r["date"] < FORWARD_START]
    fwd = [r for r in rows if r["date"] >= FORWARD_START]
    summary = {
        "_lastUpdated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "forward_start": FORWARD_START,
        "backtest": {"from": ins[0]["date"] if ins else None, "to": ins[-1]["date"] if ins else None,
                     "days": len(ins), "stats": summarize(ins) if ins else None},
        "forward": {"days": len(fwd), "stats": summarize(fwd) if len(fwd) >= 3 else None},
        "flow": grade_flow(rows),
        "recent": [{"date": r["date"], "score": r["sgt8pm"]["score"], "score_9am": r["et9am"]["score"],
                    "red_day": r["red_day"], "open_close": r["open_close"],
                    "snap_close": r["sgt8pm"]["snap_close"]} for r in rows[-15:]][::-1],
    }
    json.dump(summary, open(SUMMARY_PATH, "w"), indent=1)
    print(f"rows={len(rows)} added={added} backtest={len(ins)} forward={len(fwd)}")


if __name__ == "__main__":
    main()
