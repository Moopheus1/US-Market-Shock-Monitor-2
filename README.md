# US Market Shock Monitor — v2 (test bed)

Live: https://moopheus1.github.io/US-Market-Shock-Monitor-2/

Experimental copy of [v1](https://github.com/moopheus1/US-Market-Shock-Monitor). v1 stays unchanged; changes are tried here first.

**Data:** v2 has no fetch workflows or secrets. The page reads every data file from v1's published site (`DATA_BASE` in `index.html`), so v1 and v2 always see identical inputs and any difference between them comes from code alone.

## Changes vs v1
1. **Stale buy/sell volume excluded from the Part II bias score.** Before the US open, v1's `breadth.json` holds the *previous* session's bars under a fresh timestamp, and v1 scored it (weight 10, up to ~±5 points). v2 only scores it when its last bar is from today's New York session, and labels it otherwise. Futures/VIX/MOO scoring is unchanged.
