"""EIB signed loans in WAEMU countries, from the JSON API behind eib.org/en/projects/loans."""
import json, time, urllib.request, pathlib
UA = {"User-Agent": "Mozilla/5.0 (EU-PFI-WAEMU tracker; research)", "Accept": "application/json"}
BASE = ("https://www.eib.org/provider-eib-plr/app/loans/list?sortColumn=loanParts.loanPartStatus.statusDate"
        "&sortDir=desc&itemPerPage=100&pageable=true&language=EN&defaultLanguage=EN&orCountries=true")
pathlib.Path("raw/eib").mkdir(parents=True, exist_ok=True)
out = {}
for cc in ["BJ", "BF", "CI", "GW", "ML", "NE", "SN", "TG"]:
    page = 0
    while True:
        r = urllib.request.Request(f"{BASE}&countries={cc}&pageNumber={page}", headers=UA)
        d = json.load(urllib.request.urlopen(r, timeout=90))
        for item in d.get("data") or []:
            out.setdefault(item["id"], item)
        if (page + 1) * 100 >= d.get("totalItems", 0):
            break
        page += 1
        time.sleep(0.5)
    print(cc, d.get("totalItems"))
json.dump(list(out.values()), open("raw/eib/loans.json", "w"), ensure_ascii=False)
print(len(out), "unique EIB projects")
