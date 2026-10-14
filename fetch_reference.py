"""Download reference files: DEG CSV, ECB FX rates, IATI sector codes, world map shapes."""
import pathlib, urllib.request
ROOT = pathlib.Path(__file__).parent
UA = {"User-Agent": "Mozilla/5.0 (EU-PFI-WAEMU tracker; research)"}
def dl(url, path):
    path = ROOT / path; path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180).read())
    print("saved", path)
dl("https://deginvest-investments.de/deginvest.csv", "raw/deg/deginvest.csv")
dl("https://iatistandard.org/reference_downloads/203/codelists/downloads/clv3/json/en/Sector.json", "ref/Sector.json")
for c in ["USD", "GBP", "CHF", "ZAR", "JPY", "SEK", "DKK", "NOK"]:
    dl(f"https://data-api.ecb.europa.eu/service/data/EXR/M.{c}.EUR.SP00.A?format=csvdata&startPeriod=1995-01", f"ref/ecb_{c}.csv")
if not (ROOT / "ref/countries-110m.json").exists():
    dl("https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-110m.json", "ref/countries-110m.json")
