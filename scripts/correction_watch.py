"""
Correction watch: is a pullback already underway? (Part I companion, added 24 Nov 2026)

Why it exists: Part I's 14 signposts are mostly monthly macro data. In the Oct-Nov 2026
slide (S&P -11.6% from 6 Oct to 20 Nov) it never rose above 5/14, and its own 2015-2026
test shows fast corrections peak at ~23%. This light uses only fast, daily market inputs.

Five flags, all known after the previous close. Round numbers fixed BEFORE testing, not tuned:
  F1 VIX closed at 25 or higher
  F2 VIX closed above 3-month VIX (curve inverted)
  F3 S&P closed below its 50-day average
  F4 S&P closed below its 200-day average
  F5 credit stress: HYG/IEF total-return ratio down 2% or more over 20 sessions
Level: GREEN 0-1 flags, AMBER 2, RED 3+.

It CONFIRMS a correction within days; it does not predict one, and it is not a sell
signal: after red days the S&P's next 20 sessions averaged MORE than after green days
(stress mean-reverts). Read it as "risk is high, size down", not "the market will fall".

Sessions on/after FORWARD_START are a live out-of-sample test (rule frozen before then).
Also exports the last 30 VIX closes so Part I can score VIX from the same-day close
instead of FRED's copy, which arrives 1-2 days late.

Writes data/correction_watch.json. No API keys. Runs inside the pulse loop (fetch-pulse.yml).
"""
import bisect, json, os, time, statistics as st, datetime as dt, urllib.request
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
OUT = "data/correction_watch.json"
FORWARD_START = "2026-11-24"
TEST_FROM = "2012-01-03"
HDR = {"User-Agent": "Mozilla/5.0 (compatible; MarketShockMonitor/2.0)"}
NAMES = ["GREEN", "AMBER", "RED"]
RULE = {"vix_stress": 25.0, "ma_fast": 50, "ma_slow": 200, "credit_drop": 0.02, "credit_window": 20,
        "amber_flags": 2, "red_flags": 3}
FLAG_TEXT = {"vix25": "VIX at 25+", "inverted": "VIX above 3-month VIX", "below50": "S&P below 50-day avg",
             "below200": "S&P below 200-day avg", "credit": "credit stress (HYG vs IEF -2% in 20 sessions)"}


def get(url):
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=60) as r:
                return r.read().decode()
        except Exception:
            if attempt == 3:
                raise
            time.sleep(6 * (attempt + 1))


def yahoo_daily(ticker, adjusted=False):
    """date -> close for COMPLETED sessions only (drops today's bar until 16:15 ET)."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=20y"
    r = json.loads(get(url))["chart"]["result"][0]
    q = r["indicators"]["quote"][0]["close"]
    if adjusted:
        q = r["indicators"].get("adjclose", [{}])[0].get("adjclose") or q
    now = dt.datetime.now(NY)
    out = {}
    for t, c in zip(r["timestamp"], q):
        if c is None:
            continue
        d = dt.datetime.fromtimestamp(t, NY).date()
        if d == now.date() and (now.hour, now.minute) < (16, 15):
            continue  # session still trading
        out[d.isoformat()] = c
    return out


def ffill(m, keys, d):
    """Value of m on date d, or the latest earlier date present (keys = sorted(m))."""
    if d in m:
        return m[d]
    k = bisect.bisect_left(keys, d)
    return m[keys[k - 1]] if k > 0 else None


def build():
    spx = yahoo_daily("%5EGSPC")
    vix = yahoo_daily("%5EVIX")
    vxv = yahoo_daily("%5EVIX3M")
    hyg = yahoo_daily("HYG", adjusted=True)
    ief = yahoo_daily("IEF", adjusted=True)
    dates = sorted(spx)
    c = [spx[d] for d in dates]
    vk, xk, hk, ik = sorted(vix), sorted(vxv), sorted(hyg), sorted(ief)

    # rolling sums for averages
    def sma(i, n):
        return sum(c[i - n + 1:i + 1]) / n

    rows = []
    for i in range(RULE["ma_slow"] + 5, len(dates)):
        d = dates[i]
        v, v3 = ffill(vix, vk, d), ffill(vxv, xk, d)
        h0, i0 = ffill(hyg, hk, d), ffill(ief, ik, d)
        j = dates[i - RULE["credit_window"]]
        h1, i1 = ffill(hyg, hk, j), ffill(ief, ik, j)
        if None in (v, v3, h0, i0, h1, i1):
            continue
        f = {"vix25": v >= RULE["vix_stress"], "inverted": v > v3,
             "below50": c[i] < sma(i, RULE["ma_fast"]), "below200": c[i] < sma(i, RULE["ma_slow"]),
             "credit": (h0 / i0) / (h1 / i1) - 1 <= -RULE["credit_drop"]}
        n = sum(f.values())
        lvl = 2 if n >= RULE["red_flags"] else 1 if n >= RULE["amber_flags"] else 0
        rows.append({"d": d, "i": i, "close": c[i], "vix": v, "vix3m": v3, "ma50": sma(i, 50), "ma200": sma(i, 200),
                     "credit_chg": (h0 / i0) / (h1 / i1) - 1, "f": f, "n": n, "lvl": lvl})
    return dates, c, rows, vix


def fwd(c, i, h):
    return c[i + h] / c[i] - 1 if i + h < len(c) else None


def level_stats(c, rs, n_all):
    out = []
    for L in range(3):
        sel = [r for r in rs if r["lvl"] == L]
        f20 = [x for x in (fwd(c, r["i"], 20) for r in sel) if x is not None]
        f60 = [x for x in (fwd(c, r["i"], 60) for r in sel) if x is not None]
        nx = [x for x in (fwd(c, r["i"], 1) for r in sel) if x is not None]
        out.append({"name": NAMES[L], "n": len(sel), "share": len(sel) / n_all if n_all else 0,
                    "f20_avg": st.mean(f20) if f20 else None, "f20_down": sum(x < 0 for x in f20) / len(f20) if f20 else None,
                    "f20_worst": min(f20) if f20 else None, "f60_avg": st.mean(f60) if f60 else None,
                    "next_abs": st.mean(abs(x) for x in nx) if nx else None})
    return out


def drawdowns(dates, c, start, m=0.08):
    ev, pk, tr = [], 0, 0
    for k in range(len(c)):
        if c[k] > c[pk]:
            if c[tr] / c[pk] - 1 <= -m:
                ev.append((pk, tr, False))
            pk = tr = k
        elif c[k] < c[tr]:
            tr = k
    if c[tr] / c[pk] - 1 <= -m:
        ev.append((pk, tr, True))
    return [e for e in ev if dates[e[1]] >= start]


def main():
    dates, c, rows, vix = build()
    test = [r for r in rows if TEST_FROM <= r["d"] < FORWARD_START]
    live = [r for r in rows if r["d"] >= FORWARD_START]
    by_i = {r["i"]: r for r in rows}

    # events: the light read for a session uses the PREVIOUS close, so the first session
    # it applies to is the day after the flagged close.
    events = []
    for pk, tr, still_open in drawdowns(dates, c, TEST_FROM):
        win = [by_i[k] for k in range(pk, tr) if k in by_i]
        def first(L):
            r = next((r for r in win if r["lvl"] >= L), None)
            if not r:
                return None
            return {"close_date": r["d"], "close": r["close"], "from_peak": r["close"] / c[pk] - 1,
                    "still_to_low": c[tr] / r["close"] - 1}
        events.append({"peak": dates[pk], "peak_close": c[pk], "low": dates[tr], "low_close": c[tr],
                       "dd": c[tr] / c[pk] - 1, "open": still_open, "first_amber": first(1), "first_red": first(2)})

    # red spells and false alarms (no further 3% drop within 30 sessions of the spell starting)
    spells, cur = [], None
    for r in test:
        if r["lvl"] == 2:
            cur = cur or [r, r]
            cur[1] = r
        elif cur:
            spells.append(cur); cur = None
    if cur:
        spells.append(cur)
    no_follow = 0
    for s, e in spells:
        lo = min(c[s["i"]:min(s["i"] + 31, len(c))])
        if lo / c[s["i"]] - 1 > -0.03:
            no_follow += 1

    def curve(w):
        """w(r) = share of the S&P held for the session AFTER close r. Index only, no costs."""
        eq = pk_ = 1.0; mdd = 0.0; n = 0; held = 0
        for r in test:
            nx = fwd(c, r["i"], 1)
            if nx is None:
                continue
            x = w(r)
            eq *= 1 + x * nx; pk_ = max(pk_, eq); mdd = min(mdd, eq / pk_ - 1); n += 1; held += x > 0
        return {"cagr": eq ** (252 / n) - 1, "max_dd": mdd, "end_10k": 10000 * eq, "time_in": held / n}

    def sell_amber_buy_red():
        pos = [1.0]
        def w(r):
            if r["lvl"] == 1:
                pos[0] = 0.0
            elif r["lvl"] == 2:
                pos[0] = 1.0
            return pos[0]
        return w

    # What happened after the FIRST amber / FIRST red close of each spell (20 sessions on)
    def after_first(L):
        out, prev = [], 0
        for r in test:
            if r["lvl"] == L and prev != L and (L == 2 or prev == 0):
                f = fwd(c, r["i"], 20)
                if f is not None:
                    dip = min(c[r["i"]:r["i"] + 21]) / c[r["i"]] - 1
                    out.append((f, dip))
            prev = r["lvl"]
        if not out:
            return {"n": 0}
        f = [x for x, _ in out]
        return {"n": len(out), "f20_avg": st.mean(f), "f20_median": st.median(f), "higher": sum(x > 0 for x in f) / len(f),
                "avg_dip": st.mean(d for _, d in out), "worst_dip": min(d for _, d in out)}

    periods = {}
    for k, (a, b) in {"2012-2019": ("2012", "2020"), "2020-2024": ("2020", "2025"), "2025-now": ("2025", FORWARD_START)}.items():
        sel = [r for r in test if a <= r["d"] < b]
        periods[k] = level_stats(c, sel, len(sel))

    last = rows[-1]
    out = {
        "_lastUpdated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "_source": "Yahoo daily closes: ^GSPC, ^VIX, ^VIX3M, HYG and IEF (dividend-adjusted)",
        "rule": RULE, "flag_text": FLAG_TEXT, "forward_start": FORWARD_START,
        "latest": {"as_of": last["d"], "level": last["lvl"], "name": NAMES[last["lvl"]], "n": last["n"], "flags": last["f"],
                   "close": last["close"], "vix": last["vix"], "vix3m": last["vix3m"], "ma50": last["ma50"],
                   "ma200": last["ma200"], "credit_chg": last["credit_chg"]},
        "test_from": test[0]["d"], "test_to": test[-1]["d"], "test_days": len(test),
        "levels": level_stats(c, test, len(test)), "by_period": periods,
        "events": events,
        "red_spells": {"n": len(spells), "no_further_3pct": no_follow,
                       "median_len": st.median([e["i"] - s["i"] + 1 for s, e in spells]) if spells else 0},
        # half_on_red is the suggested sizing rule. NOTE: chosen on 24 Nov 2026 AFTER seeing the
        # other rules' results (the flags were fixed before testing; this sizing was not).
        "what_if": {"always_in": curve(lambda r: 1), "half_on_red": curve(lambda r: 0.5 if r["lvl"] == 2 else 1),
                    "out_on_red": curve(lambda r: 0 if r["lvl"] == 2 else 1),
                    "sell_amber_buy_red": curve(sell_amber_buy_red())},
        "after_first_amber": after_first(1), "after_first_red": after_first(2),
        "forward": {"days": len(live), "levels": level_stats(c, live, len(live)) if live else []},
        "recent": [{"d": r["d"], "lvl": r["lvl"], "n": r["n"], "close": r["close"]} for r in rows[-45:]],
        "vix_recent": [{"date": d, "value": vix[d]} for d in sorted(vix)[-30:]],
    }
    os.makedirs("data", exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1)
    L = out["latest"]
    print(f"{L['as_of']}: {L['name']} ({L['n']}/5) {[k for k, v in L['flags'].items() if v]} | test {out['test_days']} sessions")


if __name__ == "__main__":
    main()
