"""EU public financial institutions in the WAEMU - complete tracker in one file.

Run everything:      python tracker.py
Run some steps only: python tracker.py eib normalize build
Steps: reference iati proparco bio wp eib normalize build
"""
import os, sys, csv, json, pathlib, datetime
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
     "XI-IATI-EC_INTPA":"European Commission DG INTPA",
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
        ("eu-intpa", "European Commission – DG International Partnerships (NDICI-Global Europe, EDF)", "EU", "EU institution", "European Union", "Brussels", 50.843, 4.382, "https://international-partnerships.ec.europa.eu", "automated"),
        ("eib", "European Investment Bank (EIB)", "EU", "EU institution", "EIB Group", "Luxembourg", 49.627, 6.155, "https://www.eib.org", "automated"),
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
        if date and date[:4].isdigit() and int(date[:4]) > datetime.date.today().year + 3:
            date = ""  # placeholder dates in some IATI files
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
                 "NL-KVK-61172863": "dggf", "DE-1": "kfw-db", "XI-IATI-EC_INTPA": "eu-intpa"}
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
        ("iati", "IATI via d-portal.org (European Commission DG INTPA, AFD, KfW/BMZ, FMO, EBRD, Atradius DSB, Invest International, DGGF)", "https://d-portal.org", "api", "IATI data is published under open licences (mostly CC BY / ODbL)"),
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

    # ---------------------------------------------------------------- programmes (curated, sourced)
    # Team Europe Initiatives, Global Gateway flagships, EU country envelopes and national programmes that
    # publish no deal-level data. Participants are institution ids or ISO codes of member states ("EU" = European Commission).
    PARTICIPANT_PLACES = {
        "EU": ("European Commission", 50.843, 4.382), "EIB": ("European Investment Bank", 49.627, 6.155),
        "AT": ("Austria", 48.208, 16.374), "BE": ("Belgium", 50.850, 4.352), "CZ": ("Czechia", 50.076, 14.438),
        "DE": ("Germany", 52.520, 13.405), "DK": ("Denmark", 55.676, 12.568), "ES": ("Spain", 40.417, -3.704),
        "FI": ("Finland", 60.170, 24.938), "FR": ("France", 48.857, 2.352), "GR": ("Greece", 37.984, 23.728),
        "HU": ("Hungary", 47.498, 19.040), "IE": ("Ireland", 53.350, -6.260), "IT": ("Italy", 41.903, 12.496),
        "LU": ("Luxembourg", 49.611, 6.130), "MT": ("Malta", 35.899, 14.514), "NL": ("Netherlands", 52.370, 4.895),
        "PL": ("Poland", 52.230, 21.012), "PT": ("Portugal", 38.722, -9.139), "RO": ("Romania", 44.427, 26.103),
        "SE": ("Sweden", 59.329, 18.069),
    }
    for _i in INST:  # institutions can also be programme participants (e.g. Bpifrance, AFD)
        PARTICIPANT_PLACES.setdefault(_i[0], (_i[1], _i[6], _i[7]))
    TE_COUNTRY = {  # Team Europe members per country, as listed on the European Commission's country pages
        "CI": "EU EIB BE FI FR DE IT ES NL", "SN": "EU EIB AT BE CZ FI FR DE GR HU IE IT LU NL PL PT RO ES",
        "BJ": "EU EIB BE FR DE LU NL", "BF": "EU EIB BE NL DE IT", "ML": "EU DE BE ES IT NL",
        "NE": "EU FR DE BE ES IT LU NL", "TG": "EU FR DE", "GW": "EU EIB FR PT ES"}
    EC = "https://international-partnerships.ec.europa.eu/countries/"
    TRACKER_FR = "https://capacity4dev.europa.eu/resources/team-europe-tracker/team-europe-actors/france/tei_en"
    TRACKER_EU = "https://capacity4dev.europa.eu/resources/team-europe-tracker/team-europe-actors/eu/tei_en"
    GG_INFO = ("https://international-partnerships.ec.europa.eu/document/download/ed505ccf-18ef-4fe9-816b-587d28f10633_en"
               "?filename=infographics-global-gateway-flagship-projects-2023-2024-eu-africa_en.pdf")
    GG_LIST = "https://www.eacea.ec.europa.eu/document/download/cd93ca39-db48-4334-aebe-8bbe2b82a8df_en?filename=country_regional+GG+flagships.pdf"
    CORR = "https://international-partnerships.ec.europa.eu/policies/global-gateway/transport/eu-africa-strategic-corridors_en"
    MEMBERS_NOTE = "Participants shown are Team Europe members in the country; the EU does not openly publish membership per initiative."
    TEI, GG, ENV, PART, NAT = "Team Europe Initiative", "Global Gateway flagship", "EU country envelope", "Energy transition partnership", "National programme"
    def P(pid, name, kind, countries, participants, desc, source, amount=None, period="", note=""):
        return {"programme_id": pid, "name": name, "kind": kind, "countries": countries.split(),
                "participants": participants.split(), "amount_eur": amount, "period": period,
                "description": desc, "source_url": source, "note": note}
    PROGRAMMES = [
        # Country Team Europe Initiatives
        P("tei-ci-cocoa", "Côte d'Ivoire – Sustainable cocoa", TEI, "CI", TE_COUNTRY["CI"], "Living incomes for farmers, deforestation, child labour and compliance with EU rules in the cocoa value chain.", "https://www.eeas.europa.eu/node/447556_en", note=MEMBERS_NOTE),
        P("tei-ci-lowcarbon", "Côte d'Ivoire – Low-carbon transition", TEI, "CI", TE_COUNTRY["CI"], "Renewable power (Boundiali and Sérébou solar plants), the 400 kV eastern backbone line, clean cooking, energy efficiency and cleaner transport.", EC + "cote-divoire_en", note=MEMBERS_NOTE),
        P("tei-ci-peace", "Côte d'Ivoire – Peace, stability and social cohesion", TEI, "CI", TE_COUNTRY["CI"], "Keeping Côte d'Ivoire a pole of stability in West Africa, especially in the northern border regions.", "https://www.eeas.europa.eu/node/447556_en", note=MEMBERS_NOTE),
        P("tei-sn-green", "Senegal – Green economy", TEI, "SN", TE_COUNTRY["SN"], "Green agriculture and sustainable, digital cities.", EC + "senegal_en", note=MEMBERS_NOTE),
        P("tei-bj-port", "Benin – Investing for a sustainable port", TEI, "BJ", TE_COUNTRY["BJ"], "Port of Cotonou, coastline and the sustainable port economy.", TRACKER_EU, note=MEMBERS_NOTE),
        P("tei-bj-energy", "Benin – Investing in green energy", TEI, "BJ", "EU FR DE", "Renewables, energy efficiency, access to energy and regional cooperation through the West African Power Pool.", "https://capacity4dev.europa.eu/resources/team-europe-tracker/partner-countries/benin/benin-investing-green-energy_en"),
        P("tei-bj-jobs", "Benin – Sustainable growth and jobs", TEI, "BJ", "EU BE FR DE NL", "Vocational training, private-sector support in agriculture and digital, and digitisation of public services.", TRACKER_EU),
        P("tei-bf-greendeal", "Burkina Faso – Green Deal for youth", TEI, "BF", TE_COUNTRY["BF"], "Agri-food value chains, rural electrification, digital skills and secondary cities on the Abidjan–Ouagadougou corridor.", TRACKER_FR, note=MEMBERS_NOTE),
        P("tei-bf-stability", "Burkina Faso – Inclusion for stability", TEI, "BF", TE_COUNTRY["BF"], "Basic services, social protection and support to displaced people and host communities.", TRACKER_FR, note=MEMBERS_NOTE),
        P("tei-ml-climate", "Mali – Environment and climate change", TEI, "ML", TE_COUNTRY["ML"], "Natural resource management, climate-resilient agriculture, hydropower and off-grid electrification, the Great Green Wall.", TRACKER_FR, note=MEMBERS_NOTE),
        P("tei-ml-youth", "Mali – Youth", TEI, "ML", TE_COUNTRY["ML"], "Skills, jobs and entrepreneurship for young people and women.", TRACKER_FR, note=MEMBERS_NOTE),
        P("tei-ne-futures", "Niger – #NigerGenerationsFutures", TEI, "NE", TE_COUNTRY["NE"], "Education, vocational training and prospects for young people.", TRACKER_FR, note=MEMBERS_NOTE),
        P("tei-ne-governance", "Niger – Governance, peace and rights", TEI, "NE", TE_COUNTRY["NE"], "Governance, security and human rights.", TRACKER_FR, note=MEMBERS_NOTE),
        P("tei-tg-decentral", "Togo – Decentralisation and local governance", TEI, "TG", TE_COUNTRY["TG"], "Local authorities, civil society and governance processes.", TRACKER_FR, note=MEMBERS_NOTE),
        P("tei-tg-agri", "Togo – Sustainable agribusiness", TEI, "TG", TE_COUNTRY["TG"], "Pineapple, cashew and soya value chains, smallholder productivity and women's entrepreneurship.", TRACKER_FR, note=MEMBERS_NOTE),
        P("tei-tg-energy", "Togo – Sustainable energy and digitalisation", TEI, "TG", TE_COUNTRY["TG"], "Renewable electricity distribution for over a million people and digital entrepreneurship.", TRACKER_FR, note=MEMBERS_NOTE),
        P("tei-gw-education", "Guinea-Bissau – Education and training for an inclusive, green transition", TEI, "GW", "EU PT", "Reform of primary and higher education, teacher and student mobility, scientific research.", "https://capacity4dev.europa.eu/resources/team-europe-tracker/partner-countries/guinea-bissau/guinea-bissau-education-and-training-towards-inclusive-and-green-transition_en"),
        # Regional Team Europe Initiatives covering WAEMU countries
        P("tei-atlantic", "Migration – Atlantic and Western Mediterranean routes", TEI, "SN BF CI ML NE", "EU BE CZ DK FR DE IT NL ES", "Regional migration and mobility initiative; also covers Algeria, Mauritania, Morocco, The Gambia, Ghana, Guinea and Nigeria.", "https://enlargement.ec.europa.eu/news/eu-working-together-african-partners-migration-launch-team-europe-initiatives-2022-12-12_en", amount=908e6, period="2022–", note="€908m mobilised at launch across all 12 partner countries, not only WAEMU."),
        P("tei-centralmed", "Migration – Central Mediterranean route", TEI, "BF NE CI", "EU AT BE DE CZ DK FR IT MT NL ES", "Regional migration initiative; also covers Chad, Egypt, Libya, Ethiopia, Eritrea, Somalia, Sudan, Tunisia, Guinea and Nigeria.", "https://enlargement.ec.europa.eu/news/eu-working-together-african-partners-migration-launch-team-europe-initiatives-2022-12-12_en", period="2022–"),
        P("tei-iyba", "Investing in Young Businesses in Africa (IYBA)", TEI, "BJ SN TG BF ML NE", "EU EIB FR DE BE NL", "Finance and technical support for start-ups and small businesses; Benin was the pilot country (launched in Cotonou, March 2024).", "https://international-partnerships.ec.europa.eu/policies/global-gateway/investing-young-businesses-africa_en", period="2021–", note="Country list per the Commission; participants are the core members named in public communication and may be incomplete."),
        P("tei-opvet", "Opportunity-driven skills and vocational training in Africa (OP-VET)", TEI, "BJ BF ML NE TG CI GW SN", "EU", "Aligning vocational training with jobs created by public and private investment.", "https://capacity4dev.europa.eu/countries/nigeria/projects_en", period="2024–"),
        P("tei-mav", "Manufacturing and access to vaccines, medicines and health technologies (MAV+)", TEI, "SN", "EU EIB FR DE BE", "Continental initiative; in Senegal it backs the MADIBA vaccine plant at Institut Pasteur de Dakar and the national pharmaceutical plan.", EC + "senegal_en", note="Participants named are the most visible members; the full list is not openly published."),
        P("tei-water", "Transboundary water management in Africa", TEI, "SN ML NE BJ BF CI TG", "EU", "Senegal, Gambia, Niger and Volta basins among those targeted.", "https://capacity4dev.europa.eu/groups/public-water_and_sanitation/info/team-europe-initiative-transboundary-water-management-africa_en", period="2022–"),
        # Global Gateway flagships
        P("gg-sn-hann", "Hann Bay depollution, Dakar", GG, "SN", "EU EIB afd", "Cleaning up Dakar's Hann Bay and its industrial and household wastewater.", EC + "senegal_en"),
        P("gg-sn-brt", "Dakar Bus Rapid Transit and bus network", GG, "SN", "EU EIB", "Construction of the BRT line and restructuring of Dakar's public bus network.", GG_INFO),
        P("gg-sn-ziguinchor", "Port of Ziguinchor upgrade (Casamance)", GG, "SN", "EU", "Upgrade and operation of the port of Ziguinchor.", GG_INFO),
        P("gg-sn-river", "Senegal River Valley development", GG, "SN", "EU", "Resilience and development in the Senegal River Valley, with irrigation (PARIIS) and rural development (PADAER II).", GG_INFO),
        P("gg-sn-medusa", "Medusa subsea cable extension to Dakar", GG, "SN", "EU EIB", "Extension of the Medusa Mediterranean cable to West Africa, first landing envisaged in Dakar.", GG_LIST, note="Envisaged; not yet built."),
        P("gg-bj-wapp", "WAPP solar plant and mini-grids, Benin", GG, "BJ", "EU", "Large-scale solar power plant upgrade and photovoltaic mini-grids with the West African Power Pool.", GG_INFO),
        P("gg-bj-roads", "Benin roads on strategic corridors", GG, "BJ", "EU", "Includes the 210 km Djougou–Pehunco–Kérou and 152 km Allada–Dassa roads.", EC + "benin_en"),
        P("gg-bj-cotonou-ww", "Wastewater treatment, west Cotonou", GG, "BJ", "EU", "Sanitation systems and wastewater treatment in the west of Cotonou.", GG_INFO),
        P("gg-bj-tvet", "Technical and vocational schools, Benin", GG, "BJ", "EU EIB", "Renovation and construction of professional and technical schools.", GG_INFO),
        P("gg-ci-solar", "Boundiali and Sérébou solar plants", GG, "CI", "EU", "37.5 MWp Boundiali plant (inaugurated April 2024) and 33 MWp Sérébou plant with 14 MW battery storage.", EC + "cote-divoire_en", note="Other financing partners are not listed here; see the source."),
        P("gg-ci-backbone", "400 kV eastern backbone transmission line", GG, "CI", "EU", "Line from north of Abidjan to Ferkessédougou at the Mali and Burkina Faso borders.", EC + "cote-divoire_en"),
        P("gg-ci-300m", "Team Europe €300m package, Côte d'Ivoire (2025)", GG, "CI", "EU EIB", "Climate action, sustainable cocoa and forest restoration; includes a €50m EIB loan to raise Côte d'Ivoire's stake in ATIDI.", "https://www.eib.org/fr/press/all/2025-012-global-gateway-l-equipe-europe-renforce-a-hauteur-de-300-millions-d-euros-son-soutien-a-des-investissements-strategiques-et-durables-en-cote-d-ivoire", amount=300e6, period="2025"),
        P("gg-tg-coast", "Coastal protection, Togo", GG, "TG", "EU", "Nature-based coastal protection through dune restoration.", GG_LIST),
        P("gg-dorsale", "North Core (Dorsale Nord) 330 kV interconnector", GG, "NE BJ BF", "EU", "Regional power line Nigeria–Niger–Benin–Burkina Faso.", GG_LIST),
        P("gg-naturafrica", "NaturAfrica – West Africa landscapes", GG, "BF BJ", "EU", "Transboundary conservation landscapes, including the Sudano-Sahelian savannahs.", GG_LIST),
        P("gg-corr-abj-lagos", "Strategic corridor Abidjan–Lagos", GG, "CI TG BJ", "EU EIB", "Transport and trade corridor also crossing Ghana and Nigeria.", CORR),
        P("gg-corr-abj-ouaga", "Strategic corridor Abidjan–Ouagadougou", GG, "CI BF", "EU EIB", "Transport and trade corridor.", CORR),
        P("gg-corr-dakar-abj", "Strategic corridor Praia/Dakar–Abidjan", GG, "SN GW CI", "EU EIB", "Coastal corridor also crossing Cabo Verde, The Gambia, Guinea, Sierra Leone and Liberia.", CORR),
        P("gg-corr-cot-niamey", "Strategic corridor Cotonou–Niamey", GG, "BJ NE", "EU", "Transport and trade corridor.", CORR),
        P("gg-eib-ppf", "EU-Africa Global Gateway Infrastructure Project Delivery Facility", GG, "SN BJ CI", "EIB EU", "Project preparation support so infrastructure becomes ready for EIB financing.", "https://www.eib.org/en/products/mandates-partnerships/eu-africa-global-gateway-infrastructure-facility/index"),
        # Energy transition partnership
        P("jetp-sn", "Senegal Just Energy Transition Partnership (JETP)", PART, "SN", "EU FR DE", "Investment and reforms to raise renewables in Senegal's power mix; Canada and the United Kingdom are also partners.", EC + "senegal_en", amount=2.5e9, period="2023–", note="€2.5bn is the total from all international partners, not only European ones."),
        # EU country envelopes (NDICI-Global Europe grants)
        P("env-ci", "EU bilateral envelope – Côte d'Ivoire", ENV, "CI", "EU", "NDICI-Global Europe national allocation, complemented by regional programmes, blending and guarantees.", EC + "cote-divoire_en", amount=381e6, period="2021–2027"),
        P("env-sn", "EU bilateral envelope – Senegal", ENV, "SN", "EU", "NDICI-Global Europe grant funding for the bilateral partnership.", EC + "senegal_en", amount=337e6, period="2021–2027"),
        P("env-bj", "EU bilateral envelope – Benin", ENV, "BJ", "EU", "NDICI-Global Europe national programme: €255m for 2021–2024 and €172m for 2025–2027.", EC + "benin_en", amount=427e6, period="2021–2027"),
        P("env-bf", "EU bilateral envelope – Burkina Faso", ENV, "BF", "EU", "Grant funding around inclusive human development and a green, resilient economy.", EC + "burkina-faso_en", amount=283e6, period="2021–2024"),
        P("env-ml", "EU bilateral envelope – Mali", ENV, "ML", "EU", "Grant funding around green growth and youth; from 2025 Mali draws on funds for central Sahel countries in complex settings.", EC + "mali_en", amount=151e6, period="2021–2024"),
        P("env-ne", "EU bilateral envelope – Niger", ENV, "NE", "EU", "Governance, education and vocational training, growth and the green economy.", EC + "niger_en", amount=382.34e6, period="2021–2024"),
        P("env-tg", "EU bilateral envelope – Togo", ENV, "TG", "EU", "Agribusiness, energy, digital and governance.", EC + "togo_en", amount=201e6, period="2021–2027"),
        P("env-gw", "EU bilateral envelope – Guinea-Bissau", ENV, "GW", "EU", "Health, education and training, economic diversification and governance.", EC + "guinea-bissau_en", amount=155e6, period="2021–2027"),
        # National programmes without deal-level disclosure
        P("nat-choose-africa-2", "Choose Africa 2 (AFD Group and Bpifrance)", NAT, "BJ CI SN TG", "afd proparco bpifrance", "Financing and support for African start-ups and small businesses, plus help for states to build public banks for entrepreneurs.", "https://www.afd.fr/fr/actualites/choose-africa-2-le-soutien-lentrepreneuriat-africain-monte-en-regime", period="2023–2027"),
        P("nat-choose-africa-2-ci", "Choose Africa 2 – Côte d'Ivoire SME financing", NAT, "CI", "afd bpifrance", "XOF 52bn (€80m) loan for credit lines and the SME guarantee fund (SGPME), via Côte d'Ivoire PME.", "https://www.afd.fr/fr/actualites/communique-de-presse/choose-africa-2-un-premier-financement-en-cote-divoire-pour-renforcer-lacces-au-credit-de-plusieurs-milliers-de-tpme-en-particulier-de-lentrepreneuriat-feminin", amount=80e6, period="2024"),
        P("nat-bpifrance-ae", "Bpifrance Assurance Export – export credit and investment insurance", NAT, "CI SN", "bpifrance-ae", "Export credit insurance, guarantees and foreign investment insurance for French companies on behalf of the French state; deals are not published individually.", "https://www.bpifrance.fr/nos-actualites/bpifrance-en-afrique-25-ans-dengagement-pour-des-partenariats-economiques-durables-et-une-co-industrialisation-ambitieuse", note="Countries shown are those Bpifrance names as its West African hubs; coverage extends further."),
        P("nat-bpifrance-acc", "Bpifrance Africa Accelerator", NAT, "SN CI", "bpifrance", "Support programme for French SMEs expanding in Africa, including business missions to Dakar.", "https://presse.bpifrance.fr/bpifrance-accompagne-la-deuxieme-promotion-de-laccelerateur-afrique-a-dakar-pour-prospecter-le-marche-senegalais/?lang=fra", note="Business support, not a financing commitment."),
    ]
    manual_prog = OUT / "programmes_manual.csv"
    if manual_prog.exists():  # extra programmes you add by hand: same columns, lists separated by spaces
        for r in csv.DictReader(open(manual_prog, encoding="utf-8")):
            if r.get("programme_id") and r.get("name"):
                PROGRAMMES.append(P(r["programme_id"], r["name"], r.get("kind") or NAT, r.get("countries", ""), r.get("participants", "EU"),
                                    r.get("description", ""), r.get("source_url", ""), float(r["amount_eur"]) if (r.get("amount_eur") or "").replace(".", "", 1).isdigit() else None,
                                    r.get("period", ""), r.get("note", "")))
    PROGRAMMES = [p for p in PROGRAMMES if any(c in COUNTRIES for c in p["countries"])]
    with open(OUT / "programmes.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(PROGRAMMES[0].keys()))
        w.writeheader()
        for p in PROGRAMMES:
            w.writerow({**p, "countries": " ".join(p["countries"]), "participants": " ".join(p["participants"])})

    # compact bundle for the website
    bundle = {"generated": TODAY, "programmes": PROGRAMMES,
              "places": {k: {"name": v[0], "lat": v[1], "lon": v[2]} for k, v in PARTICIPANT_PLACES.items()}, "countries": {k: {"name": v[1], "lat": v[2], "lon": v[3]} for k, v in COUNTRIES.items()},
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
<link href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
/* Dark by design: an operations-console look, identical in light and dark system settings */
:root{
  --bg:#040a0f; --bg2:#071219; --panel:rgba(7,18,26,.9); --panel-solid:#08151d;
  --ink:#d9f4ff; --muted:#8db1c0; --dim:#56798a; --line:#163746; --line-hi:#2a6a80;
  --accent:#40e8ff; --focus:#40e8ff; --chip:#0a1c26;
  --ocean:#03131b; --land:#1f4a5c; --land-eu:#2f6f86; --land-waemu:#e0a64a; --waemu-line:#ffbf5c;
  --t-dfi:#3aa6ff; --t-bdb:#ff8c42; --t-npb:#2dffc8; --t-eca:#ff3d8e; --t-eu:#ffd84a; --t-mdb:#b77dff;
  --k-tei:#4fa8ff; --k-gg:#ffb43f; --k-env:#c592ff; --k-part:#3dffaa; --k-nat:#ff5ba0;
  --mono:"IBM Plex Mono",ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace;
  --sans:"Chakra Petch","Segoe UI",system-ui,-apple-system,sans-serif;
  color-scheme:dark;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark}}
:root[data-theme="dark"]{color-scheme:dark}
:root{box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
html{scroll-padding-top:env(safe-area-inset-top,0px)}
*,*::before,*::after{box-sizing:inherit}
html,body{height:100%;margin:0}
body{background:radial-gradient(ellipse at 35% 45%,#0a2230 0%,var(--bg) 62%);background-color:var(--bg);color:var(--ink);font:400 15px/1.5 var(--sans)}
.app{display:grid;grid-template-columns:minmax(0,1fr) 410px;height:100%}
.stage{position:relative;min-height:0;overflow:hidden}
#globe{position:absolute;inset:0}
/* faint scanlines and vignette over the globe */
.stage::after{content:"";position:absolute;inset:0;pointer-events:none;
  background:repeating-linear-gradient(to bottom,rgba(64,232,255,.035) 0 1px,transparent 1px 3px),radial-gradient(ellipse at center,transparent 55%,rgba(0,0,0,.55) 100%)}
.hud{position:absolute;z-index:2;pointer-events:none}
.title{left:clamp(16px,3vw,36px);top:clamp(14px,3vh,28px);max-width:40ch}
.title .code{font:500 12px/1 var(--mono);color:var(--accent);letter-spacing:.14em;text-transform:uppercase;margin:0 0 10px}
.title h1{margin:0;font-weight:700;font-size:clamp(26px,3.2vw,44px);line-height:1.02;letter-spacing:.01em;text-transform:uppercase;text-shadow:0 0 18px rgba(64,232,255,.25)}
.title p{margin:.7em 0 0;color:var(--muted);font-size:14px;max-width:46ch}
.readout{right:clamp(12px,2vw,24px);top:clamp(14px,3vh,28px);font:400 12px/1.7 var(--mono);color:var(--muted);text-align:right;
  background:rgba(4,12,17,.6);border:1px solid var(--line);padding:8px 12px}
.readout b{color:var(--ink);font-weight:500}
.legend{left:clamp(16px,3vw,36px);bottom:clamp(14px,3vh,28px);display:flex;flex-direction:column;gap:6px;font-size:13px;
  background:rgba(4,12,17,.72);padding:10px 12px;border:1px solid var(--line)}
.legend span{display:flex;align-items:center;gap:9px}
.legend i{width:22px;height:0;border-top:2px dotted;display:inline-block;filter:drop-shadow(0 0 4px currentColor)}
.legend small{color:var(--dim);font-family:var(--mono);font-size:11px}
.bracket::before,.bracket::after{content:"";position:absolute;width:10px;height:10px;border:1px solid var(--accent);pointer-events:none}
.bracket::before{top:-1px;left:-1px;border-right:0;border-bottom:0}
.bracket::after{bottom:-1px;right:-1px;border-left:0;border-top:0}
/* glowing pins */
.pin{position:relative;width:0;height:0;pointer-events:auto;cursor:pointer}
.pin i{position:absolute;left:-4px;top:-4px;width:8px;height:8px;border-radius:50%;background:var(--c);
  box-shadow:0 0 6px 2px var(--c),0 0 18px 6px color-mix(in srgb,var(--c) 45%,transparent)}
.pin.dest i{left:-3px;top:-3px;width:6px;height:6px;box-shadow:0 0 6px 1px var(--c)}
.pin::after{content:"";position:absolute;left:-12px;top:-12px;width:24px;height:24px;border-radius:50%;border:1px solid var(--c);opacity:.0;animation:ping 2.4s ease-out infinite}
.pin.dest::after{animation-duration:3.6s}
.pin span{position:absolute;left:9px;top:-8px;font:500 11px/1 var(--mono);color:var(--ink);white-space:nowrap;text-shadow:0 0 6px #000,0 0 2px #000;opacity:.85}
@keyframes ping{0%{transform:scale(.3);opacity:.9}100%{transform:scale(1.6);opacity:0}}
aside{background:var(--panel);border-left:1px solid var(--line);display:flex;flex-direction:column;min-height:0;backdrop-filter:blur(6px)}
.filters{padding:16px 18px 12px;border-bottom:1px solid var(--line);display:grid;gap:12px}
.views{display:grid;grid-template-columns:1fr 1fr;border:1px solid var(--line-hi)}
.views button{appearance:none;border:0;background:transparent;color:var(--muted);font:600 14px/1 var(--sans);letter-spacing:.06em;text-transform:uppercase;padding:10px 6px;cursor:pointer}
.views button[aria-pressed="true"]{background:rgba(64,232,255,.12);color:var(--accent);box-shadow:inset 0 -2px 0 var(--accent)}
[hidden]{display:none!important}
.group h2{margin:0 0 6px;font:500 11px/1 var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--dim)}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{appearance:none;border:1px solid var(--line);background:var(--chip);color:var(--ink);padding:4px 9px 4px 7px;font:500 13px/1.3 var(--sans);cursor:pointer;display:inline-flex;align-items:center;gap:6px}
.chip[aria-pressed="false"]{opacity:.4}
.chip .sw,.sw{width:8px;height:8px;border-radius:50%;display:inline-block;box-shadow:0 0 6px currentColor}
select{font:500 14px var(--sans);color:var(--ink);background:var(--chip);border:1px solid var(--line);padding:6px 8px;width:100%}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
button:focus-visible,select:focus-visible,a:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
.summary{padding:14px 18px;border-bottom:1px solid var(--line)}
.summary .sel{display:flex;justify-content:space-between;gap:8px;align-items:baseline}
.summary strong{font:500 30px/1.1 var(--mono);color:var(--accent);text-shadow:0 0 14px rgba(64,232,255,.35)}
.summary p{margin:6px 0 0;color:var(--muted);font-size:13px}
.clear{appearance:none;background:none;border:0;color:var(--accent);font:500 13px var(--sans);cursor:pointer;padding:0;text-decoration:underline}
.list{overflow:auto;min-height:0;flex:1;padding:4px 0 16px;scrollbar-color:var(--line-hi) transparent}
.deal{padding:12px 18px;border-bottom:1px solid var(--line)}
.deal h3{margin:0;font-size:15px;font-weight:600;line-height:1.3}
.deal .meta{display:flex;flex-wrap:wrap;gap:4px 12px;margin-top:4px;font-size:13px;color:var(--muted)}
.deal .amt{font:500 13px var(--mono);color:var(--ink)}
.deal .who{display:flex;align-items:center;gap:6px}
.deal .note{font-size:12.5px;color:var(--muted);margin-top:4px}
.deal a{color:var(--accent);font-size:13px}
.kind{font:500 11px/1 var(--mono);letter-spacing:.1em;text-transform:uppercase;margin-bottom:5px}
.flag{font:500 11px var(--mono);border:1px dashed var(--line-hi);padding:0 5px;color:var(--muted)}
.more{display:block;margin:12px auto;appearance:none;border:1px solid var(--line-hi);background:transparent;color:var(--accent);font:500 14px var(--sans);padding:6px 14px;cursor:pointer}
.foot{padding:10px 18px;border-top:1px solid var(--line);font-size:12px;color:var(--muted)}
.foot summary{cursor:pointer;font-family:var(--mono);letter-spacing:.06em}
.tip{font:13px/1.4 var(--sans);background:var(--panel-solid);color:var(--ink);border:1px solid var(--line-hi);padding:8px 10px;max-width:260px;box-shadow:0 0 18px rgba(64,232,255,.15)}
.tip b{color:var(--accent)}
@media (prefers-reduced-motion:reduce){.pin::after{animation:none}}
@media (max-width:860px){
  .app{grid-template-columns:1fr;grid-template-rows:64vh auto;height:auto}
  .stage{height:64vh}
  aside{border-left:0;border-top:1px solid var(--line)}
  .list{overflow:visible}
  .readout,.legend{display:none}
  .title p{display:none}
  .legend{font-size:12px}
}
</style>
</head>
<body>
<div class="app">
  <section class="stage" aria-label="Interactive globe">
    <div id="globe"></div>
    <div class="hud title" style="position:absolute">
      <p class="code">EU public finance monitor / WAEMU</p>
      <h1>European public finance in the WAEMU</h1>
      <p>Where EU institutions and member states' development banks, DFIs, promotional banks and export credit agencies invest across the eight WAEMU countries, and the Team Europe programmes they run there. Click an arc, a country or a capital.</p>
    </div>
    <div class="hud readout bracket" aria-hidden="true">
      <div>Data sync <b id="r-sync"></b></div>
      <div>Records <b id="r-rec"></b></div>
      <div>Cursor <b id="r-cur">off globe</b></div>
    </div>
    <div class="hud legend bracket" id="legend" aria-label="Legend"></div>
  </section>
  <aside>
    <div class="filters">
      <div class="views" role="group" aria-label="What to show">
        <button type="button" data-view="inv" aria-pressed="true">Investments</button>
        <button type="button" data-view="prog" aria-pressed="false">Programmes</button>
      </div>
      <div id="inv-filters">
        <div class="group"><h2>Institution type</h2><div class="chips" id="f-type"></div></div>
        <div class="row2" style="margin-top:12px">
          <div class="group"><h2><label for="f-ms">Member state</label></h2><select id="f-ms"></select></div>
          <div class="group"><h2><label for="f-inst">Institution</label></h2><select id="f-inst"></select></div>
        </div>
      </div>
      <div id="prog-filters" hidden>
        <div class="group"><h2>Programme kind</h2><div class="chips" id="f-kind"></div></div>
        <div class="group" style="margin-top:12px"><h2><label for="f-part">Participant</label></h2><select id="f-part"></select></div>
      </div>
      <div class="group"><h2>Recipient country</h2><div class="chips" id="f-cc"></div></div>
      <div class="row2" id="inv-filters-2">
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
        <p>Data updated <span id="gen"></span>. Amounts are commitments in euros. Multi-country deals without published country shares are split equally and marked as estimates. Regional deals that only mention a WAEMU country are listed but not counted in totals. Arcs end at each country's capital.</p>
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
  ["EU institution","EU institution","--t-eu"], ["Multilateral","Multilateral (EBRD)","--t-mdb"]];
const KINDS = [["Team Europe Initiative","Team Europe Initiative","--k-tei"], ["Global Gateway flagship","Global Gateway flagship","--k-gg"],
  ["EU country envelope","EU country envelope","--k-env"], ["Energy transition partnership","Energy transition partnership","--k-part"],
  ["National programme","National programme","--k-nat"]];
const MS = {FR:"France",DE:"Germany",NL:"Netherlands",BE:"Belgium",FI:"Finland",DK:"Denmark",SE:"Sweden",
  AT:"Austria",ES:"Spain",IT:"Italy",PT:"Portugal",PL:"Poland",EU:"EU institution",INT:"International (EBRD)"};
const SHORT = {"eu-intpa":"European Commission",afd:"AFD",proparco:"Proparco","kfw-db":"KfW",deg:"DEG",fmo:"FMO","invest-intl":"Invest International",
  dggf:"DGGF",bio:"BIO",finnfund:"Finnfund",ifu:"IFU","atradius-dsb":"Atradius DSB",eib:"EIB",ebrd:"EBRD"};
// Official capitals: arcs end here
const CAPITALS = {BJ:["Porto-Novo",6.497,2.605],BF:["Ouagadougou",12.371,-1.520],CI:["Yamoussoukro",6.827,-5.289],GW:["Bissau",11.864,-15.598],
  ML:["Bamako",12.639,-8.003],NE:["Niamey",13.512,2.112],SN:["Dakar",14.716,-17.467],TG:["Lomé",6.131,1.222]};
const WAEMU_NUM = {"204":"BJ","854":"BF","384":"CI","624":"GW","466":"ML","562":"NE","686":"SN","768":"TG"};
const EU_NUM = new Set(["040","056","100","191","196","203","208","233","246","250","276","300","348","372","380","428","440","442","470","528","616","620","642","703","705","724","752"]);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const typeVar = Object.fromEntries(TYPES.map(t => [t[0], t[2]]));
const kindVar = Object.fromEntries(KINDS.map(k => [k[0], k[2]]));
const INST = Object.fromEntries(DATA.institutions.map(i => [i.institution_id, i]));
const INV = Object.fromEntries(DATA.investments.map(i => [i.investment_id, i]));
const PROG = DATA.programmes || [], PLACES = DATA.places || {};
const withData = new Set(DATA.investments.map(i => i.institution_id));
const fmt = v => v >= 1e9 ? "€" + (v/1e9).toFixed(1) + " bn" : v >= 1e6 ? "€" + (v/1e6).toFixed(v >= 1e8 ? 0 : 1) + " m" : v >= 1e3 ? "€" + Math.round(v/1e3) + " k" : "€" + Math.round(v);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const plain = s => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "");  // the globe's 3D font has no accents
const rgba = (hex, a) => { const h = hex.replace("#",""); const n = parseInt(h.length === 3 ? h.split("").map(x => x+x).join("") : h, 16);
  return `rgba(${n>>16&255},${n>>8&255},${n&255},${a})`; };
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const partName = p => (PLACES[p] && PLACES[p].name) || p;
const ccName = cc => DATA.countries[cc].name;

const state = {view:"inv", types:new Set(TYPES.map(t => t[0])), kinds:new Set(KINDS.map(k => k[0])), part:"", ms:"", inst:"",
  cc:new Set(Object.keys(DATA.countries)), ins:"", yr:"", focus:null, shown:40};

// ---------- controls
function chipGroup(el, list, set) {
  list.forEach(([k,label,v]) => {
    const b = document.createElement("button"); b.className = "chip"; b.type = "button"; b.setAttribute("aria-pressed","true");
    b.innerHTML = `<span class="sw" style="background:var(${v});color:var(${v})"></span>${label}`;
    b.onclick = () => { set.has(k) ? set.delete(k) : set.add(k); b.setAttribute("aria-pressed", set.has(k)); state.focus = null; update(); };
    el.append(b);
  });
}
chipGroup(document.getElementById("f-type"), TYPES, state.types);
chipGroup(document.getElementById("f-kind"), KINDS, state.kinds);
const fCC = document.getElementById("f-cc");
Object.entries(DATA.countries).forEach(([cc,c]) => {
  const b = document.createElement("button"); b.className = "chip"; b.type = "button"; b.setAttribute("aria-pressed","true"); b.textContent = c.name;
  b.onclick = () => { state.cc.has(cc) ? state.cc.delete(cc) : state.cc.add(cc); b.setAttribute("aria-pressed", state.cc.has(cc)); state.focus = null; update(); };
  fCC.append(b);
});
function opts(el, list, all) { el.innerHTML = `<option value="">${all}</option>` + list.map(([v,l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join(""); }
const covered = DATA.institutions.filter(i => withData.has(i.institution_id));
opts(document.getElementById("f-ms"), [...new Set(covered.map(i => i.member_state))].map(m => [m, MS[m] || m]), "All");
opts(document.getElementById("f-inst"), covered.map(i => [i.institution_id, SHORT[i.institution_id] || i.name]), "All");
opts(document.getElementById("f-ins"), [...new Set(DATA.investments.map(i => i.instrument))].sort().map(x => [x,x]), "All");
const years = [...new Set(DATA.investments.map(i => i.year).filter(Boolean))].sort();
opts(document.getElementById("f-yr"), [2000,2010,2015,2020,2023,2025].filter(y => y >= +years[0]).map(y => [y, String(y)]), "Any year");
const parts = [...new Set(PROG.flatMap(p => p.participants))].filter(p => PLACES[p]).sort((a,b) => partName(a).localeCompare(partName(b)));
opts(document.getElementById("f-part"), parts.map(p => [p, partName(p)]), "All");
for (const [id,key] of [["f-ms","ms"],["f-inst","inst"],["f-ins","ins"],["f-yr","yr"],["f-part","part"]])
  document.getElementById(id).onchange = e => { state[key] = e.target.value; state.focus = null; update(); };
document.querySelectorAll(".views button").forEach(b => b.onclick = () => {
  state.view = b.dataset.view; state.focus = null;
  document.querySelectorAll(".views button").forEach(x => x.setAttribute("aria-pressed", x === b));
  document.getElementById("inv-filters").hidden = state.view !== "inv";
  document.getElementById("inv-filters-2").hidden = state.view !== "inv";
  document.getElementById("prog-filters").hidden = state.view !== "prog";
  drawLegend(); update();
});
document.getElementById("reset").onclick = () => {
  Object.assign(state, {types:new Set(TYPES.map(t => t[0])), kinds:new Set(KINDS.map(k => k[0])), part:"", ms:"", inst:"",
    cc:new Set(Object.keys(DATA.countries)), ins:"", yr:"", focus:null});
  document.querySelectorAll(".chip").forEach(c => c.setAttribute("aria-pressed","true"));
  ["f-ms","f-inst","f-ins","f-yr","f-part"].forEach(id => document.getElementById(id).value = "");
  // chip groups hold their own Set references, so rebuild them
  ["f-type","f-kind"].forEach(id => document.getElementById(id).innerHTML = "");
  chipGroup(document.getElementById("f-type"), TYPES, state.types);
  chipGroup(document.getElementById("f-kind"), KINDS, state.kinds);
  update();
};
document.getElementById("gen").textContent = DATA.generated;
document.getElementById("r-sync").textContent = DATA.generated;
document.getElementById("r-rec").textContent = DATA.investments.length.toLocaleString("en") + " deals, " + PROG.length + " programmes";
document.getElementById("gaps").textContent = "Not yet covered (no machine-readable disclosure found): " +
  DATA.institutions.filter(i => !withData.has(i.institution_id)).map(i => i.name).join(", ") + ".";
function drawLegend() {
  const list = state.view === "inv" ? TYPES : KINDS;
  document.getElementById("legend").innerHTML = list.map(([,l,v]) => `<span><i style="color:var(${v})"></i>${l}</span>`).join("") +
    `<small>${state.view === "inv" ? "Line weight grows with the amount invested" : "Lines link participants to the countries a programme covers"}</small>`;
}
drawLegend();

// ---------- globe
const el = document.getElementById("globe");
const features = topojson.feature(WORLD, WORLD.objects.countries).features;
const globe = Globe()(el)
  .backgroundColor("rgba(0,0,0,0)")
  .showGraticules(true)
  .showAtmosphere(true).atmosphereAltitude(0.17)
  .hexPolygonsData(features).hexPolygonResolution(3).hexPolygonMargin(0.55).hexPolygonUseDots(true).hexPolygonAltitude(0.003)
  .polygonsData(features.filter(f => WAEMU_NUM[f.id]))
  .polygonAltitude(0.006).polygonSideColor(() => "rgba(0,0,0,0)")
  .polygonLabel(f => `<div class="tip"><b>${esc(ccName(WAEMU_NUM[f.id]))}</b><br>Click to see what reaches this country</div>`)
  .onPolygonClick(f => { state.focus = {cc: WAEMU_NUM[f.id]}; update(); })
  .arcStartLat(d => d.sLat).arcStartLng(d => d.sLng).arcEndLat(d => d.eLat).arcEndLng(d => d.eLng)
  .arcAltitudeAutoScale(0.38)
  .arcLabel(d => d.part
    ? `<div class="tip"><b>${esc(d.label)}</b> in ${esc(ccName(d.cc))}<br>${d.n} programme${d.n>1?"s":""}</div>`
    : `<div class="tip"><b>${esc(d.label)}</b> to ${esc(ccName(d.cc))}<br>${d.n} deal${d.n>1?"s":""}${d.sum ? ", " + fmt(d.sum) : ""}</div>`)
  .onArcClick(d => { state.focus = d.part ? {part:d.part, cc:d.cc} : {inst:d.inst, cc:d.cc}; update(); })
  .ringLat("lat").ringLng("lng").ringMaxRadius(d => d.r).ringPropagationSpeed(reduceMotion ? 0 : 1.6).ringRepeatPeriod(d => d.period)
  .ringColor(d => t => rgba(d.color, Math.max(0, 0.75 * (1 - t))))
  .htmlLat("lat").htmlLng("lng").htmlAltitude(0.012)
  .htmlElement(d => {
    const p = document.createElement("div");
    p.className = "pin" + (d.dest ? " dest" : ""); p.style.setProperty("--c", d.color);
    p.innerHTML = `<i></i>${d.text ? `<span>${esc(d.text)}</span>` : ""}`;
    p.title = d.title; p.onclick = d.onclick;
    return p;
  })
  .htmlElementVisibilityModifier((elm, visible) => { elm.style.opacity = visible ? 1 : 0; elm.style.pointerEvents = visible ? "auto" : "none"; })
  .labelLat("lat").labelLng("lng").labelText("name").labelSize(1.15).labelDotRadius(0).labelAltitude(0.014).labelResolution(2);
function paint() {
  const mat = globe.globeMaterial(); mat.color.set(css("--ocean"));
  if (mat.emissive) { mat.emissive.set("#04202b"); mat.emissiveIntensity = 0.35; }
  globe.atmosphereColor(css("--accent"));
  globe.hexPolygonColor(f => WAEMU_NUM[f.id] ? css("--land-waemu") : EU_NUM.has(f.id) ? css("--land-eu") : css("--land"));
  globe.polygonCapColor(() => rgba(css("--waemu-line"), 0.06)).polygonStrokeColor(() => rgba(css("--waemu-line"), 0.85));
  globe.labelColor(() => rgba(css("--waemu-line"), 0.9));
  update(false);
}
globe.pointOfView(el.clientWidth < 600 ? {lat: 26, lng: -3, altitude: 2.5} : {lat: 28, lng: -2, altitude: 1.75}, 0);
const ctl = globe.controls(); ctl.autoRotate = false; ctl.enableDamping = true;
new ResizeObserver(() => globe.width(el.clientWidth).height(el.clientHeight)).observe(el);
const cur = document.getElementById("r-cur");
el.addEventListener("pointermove", e => {
  const r = el.getBoundingClientRect(); const c = globe.toGlobeCoords(e.clientX - r.left, e.clientY - r.top);
  cur.textContent = c ? `${Math.abs(c.lat).toFixed(2)}°${c.lat >= 0 ? "N" : "S"} ${Math.abs(c.lng).toFixed(2)}°${c.lng >= 0 ? "E" : "W"}` : "off globe";
});

// arcs drawn as streams of separated dots, colour fading in from the origin
function styleArcs(arcs, sparse) {
  globe.arcsData(arcs)
    .arcColor(d => [rgba(d.color, 0.18), rgba(d.color, 0.95)])
    .arcStroke("stroke")
    .arcDashLength(sparse ? 0.006 : 0.012).arcDashGap(sparse ? 0.03 : 0.016)
    .arcDashInitialGap(d => d.seed)
    .arcDashAnimateTime(reduceMotion ? 0 : (sparse ? 9000 : 4200));
}
function setPins(origins) {
  const dests = Object.entries(CAPITALS).filter(([cc]) => state.cc.has(cc)).map(([cc,[city,lat,lng]]) => ({
    lat, lng, dest:true, color: css("--waemu-line"), text: "", title: `${city}, ${ccName(cc)}`,
    onclick: () => { state.focus = {cc}; update(); }}));
  globe.htmlElementsData(origins.concat(dests));
  globe.ringsData(origins.map(o => ({lat:o.lat, lng:o.lng, color:o.color, r:2.6, period:1800 + (o.seed || 0) * 900}))
    .concat(dests.map(d => ({lat:d.lat, lng:d.lng, color:d.color, r:1.4, period:3200}))));
  globe.labelsData(Object.entries(DATA.countries).filter(([cc]) => state.cc.has(cc))
    .map(([cc,c]) => ({name: plain(c.name), lat: c.lat + 1.6, lng: c.lon})));
}
const seedOf = s => { let h = 0; for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) % 997; return h / 997; };

// ---------- investments view
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
    if (state.focus && ((state.focus.inst && inv.institution_id !== state.focus.inst) || (state.focus.cc && a.country !== state.focus.cc))) continue;
    rows.push([a, inv]);
  }
  return rows;
}
function update(resetList = true) {
  if (resetList) state.shown = 40;
  if (state.view === "prog") return updateProgrammes();
  const rows = filtered();
  const agg = new Map();
  for (const [a, inv] of rows) {
    const k = inv.institution_id + "|" + a.country;
    const g = agg.get(k) || {inst:inv.institution_id, cc:a.country, n:0, sum:0};
    g.n++; g.sum += a.amount_attributed_eur || 0; agg.set(k, g);
  }
  const arcs = [...agg.values()].map(g => {
    const ins = INST[g.inst], [, lat, lng] = CAPITALS[g.cc];
    return {...g, label: SHORT[g.inst] || ins.name, sLat:+ins.hq_lat, sLng:+ins.hq_lon, eLat:lat, eLng:lng, seed: seedOf(g.inst + g.cc),
      color: css(typeVar[ins.type]), stroke: Math.min(0.55, Math.max(0.14, (Math.log10(Math.max(g.sum, 1e5)) - 5) * 0.12))};
  });
  styleArcs(arcs, false);
  const ids = [...new Set(arcs.map(a => a.inst))];
  setPins(ids.map(id => { const i = INST[id]; return {lat:+i.hq_lat, lng:+i.hq_lon, color: css(typeVar[i.type]), seed: seedOf(id),
    text: "", title: `${i.name}, ${i.hq_city}`, onclick: () => { state.focus = {inst:id}; update(); }}; }));
  renderDeals(rows);
}
function renderDeals(rows) {
  const total = rows.reduce((s,[a]) => s + (a.amount_attributed_eur || 0), 0);
  const deals = new Set(rows.map(([,inv]) => inv.investment_id));
  const instN = new Set(rows.map(([,inv]) => inv.institution_id));
  document.getElementById("s-total").textContent = fmt(total);
  let scope = "";
  if (state.focus) scope = " Showing " + [state.focus.inst ? (SHORT[state.focus.inst] || INST[state.focus.inst].name) : "", state.focus.cc ? "in " + ccName(state.focus.cc) : ""].filter(Boolean).join(" ") + ".";
  const unk = rows.filter(([a]) => a.amount_attributed_eur == null).length;
  document.getElementById("s-text").textContent = `${deals.size.toLocaleString("en")} deals from ${instN.size} institution${instN.size === 1 ? "" : "s"}.` + scope +
    (unk ? ` ${unk.toLocaleString("en")} allocations have no disclosed or attributable amount.` : "");
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
        <span class="who"><span class="sw" style="background:var(${typeVar[ins.type]});color:var(${typeVar[ins.type]})"></span>${esc(SHORT[ins.institution_id] || ins.name)}</span>
        <span>${ccs.map(c => esc(ccName(c))).join(", ")}</span>
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
  if (m) m.onclick = () => { state.shown += 40; renderDeals(filtered()); };
}

// ---------- programmes view
function progFiltered() {
  return PROG.filter(p => state.kinds.has(p.kind)
    && p.countries.some(c => state.cc.has(c) && (!state.focus || !state.focus.cc || c === state.focus.cc))
    && (!state.part || p.participants.includes(state.part))
    && (!state.focus || !state.focus.part || p.participants.includes(state.focus.part)));
}
function updateProgrammes() {
  const progs = progFiltered();
  const agg = new Map();
  for (const p of progs) for (const part of p.participants) {
    if (!PLACES[part] || (state.part && part !== state.part)) continue;
    for (const cc of p.countries) {
      if (!state.cc.has(cc) || !CAPITALS[cc]) continue;
      const k = part + "|" + cc + "|" + p.kind;
      const g = agg.get(k) || {part, cc, kind:p.kind, n:0}; g.n++; agg.set(k, g);
    }
  }
  const arcs = [...agg.values()].map(g => ({...g, label: partName(g.part), sLat:PLACES[g.part].lat, sLng:PLACES[g.part].lon,
    eLat:CAPITALS[g.cc][1], eLng:CAPITALS[g.cc][2], seed: seedOf(g.part + g.cc + g.kind), color: css(kindVar[g.kind]), stroke: 0.1 + 0.05 * Math.min(g.n, 6)}));
  styleArcs(arcs, true);
  const used = [...new Set(arcs.map(a => a.part))];
  setPins(used.map(p => ({lat:PLACES[p].lat, lng:PLACES[p].lon, color: css("--accent"), seed: seedOf(p), text: "",
    title: partName(p), onclick: () => { state.focus = {part:p}; update(); }})));
  const withAmt = progs.filter(p => p.amount_eur);
  document.getElementById("s-total").textContent = progs.length + " programme" + (progs.length === 1 ? "" : "s");
  let scope = "";
  if (state.focus) scope = " Showing " + [state.focus.part ? partName(state.focus.part) : "", state.focus.cc ? "in " + ccName(state.focus.cc) : ""].filter(Boolean).join(" ") + ".";
  document.getElementById("s-text").textContent = `${withAmt.length} publish an amount. Programme amounts overlap with the investments view and with each other, so they are not added up.` + scope;
  const box = document.getElementById("list");
  if (!progs.length) { box.innerHTML = `<p class="deal">No programmes match these filters. Turn a programme kind back on or select more countries.</p>`; return; }
  const order = Object.fromEntries(KINDS.map((k,i) => [k[0], i]));
  const list = progs.slice().sort((a,b) => order[a.kind] - order[b.kind] || (b.amount_eur || 0) - (a.amount_eur || 0));
  box.innerHTML = list.slice(0, state.shown).map(p => `<article class="deal">
      <div class="kind" style="color:var(${kindVar[p.kind]})">${esc(p.kind)}</div>
      <h3>${esc(p.name)}</h3>
      <div class="meta">
        <span>${p.countries.filter(c => DATA.countries[c]).map(c => esc(ccName(c))).join(", ")}</span>
        ${p.period ? `<span>${esc(p.period)}</span>` : ""}
        ${p.amount_eur ? `<span class="amt">${fmt(p.amount_eur)}</span>` : ""}
      </div>
      <div class="note">${esc(p.description)}</div>
      <div class="note">Participants: ${p.participants.map(x => esc(partName(x))).join(", ")}</div>
      ${p.note ? `<div class="note"><span class="flag">note</span> ${esc(p.note)}</div>` : ""}
      ${p.source_url ? `<a href="${esc(p.source_url)}" target="_blank" rel="noopener">View source</a>` : ""}
    </article>`).join("") + (list.length > state.shown ? `<button class="more" id="more">Show ${Math.min(40, list.length - state.shown)} more of ${list.length - state.shown}</button>` : "");
  const m = document.getElementById("more");
  if (m) m.onclick = () => { state.shown += 40; updateProgrammes(); };
}

paint();
})();
</script>
</body>
</html>
'''

if __name__ == "__main__":
    main(sys.argv[1:] or FETCH_STEPS + ["normalize", "build"])
