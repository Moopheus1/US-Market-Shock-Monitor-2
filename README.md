# US Market Shock Monitor — v2 (test bed)

Live: https://moopheus1.github.io/US-Market-Shock-Monitor-2/

Experimental copy of [v1](https://github.com/moopheus1/US-Market-Shock-Monitor). v1 stays unchanged; changes are tried here first.

**Data:** Parts I/II and the reference panels read v1's published data files (`DATA_BASE` in `index.html`), so v1 and v2 see identical inputs. The only data v2 produces itself is the Edge Tracker (`data/edge_*.json`), which needs no API keys.

## The question v2 answers
Does the Part II pre-market bias score, as read at 8pm SGT, predict anything?

`scripts/edge_tracker.py` rebuilds the score for every trading day since May 2024 from hourly bars that had **already closed** at 8pm SGT (and at 9am ET), using the live formula and weights, then grades it against SPY. `edge-tracker.yml` reruns it after every US close (22:10 UTC Mon–Fri). Past rows are frozen, and rows from **2026-09-30** onward are a live out-of-sample test: the method was fixed before those days happened.

### Backtest result (597 sessions, 2024-05-08 → 2026-09-28, 8pm SGT snapshot)
| Question | Bullish calls right | Bearish calls right | Coin-flip rate |
|---|---|---|---|
| Red or green close (SPY close vs prior close) | 76% | 67% | 56% up / 44% down |
| Gap at the open | 96% | 91% | 59% / 41% |
| **8pm SGT → close (tradeable)** | **51%** | **49%** | 51% / 49% |
| Open → close | 48% | 47% | 52% / 48% |

Read: the score is a good summary of the overnight move, so it labels red/green days well, but all of that is already in the price at 8pm SGT. From 8pm SGT onward it has no edge. ES futures alone track the gap better than the 8-input score (rank correlation 0.87 vs 0.81).

The older v1 claim (0.555 correlation, 78–96% hit rates) compared the score with the gap it was partly built from, using daily bars; it is withdrawn here.

## Changes vs v1
1. **Score = futures, VIX, yield, dollar, crude only.** The MOO imbalance entry box is removed entirely; the buy/sell volume proxy is shown as context, not scored. Neither exists at the 8pm SGT read, neither was tested, and including them made the score mean different things at different times of day.
2. **Stale 10Y yield fixed.** ^TNX has no data before 08:20 ET; v1 then scored *yesterday's* yield move as overnight news. v2 skips TNX until it trades.
3. **Stale buy/sell volume flagged.** Before the open, the volume file holds the previous session's bars under a fresh timestamp; v2 labels it as such.
4. **Edge Tracker panel** with the backtest, live forward test and last 10 sessions.
5. **Bias text rewritten** to say what the score measures (overnight move, likely close colour) instead of trading instructions the backtest doesn't support.
6. **NAAIM removed.** Free NAAIM data has been delayed 3 months since 1 Aug 2026.
7. **Volume-proxy colours:** 40–60% up-volume shown neutral (noise band), not red/green.

Not changed on purpose: the score formula and weights. Inputs are raw % changes (not individually scaled as v1's text claimed), so VIX carries more weight than its nominal 15. Changing that would change the score being tested.
