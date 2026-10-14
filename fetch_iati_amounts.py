"""Fetch d-portal's pre-computed EUR commitment/spend per activity and country share."""
import json, urllib.request, urllib.parse, pathlib
from fetch_iati import WAEMU, PUBLISHERS
rows=[]
for ref in PUBLISHERS:
    for cc in WAEMU:
        q=urllib.parse.urlencode({"from":"act,country","reporting_ref":ref,"country_code":cc,"limit":-1,
           "select":"aid,commitment_eur,spend_eur,country_code,country_percent,status_code"})
        rows+=json.load(urllib.request.urlopen(f"https://d-portal.org/q.json?{q}",timeout=120))["rows"]
json.dump(rows,open("raw/iati_amounts.json","w")); print(len(rows))
