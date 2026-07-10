import csv

with open("ranked.csv") as f:
    rows = [r for r in csv.DictReader(f) if r.get("status", "").lower() == "passed"]

# xray-knife already sorts by latency with --sort; if you want to weight
# by download speed too, re-sort here, e.g.:
rows.sort(key=lambda r: (float(r.get("delay", "9999") or 9999)))

top20 = rows[:20]

with open("top20_configs.txt", "w") as out:
    for r in top20:
        out.write(r["raw"] + "\n")
# xray-knife CSV includes the original link in a "raw"/"link" column — check your version's header names with `head -1 ranked.csv`
