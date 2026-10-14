"""Monthly pipeline: fetch every source, normalise, record what changed, rebuild the site.
A source that fails keeps last month's raw files, so one broken website never blocks the update."""
import subprocess, sys, csv, pathlib, datetime
ROOT = pathlib.Path(__file__).parent
STEPS = ["fetch_reference.py", "fetch_iati.py", "fetch_iati_amounts.py", "fetch_proparco.py",
         "enrich_proparco.py", "fetch_bio.py", "fetch_wp_dfis.py"]
# A fresh GitHub checkout has no raw/ folder: create every folder the fetchers write into.
for d in ["raw/iati", "raw/proparco", "raw/bio", "raw/deg", "raw/finnfund", "raw/ifu", "ref", "data"]:
    (ROOT / d).mkdir(parents=True, exist_ok=True)
failed = []
for s in STEPS:
    print(f"== {s}", flush=True)
    if subprocess.run([sys.executable, s], cwd=ROOT).returncode != 0:
        failed.append(s)
inv = ROOT / "data" / "investments.csv"
before = {r["investment_id"]: r for r in csv.DictReader(open(inv, encoding="utf-8"))} if inv.exists() else {}
subprocess.run([sys.executable, "normalize.py"], cwd=ROOT, check=True)
after = {r["investment_id"]: r for r in csv.DictReader(open(inv, encoding="utf-8"))}
added = [k for k in after if k not in before]
removed = [k for k in before if k not in after]
changed = [k for k in after if k in before and (after[k]["amount_eur"], after[k]["status"]) != (before[k]["amount_eur"], before[k]["status"])]
log = ROOT / "data" / "changelog.csv"
new = not log.exists()
with open(log, "a", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    if new: w.writerow(["run_date", "added", "removed", "changed", "failed_sources"])
    w.writerow([datetime.date.today().isoformat(), len(added), len(removed), len(changed), " ".join(failed)])
print(f"added {len(added)}, removed {len(removed)}, changed {len(changed)}, failed sources: {failed or 'none'}")
subprocess.run([sys.executable, "build_site.py"], cwd=ROOT, check=True)
