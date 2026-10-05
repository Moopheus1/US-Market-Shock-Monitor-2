"""
Risk light: normal size / cut size / stay out, for the NEXT US session.

Question it answers: "is tomorrow the kind of day where a 2%+ swing is likely?"
It does NOT predict direction, and it does NOT predict the first day of a shock -
it tells you when the market is already in a state where big swings keep happening.

Inputs, all known after day D's close and so before day D+1 opens:
  GEX      SqueezeMetrics free daily file (dealer gamma)
  VIX      Yahoo ^VIX daily close
  VIX3M    Yahoo ^VIX3M daily close (3-month VIX)

Three stress flags (round numbers chosen before testing, not tuned):
  1. VIX closed at 25 or higher
  2. VIX closed above VIX3M (near-term fear above longer-term fear)
  3. GEX is negative (dealers amplify moves instead of damping them)

Levels:
  RED   (2)  two or three stress flags
  AMBER (1)  one stress flag, or VIX >= 20, or GEX in the lowest 20% of its past year
  GREEN (0)  none of the above

Test: every session since May 2012, no look-ahead (the GEX percentile uses only the
252 sessions before each day). Reported for the whole period and separately for
2012-19, 2020-24 and 2025-now, because a rule that only works in one period is noise.

Sessions dated on/after FORWARD_START are a live out-of-sample test: the rule was
frozen before those days happened.

Also writes the overnight-alarm table from data/edge_rows.json: how big the rest of
the day was when S&P futures had already moved 1%+ by 8pm SGT.

Writes data/risk_light.json. Runs hourly with the GEX job (fetch-gex.yml). No API keys.
"""
import csv, io, json, os, math, bisect, time, statistics as st, datetime as dt, urllib.request
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
DIX_URL = "https://squeezemetrics.com/monitor/static/DIX.csv"
OUT, EDGE_ROWS = "data/risk_light.json", "data/edge_rows.json"
FORWARD_START = "2026-10-06"
HDR = {"User-Agent": "Mozilla/5.0 (compatible; MarketShockMonitor/2.0)"}
NAMES = ["GREEN", "AMBER", "RED"]
ACTIONS = ["Normal size", "Cut size", "Stay out"]
VIX_STRESS, VIX_WATCH, GEX_LOW_PCT, ALARM_PCT = 25.0, 20.0, 0.20, 0.01


def get(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=60) as r:
                return r.read().decode()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5)


def yahoo_daily(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=20y"
    r = json.loads(get(url))["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    return {dt.datetime.fromtimestamp(t, NY).date().isoformat(): c
            for t, c in zip(r["timestamp"], q["close"]) if c is not None}


def level_of(o):
    if o["k"] >= 2:
        return 2
    if o["k"] == 1 or o["vix"] >= VIX_WATCH or o["p"] < GEX_LOW_PCT:
        return 1
    return 0


def describe(o):
    """State of day o as flags + level. Needs p, gex, vix, v3."""
    o["flags"] = {"vix_25": o["vix"] >= VIX_STRESS,
                  "vix_above_3m": o["v3"] is not None and o["vix"] > o["v3"],
                  "gex_negative": o["gex"] < 0}
    o["k"] = sum(o["flags"].values())
    o["level"] = level_of(o)
    return o


def stats(sel, n_all):
    n = len(sel)
    if not n:
        return {"n": 0}
    a = [abs(o["nxt"]) for o in sel]
    r = [o["nxt"] for o in sel]
    return {"n": n, "share": n / n_all, "avg_abs": st.mean(a),
            "p1": sum(x >= .01 for x in a) / n, "p2": sum(x >= .02 for x in a) / n,
            "p3": sum(x >= .03 for x in a) / n, "p_down2": sum(x <= -.02 for x in r) / n,
            "mean": st.mean(r), "green": sum(x > 0 for x in r) / n, "worst": min(r), "best": max(r)}


def equity(obs, weight):
    r = [weight(o) * o["nxt"] for o in obs]
    cum = pk = 1.0
    dd = 0.0
    for x in r:
        cum *= 1 + x
        pk = max(pk, cum)
        dd = min(dd, cum / pk - 1)
    return {"cagr": cum ** (252 / len(r)) - 1, "vol": st.pstdev(r) * math.sqrt(252), "max_dd": dd}


def overnight_alarm():
    """From the edge tracker's frozen rows: S&P futures move at 8pm SGT vs rest of day."""
    if not os.path.exists(EDGE_ROWS):
        return None
    rows = json.load(open(EDGE_ROWS))

    def pack(sel):
        n = len(sel)
        if not n:
            return {"n": 0}
        a = [abs(r["sgt8pm"]["snap_close"]) for r in sel]
        return {"n": n, "avg_abs_rest": st.mean(a), "p1_rest": sum(x >= .01 for x in a) / n,
                "p2_rest": sum(x >= .02 for x in a) / n,
                "p2_full_day": sum(abs(r["red_day"]) >= .02 for r in sel) / n,
                "up_rest": sum(r["sgt8pm"]["snap_close"] > 0 for r in sel) / n}
    big = [r for r in rows if abs(r["sgt8pm"]["es_chg"]) >= ALARM_PCT]
    return {"threshold": ALARM_PCT, "from": rows[0]["date"], "to": rows[-1]["date"],
            "moved": pack(big), "all": pack(rows),
            "down": pack([r for r in big if r["sgt8pm"]["es_chg"] < 0]),
            "up": pack([r for r in big if r["sgt8pm"]["es_chg"] > 0])}


def main():
    rows = [(x["date"], float(x["price"]), float(x["gex"])) for x in csv.DictReader(io.StringIO(get(DIX_URL)))
            if x.get("gex") not in (None, "") and x.get("price") not in (None, "")]
    vix, v3 = yahoo_daily("%5EVIX"), yahoo_daily("%5EVIX3M")

    def state(i):
        d = rows[i][0]
        if d not in vix:
            return None
        past = sorted(r[2] for r in rows[i - 252:i])
        return describe({"d": d, "p": bisect.bisect_left(past, rows[i][2]) / 252, "gex": rows[i][2],
                         "vix": vix[d], "v3": v3.get(d)})

    obs = []
    for i in range(253, len(rows) - 1):
        o = state(i)
        if o is None:
            continue
        o["nd"], o["nxt"] = rows[i + 1][0], rows[i + 1][1] / rows[i][1] - 1
        obs.append(o)

    periods = {"all": obs, "2012-2019": [o for o in obs if o["d"] < "2020"],
               "2020-2024": [o for o in obs if "2020" <= o["d"] < "2025"],
               "2025-now": [o for o in obs if o["d"] >= "2025"]}
    by_period = {name: [stats([o for o in sel if o["level"] == L], len(sel)) for L in (0, 1, 2)]
                 for name, sel in periods.items()}

    # the days it is meant to protect against: how were they flagged the evening before?
    def coverage(test):
        hit = [o for o in obs if test(o)]
        return {"n": len(hit), **{NAMES[L].lower(): sum(o["level"] == L for o in hit) for L in (0, 1, 2)}}
    cov = {"abs2": coverage(lambda o: abs(o["nxt"]) >= .02), "abs3": coverage(lambda o: abs(o["nxt"]) >= .03),
           "down3": coverage(lambda o: o["nxt"] <= -.03)}

    # how long RED lasts, and whether it arrives with warning
    runs, cur = [], 0
    for o in obs:
        if o["level"] == 2:
            cur += 1
        elif cur:
            runs.append(cur); cur = 0
    if cur:
        runs.append(cur)
    enter = [obs[i - 1]["level"] for i in range(1, len(obs)) if obs[i]["level"] == 2 and obs[i - 1]["level"] != 2]

    fwd = [o for o in obs if o["nd"] >= FORWARD_START]
    latest = state(len(rows) - 1)
    if latest is None:
        raise SystemExit(f"no VIX close for {rows[-1][0]} yet - keeping the previous file")
    A = by_period["all"]
    base = A[0]["avg_abs"]
    out = {
        "_lastUpdated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "_source": "SqueezeMetrics DIX.csv + Yahoo ^VIX, ^VIX3M daily closes",
        "forward_start": FORWARD_START,
        "rule": {"vix_stress": VIX_STRESS, "vix_watch": VIX_WATCH, "gex_low_pct": GEX_LOW_PCT},
        "latest": {"as_of": latest["d"], "level": latest["level"], "name": NAMES[latest["level"]],
                   "action": ACTIONS[latest["level"]], "flags": latest["flags"], "stress_flags": latest["k"],
                   "vix": latest["vix"], "vix3m": latest["v3"], "gex": latest["gex"],
                   "gex_pct_vs_past_year": latest["p"], "sp500_close": rows[-1][1]},
        "levels": [{"name": NAMES[L], "action": ACTIONS[L], **A[L],
                    # position size that keeps the expected daily swing equal to a GREEN day
                    "size_for_equal_risk": min(1.0, base / A[L]["avg_abs"])} for L in (0, 1, 2)],
        "by_period": by_period,
        "coverage": cov,
        "red_runs": {"episodes": len(runs), "median_days": st.median(runs) if runs else None,
                     "longest_days": max(runs) if runs else None,
                     "entered_from_green": enter.count(0), "entered_from_amber": enter.count(1)},
        # S&P 500 held every day vs sitting out the flagged days. Index only, no costs.
        "what_if": {"always_in": equity(obs, lambda o: 1), "out_on_red": equity(obs, lambda o: 0 if o["level"] == 2 else 1),
                    "half_on_amber_out_on_red": equity(obs, lambda o: 0 if o["level"] == 2 else .5 if o["level"] == 1 else 1)},
        "overnight_alarm": overnight_alarm(),
        "test_days": len(obs), "test_from": obs[0]["nd"], "test_to": obs[-1]["nd"],
        "forward": {"days": len(fwd), "levels": [stats([o for o in fwd if o["level"] == L], len(fwd) or 1) for L in (0, 1, 2)]},
        "recent": [{"session": o["nd"], "level": o["level"], "name": NAMES[o["level"]], "move": o["nxt"]}
                   for o in obs[-15:]][::-1],
    }
    json.dump(out, open(OUT, "w"), indent=1)
    L = out["latest"]
    print(f"{L['as_of']}: {L['name']} ({L['action']}) - VIX {L['vix']:.1f}, VIX3M {L['vix3m']}, GEX {L['gex']/1e9:.1f}bn, pct {L['gex_pct_vs_past_year']:.2f}")
    for lv in out["levels"]:
        print(f"  {lv['name']:5} n={lv['n']:4} {lv['share']:5.1%} avg {100*lv['avg_abs']:.2f}%  1%+ {lv['p1']:.0%}  2%+ {lv['p2']:.1%}  3%+ {lv['p3']:.1%}  size {lv['size_for_equal_risk']:.2f}")


if __name__ == "__main__":
    main()
