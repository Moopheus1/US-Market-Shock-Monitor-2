"""Keep tonight's 8pm SGT pre-market score inputs (24 Nov 2026).

The page re-scores every 5 min, so after the US open the headline number stopped being
the tested signal (the Edge Tracker grades the 8pm SGT reading) and became a copy of the
live move. This saves the first pulse fetch between 8:00pm and 9:29pm SGT (12:00-13:29 UTC)
on US weekdays, so the page can keep showing the 8pm call after the open.
Usage: python3 scripts/snap8pm.py <path of the published snapshot on the pulse-data branch>
"""
import datetime
import json
import os
import sys

target = sys.argv[1]
now = datetime.datetime.now(datetime.timezone.utc)
if now.weekday() > 4 or not (12 <= now.hour < 14 and (now.hour, now.minute) < (13, 30)):
    sys.exit(0)  # outside the 8pm SGT window
sgt_date = (now + datetime.timedelta(hours=8)).date().isoformat()
if os.path.exists(target):
    try:
        if json.load(open(target)).get("_snapSgtDate") == sgt_date:
            sys.exit(0)  # tonight's snapshot already taken
    except Exception:
        pass
snap = json.load(open("data/pulse.json"))
snap["_snapSgtDate"] = sgt_date
snap["_snapAt"] = snap.get("_lastUpdated")
json.dump(snap, open(target, "w"), indent=2)
print(f"8pm snapshot saved for {sgt_date} (data at {snap['_snapAt']})")
