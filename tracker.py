"""EU public financial institutions in the WAEMU - complete tracker in one file.

Run everything:      python tracker.py
Run some steps only: python tracker.py eib normalize build
Steps: reference iati proparco bio wp eib normalize build
"""
import os, sys, csv, json, pathlib, datetime, subprocess
ROOT = pathlib.Path(__file__).resolve().parent
os.chdir(ROOT)
for _d in ["raw/iati", "raw/proparco", "raw/bio", "raw/deg", "raw/finnfund", "raw/ifu", "raw/eib", "ref", "data", "site"]:
    (ROOT / _d).mkdir(parents=True, exist_ok=True)

def step_reference():
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

def step_iati():
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
    main()
    """Fetch d-portal's pre-computed EUR commitment/spend per activity and country share."""
    import json, urllib.request, urllib.parse, pathlib
    rows=[]
    for ref in PUBLISHERS:
        for cc in WAEMU:
            q=urllib.parse.urlencode({"from":"act,country","reporting_ref":ref,"country_code":cc,"limit":-1,
               "select":"aid,commitment_eur,spend_eur,country_code,country_percent,status_code"})
            rows+=json.load(urllib.request.urlopen(f"https://d-portal.org/q.json?{q}",timeout=120))["rows"]
    json.dump(rows,open("raw/iati_amounts.json","w")); print(len(rows))

def step_proparco():
    """Scrape Proparco's public project list (paged HTML) -> raw/proparco/projects.json"""
    import re, json, time, urllib.request, html as H
    UA={"User-Agent":"Mozilla/5.0 (EU-PFI-WAEMU tracker; research)"}
    def get(p):
        r=urllib.request.Request(f"https://www.proparco.fr/en/projects/list?page={p}",headers=UA)
        return urllib.request.urlopen(r,timeout=60).read().decode("utf-8","replace")
    card=re.compile(r'<h3 class="fr-card__title">\s*<a href="([^"]+)"[^>]*>(.*?)</a>(.*?)(?=<h3 class="fr-card__title">|<nav|$)',re.S)
    def clean(s): return H.unescape(re.sub(r"\s+"," ",re.sub("<[^>]+>"," ",s))).strip()
    out=[]; p=0
    while True:
        h=get(p); cards=card.findall(h)
        if not cards: break
        for href,title,body in cards:
            tags=[clean(t) for t in re.findall(r'class="fr-tag">(.*?)</p>',body,re.S)]
            det=[clean(d) for d in re.findall(r'class="fr-card__detail[^"]*">(.*?)</p>',body,re.S)]
            year=next((d for d in det if re.fullmatch(r"\d{4}",d)),None)
            amt=next((d for d in det if "Financing amount" in d),None)
            ctry=next((d for d in det if d not in (year,amt)),None)
            out.append({"url":"https://www.proparco.fr"+href,"title":clean(title),"tags":tags,"year":year,
                        "countries":ctry,"amount_raw":amt})
        p+=1; time.sleep(0.5)
    json.dump(out,open("raw/proparco/projects.json","w"),ensure_ascii=False,indent=0)
    print(p,"pages",len(out),"projects")
    """Fetch Proparco detail pages for WAEMU-related (or possibly truncated) cards and extract labelled fields."""
    import json,re,urllib.request,time,html as H
    W=["Benin","Burkina Faso","Côte d'Ivoire","Guinea-Bissau","Mali","Niger","Senegal","Togo"]
    LABELS=["Financing tool","Financing amount (Euro)","Financing details","Customer","Type of customer",
            "Country of headquarters","Project number","Environmental and social ranking"]
    UA={"User-Agent":"Mozilla/5.0 (EU-PFI-WAEMU tracker; research)"}
    def txt(url):
        h=urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=60).read().decode("utf-8","replace")
        return H.unescape(re.sub(r"\s+"," ",re.sub("<[^>]+>"," ",h)))
    def fields(t):
        f={}
        for i,l in enumerate(LABELS):
            m=re.search(re.escape(l)+r" (.*?)(?= "+"| ".join(map(re.escape,LABELS+["Download the report","This information is given"]))+r" )",t)
            if m: f[l]=m.group(1).strip()[:300]
        m=re.search(r"Country (.*?) Financing tool",t)
        if m: f["Countries_full"]=m.group(1).strip()[-400:]
        return f
    d=json.load(open("raw/proparco/projects.json"))
    n=0
    for x in d:
        c=x.get("countries") or ""
        if any(w in c for w in W) or c.count(",")>=5:
            if "fields" in x: continue
            try: x["fields"]=fields(x.pop("detail_text",None) or txt(x["url"])); n+=1
            except Exception as e: x["detail_error"]=str(e)
            if n % 20 == 0:  # save progress so an interrupted run can resume
                json.dump(d,open("raw/proparco/projects.json","w"),ensure_ascii=False,indent=0)
            time.sleep(0.3)
    json.dump(d,open("raw/proparco/projects.json","w"),ensure_ascii=False,indent=0); print("details",n)

def step_bio():
    """BIO (Belgium): list investments per WAEMU country via the site's filter, then read each detail page."""
    import re,json,time,urllib.request,urllib.parse,html as H
    UA={"User-Agent":"Mozilla/5.0 (EU-PFI-WAEMU tracker; research)"}
    C={"BJ":359,"BF":371,"CI":390,"GW":259517,"ML":473,"NE":497,"SN":530,"TG":558}
    def get(u): return urllib.request.urlopen(urllib.request.Request(urllib.parse.quote(u,safe=":/?=&%[]"),headers=UA),timeout=60).read().decode("utf-8","replace")
    def clean(s): return H.unescape(re.sub(r"\s+"," ",re.sub("<[^>]+>"," ",s))).strip()
    links={}
    for cc,v in C.items():
        p=1
        while True:
            h=get(f"https://www.bio-invest.be/en/investments{'/p'+str(p) if p>1 else ''}?country%5B0%5D={v}")
            L={l for l in re.findall(r'href="(https://www\.bio-invest\.be/en/investments/[^"?#]+)"',h) if not re.search(r"/p\d+$",l)}
            new=[l for l in L if l not in links or cc not in links[l]]
            for l in L: links.setdefault(l,set()).add(cc)
            if not new or p>40: break
            p+=1
    out=[]
    for url,ccs in links.items():
        t=clean(get(url)); time.sleep(0.3)
        out.append({"url":url,"countries_filter":sorted(ccs),"text":t[:12000]})
    json.dump(out,open("raw/bio/projects.json","w"),ensure_ascii=False)
    print(len(out),"BIO investments",{cc:sum(cc in x["countries_filter"] for x in out) for cc in C})

def step_wp():
    """Generic WordPress REST fetcher for DFIs that publish portfolios as WP post types (Finnfund, IFU)."""
    import json,urllib.request,re,unicodedata,pathlib
    UA={"User-Agent":"Mozilla/5.0 (EU-PFI-WAEMU tracker; research)"}
    WAEMU={"BJ":["benin","bénin"],"BF":["burkina"],"CI":["ivoire","divoire","ivory","elfenben\\w*"],"GW":["bissau"],
           "ML":["mali"],"NE":["niger"],"SN":["senegal","sénégal"],"TG":["togo"]}
    SITES={"finnfund":("https://www.finnfund.fi","venture","country"),
           "ifu":("https://impactfund.dk","investment","region")}
    def g(u):
        r=urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=90)
        return json.load(r), int(r.headers.get("X-WP-TotalPages",1))
    def terms(base,tax):
        out,p=[],1
        while True:
            d,tp=g(f"{base}/wp-json/wp/v2/{tax}?per_page=100&page={p}"); out+=d
            if p>=tp: return out
            p+=1
    def match(name):
        n=unicodedata.normalize("NFKD",name.lower())
        return [cc for cc,keys in WAEMU.items() if any(re.search(r"\b"+k+r"\b",n) for k in keys)]
    for key,(base,ptype,tax) in SITES.items():
        T=terms(base,tax); tid={t["id"]:t["name"] for t in T}
        ids=[t["id"] for t in T if match(t["name"])]
        posts,p={},1
        while True:
            d,tp=g(f"{base}/wp-json/wp/v2/{ptype}?{tax}={','.join(map(str,ids))}&per_page=100&page={p}&_embed=wp:term")
            for x in d: posts[x["id"]]=x
            if p>=tp: break
            p+=1
        pathlib.Path(f"raw/{key}").mkdir(exist_ok=True)
        json.dump({"terms":tid,"posts":list(posts.values())},open(f"raw/{key}/posts.json","w"),ensure_ascii=False)
        print(key,"WAEMU terms:",[tid[i] for i in ids],"posts:",len(posts))

def step_eib():
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

def step_normalize():
    """Normalise all raw sources into the tracker data model.

    Outputs (data/):
      institutions.csv, investments.csv, investment_countries.csv, sources.csv, countries.csv
      tracker.json  -> compact bundle read by the globe page
    """
    import csv, io, json, re, glob, datetime, html, pathlib, unicodedata
    from lxml import etree

    ROOT = pathlib.Path(__file__).parent
    RAW, REF, OUT = ROOT / "raw", ROOT / "ref", ROOT / "data"
    OUT.mkdir(exist_ok=True)
    TODAY = datetime.date.today().isoformat()

    # ---------------------------------------------------------------- reference data
    COUNTRIES = {  # WAEMU member states, approximate geographic centroids
        "BJ": ("BEN", "Benin", 9.31, 2.32), "BF": ("BFA", "Burkina Faso", 12.24, -1.56),
        "CI": ("CIV", "Côte d'Ivoire", 7.54, -5.55), "GW": ("GNB", "Guinea-Bissau", 11.80, -15.18),
        "ML": ("MLI", "Mali", 17.57, -4.00), "NE": ("NER", "Niger", 17.61, 8.08),
        "SN": ("SEN", "Senegal", 14.50, -14.45), "TG": ("TGO", "Togo", 8.62, 0.82),
    }
    NAME_TO_CC = {
        "benin": "BJ", "bénin": "BJ", "burkina faso": "BF", "burkina": "BF", "cote d'ivoire": "CI",
        "côte d'ivoire": "CI", "côte d’ivoire": "CI", "ivory coast": "CI", "cote d’ivoire": "CI",
        "guinea-bissau": "GW", "guinea bissau": "GW", "mali": "ML", "niger": "NE", "senegal": "SN",
        "sénégal": "SN", "togo": "TG",
    }
    CC_PATTERN = re.compile(r"\b(benin|bénin|burkina faso|c[oô]te d[’'`]?\s?ivoire|ivory coast|guinea[- ]bissau|"
                            r"mali|niger|s[eé]n[eé]gal|togo)\b", re.I)

    def countries_in(text):
        """Return WAEMU ISO2 codes mentioned in free text (ignores 'Nigeria', 'Somalia')."""
        found = []
        for m in CC_PATTERN.finditer(text or ""):
            k = m.group(1).lower().replace("`", "'").replace("’", "'")
            k = re.sub(r"c[oô]te d'?\s?ivoire", "côte d'ivoire", k)
            k = k.replace("guinea bissau", "guinea-bissau").replace("sénégal", "senegal").replace("senégal", "senegal")
            cc = NAME_TO_CC.get(k) or NAME_TO_CC.get(unicodedata.normalize("NFKD", k).encode("ascii", "ignore").decode())
            if cc and cc not in found:
                found.append(cc)
        return found

    # ECB monthly reference rates: units of currency per 1 EUR
    FX = {}
    for f in REF.glob("ecb_*.csv"):
        cur = f.stem.split("_")[1]
        for r in csv.DictReader(open(f)):
            FX[(cur, r["TIME_PERIOD"])] = float(r["OBS_VALUE"])
    FX_FIXED = {"EUR": 1.0, "XOF": 655.957}  # CFA franc is pegged to the euro

    def to_eur(amount, cur, ym):
        """Convert using the ECB monthly average for ym (YYYY-MM); fall back to nearest earlier month."""
        if amount is None:
            return None, None
        cur = (cur or "EUR").upper()
        if cur in FX_FIXED:
            return amount / FX_FIXED[cur], FX_FIXED[cur]
        months = sorted(k[1] for k in FX if k[0] == cur)
        if not months:
            return None, None
        ym = ym or months[-1]
        cand = [m for m in months if m <= ym] or months[:1]
        rate = FX[(cur, cand[-1])]
        return amount / rate, rate

    SECTORS = {d["code"]: d["name"] for d in json.load(open(REF / "Sector.json"))["data"]}
    def broad_sector(text="", dac=None):
        """Map a DAC code or free-text sector label to one shared, broad sector."""
        if dac:
            c = str(dac)[:3]
            table = {"230": "Energy", "240": "Financial services", "250": "Business & industry",
                     "311": "Agriculture & food", "312": "Agriculture & food", "313": "Agriculture & food",
                     "520": "Agriculture & food", "210": "Transport & infrastructure", "220": "Telecoms & digital",
                     "140": "Water & sanitation", "120": "Health", "122": "Health", "130": "Health",
                     "110": "Education", "111": "Education", "112": "Education", "113": "Education", "114": "Education",
                     "321": "Business & industry", "322": "Business & industry", "323": "Business & industry",
                     "331": "Business & industry", "332": "Business & industry", "151": "Governance & public sector",
                     "152": "Governance & public sector", "160": "Social protection", "410": "Environment & climate",
                     "430": "Multi-sector", "510": "Budget support", "600": "Debt", "720": "Humanitarian",
                     "730": "Humanitarian", "740": "Humanitarian", "910": "Other", "930": "Other", "998": "Other"}
            if c in table:
                return table[c]
        t = (text or "").lower()
        rules = [("Energy", r"energ|solar|power|climate|hydro|electric"),
                 ("Financial services", r"financ|bank|microfin|fund|insur|leasing|payment|credit line"),
                 ("Agriculture & food", r"agri|food|farm|cocoa|cashew|fish|forest"),
                 ("Telecoms & digital", r"telecom|digital|tech|start-up|startup|ict"),
                 ("Transport & infrastructure", r"infra|transport|network|logist|port|road|urban"),
                 ("Health", r"health|hospital|pharma|medic"), ("Education", r"educat|school"),
                 ("Water & sanitation", r"water|sanitation"),
                 ("Business & industry", r"industr|manufact|cement|service|trade|tourism|real estate|mining")]
        for name, rx in rules:
            if re.search(rx, t):
                return name
        return "Other"

    def instrument_from(text):
        t = (text or "").lower()
        for name, rx in [("Equity", r"equity|share|fund invest"), ("Guarantee", r"guarant|insur|cover"),
                         ("Grant", r"grant|subvention|subsid|don\b|technical assistance"),
                         ("Loan", r"loan|debt|credit|prêt|mezzanine|bond|facility")]:
            if re.search(rx, t):
                return name
        return "Unknown"

    IATI_FIN = lambda code: ("Grant" if code[:1] == "1" and code != "1100" else
                             "Loan" if code[:1] == "4" else "Equity" if code[:1] == "5" else
                             "Guarantee" if code == "1100" else "Debt relief" if code[:1] == "6" else "Unknown")
    IATI_STATUS = {"1": "Pipeline", "2": "Active", "3": "Completing", "4": "Closed", "5": "Cancelled", "6": "Suspended"}

    # ---------------------------------------------------------------- institutions in scope
    INST = [  # id, name, member state, type, parent, hq city, lat, lon, website, coverage
        ("afd", "Agence Française de Développement (AFD)", "FR", "Bilateral development bank", "AFD Group", "Paris", 48.835, 2.383, "https://www.afd.fr", "automated"),
        ("proparco", "Proparco", "FR", "DFI", "AFD Group", "Paris", 48.871, 2.305, "https://www.proparco.fr", "automated"),
        ("kfw-db", "KfW Development Bank", "DE", "NPB", "KfW Group", "Frankfurt", 50.110, 8.682, "https://www.kfw-entwicklungsbank.de", "automated"),
        ("deg", "DEG – Deutsche Investitions- und Entwicklungsgesellschaft", "DE", "DFI", "KfW Group", "Cologne", 50.938, 6.960, "https://www.deginvest.de", "automated"),
        ("fmo", "FMO – Dutch Entrepreneurial Development Bank", "NL", "DFI", "", "The Hague", 52.080, 4.310, "https://www.fmo.nl", "automated"),
        ("invest-intl", "Invest International", "NL", "DFI", "Dutch State / FMO", "Amsterdam", 52.370, 4.895, "https://investinternational.nl", "automated"),
        ("dggf", "Dutch Good Growth Fund – Local SME (DGGF)", "NL", "DFI", "Dutch Ministry of Foreign Affairs", "The Hague", 52.070, 4.300, "https://english.dggf.nl", "automated"),
        ("bio", "BIO – Belgian Investment Company for Developing Countries", "BE", "DFI", "", "Brussels", 50.850, 4.352, "https://www.bio-invest.be", "automated"),
        ("finnfund", "Finnfund", "FI", "DFI", "", "Helsinki", 60.170, 24.938, "https://www.finnfund.fi", "automated"),
        ("ifu", "IFU – Investment Fund for Developing Countries", "DK", "DFI", "", "Copenhagen", 55.676, 12.568, "https://impactfund.dk", "automated"),
        ("swedfund", "Swedfund", "SE", "DFI", "", "Stockholm", 59.329, 18.069, "https://www.swedfund.se", "not yet covered"),
        ("oeeb", "OeEB – Development Bank of Austria", "AT", "DFI", "OeKB Group", "Vienna", 48.208, 16.374, "https://www.oe-eb.at", "not yet covered"),
        ("cofides", "COFIDES", "ES", "DFI", "", "Madrid", 40.417, -3.704, "https://www.cofides.es", "not yet covered"),
        ("simest", "SIMEST", "IT", "DFI", "CDP Group", "Rome", 41.903, 12.496, "https://www.simest.it", "not yet covered"),
        ("sofid", "SOFID", "PT", "DFI", "", "Lisbon", 38.722, -9.139, "https://www.sofid.pt", "not yet covered"),
        ("cdp", "Cassa Depositi e Prestiti (CDP)", "IT", "NPB", "CDP Group", "Rome", 41.900, 12.480, "https://www.cdp.it", "manual"),
        ("bpifrance", "Bpifrance", "FR", "NPB", "", "Paris", 48.880, 2.330, "https://www.bpifrance.fr", "manual"),
        ("ico", "Instituto de Crédito Oficial (ICO)", "ES", "NPB", "", "Madrid", 40.410, -3.690, "https://www.ico.es", "manual"),
        ("bgk", "Bank Gospodarstwa Krajowego (BGK)", "PL", "NPB", "", "Warsaw", 52.230, 21.012, "https://www.bgk.pl", "manual"),
        ("atradius-dsb", "Atradius Dutch State Business", "NL", "ECA", "Atradius", "Amsterdam", 52.340, 4.870, "https://atradiusdutchstatebusiness.nl", "automated"),
        ("allianz-trade-de", "Allianz Trade (Euler Hermes) for the German Federal Government", "DE", "ECA", "", "Hamburg", 53.551, 9.994, "https://www.exportkreditgarantien.de", "manual"),
        ("bpifrance-ae", "Bpifrance Assurance Export", "FR", "ECA", "Bpifrance", "Paris", 48.890, 2.300, "https://www.bpifrance.fr", "manual"),
        ("sace", "SACE", "IT", "ECA", "", "Rome", 41.910, 12.500, "https://www.sace.it", "manual"),
        ("credendo", "Credendo", "BE", "ECA", "", "Brussels", 50.840, 4.370, "https://credendo.com", "manual"),
        ("cesce", "CESCE", "ES", "ECA", "", "Madrid", 40.440, -3.690, "https://www.cesce.es", "manual"),
        ("ekn", "EKN – Swedish Export Credit Agency", "SE", "ECA", "", "Stockholm", 59.340, 18.050, "https://www.ekn.se", "manual"),
        ("eifo", "EIFO – Export and Investment Fund of Denmark", "DK", "ECA", "", "Copenhagen", 55.690, 12.590, "https://www.eifo.dk", "manual"),
        ("finnvera", "Finnvera", "FI", "ECA", "", "Helsinki", 60.180, 24.950, "https://www.finnvera.fi", "manual"),
        ("oekb", "OeKB – Oesterreichische Kontrollbank", "AT", "ECA", "OeKB Group", "Vienna", 48.215, 16.365, "https://www.oekb.at", "manual"),
        ("kuke", "KUKE – Export Credit Insurance Corporation", "PL", "ECA", "", "Warsaw", 52.240, 21.000, "https://www.kuke.com.pl", "manual"),
        ("eib", "European Investment Bank (EIB)", "EU", "Multilateral", "EIB Group", "Luxembourg", 49.627, 6.155, "https://www.eib.org", "automated"),
        ("ebrd", "European Bank for Reconstruction and Development (EBRD)", "INT", "Multilateral", "", "London", 51.507, -0.128, "https://www.ebrd.com", "automated"),
    ]
    INST_FIELDS = ["institution_id", "name", "member_state", "type", "parent_group", "hq_city", "hq_lat", "hq_lon", "website", "coverage"]

    # ---------------------------------------------------------------- collectors
    investments, allocations = [], []

    def add(inst, src, rec_id, url, title, *, desc="", client="", client_domicile="", instrument="Unknown",
            sector_broad="Other", sector_detail="", status="", date="", amount=None, currency="EUR",
            amount_eur=None, es="", shares=None, method="", note="", points=None):
        """shares: dict cc -> pct (or None for unknown); method as in the data model."""
        if not shares:
            return
        inv_id = f"{inst}:{rec_id}"
        ym = (date or "")[:7] if re.match(r"\d{4}-\d{2}", date or "") else (f"{date[:4]}-06" if date else None)
        fx_rate = None
        if amount_eur is None and amount is not None:
            amount_eur, fx_rate = to_eur(amount, currency, ym)
        investments.append({
            "investment_id": inv_id, "institution_id": inst, "source_id": src, "source_record_id": rec_id,
            "source_url": url, "title": (title or "").strip()[:250], "description": re.sub(r"\s+", " ", desc or "").strip()[:600],
            "client": client, "client_domicile": client_domicile, "instrument": instrument,
            "sector_broad": sector_broad, "sector_detail": sector_detail, "status": status, "date": date,
            "year": (date or "")[:4], "amount_original": amount, "currency_original": currency,
            "fx_rate_per_eur": fx_rate, "amount_eur": round(amount_eur) if amount_eur is not None else None,
            "es_category": es, "countries": "|".join(shares), "multi_country": len(shares) > 1,
            "note": note, "retrieved_at": TODAY})
        n = len(shares)
        for cc, pct in shares.items():
            if method == "iati_percentage":
                share = pct if pct is not None else 100.0 / n
            elif method in ("single_country",):
                share = 100.0
            elif method == "equal_split_estimate":
                share = 100.0 / n
            else:
                share = None  # regional_unallocated
            att = round(amount_eur * share / 100) if (amount_eur is not None and share is not None) else None
            _, name, lat, lon = COUNTRIES[cc]
            pt = (points or {}).get(cc)
            allocations.append({"investment_id": inv_id, "institution_id": inst, "country": cc,
                                "share_pct": round(share, 2) if share is not None else None,
                                "amount_attributed_eur": att, "attribution_method": method,
                                "lat": pt[0] if pt else lat, "lon": pt[1] if pt else lon,
                                "geo_precision": "site" if pt else "country_centroid"})

    # ---- IATI (AFD, KfW via BMZ, FMO, EIB, EBRD, Atradius DSB, Invest International, DGGF)
    IATI_INST = {"FR-3": "afd", "NL-KVK-27078545": "fmo", "XM-DAC-918-3": "eib", "XI-IATI-EBRD": "ebrd",
                 "NL-KVK-33226495": "atradius-dsb", "NL-KVK-83517626": "invest-intl",
                 "NL-KVK-61172863": "dggf", "DE-1": "kfw-db"}
    amounts = {}
    for r in json.load(open(RAW / "iati_amounts.json")):
        amounts[r["aid"]] = r
    seen = set()
    for f in sorted(glob.glob(str(RAW / "iati" / "*.xml"))):
        ref = pathlib.Path(f).stem.rsplit("_", 1)[0]
        try:
            tree = etree.parse(f)
        except etree.XMLSyntaxError:
            continue
        for a in tree.iter("iati-activity"):
            aid = (a.findtext("iati-identifier") or "").strip()
            if not aid or aid in seen:
                continue
            inst = IATI_INST[ref]
            if inst == "eib" and (RAW / "eib" / "loans.json").exists():
                continue  # EIB's own project list is more complete and already contains every IATI record
            porgs = a.findall("participating-org")
            if ref == "DE-1":  # keep only KfW-implemented financial cooperation
                if not any(p.get("ref") == "XM-DAC-5-2" or "kfw" in (p.findtext("narrative") or "").lower() for p in porgs):
                    continue
            seen.add(aid)
            shares = {}
            for rc in a.findall("recipient-country"):
                cc = rc.get("code", "").upper()
                if cc in COUNTRIES:
                    p = rc.get("percentage")
                    shares[cc] = float(p) if p not in (None, "") else None
            if not shares:
                continue
            n_all = len(a.findall("recipient-country")) + len(a.findall("recipient-region"))
            method = "single_country" if n_all == 1 and len(shares) == 1 else "iati_percentage"
            if method == "iati_percentage" and all(v is None for v in shares.values()):
                method = "equal_split_estimate"
            title = (a.findtext("title/narrative") or "").strip()
            desc = " ".join(n.text or "" for n in a.findall("description/narrative"))[:600]
            if desc.strip() == "Description not provided":
                desc = ""
            receivers = [p.findtext("narrative") for p in porgs if p.get("role") == "4" and p.findtext("narrative")]
            dates = {d.get("type"): d.get("iso-date") for d in a.findall("activity-date")}
            start = dates.get("2") or dates.get("1") or ""
            sec = a.find("sector[@vocabulary='1']")
            if sec is None:
                sec = a.find("sector")
            dac = sec.get("code") if sec is not None else None
            fin = a.find("default-finance-type")
            fin_code = fin.get("code") if fin is not None else (a.findtext("transaction/finance-type") or "")
            if fin is None:
                t_fin = a.find("transaction/finance-type")
                fin_code = t_fin.get("code") if t_fin is not None else ""
            status_el = a.find("activity-status")
            am = amounts.get(aid, {})
            total = float(am.get("commitment_eur") or 0) or float(am.get("spend_eur") or 0) or None
            # d-portal's commitment_eur is the whole-activity total (verified); country split happens in add()
            pts = {}
            for loc in a.findall("location"):
                pos = loc.findtext("point/pos")
                if pos:
                    try:
                        la, lo = map(float, pos.split())
                    except ValueError:
                        continue
                    for cc in shares:
                        _, _, cla, clo = COUNTRIES[cc]
                        if abs(la - cla) < 8 and abs(lo - clo) < 9 and cc not in pts:
                            pts[cc] = (la, lo)
            add(inst, "iati", aid, f"https://d-portal.org/ctrack.html#view=act&aid={aid}", title or aid,
                desc=desc, client="; ".join(dict.fromkeys(receivers))[:200], instrument=IATI_FIN(fin_code) if fin_code else "Unknown",
                sector_broad=broad_sector(dac=dac), sector_detail=SECTORS.get(dac, dac or ""),
                status=IATI_STATUS.get(status_el.get("code") if status_el is not None else "", ""),
                date=start, amount_eur=total, shares=shares, method=method, points=pts,
                note="Amount = commitment (or disbursement if no commitment) in EUR as computed by d-portal.")

    # ---- EIB (its own signed-loans API; replaces the smaller IATI feed)
    eib_file = RAW / "eib" / "loans.json"
    if eib_file.exists():
        for x in json.load(open(eib_file, encoding="utf-8")):
            tags = x.get("primaryTags") or []
            ccs = [t["value"] for t in tags if t.get("subType") == "countries" and t.get("value") in COUNTRIES]
            if not ccs:
                continue
            info = x.get("additionalInformation") or []
            amt = re.sub(r"[^\d]", "", info[0]) if info and isinstance(info[0], str) else ""
            ts = info[1] if len(info) > 1 and isinstance(info[1], (int, float)) else x.get("startDate")
            date = datetime.datetime.fromtimestamp(ts / 1000, datetime.UTC).strftime("%Y-%m") if ts else ""
            sector = ", ".join(t["label"] for t in tags if t.get("subType") == "sectors")
            title = x.get("title") or x["id"]
            add("eib", "eib-api", x["id"], f"https://www.eib.org/en/projects/all/{x['id']}", title,
                desc=x.get("description") or "", instrument="Equity" if re.search(r"\bFUND\b", title.upper()) else "Loan",
                sector_broad=broad_sector(sector + " " + title), sector_detail=sector, status="Signed", date=date,
                amount=float(amt) if amt else None, currency="EUR", shares={c: None for c in ccs},
                method="single_country" if len(ccs) == 1 else "equal_split_estimate",
                note="Signed amount as allocated to this country by the EIB. Instrument inferred: fund investments shown as equity, everything else as loans.")

    # ---- Proparco
    for p in json.load(open(RAW / "proparco" / "projects.json")):
        f = p.get("fields", {})
        ctext = f.get("Countries_full") or p.get("countries") or ""
        ccs = countries_in(ctext)
        if not ccs:
            continue
        amt = f.get("Financing amount (Euro)") or re.sub(r"[^\d.,]", "", p.get("amount_raw") or "")
        amt = amt.replace(" ", "")
        if "," in amt and "." not in amt:
            amt = amt.split(",")[0]
        amt = re.sub(r"[^\d.]", "", amt)
        amount = float(amt) if amt else None
        multi = len([c for c in ctext.split(",") if c.strip()]) > 1
        method = "single_country" if not multi else "equal_split_estimate"
        rec = f.get("Project number") or p["url"].rsplit("/", 1)[-1]
        add("proparco", "proparco-web", rec, p["url"], p["title"], client=f.get("Customer", ""),
            client_domicile=f.get("Country of headquarters", ""),
            instrument=instrument_from(f.get("Financing tool", "")), sector_broad=broad_sector(" ".join(p["tags"])),
            sector_detail=", ".join(p["tags"]), status="Signed", date=p.get("year") or "",
            amount=amount, currency="EUR", es=f.get("Environmental and social ranking", "")[:20],
            shares={c: None for c in ccs}, method=method,
            note=("Multi-country deal; countries listed: " + ctext[:300]) if multi else "")

    # ---- BIO
    MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                          "september", "october", "november", "december"], 1)}
    for p in json.load(open(RAW / "bio" / "projects.json")):
        t = p["text"]
        i = t.find("BIO investment portfolio")
        body = t[i + len("BIO investment portfolio"):] if i >= 0 else t
        m = re.match(r"\s*(.+?)\s+\1\s+(Debt|Equity|Mezzanine|Guarantee|Grant|[A-Za-z ]+?)\s*:\s*([A-Za-z]+)\s+(\d{4})", body)
        title = m.group(1) if m else p["url"].rsplit("/", 1)[-1]
        date = f"{m.group(4)}-{MONTHS.get(m.group(3).lower(), 6):02d}" if m else ""
        am = re.search(r"Amount\s+([€$£]|[A-Z]{3})\s*([\d,\.]+)", body)
        cur = {"€": "EUR", "$": "USD", "£": "GBP"}.get(am.group(1), am.group(1)) if am else "EUR"
        amount = float(am.group(2).replace(",", "")) if am else None
        loc = re.search(r"Beneficiary locations (.*?) Investment field", body)
        ccs = countries_in(loc.group(1)) if loc else p["countries_filter"]
        n_countries = len([x for x in re.split(r"[,:]", loc.group(1)) if x.strip() and x.strip() not in
                           ("Africa", "Asia", "Latin America and Caribbean", "Middle East")]) if loc else len(ccs)
        field = re.search(r"Investment field (.*?) Activity (.*?) Organisation (.*?) (?:Website|Domicile)", body)
        dom = re.search(r"Domicile (.+?)(?: More investments| [A-Z][a-z]+ [a-z])", body)
        typ = re.search(r"Type of investment (\w+)", body)
        add("bio", "bio-web", p["url"].rsplit("/", 1)[-1], p["url"], title,
            desc=body[body.find(date[:4]) + 4:][:400] if m else "", client=field.group(3) if field else title,
            client_domicile=dom.group(1).strip()[:60] if dom else "",
            instrument=instrument_from(typ.group(1) if typ else ""), sector_broad=broad_sector(
                (field.group(1) + " " + field.group(2)) if field else ""),
            sector_detail=(field.group(2) if field else "")[:100], status="Signed", date=date,
            amount=amount, currency=cur, shares={c: None for c in ccs},
            method="single_country" if n_countries <= 1 and len(ccs) == 1 else "equal_split_estimate",
            note=f"Beneficiary locations span {n_countries} countries; WAEMU share estimated by equal split." if n_countries > 1 else "")

    # ---- DEG (official CSV)
    rows = list(csv.DictReader(io.StringIO(open(RAW / "deg" / "deginvest.csv", encoding="utf-8-sig").read()), delimiter=";"))
    for i, r in enumerate(rows):
        direct = countries_in(r["Country"])
        mentioned = countries_in(" ".join([r["Customer description"] or "", r["Funding Objective"] or "", r["Reasons for financing"] or ""]))
        if direct:
            shares, method = {c: None for c in direct}, "single_country" if len(direct) == 1 else "equal_split_estimate"
        elif r["Country"].strip().lower() in ("supraregional", "") and mentioned:
            shares, method = {c: None for c in mentioned}, "regional_unallocated"
        else:
            continue
        fm = re.match(r"([A-Z]{3})\s*([\d\.]+)", (r["Funding"] or "").strip())
        sd = re.match(r"(\d{2})-(\d{4})", r["Signing Date"] or "")
        add("deg", "deg-csv", f"{i}-{re.sub(r'[^a-z0-9]+', '-', r['Customer Name'].lower())[:40]}",
            "https://deginvest-investments.de/", r["Customer Name"], desc=r["Funding Objective"],
            client=r["Customer Name"], client_domicile=r["Domiciliation"] or r["Country"],
            instrument=instrument_from(r["Investment Instrument"]), sector_broad=broad_sector(r["Sector"]),
            sector_detail=r["Sector"], status="Signed", date=f"{sd.group(2)}-{sd.group(1)}" if sd else "",
            amount=float(fm.group(2)) if fm else None, currency=fm.group(1) if fm else "EUR",
            es=r["Environmental & Social Category"], shares=shares, method=method,
            note="Supraregional commitment; WAEMU countries mentioned in DEG's description, amount not allocated."
            if method == "regional_unallocated" else "")

    # ---- Finnfund & IFU (WordPress)
    for key, inst in (("finnfund", "finnfund"), ("ifu", "ifu")):
        d = json.load(open(RAW / key / "posts.json"))
        seen_titles = set()
        for p in d["posts"]:
            terms = [(t["taxonomy"], html.unescape(t["name"])) for grp in p.get("_embedded", {}).get("wp:term", []) if isinstance(grp, list) for t in grp if isinstance(t, dict)]
            if not terms:  # some sites don't embed terms: resolve ids via the saved term table
                terms = [(tx, html.unescape(d["terms"].get(str(i), ""))) for tx in ("country", "region") for i in p.get(tx, []) or []]
            title = html.unescape(p["title"]["rendered"])
            if title.lower() in seen_titles:
                continue  # Finnish/English duplicates
            seen_titles.add(title.lower())
            ctry = [n for tx, n in terms if tx in ("country", "region")]
            ccs = countries_in(", ".join(ctry))
            if not ccs:
                continue
            other = [c for c in ctry if not countries_in(c) and c not in ("Africa", "Afrika", "Africa (Regional)", "Global")]
            amt = next((n for tx, n in terms if tx == "sum_of_investment"), None)
            year = next((n for tx, n in terms if tx == "year_category"), "") or p["date"][:4]
            sect = ", ".join(n for tx, n in terms if tx in ("venture_sector", "sector"))
            inst_t = ", ".join(n for tx, n in terms if tx in ("venture_category", "instrument"))
            add(inst, f"{key}-wp", str(p["id"]), p["link"], title, client=title,
                instrument=instrument_from(inst_t + (" fund" if "fund" in inst_t.lower() else "")),
                sector_broad=broad_sector(sect), sector_detail=sect, status="Signed", date=str(year),
                amount=float(amt) if amt and amt.isdigit() else None, currency="EUR",
                shares={c: None for c in ccs}, method="single_country" if len(ccs) == 1 and not other else "equal_split_estimate",
                note="Amount is the band published by Finnfund." if key == "finnfund" and amt else
                     ("Amount not disclosed." if not amt else ""))

    # ---- Manual research sheet (ECAs, NPBs, JavaScript-only DFI sites). One row per deal.
    # countries: ISO2 codes separated by | (e.g. SN|CI). Keep a source_url for every row.
    manual = OUT / "manual_entries.csv"
    if manual.exists():
        for i, r in enumerate(csv.DictReader(open(manual, encoding="utf-8"))):
            ccs = [c.strip().upper() for c in (r.get("countries") or "").split("|") if c.strip().upper() in COUNTRIES]
            if not r.get("institution_id") or not ccs:
                continue
            amt = float(r["amount"]) if (r.get("amount") or "").replace(".", "", 1).isdigit() else None
            add(r["institution_id"], "manual", f"m{i}", r.get("source_url", ""), r.get("title", ""),
                client=r.get("client", ""), instrument=r.get("instrument") or "Unknown",
                sector_broad=broad_sector(r.get("sector", "")), sector_detail=r.get("sector", ""), status="Signed",
                date=r.get("year", ""), amount=amt, currency=r.get("currency") or "EUR",
                shares={c: None for c in ccs}, method="single_country" if len(ccs) == 1 else "equal_split_estimate",
                note=r.get("note", ""))

    # ---------------------------------------------------------------- write tables
    def write(name, rows, fields):
        with open(OUT / f"{name}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

    inst_rows = [dict(zip(INST_FIELDS, x)) for x in INST]
    write("institutions", inst_rows, INST_FIELDS)
    write("investments", investments, list(investments[0].keys()))
    write("investment_countries", allocations, list(allocations[0].keys()))
    write("countries", [{"iso2": k, "iso3": v[0], "name": v[1], "lat": v[2], "lon": v[3]} for k, v in COUNTRIES.items()],
          ["iso2", "iso3", "name", "lat", "lon"])
    counts = {}
    for inv in investments:
        counts[inv["source_id"]] = counts.get(inv["source_id"], 0) + 1
    SOURCES = [
        ("iati", "IATI via d-portal.org (AFD, KfW/BMZ, FMO, EBRD, Atradius DSB, Invest International, DGGF)", "https://d-portal.org", "api", "IATI data is published under open licences (mostly CC BY / ODbL)"),
        ("eib-api", "EIB signed loans (JSON API behind eib.org/en/projects/loans)", "https://www.eib.org/en/projects/loans/index", "api", "Public website; cite the EIB"),
        ("proparco-web", "Proparco project list and project pages", "https://www.proparco.fr/en/projects/list", "scrape", "Public website; cite Proparco"),
        ("bio-web", "BIO investment portfolio pages", "https://www.bio-invest.be/en/investments", "scrape", "Public website; cite BIO"),
        ("deg-csv", "DEG investments database (CSV export)", "https://deginvest-investments.de/deginvest.csv", "csv", "Public download; cite DEG"),
        ("finnfund-wp", "Finnfund investments (WordPress REST API)", "https://www.finnfund.fi/en/investments/", "api", "Public website; cite Finnfund"),
        ("ifu-wp", "IFU investments (WordPress REST API)", "https://impactfund.dk", "api", "Public website; cite IFU"),
        ("ecb-fx", "ECB monthly reference exchange rates", "https://data.ecb.europa.eu", "api", "ECB statistics, free reuse with attribution"),
        ("manual", "Manual research sheet (ECAs, NPBs, JavaScript-only DFI sites)", "", "manual", "Per-record source URLs"),
    ]
    write("sources", [{"source_id": s[0], "name": s[1], "url": s[2], "method": s[3], "terms": s[4],
                       "last_retrieved": TODAY, "records": counts.get(s[0], "")} for s in SOURCES],
          ["source_id", "name", "url", "method", "terms", "last_retrieved", "records"])

    # compact bundle for the website
    bundle = {"generated": TODAY, "countries": {k: {"name": v[1], "lat": v[2], "lon": v[3]} for k, v in COUNTRIES.items()},
              "institutions": inst_rows,
              "investments": [{k: inv[k] for k in ("investment_id", "institution_id", "title", "client", "client_domicile",
                                                   "instrument", "sector_broad", "status", "year", "amount_eur", "es_category",
                                                   "source_url", "note", "multi_country")} for inv in investments],
              "allocations": [{k: a[k] for k in ("investment_id", "country", "amount_attributed_eur", "attribution_method",
                                                 "lat", "lon", "geo_precision")} for a in allocations]}
    json.dump(bundle, open(OUT / "tracker.json", "w"), ensure_ascii=False, separators=(",", ":"))
    print(f"{len(investments)} investments, {len(allocations)} country allocations")
    by = {}
    for inv in investments:
        by[inv["institution_id"]] = by.get(inv["institution_id"], 0) + 1
    print(by)

def step_build():
    """Inline the data and the world map into the page -> site/index.html"""
    data = json.dumps(json.load(open(ROOT / "data" / "tracker.json", encoding="utf-8")), ensure_ascii=False, separators=(",", ":"))
    world = (ROOT / "ref" / "countries-110m.json").read_text(encoding="utf-8")
    safe = lambda s: s.replace("</", "<\\/")
    html = TEMPLATE.replace("/*__DATA__*/null", safe(data)).replace("/*__WORLD__*/null", safe(world))
    (ROOT / "site" / "index.html").write_text(html, encoding="utf-8")
    print("site/index.html", round(len(html.encode()) / 1e6, 2), "MB")

FETCH_STEPS = ["reference", "iati", "proparco", "bio", "wp", "eib"]

def main(steps):
    inv = ROOT / "data" / "investments.csv"
    before = {r["investment_id"]: r for r in csv.DictReader(open(inv, encoding="utf-8"))} if inv.exists() else {}
    failed = []
    for s in [x for x in FETCH_STEPS if x in steps]:
        print(f"== {s}", flush=True)
        try:
            globals()["step_" + s]()
        except Exception as e:  # one broken website must not stop the update: last month's raw files are kept
            print(f"!! {s} failed: {e!r}", flush=True)
            failed.append(s)
    if "normalize" in steps:
        print("== normalize", flush=True)
        step_normalize()
        after = {r["investment_id"]: r for r in csv.DictReader(open(inv, encoding="utf-8"))}
        added = [k for k in after if k not in before]
        removed = [k for k in before if k not in after]
        changed = [k for k in after if k in before and (after[k]["amount_eur"], after[k]["status"]) != (before[k]["amount_eur"], before[k]["status"])]
        log = ROOT / "data" / "changelog.csv"
        new = not log.exists()
        with open(log, "a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(["run_date", "added", "removed", "changed", "failed_sources"])
            w.writerow([datetime.date.today().isoformat(), len(added), len(removed), len(changed), " ".join(failed)])
        print(f"added {len(added)}, removed {len(removed)}, changed {len(changed)}, failed sources: {failed or 'none'}")
    if "build" in steps:
        print("== build", flush=True)
        step_build()

TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>European public finance in the WAEMU</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,400..800&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#e9eef0; --panel:#f8fafa; --ink:#14232c; --muted:#56666f; --line:#cfd9dd;
  --ocean:#c9dbe2; --land:#f4f2ec; --land-line:#b7c5cb; --eu:#dfe6ea; --waemu:#f1d9a6; --waemu-line:#a8833d;
  --focus:#1d5fd1; --chip:#ffffff;
  --t-dfi:#1f63b5; --t-bdb:#c0520e; --t-npb:#0b7a6e; --t-eca:#b0225c; --t-mdb:#6a3fbf;
  color-scheme:light;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#0f1a20; --panel:#15232b; --ink:#e7eef1; --muted:#9db0b9; --line:#2a3b44;
  --ocean:#18303b; --land:#22343d; --land-line:#3b5260; --eu:#2b414c; --waemu:#6b5426; --waemu-line:#d9b064;
  --focus:#7fb0ff; --chip:#1b2c35;
  --t-dfi:#6aa8ff; --t-bdb:#ff9a57; --t-npb:#3fd1bd; --t-eca:#ff6fa6; --t-mdb:#b493ff;
  color-scheme:dark;}}
:root[data-theme="dark"]{
  --bg:#0f1a20; --panel:#15232b; --ink:#e7eef1; --muted:#9db0b9; --line:#2a3b44;
  --ocean:#18303b; --land:#22343d; --land-line:#3b5260; --eu:#2b414c; --waemu:#6b5426; --waemu-line:#d9b064;
  --focus:#7fb0ff; --chip:#1b2c35;
  --t-dfi:#6aa8ff; --t-bdb:#ff9a57; --t-npb:#3fd1bd; --t-eca:#ff6fa6; --t-mdb:#b493ff;
  color-scheme:dark;}
:root{box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
html{scroll-padding-top:env(safe-area-inset-top,0px)}
*,*::before,*::after{box-sizing:inherit}
html,body{height:100%;margin:0}
body{background:var(--bg);color:var(--ink);font:400 15px/1.5 "Archivo",system-ui,-apple-system,"Segoe UI",sans-serif;font-variation-settings:"wdth" 100}
.app{display:grid;grid-template-columns:minmax(0,1fr) 400px;height:100%}
.stage{position:relative;min-height:0;overflow:hidden}
#globe{position:absolute;inset:0}
.title{position:absolute;left:clamp(16px,3vw,36px);top:clamp(14px,3vh,30px);max-width:34ch;pointer-events:none}
.title h1{margin:0;font-weight:800;font-size:clamp(26px,3.4vw,46px);line-height:1;letter-spacing:-.01em;font-variation-settings:"wdth" 70}
.title p{margin:.6em 0 0;color:var(--muted);font-size:14px;max-width:46ch}
.legend{position:absolute;left:clamp(16px,3vw,36px);bottom:clamp(14px,3vh,28px);display:flex;flex-direction:column;gap:6px;font-size:13px;background:color-mix(in srgb,var(--panel) 82%,transparent);padding:10px 12px;border-radius:10px;border:1px solid var(--line)}
.legend span{display:flex;align-items:center;gap:8px}
.legend i{width:18px;height:3px;border-radius:2px;display:inline-block}
.legend small{color:var(--muted)}
aside{background:var(--panel);border-left:1px solid var(--line);display:flex;flex-direction:column;min-height:0}
.filters{padding:18px 20px 12px;border-bottom:1px solid var(--line);display:grid;gap:12px}
.group h2{margin:0 0 6px;font-size:13px;font-weight:600;color:var(--muted)}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{appearance:none;border:1px solid var(--line);background:var(--chip);color:var(--ink);border-radius:999px;padding:4px 10px 4px 8px;font:inherit;font-size:13px;cursor:pointer;display:inline-flex;align-items:center;gap:6px}
.chip[aria-pressed="false"]{opacity:.45}
.chip .sw{width:10px;height:10px;border-radius:50%}
select{font:inherit;font-size:14px;color:var(--ink);background:var(--chip);border:1px solid var(--line);border-radius:8px;padding:6px 8px;width:100%}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
button:focus-visible,select:focus-visible,a:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
.summary{padding:14px 20px;border-bottom:1px solid var(--line)}
.summary .sel{display:flex;justify-content:space-between;gap:8px;align-items:baseline}
.summary strong{font-size:30px;font-weight:700;font-variation-settings:"wdth" 75;letter-spacing:-.01em}
.summary p{margin:4px 0 0;color:var(--muted);font-size:13px}
.clear{appearance:none;background:none;border:0;color:var(--focus);font:inherit;font-size:13px;cursor:pointer;padding:0;text-decoration:underline}
.list{overflow:auto;min-height:0;flex:1;padding:4px 0 16px}
.deal{padding:12px 20px;border-bottom:1px solid var(--line)}
.deal h3{margin:0;font-size:15px;font-weight:600;line-height:1.3}
.deal .meta{display:flex;flex-wrap:wrap;gap:4px 12px;margin-top:4px;font-size:13px;color:var(--muted)}
.deal .amt{font-variation-settings:"wdth" 80;font-weight:600;color:var(--ink)}
.deal .who{display:flex;align-items:center;gap:6px}
.deal .note{font-size:12px;color:var(--muted);margin-top:4px}
.deal a{color:var(--focus);font-size:13px}
.flag{font-size:12px;border:1px dashed var(--line);border-radius:4px;padding:0 5px}
.more{display:block;margin:12px auto;appearance:none;border:1px solid var(--line);background:var(--chip);color:var(--ink);font:inherit;font-size:14px;border-radius:8px;padding:6px 14px;cursor:pointer}
.foot{padding:10px 20px;border-top:1px solid var(--line);font-size:12px;color:var(--muted)}
.foot details summary{cursor:pointer}
.tip{font:13px/1.4 "Archivo",system-ui,sans-serif;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:8px 10px;max-width:260px}
@media (max-width:860px){
  .app{grid-template-columns:1fr;grid-template-rows:62vh auto;height:auto}
  .stage{height:62vh}
  aside{border-left:0;border-top:1px solid var(--line)}
  .list{overflow:visible}
  .legend{font-size:12px}
}
</style>
</head>
<body>
<div class="app">
  <section class="stage" aria-label="Interactive globe">
    <div id="globe"></div>
    <div class="title">
      <h1>European public finance in the WAEMU</h1>
      <p>Where European development banks, DFIs, promotional banks and export credit agencies invest across the eight countries of the West African Monetary Union. Click an arc, a country or a capital.</p>
    </div>
    <div class="legend" id="legend" aria-label="Legend"></div>
  </section>
  <aside>
    <div class="filters">
      <div class="group"><h2>Institution type</h2><div class="chips" id="f-type"></div></div>
      <div class="row2">
        <div class="group"><h2><label for="f-ms">Member state</label></h2><select id="f-ms"></select></div>
        <div class="group"><h2><label for="f-inst">Institution</label></h2><select id="f-inst"></select></div>
      </div>
      <div class="group"><h2>Recipient country</h2><div class="chips" id="f-cc"></div></div>
      <div class="row2">
        <div class="group"><h2><label for="f-ins">Instrument</label></h2><select id="f-ins"></select></div>
        <div class="group"><h2><label for="f-yr">Signed or started since</label></h2><select id="f-yr"></select></div>
      </div>
    </div>
    <div class="summary" aria-live="polite">
      <div class="sel"><strong id="s-total">–</strong><button class="clear" id="reset">Reset filters</button></div>
      <p id="s-text"></p>
    </div>
    <div class="list" id="list"></div>
    <div class="foot">
      <details><summary>About the data</summary>
        <p>Data updated <span id="gen"></span>. Amounts are commitments in euros. Multi-country deals without published country shares are split equally and marked as estimates. Regional deals that only mention a WAEMU country are listed but not counted in totals.</p>
        <p id="gaps"></p>
      </details>
    </div>
  </aside>
</div>
<script src="https://cdn.jsdelivr.net/npm/topojson-client@3.1.0/dist/topojson-client.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/globe.gl@2.46.2/dist/globe.gl.min.js"></script>
<script>
const DATA = /*__DATA__*/null;
const WORLD = /*__WORLD__*/null;
</script>
<script>
(() => {
const TYPES = [
  ["DFI","DFI","--t-dfi"], ["Bilateral development bank","Development bank","--t-bdb"],
  ["NPB","Promotional bank","--t-npb"], ["ECA","Export credit agency","--t-eca"],
  ["Multilateral","Multilateral","--t-mdb"]];
const MS = {FR:"France",DE:"Germany",NL:"Netherlands",BE:"Belgium",FI:"Finland",DK:"Denmark",SE:"Sweden",
  AT:"Austria",ES:"Spain",IT:"Italy",PT:"Portugal",PL:"Poland",EU:"EU institution",INT:"International (EBRD)"};
const SHORT = {afd:"AFD",proparco:"Proparco","kfw-db":"KfW",deg:"DEG",fmo:"FMO","invest-intl":"Invest International",
  dggf:"DGGF",bio:"BIO",finnfund:"Finnfund",ifu:"IFU","atradius-dsb":"Atradius DSB",eib:"EIB",ebrd:"EBRD"};
const WAEMU_NUM = {"204":"BJ","854":"BF","384":"CI","624":"GW","466":"ML","562":"NE","686":"SN","768":"TG"};
const EU_NUM = new Set(["040","056","100","191","196","203","208","233","246","250","276","300","348","372","380","428","440","442","470","528","616","620","642","703","705","724","752"]);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const typeVar = Object.fromEntries(TYPES.map(t => [t[0], t[2]]));
const INST = Object.fromEntries(DATA.institutions.map(i => [i.institution_id, i]));
const INV = Object.fromEntries(DATA.investments.map(i => [i.investment_id, i]));
const withData = new Set(DATA.investments.map(i => i.institution_id));
const fmt = v => v >= 1e9 ? "€" + (v/1e9).toFixed(1) + " bn" : v >= 1e6 ? "€" + (v/1e6).toFixed(v >= 1e8 ? 0 : 1) + " m" : v >= 1e3 ? "€" + Math.round(v/1e3) + " k" : "€" + Math.round(v);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

const state = {types:new Set(TYPES.map(t => t[0])), ms:"", inst:"", cc:new Set(Object.keys(DATA.countries)), ins:"", yr:"", focus:null, shown:40};

// ---------- filter controls
const fType = document.getElementById("f-type");
TYPES.forEach(([k,label,v]) => {
  const b = document.createElement("button"); b.className = "chip"; b.type = "button"; b.setAttribute("aria-pressed","true");
  b.innerHTML = `<span class="sw" style="background:var(${v})"></span>${label}`;
  b.onclick = () => { state.types.has(k) ? state.types.delete(k) : state.types.add(k); b.setAttribute("aria-pressed", state.types.has(k)); update(); };
  fType.append(b);
});
const fCC = document.getElementById("f-cc");
Object.entries(DATA.countries).forEach(([cc,c]) => {
  const b = document.createElement("button"); b.className = "chip"; b.type = "button"; b.dataset.cc = cc;
  b.setAttribute("aria-pressed","true"); b.textContent = c.name;
  b.onclick = () => { state.cc.has(cc) ? state.cc.delete(cc) : state.cc.add(cc); b.setAttribute("aria-pressed", state.cc.has(cc)); update(); };
  fCC.append(b);
});
function opts(el, list, all) { el.innerHTML = `<option value="">${all}</option>` + list.map(([v,l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join(""); }
const msList = [...new Set(DATA.institutions.filter(i => withData.has(i.institution_id)).map(i => i.member_state))];
opts(document.getElementById("f-ms"), msList.map(m => [m, MS[m] || m]), "All");
opts(document.getElementById("f-inst"), DATA.institutions.filter(i => withData.has(i.institution_id)).map(i => [i.institution_id, SHORT[i.institution_id] || i.name]), "All");
opts(document.getElementById("f-ins"), [...new Set(DATA.investments.map(i => i.instrument))].sort().map(x => [x,x]), "All");
const years = [...new Set(DATA.investments.map(i => i.year).filter(Boolean))].sort();
opts(document.getElementById("f-yr"), [2000,2010,2015,2020,2023,2025].filter(y => y >= +years[0]).map(y => [y, String(y)]), "Any year");
for (const [id,key] of [["f-ms","ms"],["f-inst","inst"],["f-ins","ins"],["f-yr","yr"]])
  document.getElementById(id).onchange = e => { state[key] = e.target.value; state.focus = null; update(); };
document.getElementById("reset").onclick = () => {
  Object.assign(state, {types:new Set(TYPES.map(t => t[0])), ms:"", inst:"", cc:new Set(Object.keys(DATA.countries)), ins:"", yr:"", focus:null});
  document.querySelectorAll(".chip").forEach(c => c.setAttribute("aria-pressed","true"));
  ["f-ms","f-inst","f-ins","f-yr"].forEach(id => document.getElementById(id).value = "");
  update();
};
document.getElementById("gen").textContent = DATA.generated;
const gaps = DATA.institutions.filter(i => !withData.has(i.institution_id));
document.getElementById("gaps").textContent = "Not yet covered (no machine-readable disclosure found): " + gaps.map(i => i.name).join(", ") + ".";

// ---------- legend
document.getElementById("legend").innerHTML = TYPES.map(([,l,v]) => `<span><i style="background:var(${v})"></i>${l}</span>`).join("") +
  `<small>Arc width grows with the amount invested</small>`;

// ---------- filtering
function passInv(inv) {
  const ins = INST[inv.institution_id];
  if (!state.types.has(ins.type)) return false;
  if (state.ms && ins.member_state !== state.ms) return false;
  if (state.inst && inv.institution_id !== state.inst) return false;
  if (state.ins && inv.instrument !== state.ins) return false;
  if (state.yr && !(inv.year && +inv.year >= +state.yr)) return false;
  return true;
}
function filtered() {
  const rows = [];
  for (const a of DATA.allocations) {
    if (!state.cc.has(a.country)) continue;
    const inv = INV[a.investment_id];
    if (!passInv(inv)) continue;
    if (state.focus) {
      if (state.focus.inst && inv.institution_id !== state.focus.inst) continue;
      if (state.focus.cc && a.country !== state.focus.cc) continue;
    }
    rows.push([a, inv]);
  }
  return rows;
}

// ---------- globe
const el = document.getElementById("globe");
const globe = Globe()(el)
  .backgroundColor("rgba(0,0,0,0)")
  .showAtmosphere(true).atmosphereAltitude(0.12)
  .polygonsData(topojson.feature(WORLD, WORLD.objects.countries).features)
  .polygonAltitude(f => WAEMU_NUM[f.id] ? 0.012 : 0.004)
  .polygonStrokeColor(f => WAEMU_NUM[f.id] ? css("--waemu-line") : css("--land-line"))
  .polygonSideColor(() => "rgba(0,0,0,0)")
  .polygonLabel(f => WAEMU_NUM[f.id] ? `<div class="tip"><b>${esc(f.properties.name)}</b><br>Click to see deals</div>` : "")
  .onPolygonClick(f => { const cc = WAEMU_NUM[f.id]; if (cc) { state.focus = {cc}; update(); } })
  .arcStartLat(d => d.sLat).arcStartLng(d => d.sLng).arcEndLat(d => d.eLat).arcEndLng(d => d.eLng)
  .arcAltitudeAutoScale(0.35)
  .arcLabel(d => `<div class="tip"><b>${esc(d.label)}</b> to ${esc(DATA.countries[d.cc].name)}<br>${d.n} deal${d.n>1?"s":""}${d.sum ? ", " + fmt(d.sum) : ""}</div>`)
  .onArcClick(d => { state.focus = {inst:d.inst, cc:d.cc}; update(); })
  .pointLat("lat").pointLng("lng").pointAltitude(0.01).pointRadius(0.35)
  .pointLabel(d => `<div class="tip"><b>${esc(d.name)}</b><br>${esc(d.city)}</div>`)
  .onPointClick(d => { state.focus = {inst:d.id}; update(); })
  .labelLat("lat").labelLng("lng").labelText("name").labelSize(0.9).labelDotRadius(0).labelAltitude(0.015)
  .labelResolution(2);
function paint() {
  globe.globeMaterial().color.set(css("--ocean"));
  globe.atmosphereColor(css("--ocean"));
  globe.polygonCapColor(f => WAEMU_NUM[f.id] ? css("--waemu") : EU_NUM.has(f.id) ? css("--eu") : css("--land"));
  globe.labelColor(() => css("--ink"));
  update(false);
}
globe.pointOfView({lat: 28, lng: -4, altitude: 1.75}, 0);
const ctl = globe.controls(); ctl.autoRotate = false; ctl.enableDamping = true;
new ResizeObserver(() => globe.width(el.clientWidth).height(el.clientHeight)).observe(el);

function update(resetList = true) {
  if (resetList) state.shown = 40;
  const rows = filtered();
  // aggregate arcs institution -> country
  const agg = new Map();
  for (const [a, inv] of rows) {
    const k = inv.institution_id + "|" + a.country;
    const g = agg.get(k) || {inst:inv.institution_id, cc:a.country, n:0, sum:0};
    g.n++; g.sum += a.amount_attributed_eur || 0; agg.set(k, g);
  }
  const arcs = [...agg.values()].map(g => {
    const ins = INST[g.inst], c = DATA.countries[g.cc];
    return {...g, label: SHORT[g.inst] || ins.name, sLat:+ins.hq_lat, sLng:+ins.hq_lon, eLat:c.lat, eLng:c.lon,
            color: css(typeVar[ins.type]), stroke: Math.max(0.06, Math.log10(Math.max(g.sum, 1e5)) - 4.8) * 0.13};
  });
  globe.arcsData(arcs).arcColor("color").arcStroke("stroke")
    .arcDashLength(reduceMotion ? 1 : 0.5).arcDashGap(reduceMotion ? 0 : 0.15).arcDashAnimateTime(reduceMotion ? 0 : 5000);
  const instIds = new Set(arcs.map(a => a.inst));
  globe.pointsData(DATA.institutions.filter(i => instIds.has(i.institution_id)).map(i => ({id:i.institution_id, name:i.name, city:i.hq_city, lat:+i.hq_lat, lng:+i.hq_lon})))
    .pointColor(d => css(typeVar[INST[d.id].type]));
  globe.labelsData(Object.entries(DATA.countries).filter(([cc]) => state.cc.has(cc)).map(([cc,c]) => ({name:c.name, lat:c.lat, lng:c.lon})));
  renderPanel(rows);
}

function renderPanel(rows) {
  const counted = rows.filter(([a]) => a.amount_attributed_eur != null);
  const total = counted.reduce((s,[a]) => s + a.amount_attributed_eur, 0);
  const deals = new Set(rows.map(([,inv]) => inv.investment_id));
  const instN = new Set(rows.map(([,inv]) => inv.institution_id));
  document.getElementById("s-total").textContent = fmt(total);
  let scope = "";
  if (state.focus) {
    const parts = [];
    if (state.focus.inst) parts.push(SHORT[state.focus.inst] || INST[state.focus.inst].name);
    if (state.focus.cc) parts.push("in " + DATA.countries[state.focus.cc].name);
    scope = " Showing " + parts.join(" ") + ".";
  }
  const unk = rows.filter(([a]) => a.amount_attributed_eur == null).length;
  document.getElementById("s-text").textContent =
    `${deals.size.toLocaleString()} deals from ${instN.size} institution${instN.size === 1 ? "" : "s"}.` + scope +
    (unk ? ` ${unk} allocations have no disclosed or attributable amount.` : "");
  // list, one row per deal (country allocations merged)
  const byDeal = new Map();
  for (const [a, inv] of rows) {
    const d = byDeal.get(inv.investment_id) || {inv, ccs:[], sum:0, est:false, reg:false};
    d.ccs.push(a.country); d.sum += a.amount_attributed_eur || 0;
    if (a.attribution_method === "equal_split_estimate") d.est = true;
    if (a.attribution_method === "regional_unallocated") d.reg = true;
    byDeal.set(inv.investment_id, d);
  }
  const list = [...byDeal.values()].sort((x,y) => (y.sum || y.inv.amount_eur || 0) - (x.sum || x.inv.amount_eur || 0));
  const box = document.getElementById("list");
  if (!list.length) { box.innerHTML = `<p class="deal">No deals match these filters. Widen the year range or turn an institution type back on.</p>`; return; }
  box.innerHTML = list.slice(0, state.shown).map(({inv, ccs, sum, est, reg}) => {
    const ins = INST[inv.institution_id];
    const amount = sum ? fmt(sum) : inv.amount_eur ? fmt(inv.amount_eur) + " total" : "Amount not disclosed";
    return `<article class="deal">
      <h3>${esc(inv.title)}</h3>
      <div class="meta">
        <span class="who"><span class="sw" style="width:9px;height:9px;border-radius:50%;background:var(${typeVar[ins.type]})"></span>${esc(SHORT[ins.institution_id] || ins.name)}</span>
        <span>${ccs.map(c => esc(DATA.countries[c].name)).join(", ")}</span>
        ${inv.year ? `<span>${esc(inv.year)}</span>` : ""}
        <span>${esc(inv.instrument)}</span>
        <span class="amt">${amount}</span>
        ${est ? `<span class="flag" title="Multi-country deal split equally across listed countries">estimated share</span>` : ""}
        ${reg ? `<span class="flag" title="Regional deal, amount not allocated to WAEMU countries">regional</span>` : ""}
      </div>
      ${inv.client && inv.client !== inv.title ? `<div class="note">Client: ${esc(inv.client)}${inv.client_domicile ? ", " + esc(inv.client_domicile) : ""}</div>` : ""}
      <a href="${esc(inv.source_url)}" target="_blank" rel="noopener">View source record</a>
    </article>`;
  }).join("") + (list.length > state.shown ? `<button class="more" id="more">Show ${Math.min(40, list.length - state.shown)} more of ${list.length - state.shown}</button>` : "");
  const m = document.getElementById("more");
  if (m) m.onclick = () => { state.shown += 40; renderPanel(filtered()); };
}

matchMedia("(prefers-color-scheme: dark)").addEventListener("change", paint);
paint();
})();
</script>
</body>
</html>
'''

if __name__ == "__main__":
    main(sys.argv[1:] or FETCH_STEPS + ["normalize", "build"])
