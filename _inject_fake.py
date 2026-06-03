"""
Injects fake historical snapshots so the dashboard has multiple days to display.
Run:   python _inject_fake.py
Undo:  python _inject_fake.py --undo

Edit FAKE_ADDITIONS and the baseline date glob below to match real snapshot dates.
"""
import json
import sys
from pathlib import Path

SNAPSHOTS_DIR = Path("snapshots")

# Edit these to inject fake history for testing.
# Format: (date, company_name, [(title, url, location), ...])
FAKE_ADDITIONS = [
    ("2026-06-01", "SWTCH", [
        ("Senior Software Engineer", "https://apply.workable.com/swtch-energy/", "Toronto, ON"),
        ("Field Operations Technician", "https://apply.workable.com/swtch-energy/", "Vancouver, BC"),
    ]),
    ("2026-06-01", "FLO EV Charging", [
        ("Product Manager, Charging Networks", "https://apply.workable.com/flo-addenergie/", "Montreal, QC"),
    ]),
    ("2026-06-02", "ChargePoint", [
        ("Account Executive, Canada", "https://www.chargepoint.com/en-ca/about/opportunities", "Toronto, ON"),
    ]),
    ("2026-06-02", "GeoTab", [
        ("Data Scientist", "https://careers.geotab.com/jobs", "Oakville, ON"),
        ("Cloud Infrastructure Engineer", "https://careers.geotab.com/jobs", "Oakville, ON"),
    ]),
]

FAKE_DATES = sorted({d for d, _, _ in FAKE_ADDITIONS})

if "--undo" in sys.argv:
    removed = []
    for d in FAKE_DATES:
        for p in SNAPSHOTS_DIR.glob(f"{d}_0000_fake.json"):
            p.unlink()
            removed.append(p.name)
    if removed:
        print("Removed:", ", ".join(removed))
    else:
        print("Nothing to remove.")
    sys.exit(0)

# Load the most recent real snapshot as baseline
real_snaps = sorted(
    p for p in SNAPSHOTS_DIR.glob("*.json")
    if p.name != "index.json" and "_fake" not in p.stem
)
if not real_snaps:
    print("No real snapshots found in snapshots/. Run 'python tracker.py scrape' first.")
    sys.exit(1)

baseline_path = real_snaps[-1]
print(f"Using baseline: {baseline_path.name}")
raw_baseline = json.loads(baseline_path.read_text(encoding="utf-8"))


def _normalise(jobs):
    out = []
    for j in jobs:
        if isinstance(j, str):
            out.append({"title": j, "url": None, "location": None})
        else:
            out.append({"title": j.get("title", ""), "url": j.get("url"), "location": j.get("location")})
    return out


running: dict[str, list[dict]] = {c: _normalise(js) for c, js in raw_baseline.items()}

for date in FAKE_DATES:
    day_additions = [(c, jobs) for d, c, jobs in FAKE_ADDITIONS if d == date]
    for company, new_jobs in day_additions:
        existing_titles = {j["title"].lower() for j in running.get(company, [])}
        running.setdefault(company, [])
        for title, url, loc in new_jobs:
            if title.lower() not in existing_titles:
                running[company].append({"title": title, "url": url, "location": loc})
                existing_titles.add(title.lower())
        running[company].sort(key=lambda j: j["title"].lower())

    out = SNAPSHOTS_DIR / f"{date}_0000_fake.json"
    out.write_text(json.dumps(running, indent=2, ensure_ascii=False), encoding="utf-8")
    total = sum(len(v) for v in running.values())
    print(f"  {out.name}  ({total} total jobs)")

print("\nFake snapshots written.")
print("To view: python -m http.server 8000  then open http://localhost:8000/dashboard.html")
print("To undo: python _inject_fake.py --undo")
