"""
"Size of today" from GEX (dealer gamma).

Source: SqueezeMetrics' free daily file (date, S&P 500 close, DIX, GEX) back to 2011.
GEX for day D is published after D's close, so it is known before the NEXT session opens.

What it predicts (15-year test, repeated in 2012-19, 2020-24 and 2025-26): how BIG the
next session's move is - not which direction. Low GEX vs its own past year -> bigger
moves; high GEX -> smaller moves.

Method (no look-ahead): each day's GEX is ranked only against the 252 sessions before it.
Move size = |next-day % change| / average |daily % change| of the 20 sessions before it
("normal daily move"). Results are grouped into 5 bands of the percentile rank.

Writes data/gex_size.json. Runs hourly (fetch-gex.yml). No API keys.
"""
import csv, io, json, bisect, statistics as st, datetime as dt, urllib.request

URL = "https://squeezemetrics.com/monitor/static/DIX.csv"
OUT = "data/gex_size.json"
BANDS = [(0, .2, "lowest 20%"), (.2, .4, "20-40%"), (.4, .6, "middle"), (.6, .8, "60-80%"), (.8, 1.01, "highest 20%")]
LABELS = ["BIG day likely", "Somewhat bigger than normal", "Normal-sized day", "Somewhat quieter than normal", "QUIET day likely"]


def load():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (compatible; MarketShockMonitor/2.0)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        text = r.read().decode()
    rows = [(x["date"], float(x["price"]), float(x["gex"])) for x in csv.DictReader(io.StringIO(text))
            if x.get("gex") not in (None, "") and x.get("price") not in (None, "")]
    return rows


def pct_rank(rows, i):
    past = sorted(r[2] for r in rows[i - 252:i])
    return bisect.bisect_left(past, rows[i][2]) / 252


def normal_move(rows, i):
    """Average |daily % move| over the 20 sessions up to and including i."""
    return st.mean(abs(rows[j][1] / rows[j - 1][1] - 1) for j in range(i - 19, i + 1))


def band_of(p):
    for k, (lo, hi, _) in enumerate(BANDS):
        if lo <= p < hi:
            return k
    return len(BANDS) - 1


def main():
    rows = load()
    obs = []  # (date_of_gex, band, size_ratio_next_day, next_day_date)
    for i in range(253, len(rows) - 1):
        p = pct_rank(rows, i)
        nm = normal_move(rows, i)
        nxt = abs(rows[i + 1][1] / rows[i][1] - 1)
        obs.append((rows[i][0], band_of(p), nxt / nm if nm else None, rows[i + 1][0]))
    obs = [o for o in obs if o[2] is not None]

    def table(sel):
        t = []
        for k in range(len(BANDS)):
            v = [o[2] for o in sel if o[1] == k]
            t.append({"n": len(v), "avg_size": st.mean(v) if v else None,
                      "p_bigger": sum(x > 1 for x in v) / len(v) if v else None,
                      "p_double": sum(x > 2 for x in v) / len(v) if v else None})
        return t

    periods = {"2012-2019": [o for o in obs if o[0] < "2020"],
               "2020-2024": [o for o in obs if "2020" <= o[0] < "2025"],
               "2025-now": [o for o in obs if o[0] >= "2025"]}

    i = len(rows) - 1
    p = pct_rank(rows, i)
    b = band_of(p)
    full = table(obs)
    nm = normal_move(rows, i)
    out = {
        "_lastUpdated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "_source": "SqueezeMetrics DIX.csv (free, daily)",
        "latest": {
            "gex_date": rows[i][0], "gex": rows[i][2], "pct_vs_past_year": p, "band": b,
            "band_name": BANDS[b][2], "label": LABELS[b],
            "normal_move_pct": 100 * nm, "sp500_close": rows[i][1],
            "expected_size": full[b]["avg_size"],
            "expected_move_pct": 100 * nm * full[b]["avg_size"],
            "expected_move_points": rows[i][1] * nm * full[b]["avg_size"],
            "p_bigger_than_normal": full[b]["p_bigger"],
        },
        "bands": [{"name": BANDS[k][2], "label": LABELS[k], **full[k]} for k in range(len(BANDS))],
        "by_period": {name: table(sel) for name, sel in periods.items()},
        "test_days": len(obs), "test_from": obs[0][0], "test_to": obs[-1][3],
        # last 15 calls, newest first: what the band said vs how big the next session actually was
        "recent": [{"session": o[3], "band": o[1], "label": LABELS[o[1]], "expected": full[o[1]]["avg_size"],
                    "actual": o[2]} for o in obs[-15:]][::-1],
    }
    json.dump(out, open(OUT, "w"), indent=1)
    L = out["latest"]
    print(f"GEX {L['gex_date']}: pct {p:.2f} -> {L['label']} (expected {L['expected_size']:.2f}x normal = {L['expected_move_pct']:.2f}%)")
    for k, r in enumerate(full):
        print(f"  {BANDS[k][2]:12} n={r['n']:4} avg {r['avg_size']:.2f}x  bigger-than-normal {r['p_bigger']:.0%}  double {r['p_double']:.0%}")


if __name__ == "__main__":
    main()
