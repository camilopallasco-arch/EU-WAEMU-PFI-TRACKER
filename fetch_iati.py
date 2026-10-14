"""Fetch full IATI XML (via d-portal, no API key) for target publishers x WAEMU countries."""
import urllib.request, urllib.parse, pathlib, time
WAEMU = ["BJ","BF","CI","GW","ML","NE","SN","TG"]
PUBLISHERS = {
 "FR-3":"AFD group", "NL-KVK-27078545":"FMO", "XM-DAC-918-3":"EIB",
 "XI-IATI-EBRD":"EBRD", "NL-KVK-33226495":"Atradius DSB",
 "NL-KVK-83517626":"Invest International", "NL-KVK-61172863":"DGGF Lokaal MKB",
 "DE-1":"BMZ (filtered to KfW later)",
}
def main():
  out = pathlib.Path("raw/iati")
  for ref in PUBLISHERS:
    for cc in WAEMU:
        q = urllib.parse.urlencode({"from":"act,country","reporting_ref":ref,"country_code":cc,"limit":-1})
        f = out/f"{ref}_{cc}.xml"
        try:
            data = urllib.request.urlopen(f"https://d-portal.org/q.xml?{q}", timeout=180).read()
            f.write_bytes(data); print(ref, cc, len(data))
        except Exception as e: print("ERR", ref, cc, e)
        time.sleep(0.3)
if __name__=="__main__": main()
