"""EU public financial institutions in the WAEMU - complete tracker in one file.

Run everything:      python tracker.py
Run some steps only: python tracker.py eib normalize build
Steps: reference iati proparco bio wp eib cofides noneu normalize build
"""
import os, sys, csv, json, pathlib, datetime
ROOT = pathlib.Path(__file__).resolve().parent
os.chdir(ROOT)
for _d in ["raw/iati", "raw/proparco", "raw/bio", "raw/deg", "raw/finnfund", "raw/ifu", "raw/eib", "raw/cofides", "raw/nonEU", "ref", "data", "site"]:
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
    # Map libraries, embedded into the page at build time so visitors never need to reach an outside server
    for name, url in [("topojson-client.min.js", "https://cdn.jsdelivr.net/npm/topojson-client@3.1.0/dist/topojson-client.min.js"),
                      ("globe.gl.min.js", "https://cdn.jsdelivr.net/npm/globe.gl@2.46.2/dist/globe.gl.min.js")]:
        if not (ROOT / "ref" / name).exists():
            dl(url, f"ref/{name}")

def step_iati():
    """Fetch full IATI XML (via d-portal, no API key) for target publishers x WAEMU countries."""
    import urllib.request, urllib.parse, pathlib, time
    WAEMU = ["BJ","BF","CI","GW","ML","NE","SN","TG","CM","CF","TD","CG","GQ","GA"]  # WAEMU + CEMAC (Franc Zone, without the Comoros)
    PUBLISHERS = {
     "FR-3":"AFD group", "NL-KVK-27078545":"FMO", "XM-DAC-918-3":"EIB",
     "XI-IATI-EBRD":"EBRD", "NL-KVK-33226495":"Atradius DSB",
     "NL-KVK-83517626":"Invest International", "NL-KVK-61172863":"DGGF Lokaal MKB",
     "DE-1":"BMZ (filtered to KfW later)",
     "XI-IATI-EC_INTPA":"European Commission DG INTPA",
     "XM-DAC-46002":"African Development Bank Group (non-EU comparison)", "XM-DAC-903":"IFC (non-EU comparison)",
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
    W=["Benin","Burkina Faso","Côte d'Ivoire","Guinea-Bissau","Mali","Niger","Senegal","Togo","Cameroon","Central African Republic","Chad","Congo","Equatorial Guinea","Gabon"]
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
    C={"BJ":359,"BF":371,"CI":390,"GW":259517,"ML":473,"NE":497,"SN":530,"TG":558,
       "CM":374,"CF":259502,"TD":259511,"CG":259513}  # BIO has no filter for Equatorial Guinea or Gabon
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
           "ML":["mali"],"NE":["niger"],"SN":["senegal","sénégal"],"TG":["togo"],
           "CM":["cameroon","cameroun","kamerun"],"CF":["central african"],"TD":["chad","tchad"],"GQ":["equatorial guinea"],"GA":["gabon"],
           "CG":["republic of congo","congo-brazzaville","congo brazzaville"]}
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
        if "democratic" in n or "demokratiske" in n:
            return []  # never the DR Congo
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
    for cc in ["BJ", "BF", "CI", "GW", "ML", "NE", "SN", "TG", "CM", "CF", "TD", "CG", "GQ", "GA"]:
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

def step_cofides():
    """COFIDES (Spain): project list filtered by WAEMU country (plain HTML, no JavaScript needed)."""
    import re, json, html as H, urllib.request, pathlib, time
    UA = {"User-Agent": "Mozilla/5.0 (EU-PFI-WAEMU tracker; research)"}
    pathlib.Path("raw/cofides").mkdir(parents=True, exist_ok=True)
    out = []
    for cc in ["BJ", "BF", "CI", "GW", "ML", "NE", "SN", "TG", "CM", "CF", "TD", "CG", "GQ", "GA"]:
        url = f"https://www.cofides.es/en/projects?field_direccion_country_code={cc}&field_sector_target_id=All"
        s = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read().decode("utf-8", "replace")
        t = H.unescape(re.sub(r"\s+", " ", re.sub("<[^>]+>", "\n", re.sub(r"<script.*?</script>|<style.*?</style>", "", s, flags=re.S))))
        i, j = t.find("Textile - Footwear Transport"), t.find("Paseo de la Castellana")
        block = t[i + 28:j] if i > 0 and j > i else ""
        for m in re.finditer(r"(.+?) Activity: (.+?) Sector: (.+?) Instrument: (.+?) Country: (.+?)(?= [A-Z0-9][^:]{2,80} Activity:|$)", block.strip()):
            out.append({"cc": cc, "name": m.group(1).strip(), "activity": m.group(2).strip(), "sector": m.group(3).strip(),
                        "instrument": m.group(4).strip(), "country": m.group(5).strip(), "url": url})
        time.sleep(0.5)
    json.dump(out, open("raw/cofides/projects.json", "w"), ensure_ascii=False, indent=0)
    print(len(out), "COFIDES projects in WAEMU")

def step_noneu():
    """Non-EU comparison layer: World Bank (IBRD/IDA) projects API and AIIB project list.
    AfDB (incl. African Development Fund) and IFC come through the IATI step."""
    import json, re, time, urllib.request, pathlib
    UA = {"User-Agent": "Mozilla/5.0 (EU-PFI-WAEMU tracker; research)"}
    pathlib.Path("raw/nonEU").mkdir(parents=True, exist_ok=True)
    def get(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=120).read()
    wb = []
    for cc in ["BJ", "BF", "CI", "GW", "ML", "NE", "SN", "TG", "CM", "CF", "TD", "CG", "GQ", "GA"]:
        start = 0
        while True:
            d = json.loads(get("https://search.worldbank.org/api/v2/projects?format=json&countrycode_exact=" + cc +
                               f"&rows=200&os={start}&fl=id,project_name,totalamt,boardapprovaldate,sector1,mjsector1Name,status,url,lendinginstr"))
            rows = list((d.get("projects") or {}).values())
            for r in rows:
                r["cc"] = cc
            wb += rows
            start += 200
            if start >= int(d.get("total", 0)) or not rows:
                break
            time.sleep(0.3)
    json.dump(wb, open("raw/nonEU/worldbank.json", "w"), ensure_ascii=False)
    js = get("https://www.aiib.org/en/projects/list/.content/all-projects-data.js").decode("utf-8", "replace")
    aiib = []
    for m in re.finditer(r"\{[^{}]*\"economy\"[^{}]*\}", js):
        try:
            aiib.append(json.loads(m.group(0)))
        except ValueError:
            pass
    json.dump(aiib, open("raw/nonEU/aiib.json", "w"), ensure_ascii=False)
    print(len(wb), "World Bank projects;", len(aiib), "AIIB projects (all countries)")

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
    COUNTRIES = {  # Franc Zone countries covered: WAEMU (West) and CEMAC (Central); approximate geographic centroids
        "BJ": ("BEN", "Benin", 9.31, 2.32), "BF": ("BFA", "Burkina Faso", 12.24, -1.56),
        "CI": ("CIV", "Côte d'Ivoire", 7.54, -5.55), "GW": ("GNB", "Guinea-Bissau", 11.80, -15.18),
        "ML": ("MLI", "Mali", 17.57, -4.00), "NE": ("NER", "Niger", 17.61, 8.08),
        "SN": ("SEN", "Senegal", 14.50, -14.45), "TG": ("TGO", "Togo", 8.62, 0.82),
        "CM": ("CMR", "Cameroon", 6.00, 12.35), "CF": ("CAF", "Central African Republic", 6.61, 20.94),
        "TD": ("TCD", "Chad", 15.45, 18.73), "CG": ("COG", "Republic of the Congo", -0.66, 15.20),
        "GQ": ("GNQ", "Equatorial Guinea", 1.60, 10.40), "GA": ("GAB", "Gabon", -0.80, 11.61),
    }
    UNION = {cc: ("WAEMU" if cc in ("BJ", "BF", "CI", "GW", "ML", "NE", "SN", "TG") else "CEMAC") for cc in COUNTRIES}
    _NAMES = [
        ("BJ", r"b[eé]nin"), ("BF", r"burkina(?: faso)?"),
        ("CI", r"c[oô]te d[’'`]?\s?ivoire|ivory coast|costa de marfil|costa d.avorio|elfenbenskysten"),
        ("GW", r"guin(?:ea|[eé]e?)[- ]bissau"), ("ML", r"mali"), ("NE", r"niger"), ("SN", r"s[eé]n[eé]gal"), ("TG", r"togo"),
        ("CM", r"cameroon|cameroun|camer[uú]n|kamerun"),
        ("CF", r"central african rep(?:ublic|\.)?|centrafri(?:que|caine)|rep[uú]blica centroafricana"),
        ("TD", r"chad|tchad|ciad"),
        ("GQ", r"equatorial guinea|guin[eé]e [eé]quatoriale|guinea ecuatorial|guinea equatoriale"),
        ("GA", r"gab[oó]n"),
        ("CG", r"congo"),
    ]
    CC_PATTERN = re.compile(r"\b(" + "|".join(f"(?P<{cc}>{rx})" for cc, rx in _NAMES) + r")\b", re.I)
    _NOT_ROC_BEFORE = re.compile(r"(democratic|dem\.|d\.r\.|\bdr\b|\brd\b|\brdc\b|d[eé]mocratique|bassin du|basin|river|fleuve)"
                                 r"[\s,]*(republic|rep\.?)?[\s,]*(of)?[\s,]*(the)?[\s,]*(du)?[\s,]*$", re.I)
    _NOT_ROC_AFTER = re.compile(r"^[\s,(-]*(kinshasa|dem\b|dem\.|democratic|basin|river|drc)", re.I)

    def countries_in(text):
        """Return Franc Zone ISO2 codes mentioned in free text.
        Ignores Nigeria, Somalia, Guinea (Conakry); 'Congo' counts only for the Republic of the Congo (never the DRC,
        the Congo Basin or the Congo River); 'Chad' is not counted when it means Lake Chad."""
        text = text or ""
        found = []
        for m in CC_PATTERN.finditer(text):
            cc = next(k for k, v in m.groupdict().items() if v)
            before = text[max(0, m.start() - 45):m.start()]
            after = text[m.end():m.end() + 25]
            if cc == "CG" and (_NOT_ROC_BEFORE.search(before) or _NOT_ROC_AFTER.search(after)):
                continue
            if cc == "TD" and re.search(r"(lake|lac)\s*$", before, re.I):
                continue
            if cc not in found:
                found.append(cc)
        return found

    # ECB monthly reference rates: units of currency per 1 EUR
    FX = {}
    for f in REF.glob("ecb_*.csv"):
        cur = f.stem.split("_")[1]
        for r in csv.DictReader(open(f)):
            FX[(cur, r["TIME_PERIOD"])] = float(r["OBS_VALUE"])
    FX_FIXED = {"EUR": 1.0, "XOF": 655.957, "XAF": 655.957}  # both CFA francs are pegged to the euro at the same rate

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
    SECTOR_LIST = ["Energy and climate", "Transport and corridors", "Digital and telecoms", "Health", "Education and skills",
                   "Agriculture and food systems", "Water and sanitation", "Financial sector and SMEs", "Industry and trade",
                   "Governance and budget support", "Other (social, humanitarian, multi-sector)"]
    OTHER_SECTOR = SECTOR_LIST[-1]
    def broad_sector(text="", dac=None):
        """Map a DAC code or free-text label to one of 10 sectors aligned with the EU's Global Gateway priorities."""
        if dac:
            c = str(dac)
            table = {"23": "Energy and climate", "41": "Energy and climate", "21": "Transport and corridors", "22": "Digital and telecoms",
                     "12": "Health", "13": "Health", "11": "Education and skills", "31": "Agriculture and food systems",
                     "52": "Agriculture and food systems", "14": "Water and sanitation", "24": "Financial sector and SMEs",
                     "25": "Financial sector and SMEs", "32": "Industry and trade", "33": "Industry and trade",
                     "15": "Governance and budget support", "51": "Governance and budget support", "60": "Governance and budget support"}
            if c[:2] in table:
                return table[c[:2]]
            if len(c) >= 3 and c[:1].isdigit():
                return OTHER_SECTOR
        t = (text or "").lower()
        rules = [("Energy and climate", r"energ|solar|power|climate|hydro|electric|renewable|forest|environment"),
                 ("Water and sanitation", r"water|sanitation|sewer|wastewater"),
                 ("Transport and corridors", r"transport|road|rail|port\b|corridor|logist|airport|mobility|brt|\bbus"),
                 ("Digital and telecoms", r"telecom|digital|\bict\b|internet|cable|tech|start-up|startup"),
                 ("Health", r"health|hospital|pharma|medic|vaccine"),
                 ("Education and skills", r"educat|school|training|vocational|skills|universit"),
                 ("Agriculture and food systems", r"agri|food|farm|cocoa|cacao|cashew|fish|livestock|dairy|agro"),
                 ("Financial sector and SMEs", r"financ|bank|microfin|fund|insur|leasing|payment|credit line|\bsme|\bpme|entrepreneur"),
                 ("Industry and trade", r"industr|manufact|cement|trade|tourism|real estate|mining|construction|services|export|equipment"),
                 ("Governance and budget support", r"governance|budget|public finance|decentrali|justice|security|stability|rights|migration")]
        for name, rx in rules:
            if re.search(rx, t):
                return name
        return OTHER_SECTOR

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
        ("bgk", "Bank Gospodarstwa Krajowego (BGK)", "PL", "NPB", "", "Warsaw", 52.230, 21.012, "https://www.bgk.pl", "curated"),
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
        ("kuke", "KUKE – Export Credit Insurance Corporation", "PL", "ECA", "", "Warsaw", 52.240, 21.000, "https://www.kuke.com.pl", "curated"),
        ("eu-intpa", "European Commission – DG International Partnerships (NDICI-Global Europe, EDF)", "EU", "EU institution", "European Union", "Brussels", 50.843, 4.382, "https://international-partnerships.ec.europa.eu", "automated"),
        ("eib", "European Investment Bank (EIB)", "EU", "EU institution", "EIB Group", "Luxembourg", 49.627, 6.155, "https://www.eib.org", "automated"),
        ("ebrd", "European Bank for Reconstruction and Development (EBRD)", "INT", "Multilateral", "", "London", 51.507, -0.128, "https://www.ebrd.com", "automated"),
    ]
    # Coverage status after the round-2 research (automated feed, curated from public sources, programme level only, or checked with nothing found)
    COVERAGE = {"swedfund": "curated", "cofides": "automated", "oeeb": "checked: no Franc Zone deals found", "sace": "curated", "credendo": "curated",
                "eifo": "curated", "bpifrance-ae": "curated", "cdp": "curated", "cesce": "programme level", "sofid": "programme level",
                "simest": "programme level", "bpifrance": "programme level"}
    INST = [i[:9] + (COVERAGE.get(i[0], i[9]),) for i in INST]
    CHECKED = "checked: no Franc Zone deals found"
    INST += [  # member states added in round 4: institutions researched, no published Franc Zone deals found so far
        ("bpf", "Banco Português de Fomento (BPF)", "PT", "NPB", "", "Lisbon", 38.725, -9.150, "https://www.bpfomento.pt", CHECKED),
        ("egap", "EGAP – Export Guarantee and Insurance Corporation", "CZ", "ECA", "", "Prague", 50.083, 14.420, "https://www.egap.cz", CHECKED),
        ("ceb", "Czech Export Bank (ČEB)", "CZ", "ECA", "", "Prague", 50.075, 14.440, "https://www.ceb.cz", CHECKED),
        ("eximbanka-sr", "Eximbanka SR – Export-Import Bank of the Slovak Republic", "SK", "ECA", "", "Bratislava", 48.148, 17.107, "https://www.eximbanka.sk", CHECKED),
        ("hbor", "HBOR – Croatian Bank for Reconstruction and Development", "HR", "NPB", "", "Zagreb", 45.815, 15.982, "https://www.hbor.hr", CHECKED),
        ("ecg", "Export Credit Greece (ECG)", "GR", "ECA", "", "Athens", 37.984, 23.728, "https://www.ecg.gr", CHECKED),
        ("sid", "SID Banka – Slovenian Export and Development Bank", "SI", "NPB", "", "Ljubljana", 46.056, 14.506, "https://www.sid.si", CHECKED),
        ("exim-hu", "EXIM Hungary (Eximbank and MEHIB)", "HU", "ECA", "", "Budapest", 47.498, 19.040, "https://exim.hu", CHECKED),
        ("exim-ro", "Exim Banca Românească (state export credit agent)", "RO", "ECA", "", "Bucharest", 44.427, 26.103, "https://www.eximbank.ro", CHECKED),
        ("baez", "BAEZ – Bulgarian Export Insurance Agency", "BG", "ECA", "", "Sofia", 42.698, 23.322, "https://www.baez.bg", CHECKED),
        ("bdb", "Bulgarian Development Bank (BDB)", "BG", "NPB", "", "Sofia", 42.690, 23.330, "https://www.bbr.bg", CHECKED),
        ("eis-ee", "EIS – Enterprise Estonia and KredEx (state export guarantees)", "EE", "ECA", "", "Tallinn", 59.437, 24.754, "https://eis.ee", CHECKED),
        ("altum", "ALTUM – Development Finance Institution of Latvia", "LV", "NPB", "", "Riga", 56.949, 24.105, "https://www.altum.lv", CHECKED),
        ("invega", "INVEGA – Lithuanian Development Promotion Agency", "LT", "NPB", "", "Vilnius", 54.687, 25.279, "https://invega.lt", CHECKED),
    ]
    INST += [  # non-EU comparison layer: shown only in the overlap analysis, never added to European totals
        ("worldbank", "World Bank (IBRD/IDA)", "NONEU", "Non-EU", "World Bank Group", "Washington", 38.899, -77.042, "https://projects.worldbank.org", "automated"),
        ("ifc", "International Finance Corporation (IFC)", "NONEU", "Non-EU", "World Bank Group", "Washington", 38.902, -77.044, "https://disclosures.ifc.org", "automated"),
        ("afdb", "African Development Bank Group (incl. African Development Fund)", "NONEU", "Non-EU", "AfDB Group", "Abidjan", 5.320, -4.020, "https://www.afdb.org", "automated"),
        ("aiib", "Asian Infrastructure Investment Bank (AIIB)", "NONEU", "Non-EU", "", "Beijing", 39.990, 116.390, "https://www.aiib.org", "automated"),
    ]
    INST_FIELDS = ["institution_id", "name", "member_state", "type", "parent_group", "hq_city", "hq_lat", "hq_lon", "website", "coverage"]

    # ---------------------------------------------------------------- collectors
    investments, allocations = [], []

    def add(inst, src, rec_id, url, title, *, desc="", client="", client_domicile="", instrument="Unknown",
            sector_broad="Other", sector_detail="", status="", date="", amount=None, currency="EUR",
            amount_eur=None, es="", shares=None, method="", note="", points=None, basis=None):
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
            "amount_basis": basis or ("commitment" if amount_eur is not None else "not disclosed"),
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
                 "NL-KVK-61172863": "dggf", "DE-1": "kfw-db", "XI-IATI-EC_INTPA": "eu-intpa",
                 "XM-DAC-46002": "afdb", "XM-DAC-903": "ifc"}
    amounts = {}
    for r in json.load(open(RAW / "iati_amounts.json")):
        amounts[r["aid"]] = r
    # Parent activities whose sub-activities are also published (AFD projects, Commission decisions) are skipped:
    # the money is counted once, at the sub-activity (contract) level.
    _ids, _kids = set(), {}
    for f in sorted(glob.glob(str(RAW / "iati" / "*.xml"))):
        try:
            for a in etree.parse(f).iter("iati-activity"):
                aid = (a.findtext("iati-identifier") or "").strip()
                _ids.add(aid)
                _kids.setdefault(aid, set()).update(r.get("ref") for r in a.findall("related-activity") if r.get("type") == "2")
        except etree.XMLSyntaxError:
            pass
    PARENTS_WITH_CHILDREN = {aid for aid, kids in _kids.items() if kids & _ids}
    seen = set()
    for f in sorted(glob.glob(str(RAW / "iati" / "*.xml"))):
        ref = pathlib.Path(f).stem.rsplit("_", 1)[0]
        try:
            tree = etree.parse(f)
        except etree.XMLSyntaxError:
            continue
        for a in tree.iter("iati-activity"):
            aid = (a.findtext("iati-identifier") or "").strip()
            if not aid or aid in seen or aid in PARENTS_WITH_CHILDREN:
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
            total, basis = None, None
            if float(am.get("commitment_eur") or 0):
                total, basis = float(am["commitment_eur"]), "commitment"
            elif float(am.get("spend_eur") or 0):
                total, basis = float(am["spend_eur"]), "disbursement"
            else:
                cur0 = a.get("default-currency") or "EUR"
                def _sum(elems):
                    tot = 0.0
                    for v in elems:
                        try:
                            val = float(v.text)
                        except (TypeError, ValueError):
                            continue
                        eur, _ = to_eur(val, v.get("currency") or cur0, (v.get("value-date") or "")[:7] or None)
                        tot += eur or 0
                    return tot or None
                buds = a.findall("budget")
                revised = [b for b in buds if b.get("type") == "2"]
                total = _sum([b.find("value") for b in (revised or buds) if b.find("value") is not None])
                basis = "budget" if total else None
                if not total:
                    total = _sum([pd.find("value") for pd in a.findall("planned-disbursement") if pd.find("value") is not None])
                    basis = "planned disbursement" if total else None
            eu_delegated = inst != "eu-intpa" and bool(re.search(
                r"(d[ée]l[ée]gu[ée]e?s? (par|de) l.Union|financ[ée]e?s? par l.Union europ|fonds (de l.)?Union europ[ée]enne|EU-funded|funded by the European Union|délégation de fonds de l.UE|cofinanc[ée]e? par l.UE)",
                " ".join(n.text or "" for n in a.findall(".//narrative")), re.I))
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
                date=start, amount_eur=total, shares=shares, method="eu_delegated" if eu_delegated else method, points=pts, basis=basis,
                note=("EU-funded activity implemented by this agency: counted under the European Commission to avoid double counting. "
                      if eu_delegated else "") + {"commitment": "Amount: commitment in EUR (d-portal).",
                      "disbursement": "Amount: disbursements in EUR (no commitment reported).",
                      "budget": "Amount: budget figure from the publisher's IATI record (no commitment or disbursement reported).",
                      "planned disbursement": "Amount: planned disbursements from the IATI record (no commitment reported).",
                      None: "No amount reported in IATI."}[basis])

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
    _proparco_ids = set()
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
        if rec in _proparco_ids:  # Proparco sometimes reuses a project number for a renewal: keep both deals
            rec = rec + "-" + p["url"].rstrip("/").rsplit("/", 1)[-1][:40]
        _proparco_ids.add(rec)
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
                amount=float(amt) if amt and amt.isdigit() else None, currency="EUR", basis="band estimate" if (key == "finnfund" and amt and amt.isdigit()) else None,
                shares={c: None for c in ccs}, method="single_country" if len(ccs) == 1 and not other else "equal_split_estimate",
                note="Amount is the band published by Finnfund." if key == "finnfund" and amt else
                     ("Amount not disclosed." if not amt else ""))

    # ---- Editable templates: created once so they can be filled in directly on GitHub
    for _name, _header in [("manual_entries.csv", "institution_id,title,client,countries,year,instrument,sector,amount,currency,source_url,note"),
                           ("programmes_manual.csv", "programme_id,name,kind,countries,participants,amount_eur,period,description,source_url,note")]:
        if not (OUT / _name).exists():
            (OUT / _name).write_text(_header + "\n", encoding="utf-8")

    # ---- Manual research sheet (ECAs, NPBs, JavaScript-only DFI sites). One row per deal.
    # countries: ISO2 codes separated by | (e.g. SN|CI). Keep a source_url for every row.
    manual = OUT / "manual_entries.csv"
    KNOWN_INST = {i[0] for i in INST}
    rejected = []
    if manual.exists():
        for i, r in enumerate(csv.DictReader(open(manual, encoding="utf-8-sig"))):
            r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
            if not any(r.values()):
                continue
            ccs = [c.strip().upper() for c in (r.get("countries") or "").split("|") if c.strip().upper() in COUNTRIES]
            problems = []
            if r.get("institution_id") not in KNOWN_INST:
                problems.append(f"unknown institution_id '{r.get('institution_id')}' (see data/institutions.csv)")
            if not ccs:
                problems.append(f"no valid country code in '{r.get('countries')}' (use codes such as SN or CM|TD)")
            amt_txt = (r.get("amount") or "").replace(" ", "")
            if amt_txt and not amt_txt.replace(".", "", 1).isdigit():
                problems.append(f"amount '{r.get('amount')}' must be digits only")
            if (r.get("currency") or "EUR").upper() not in set(FX_FIXED) | {c for c, _ in FX}:
                problems.append(f"currency '{r.get('currency')}' not supported")
            if problems:
                rejected.append({"row": i + 2, "title": r.get("title", ""), "problems": "; ".join(problems)})
                continue
            r["currency"] = (r.get("currency") or "EUR").upper()
            r["amount"] = amt_txt
            amt = float(r["amount"]) if (r.get("amount") or "").replace(".", "", 1).isdigit() else None
            add(r["institution_id"], "manual", f"m{i}", r.get("source_url", ""), r.get("title", ""),
                client=r.get("client", ""), instrument=r.get("instrument") or "Unknown",
                sector_broad=broad_sector(r.get("sector", "")), sector_detail=r.get("sector", ""), status="Signed",
                date=r.get("year", ""), amount=amt, currency=r.get("currency") or "EUR",
                shares={c: None for c in ccs}, method="single_country" if len(ccs) == 1 else "equal_split_estimate",
                note=r.get("note", ""))

    # ---- Curated deals from press releases (institutions that publish no deal database). Amounts only when published.
    CURATED_DEALS = [
        # inst, record id, title, countries, year, instrument, sector, client, source, note
        ("bgk", "wielton-ci-2020", "Export of 25 Wielton trailers to Côte d'Ivoire (purchase of export receivables)", "CI", "2020",
         "Export finance", "Transport equipment", "Wielton S.A. (Polish exporter)", "https://kuke.com.pl/wiedza/bgk-i-kuke-wspieraja-afrykanski-kontrakt-wieltonu/",
         "BGK bought the receivables of the export contract; amount not published."),
        ("kuke", "wielton-ci-2020", "Insurance of Wielton's export contract for 25 trailers to Côte d'Ivoire", "CI", "2020",
         "Guarantee", "Transport equipment", "Wielton S.A. (Polish exporter)", "https://kuke.com.pl/wiedza/bgk-i-kuke-wspieraja-afrykanski-kontrakt-wieltonu/",
         "Export credit insurance; amount not published."),
        ("bgk", "wielton-wa-buyer-credit", "Buyer credit for Wielton trailers and tractors sold to transport companies in Mali, Côte d'Ivoire, Togo and Benin", "ML CI TG BJ", "",
         "Export finance", "Transport equipment", "West African transport companies", "https://www.trade.gov.pl/wiedza/biznesowy-wymiar-wspolpracy-polski-z-afryka-czesc-3-3/",
         "Financing of foreign buyers of Polish goods; amounts and dates not published."),
        ("bgk", "senegal-deferred-payment", "Two-year deferred payment financing for Senegalese buyers of Polish goods, including food products", "SN", "",
         "Export finance", "Trade", "Senegalese importers", "https://www.trade.gov.pl/wiedza/biznesowy-wymiar-wspolpracy-polski-z-afryka-czesc-3-3/",
         "Amount and date not published."),
    ]
    for inst, rid, title, ccs, year, instrument, sector, client, src, note in CURATED_DEALS:
        cc_list = ccs.split()
        add(inst, "curated", rid, src, title, client=client, instrument=instrument, sector_broad=broad_sector(sector),
            sector_detail=sector, status="Signed", date=year, amount=None, shares={c: None for c in cc_list},
            method="single_country" if len(cc_list) == 1 else "equal_split_estimate", note=note)

    # ---- COFIDES (Spain), from its filtered project list
    cof_file = RAW / "cofides" / "projects.json"
    if cof_file.exists():
        seen_cof = set()
        for r in json.load(open(cof_file, encoding="utf-8")):
            ccs = countries_in(r["country"]) or [r["cc"]]
            key = r["name"]
            if key in seen_cof:
                continue
            seen_cof.add(key)
            add("cofides", "cofides-web", re.sub(r"[^a-z0-9]+", "-", key.lower())[:50], r["url"], key, desc=r["activity"], client=key,
                instrument=instrument_from(r["instrument"]), sector_broad=broad_sector(r["sector"] + " " + r["activity"]),
                sector_detail=r["sector"], status="Signed", shares={c: None for c in ccs},
                method="single_country" if len(ccs) == 1 else "equal_split_estimate", note="Amount not published by COFIDES.")

    # ---- More curated deals from public sources (round 2). Amounts as published; None when not published.
    CURATED_DEALS_2 = [
        # inst, id, title, countries, year, instrument, sector, client, amount, currency, source, note
        ("swedfund", "cofina-2024", "Loan to COFINA for MSME and women-entrepreneur finance in Côte d'Ivoire and Senegal", "CI SN", "2024", "Loan",
         "Financial inclusion SME", "Compagnie Financière Africaine (COFINA)", 20e6, "EUR",
         "https://www.mynewsdesk.com/swedfund/pressreleases/closing-msme-finance-gap-in-cote-divoire-and-senegal-3354367", "Split equally between the two countries."),
        ("swedfund", "bbm-2024", "Loan to Teyliom Finance for Bridge Bank Microfinance, Côte d'Ivoire", "CI", "2024", "Loan",
         "Microfinance SME", "Teyliom Finance / Bridge Bank Microfinance", 5e6, "USD",
         "https://www.avca.africa/news-insights/member-news/swedfunds-investment-fuels-financial-inclusion-in-west-africa/", "Co-investment with BluePeak (USD 25m in total)."),
        ("bpifrance-ae", "air-senegal-2019", "Export credit guarantee for Airbus aircraft delivered to Air Sénégal", "SN", "2019", "Guarantee",
         "Air transport", "Air Sénégal", None, "EUR", "https://www.bpifrance.fr/download/media-file/69978", "Amount not published in the source."),
        ("sace", "benin-push-2024", "Guarantee on a €120m financing for Benin's Ministry of Finance (Push Strategy)", "BJ", "2024", "Guarantee",
         "Budget public finance", "Ministry of Finance of Benin", 120e6, "EUR",
         "https://www.teleborsa.it/News/2024/07/24/sace-prima-operazione-di-push-strategy-in-benin-garanzia-su-finanziamento-da-120-milioni-di-euro-83.html", "Amount is the guaranteed financing."),
        ("sace", "togo-agri-machinery", "Guarantee on a €78.3m financing for Italian agricultural machinery (€100m contract)", "TG", "", "Guarantee",
         "Agriculture equipment", "Togolese buyer", 78.3e6, "EUR",
         "https://www.ilviaggiomagazine.it/piano-mattei-sogno-o-realta-il-viceministro-cirielli-tracciata-la-strada-ora-velocizziamo-i-progetti/", "Under the Mattei Plan; date not stated in the source."),
        ("cdp", "ci-agropole-north", "Co-financing of an agropole in northern Côte d'Ivoire", "CI", "2026", "Loan",
         "Agriculture agro-industry", "Government of Côte d'Ivoire", None, "EUR",
         "https://news.abidjan.net/articles/749230/financement-du-developpement-la-cassa-depositi-e-prestiti-ouvre-un-bureau-a-abidjan", "Amount and instrument not published; CDP opened an Abidjan office in 2026."),
        ("eifo", "taiba-ndiaye-2018", "Guarantee on a €140m export loan for the Taiba N'Diaye wind farm (Vestas turbines)", "SN", "2018", "Guarantee",
         "Wind energy", "Parc Eolien Taiba N'Diaye (Lekela)", 140e6, "EUR",
         "https://www.nsenergybusiness.com/projects/taiba-ndiaye-wind-farm-senegal/", "Guaranteed by EKF, now EIFO."),
        ("credendo", "cotonou-coast-2018", "Insurance of a €43.5m financing for coastal protection works in Cotonou", "BJ", "2018", "Guarantee",
         "Coastal protection climate adaptation", "Republic of Benin", 43.5e6, "EUR",
         "https://iciec.isdb.org/wp-content/uploads/2020/12/2018-en.pdf", "Listed in ICIEC's 2018 annual report with Credendo as client."),
    ]
    for inst, rid, title, ccs, year, instrument, sector, client, amount, cur, src, note in CURATED_DEALS_2:
        cc_list = ccs.split()
        add(inst, "curated", rid, src, title, client=client, instrument=instrument, sector_broad=broad_sector(sector), sector_detail=sector,
            status="Signed", date=year, amount=amount, currency=cur, shares={c: None for c in cc_list},
            method="single_country" if len(cc_list) == 1 else "equal_split_estimate", note=note,
            basis="published in press release" if amount else None)

    # ---- World Bank (IBRD/IDA): non-EU comparison layer
    wb_file = RAW / "nonEU" / "worldbank.json"
    if wb_file.exists():
        seen_wb = set()
        for r in json.load(open(wb_file, encoding="utf-8")):
            if r.get("id") in seen_wb or r.get("cc") not in COUNTRIES:
                continue
            seen_wb.add(r["id"])
            amt = float(re.sub(r"[^0-9.]", "", r.get("totalamt") or "") or 0) or None
            date = (r.get("boardapprovaldate") or "")[:7]
            sect = r.get("sector1") if isinstance(r.get("sector1"), str) else (r.get("sector1") or {}).get("Name", "")
            if isinstance(sect, str) and sect.startswith("{"):
                m = re.search(r"'Name': '([^']*)'", sect); sect = m.group(1) if m else ""
            add("worldbank", "wb-api", r["id"], r.get("url") or f"https://projects.worldbank.org/en/projects-operations/project-detail/{r['id']}",
                r.get("project_name") or r["id"], instrument="Loan", sector_broad=broad_sector(f"{sect} {r.get('project_name', '')}"),
                sector_detail=sect, status=r.get("status") or "", date=date, amount=amt, currency="USD", shares={r["cc"]: None},
                method="single_country", note="IBRD/IDA commitment in USD converted with ECB rates.")

    # ---- AIIB: non-EU comparison layer
    aiib_file = RAW / "nonEU" / "aiib.json"
    if aiib_file.exists():
        for r in json.load(open(aiib_file, encoding="utf-8")):
            ccs = countries_in(r.get("economy", ""))
            if not ccs:
                continue
            money = r.get("approved_funding") or r.get("committed_funding") or r.get("proposed_funding") or ""
            m = re.search(r"(USD|EUR)\s*([\d.,]+)\s*(million|billion)", money, re.I)
            amt = float(m.group(2).replace(",", "")) * (1e9 if m.group(3).lower() == "billion" else 1e6) if m else None
            add("aiib", "aiib-web", r.get("path", r.get("name"))[-60:], "https://www.aiib.org" + r.get("path", ""), r.get("name", ""),
                instrument="Loan", sector_broad=broad_sector(r.get("sector", "") + " " + r.get("name", "")), sector_detail=r.get("sector", ""),
                status=r.get("status", ""), date=r.get("date") if (r.get("date") or "").isdigit() else "", amount=amt,
                currency=(m.group(1).upper() if m else "USD"), shares={c: None for c in ccs},
                method="single_country" if len(ccs) == 1 else "equal_split_estimate", note=f"AIIB status: {r.get('status', '')}.")

    # ---- Separate the non-EU comparison layer from European data
    NONEU = {i[0] for i in INST if i[3] == "Non-EU"}
    comp_inv = {v["investment_id"]: v for v in investments if v["institution_id"] in NONEU}
    # IFC Global Trade Finance Program records carry the worldwide programme limit, not a country amount: left out
    comparators = [a for a in allocations if a["institution_id"] in NONEU
                   and not (a["institution_id"] == "ifc" and comp_inv[a["investment_id"]]["title"].upper().startswith("GTFP"))]
    investments[:] = [v for v in investments if v["institution_id"] not in NONEU]
    allocations[:] = [a for a in allocations if a["institution_id"] not in NONEU]
    with open(OUT / "comparators.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["institution_id", "country", "sector_broad", "amount_attributed_eur", "year", "instrument", "title", "source_url"])
        for a in comparators:
            v = comp_inv[a["investment_id"]]
            w.writerow([a["institution_id"], a["country"], v["sector_broad"], a["amount_attributed_eur"], v["year"], v["instrument"], v["title"], v["source_url"]])

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
    write("countries", [{"iso2": k, "iso3": v[0], "name": v[1], "lat": v[2], "lon": v[3], "union": UNION[k]} for k, v in COUNTRIES.items()],
          ["iso2", "iso3", "name", "lat", "lon", "union"])
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
        ("curated", "Curated deals from press releases (BGK, KUKE)", "", "manual", "Per-record source URLs"),
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
        "NE": "EU FR DE BE ES IT LU NL", "TG": "EU FR DE", "GW": "EU EIB FR PT ES",
        "CM": "EU EIB BE FR DE IT ES", "CF": "EU BE ES FR DE", "TD": "EU EIB FR DE IT NL ES", "CG": "EU FR DE", "GA": "EU FR"}
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
        # CEMAC country Team Europe Initiatives
        P("tei-cm-north", "Cameroon – Green Deal and resilience in North Cameroon", TEI, "CM", TE_COUNTRY["CM"], "Agri-food systems, rural livelihoods, natural resources, local governance and stability in Cameroon's three northern regions.", "https://capacity4dev.europa.eu/resources/team-europe-tracker/partner-countries/cameroon/tei_en", note=MEMBERS_NOTE),
        P("tei-cf-court", "Central African Republic – Special Criminal Court", TEI, "CF", "EU BE ES FR DE", "Support for the court trying serious international crimes, with resources and expertise for its independent operation.", EC + "central-african-republic_en"),
        P("tei-cg-forests", "Republic of the Congo – Congo Basin forests and sustainable development", TEI, "CG", "EU FR DE", "Preserving the Congo Basin's forests and moving the economy away from oil towards a green, diversified path.", EC + "congo_en", note="Name describes the initiative as presented by the Commission."),
        # Regional Team Europe Initiatives covering WAEMU countries
        P("tei-atlantic", "Migration – Atlantic and Western Mediterranean routes", TEI, "SN BF CI ML NE", "EU BE CZ DK FR DE IT NL ES", "Regional migration and mobility initiative; also covers Algeria, Mauritania, Morocco, The Gambia, Ghana, Guinea and Nigeria.", "https://enlargement.ec.europa.eu/news/eu-working-together-african-partners-migration-launch-team-europe-initiatives-2022-12-12_en", amount=908e6, period="2022–", note="€908m mobilised at launch across all 12 partner countries, not only WAEMU."),
        P("tei-centralmed", "Migration – Central Mediterranean route", TEI, "BF NE CI", "EU AT BE DE CZ DK FR IT MT NL ES", "Regional migration initiative; also covers Chad, Egypt, Libya, Ethiopia, Eritrea, Somalia, Sudan, Tunisia, Guinea and Nigeria.", "https://enlargement.ec.europa.eu/news/eu-working-together-african-partners-migration-launch-team-europe-initiatives-2022-12-12_en", period="2022–"),
        P("tei-iyba", "Investing in Young Businesses in Africa (IYBA)", TEI, "BJ SN TG BF ML NE", "EU EIB FR DE BE NL", "Finance and technical support for start-ups and small businesses; Benin was the pilot country (launched in Cotonou, March 2024).", "https://international-partnerships.ec.europa.eu/policies/global-gateway/investing-young-businesses-africa_en", period="2021–", note="Country list per the Commission; participants are the core members named in public communication and may be incomplete."),
        P("tei-opvet", "Opportunity-driven skills and vocational training in Africa (OP-VET)", TEI, "BJ BF ML NE TG CI GW SN TD", "EU", "Aligning vocational training with jobs created by public and private investment.", "https://capacity4dev.europa.eu/countries/nigeria/projects_en", period="2024–"),
        P("tei-mav", "Manufacturing and access to vaccines, medicines and health technologies (MAV+)", TEI, "SN", "EU EIB FR DE BE", "Continental initiative; in Senegal it backs the MADIBA vaccine plant at Institut Pasteur de Dakar and the national pharmaceutical plan.", EC + "senegal_en", note="Participants named are the most visible members; the full list is not openly published."),
        P("tei-water", "Transboundary water management in Africa", TEI, "SN ML NE BJ BF CI TG CM TD", "EU", "Senegal, Gambia, Niger and Volta basins among those targeted.", "https://capacity4dev.europa.eu/groups/public-water_and_sanitation/info/team-europe-initiative-transboundary-water-management-africa_en", period="2022–"),
        # Global Gateway flagships
        P("gg-cm-nachtigal", "Nachtigal hydropower (420 MW) and Cameroon–Chad interconnection", GG, "CM TD", "EU EIB", "Exporting electricity from the Nachtigal plant to Chad through a new interconnection; support also for the 500 MW Kikot dam.", EC + "cameroon_en"),
        P("gg-cm-logone", "Logone River bridge (Cameroon–Chad)", GG, "CM TD", "EU", "Bridge linking Cameroon and Chad on the Douala–N'Djamena corridor.", EC + "cameroon_en"),
        P("gg-cm-transcam", "TRANSCAM 2 railway rehabilitation (Belabo–Ngaoundéré)", GG, "CM", "EU EIB afd", "Railway on the Douala–N'Djamena corridor, with planned extensions to Chad; €243m blended scheme including €23.6m of EU grant.", "https://international-partnerships.ec.europa.eu/system/files/2023-10/GG_Factsheet_Africa_Strategic%20Corridors.pdf", amount=243e6, note="Total blended financing, not EU money alone."),
        P("gg-td-road", "Chad–Cameroon road corridor rehabilitation", GG, "TD", "EU EIB", "229 km road on the corridor giving Chad access to the port of Douala.", "https://www.eib.org/en/press/all/2023-154-global-gateway-l-equipe-europe-finance-a-hauteur-de-176-2meur-le-projet-de-corridor-routier-entre-le-tchad-et-le-cameroun", amount=176.2e6, period="2023"),
        P("gg-corr-libreville-ndjamena", "Strategic corridor Libreville/Kribi/Douala–N'Djamena", GG, "GA GQ CM TD", "EU EIB afd", "Central African transport corridor; also covers São Tomé and Príncipe.", CORR),
        P("gg-corr-douala-kampala", "Strategic corridor Douala/Kribi–Kampala", GG, "CM CF", "EU", "Corridor linking Cameroon's ports to the Central African Republic, DR Congo and Uganda.", CORR),
        P("gg-ga-transgabonais", "Transgabonais railway rehabilitation", GG, "GA", "EU", "Connecting production areas with Libreville's economic zones and sawmills.", EC + "gabon_en", amount=30e6),
        P("gg-cf-backbone", "Central Africa Backbone fibre network (CAR)", GG, "CF", "EU", "Extension of the fibre-optic network.", EC + "central-african-republic_en"),
        P("gg-cg-forest", "EU–Republic of the Congo Forest Partnership", GG, "CG", "EU", "Partnership on forest protection and the forest economy (memorandum signed 2022).", EC + "congo_en", period="2022–"),
        P("gg-ga-forest", "EU–Gabon Forest Partnership", GG, "GA", "EU", "Biodiversity protection with benefits for local populations, protected areas and certified forest concessions.", EC + "gabon_en"),
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
        P("env-cm", "EU bilateral envelope – Cameroon", ENV, "CM", "EU", "NDICI-Global Europe grant funding for the partnership.", EC + "cameroon_en", amount=244e6, period="2021–2027"),
        P("env-cf", "EU bilateral envelope – Central African Republic", ENV, "CF", "EU", "Peace and security, education and health, agriculture and governance.", EC + "central-african-republic_en", amount=204e6, period="2021–2024"),
        P("env-td", "EU bilateral envelope – Chad", ENV, "TD", "EU", "Corridor investments, rural electrification, value chains and vocational training.", EC + "chad_en", amount=280e6, period="2021–2024"),
        P("env-cg", "EU bilateral envelope – Republic of the Congo", ENV, "CG", "EU", "Green, digital and diversified economy.", EC + "congo_en", amount=110e6, period="2021–2027"),
        P("env-ga", "EU bilateral envelope – Gabon", ENV, "GA", "EU", "Green transition, sustainable growth and governance.", EC + "gabon_en", amount=11e6, period="2021–2027", note="Amount as stated on the Commission's Gabon page."),
        P("env-gw", "EU bilateral envelope – Guinea-Bissau", ENV, "GW", "EU", "Health, education and training, economic diversification and governance.", EC + "guinea-bissau_en", amount=155e6, period="2021–2027"),
        # National programmes without deal-level disclosure
        P("nat-choose-africa-2", "Choose Africa 2 (AFD Group and Bpifrance)", NAT, "BJ CI SN TG", "afd proparco bpifrance", "Financing and support for African start-ups and small businesses, plus help for states to build public banks for entrepreneurs.", "https://www.afd.fr/fr/actualites/choose-africa-2-le-soutien-lentrepreneuriat-africain-monte-en-regime", period="2023–2027"),
        P("nat-choose-africa-2-ci", "Choose Africa 2 – Côte d'Ivoire SME financing", NAT, "CI", "afd bpifrance", "XOF 52bn (€80m) loan for credit lines and the SME guarantee fund (SGPME), via Côte d'Ivoire PME.", "https://www.afd.fr/fr/actualites/communique-de-presse/choose-africa-2-un-premier-financement-en-cote-divoire-pour-renforcer-lacces-au-credit-de-plusieurs-milliers-de-tpme-en-particulier-de-lentrepreneuriat-feminin", amount=80e6, period="2024"),
        P("nat-bpifrance-ae", "Bpifrance Assurance Export – export credit and investment insurance", NAT, "CI SN", "bpifrance-ae", "Export credit insurance, guarantees and foreign investment insurance for French companies on behalf of the French state; deals are not published individually.", "https://www.bpifrance.fr/nos-actualites/bpifrance-en-afrique-25-ans-dengagement-pour-des-partenariats-economiques-durables-et-une-co-industrialisation-ambitieuse", note="Countries shown are those Bpifrance names as its West African hubs; coverage extends further."),
        P("nat-pl-fwe", "Government programme 'Financial Support for Exports' (BGK and KUKE)", NAT, "CI SN", "bgk kuke", "Polish state programme financing and insuring export contracts on higher-risk markets; BGK names Côte d'Ivoire and Senegal among its African markets.", "https://polskieradio24.pl/artykul/3177646,polscy-przedsiebiorcy-podbijaja-swiatowe-rynki-bgk-umozliwia-im-bezpieczny-start-za-granica", note="Deal-level amounts are not published."),
        P("nat-bgk-africa-limit", "BGK Africa export financing limit to 2030", NAT, "CI", "bgk kuke", "Credit, guarantee and letter-of-credit limit of PLN 4bn (about USD 1.1bn) for Polish firms exporting to and investing in seven African countries, including Côte d'Ivoire.", "https://www.wnp.pl/rynki/bgk-przeznaczy-miliardy-zlotych-na-wsparcie-polskich-firm-w-afryce,999155.html", period="to 2030", note="The limit covers seven countries (also Angola, Morocco, South Africa, Tanzania, Kenya, Rwanda), so no WAEMU amount is shown."),
        P("nat-cwa", "G20 Compact with Africa (initiated by Germany)", NAT, "BJ BF CI SN TG", "DE kfw-db deg", "G20 initiative launched under Germany's 2017 presidency to coordinate reforms and attract private investment; Germany backs it with KfW and DEG instruments.", "https://www.compactwithafrica.org/en/programs/g20-compact-with-africa", period="2017–"),
        P("nat-africaconnect", "AfricaConnect (DEG, BMZ Development Investment Fund)", NAT, "BJ BF CI SN TG", "deg", "Loans of €0.75–4m with risk sharing for European companies investing in Africa, focused on Compact with Africa countries.", "https://www.bmz.de/resource/blob/39670/factsheet-africaconnect-en.pdf", period="2019–"),
        P("nat-mattei", "Italy's Mattei Plan", NAT, "CI BJ TG CG GA", "IT cdp simest sace", "Italy's Africa strategy, delivered through CDP (a €500m Africa facility), SIMEST (€200m 'Misura Africa') and SACE guarantees.", "https://www.ilviaggiomagazine.it/piano-mattei-sogno-o-realta-il-viceministro-cirielli-tracciata-la-strada-ora-velocizziamo-i-progetti/", period="2024–", note="Côte d'Ivoire and the Republic of the Congo are original priority countries; Gabon joined in 2026; Benin and Togo have documented SACE operations."),
        P("nat-cesce-ci", "CESCE cover ceiling for the Ivorian public sector", NAT, "CI", "cesce", "Spanish state risk committee ceiling for new medium- and long-term operations of Spanish firms with Ivorian public buyers.", "https://www.monedaunica.net/2018/06/cesce-amplia-la-cobertura-en-costa-de-marfil-y-turkmenistan/", amount=100e6, period="2018–", note="A cover limit, not money spent."),
        P("nat-finexpo", "Belgian Finexpo mixed credits (with Credendo)", NAT, "CI", "credendo BE", "Belgian state-supported mixed credits for projects with Belgian suppliers.", "https://credendo.com/sites/default/files/media/files/2021-03/annualreports2017.pdf"),
        P("nat-c2d", "Debt-for-development swaps (C2D) with Côte d'Ivoire", NAT, "CI", "afd ES", "Côte d'Ivoire's debt payments to France and Spain are returned as financing for poverty-reduction projects.", "https://www.cesce.es/documents/20122/0/INFORME+COSTA+DE+MARFIL+-+22+septiembre+2021_compressed.pdf/da7a101b-6d0e-f02a-dbd8-073b8d128721?t=1633361771235"),
        P("nat-bpifrance-ebid", "Bpifrance and EBID export finance cooperation", NAT, "BJ BF CI GW ML NE SN TG", "bpifrance bpifrance-ae", "Joint identification and financing of public and private buyers of French exports, backed by state export guarantees.", "https://presse.bpifrance.fr/bpifrance-et-la-bidc-banque-dinvestissement-et-de-developpement-de-la-cedeao-renforcent-leur-cooperation-en-faveur-du-developpement-des-exportations-francaises-en-afrique/", period="2024–"),
        P("nat-sofid", "SOFID investments in Portuguese-speaking Africa", NAT, "GW", "sofid", "Portugal's DFI focuses on Portuguese-speaking countries and lists Guinea-Bissau among countries with approved projects.", "https://pipelineroad.com/directory/sofid", note="Individual deals are not published."),
        P("nat-bpifrance-acc", "Bpifrance Africa Accelerator", NAT, "SN CI", "bpifrance", "Support programme for French SMEs expanding in Africa, including business missions to Dakar.", "https://presse.bpifrance.fr/bpifrance-accompagne-la-deuxieme-promotion-de-laccelerateur-afrique-a-dakar-pour-prospecter-le-marche-senegalais/?lang=fra", note="Business support, not a financing commitment."),
    ]
    manual_prog = OUT / "programmes_manual.csv"
    if manual_prog.exists():  # extra programmes you add by hand: same columns, lists separated by spaces
        for _j, r in enumerate(csv.DictReader(open(manual_prog, encoding="utf-8-sig"))):
            r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
            if r.get("programme_id") and r.get("name") and r.get("kind") and r["kind"] not in (TEI, GG, ENV, PART, NAT):
                rejected.append({"file": "programmes_manual.csv", "row": _j + 2, "title": r["name"],
                                 "problems": f"kind '{r['kind']}' unknown; shown as 'National programme'"})
                r["kind"] = NAT
            if r.get("programme_id") and r.get("name"):
                PROGRAMMES.append(P(r["programme_id"], r["name"], r.get("kind") or NAT, r.get("countries", ""), r.get("participants", "EU"),
                                    r.get("description", ""), r.get("source_url", ""), float(r["amount_eur"]) if (r.get("amount_eur") or "").replace(".", "", 1).isdigit() else None,
                                    r.get("period", ""), r.get("note", "")))
    PROGRAMMES = [p for p in PROGRAMMES if any(c in COUNTRIES for c in p["countries"])]
    PROG_SECTORS = {'tei-ci-cocoa': ['Agriculture and food systems', 'Energy and climate'], 'tei-ci-lowcarbon': ['Energy and climate', 'Transport and corridors'], 'tei-ci-peace': ['Governance and budget support'], 'tei-sn-green': ['Agriculture and food systems', 'Energy and climate', 'Digital and telecoms'], 'tei-bj-port': ['Transport and corridors'], 'tei-bj-energy': ['Energy and climate'], 'tei-bj-jobs': ['Education and skills', 'Financial sector and SMEs', 'Digital and telecoms'], 'tei-bf-greendeal': ['Agriculture and food systems', 'Energy and climate', 'Digital and telecoms', 'Education and skills'], 'tei-bf-stability': ['Governance and budget support', 'Other (social, humanitarian, multi-sector)'], 'tei-ml-climate': ['Energy and climate', 'Agriculture and food systems'], 'tei-ml-youth': ['Education and skills', 'Financial sector and SMEs'], 'tei-ne-futures': ['Education and skills'], 'tei-ne-governance': ['Governance and budget support'], 'tei-tg-decentral': ['Governance and budget support'], 'tei-tg-agri': ['Agriculture and food systems', 'Financial sector and SMEs'], 'tei-tg-energy': ['Energy and climate', 'Digital and telecoms'], 'tei-gw-education': ['Education and skills'], 'tei-atlantic': ['Governance and budget support'], 'tei-centralmed': ['Governance and budget support'], 'tei-iyba': ['Financial sector and SMEs'], 'tei-opvet': ['Education and skills'], 'tei-mav': ['Health', 'Industry and trade'], 'tei-water': ['Water and sanitation'], 'gg-sn-hann': ['Water and sanitation', 'Energy and climate'], 'gg-sn-brt': ['Transport and corridors'], 'gg-sn-ziguinchor': ['Transport and corridors'], 'gg-sn-river': ['Agriculture and food systems', 'Water and sanitation'], 'gg-sn-medusa': ['Digital and telecoms'], 'gg-bj-wapp': ['Energy and climate'], 'gg-bj-roads': ['Transport and corridors'], 'gg-bj-cotonou-ww': ['Water and sanitation'], 'gg-bj-tvet': ['Education and skills'], 'gg-ci-solar': ['Energy and climate'], 'gg-ci-backbone': ['Energy and climate'], 'gg-ci-300m': ['Energy and climate', 'Agriculture and food systems', 'Financial sector and SMEs'], 'gg-tg-coast': ['Energy and climate'], 'gg-dorsale': ['Energy and climate'], 'gg-naturafrica': ['Energy and climate'], 'gg-corr-abj-lagos': ['Transport and corridors'], 'gg-corr-abj-ouaga': ['Transport and corridors'], 'gg-corr-dakar-abj': ['Transport and corridors'], 'gg-corr-cot-niamey': ['Transport and corridors'], 'gg-eib-ppf': ['Transport and corridors', 'Energy and climate'], 'jetp-sn': ['Energy and climate'], 'env-ci': ['Other (social, humanitarian, multi-sector)'], 'env-sn': ['Other (social, humanitarian, multi-sector)'], 'env-bj': ['Other (social, humanitarian, multi-sector)'], 'env-bf': ['Other (social, humanitarian, multi-sector)'], 'env-ml': ['Other (social, humanitarian, multi-sector)'], 'env-ne': ['Other (social, humanitarian, multi-sector)'], 'env-tg': ['Other (social, humanitarian, multi-sector)'], 'env-gw': ['Other (social, humanitarian, multi-sector)'], 'nat-choose-africa-2': ['Financial sector and SMEs'], 'nat-choose-africa-2-ci': ['Financial sector and SMEs'], 'nat-bpifrance-ae': ['Industry and trade'], 'nat-bpifrance-acc': ['Industry and trade'], 'nat-pl-fwe': ['Industry and trade'], 'nat-bgk-africa-limit': ['Industry and trade'], 'nat-cwa': ['Financial sector and SMEs', 'Industry and trade'], 'nat-africaconnect': ['Financial sector and SMEs'], 'nat-mattei': ['Agriculture and food systems', 'Energy and climate', 'Industry and trade'], 'nat-cesce-ci': ['Industry and trade'], 'nat-finexpo': ['Industry and trade'], 'nat-c2d': ['Governance and budget support', 'Other (social, humanitarian, multi-sector)'], 'nat-bpifrance-ebid': ['Industry and trade'], 'nat-sofid': ['Financial sector and SMEs'], 'tei-cm-north': ['Agriculture and food systems', 'Energy and climate', 'Governance and budget support'], 'tei-cf-court': ['Governance and budget support'], 'tei-cg-forests': ['Energy and climate'], 'gg-cm-nachtigal': ['Energy and climate'], 'gg-cm-logone': ['Transport and corridors'], 'gg-cm-transcam': ['Transport and corridors'], 'gg-td-road': ['Transport and corridors'], 'gg-corr-libreville-ndjamena': ['Transport and corridors'], 'gg-corr-douala-kampala': ['Transport and corridors'], 'gg-ga-transgabonais': ['Transport and corridors'], 'gg-cf-backbone': ['Digital and telecoms'], 'gg-cg-forest': ['Energy and climate'], 'gg-ga-forest': ['Energy and climate'], 'env-cm': ['Other (social, humanitarian, multi-sector)'], 'env-cf': ['Other (social, humanitarian, multi-sector)'], 'env-td': ['Other (social, humanitarian, multi-sector)'], 'env-cg': ['Other (social, humanitarian, multi-sector)'], 'env-ga': ['Other (social, humanitarian, multi-sector)']}
    for _p in PROGRAMMES:  # sector tags for the overlap analysis; manual programmes are tagged from their text
        _p["sectors"] = PROG_SECTORS.get(_p["programme_id"]) or [broad_sector(_p["name"] + " " + _p["description"])]
    with open(OUT / "programmes.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(PROGRAMMES[0].keys()))
        w.writeheader()
        for p in PROGRAMMES:
            w.writerow({**p, "countries": " ".join(p["countries"]), "participants": " ".join(p["participants"]), "sectors": "; ".join(p["sectors"])})

    with open(OUT / "manual_rejected.csv", "w", newline="", encoding="utf-8") as fh:  # rows from your manual files that need fixing
        w = csv.DictWriter(fh, fieldnames=["file", "row", "title", "problems"])
        w.writeheader()
        for r in rejected:
            w.writerow({"file": r.get("file", "manual_entries.csv"), **{k: r[k] for k in ("row", "title", "problems")}})
    if rejected:
        print(f"{len(rejected)} manual row(s) set aside: see data/manual_rejected.csv")

    # compact bundle for the website
    bundle = {"generated": TODAY, "programmes": PROGRAMMES,
              "places": {k: {"name": v[0], "lat": v[1], "lon": v[2]} for k, v in PARTICIPANT_PLACES.items()}, "countries": {k: {"name": v[1], "lat": v[2], "lon": v[3], "union": UNION[k]} for k, v in COUNTRIES.items()},
              "institutions": inst_rows,
              "sectors": SECTOR_LIST, "peg_year": 1999,
              "comparators": [{"i": a["institution_id"], "c": a["country"], "s": comp_inv[a["investment_id"]]["sector_broad"],
                               "v": a["amount_attributed_eur"], "y": comp_inv[a["investment_id"]]["year"], "n": comp_inv[a["investment_id"]]["instrument"]}
                              for a in comparators if a["amount_attributed_eur"]],
              "investments": [{k: inv[k] for k in ("investment_id", "institution_id", "title", "client", "client_domicile",
                                                   "instrument", "sector_broad", "status", "year", "amount_eur", "amount_basis", "es_category",
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
    """Inline the data, the world map and both map libraries into the page -> site/index.html"""
    data = json.dumps(json.load(open(ROOT / "data" / "tracker.json", encoding="utf-8")), ensure_ascii=False, separators=(",", ":"))
    world = (ROOT / "ref" / "countries-110m.json").read_text(encoding="utf-8")
    safe = lambda s: s.replace("</", "<\\/")
    html = TEMPLATE.replace("/*__DATA__*/null", safe(data)).replace("/*__WORLD__*/null", safe(world))
    libs = {"/*__LIB_TOPOJSON__*/": ("topojson-client.min.js", "https://cdn.jsdelivr.net/npm/topojson-client@3.1.0/dist/topojson-client.min.js"),
            "/*__LIB_GLOBE__*/": ("globe.gl.min.js", "https://cdn.jsdelivr.net/npm/globe.gl@2.46.2/dist/globe.gl.min.js")}
    for mark, (fname, url) in libs.items():
        f = ROOT / "ref" / fname
        code = f.read_text(encoding="utf-8") if f.exists() else ""
        if code and "</script" not in code.lower():
            html = html.replace(f"<script>{mark}</script>", "<script>" + code + "</script>")
        else:  # library file missing: fall back to loading it from the CDN
            html = html.replace(f"<script>{mark}</script>", f'<script src="{url}"></script>')
    (ROOT / "site" / "index.html").write_text(html, encoding="utf-8")
    print("site/index.html", round(len(html.encode()) / 1e6, 2), "MB")

FETCH_STEPS = ["reference", "iati", "proparco", "bio", "wp", "eib", "cofides", "noneu"]

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
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
/* Dark by design: an operations-console look, identical in light and dark system settings */
:root{
  --bg:#040a0f; --bg2:#071219; --panel:rgba(7,18,26,.9); --panel-solid:#08151d;
  --ink:#d9f4ff; --muted:#8db1c0; --dim:#56798a; --line:#163746; --line-hi:#2a6a80;
  --accent:#40e8ff; --focus:#40e8ff; --chip:#0a1c26;
  --ocean:#04141c; --land:#12303c; --land-eu:#1b4556; --land-waemu:#5a4317; --land-cemac:#55271c; --border:#5d93a6; --waemu-line:#ffbf5c; --cemac-line:#ff9a7a;
  --t-dfi:#3aa6ff; --t-bdb:#ff8c42; --t-npb:#2dffc8; --t-eca:#ff3d8e; --t-eu:#ffd84a; --t-mdb:#b77dff;
  --t-non:#c3ccd1; --k-tei:#4fa8ff; --k-gg:#ffb43f; --k-env:#c592ff; --k-part:#3dffaa; --k-nat:#ff5ba0;
  --mono:"IBM Plex Mono",ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace;
  --sans:"IBM Plex Sans","Segoe UI",system-ui,-apple-system,sans-serif;
  color-scheme:dark;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark}}
:root[data-theme="dark"]{color-scheme:dark}
:root{box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
html{scroll-padding-top:env(safe-area-inset-top,0px)}
*,*::before,*::after{box-sizing:inherit}
html,body{height:100%;margin:0}
body{background:radial-gradient(ellipse at 35% 45%,#0a2230 0%,var(--bg) 62%);background-color:var(--bg);color:var(--ink);font:400 15px/1.5 var(--sans)}
.app{display:grid;grid-template-columns:minmax(0,1fr) 8px var(--pw,440px);height:100%}
.resizer{cursor:col-resize;background:var(--line);position:relative;touch-action:none}
.resizer::after{content:"";position:absolute;top:50%;left:2px;width:4px;height:44px;margin-top:-22px;border-left:1px solid var(--line-hi);border-right:1px solid var(--line-hi)}
.resizer:hover,.resizer:focus-visible{background:var(--line-hi);outline:none}
.stage{position:relative;min-height:0;overflow:hidden}
#globe{position:absolute;top:0;right:0;bottom:0;left:0}
/* faint scanlines and vignette over the globe */
.stage::after{content:"";position:absolute;top:0;right:0;bottom:0;left:0;pointer-events:none;background:radial-gradient(ellipse at center,transparent 58%,rgba(0,0,0,.5) 100%)}
.hud{position:absolute;z-index:2;pointer-events:none}
.title{left:clamp(16px,3vw,36px);top:clamp(14px,3vh,28px);max-width:40ch}
.title .code{font:500 12px/1 var(--mono);color:var(--muted);letter-spacing:.08em;margin:0 0 10px}
.title h1{margin:0;font-weight:600;font-size:clamp(24px,2.8vw,38px);line-height:1.1;letter-spacing:-.005em}
.title p{margin:.7em 0 0;color:var(--muted);font-size:14px;max-width:46ch}
.readout{right:clamp(12px,2vw,24px);top:clamp(14px,3vh,28px);font:400 12px/1.7 var(--mono);color:var(--muted);text-align:right;
  background:rgba(4,12,17,.6);border:1px solid var(--line);padding:8px 12px}
.readout b{color:var(--ink);font-weight:500}
.readout .r-total{font:500 14px/1.6 var(--sans);color:var(--muted);margin-top:2px}
.readout .r-total b{font:600 20px/1.2 var(--sans);color:var(--ink)}
.readout .r-small{font-size:11px;color:var(--dim)}
.legend{left:clamp(16px,3vw,36px);bottom:clamp(14px,3vh,28px);display:flex;flex-direction:column;gap:6px;font-size:13px;
  background:rgba(4,12,17,.72);padding:10px 12px;border:1px solid var(--line)}
.legend span{display:flex;align-items:center;gap:9px}
.legend i{width:22px;height:0;border-top:2px dotted;display:inline-block}
.legend .fz{margin-top:2px}
.legend i.box{width:14px;height:10px;border:1.5px solid;border-top-width:1.5px}
.legend small{color:var(--dim);font-family:var(--mono);font-size:11px}
.bracket::before,.bracket::after{content:"";position:absolute;width:10px;height:10px;border:1px solid var(--accent);pointer-events:none}
.bracket::before{top:-1px;left:-1px;border-right:0;border-bottom:0}
.bracket::after{bottom:-1px;right:-1px;border-left:0;border-top:0}
/* glowing pins */
.pin{position:relative;width:0;height:0;pointer-events:auto;cursor:pointer;z-index:5}
.pin b{position:absolute;left:-15px;top:-15px;width:30px;height:30px;border-radius:50%;background:transparent}
.pin:hover i{transform:scale(1.5)}
.pin:hover span,.pin:focus-visible span{opacity:1}
.pin i{position:absolute;left:-4px;top:-4px;width:8px;height:8px;border-radius:50%;background:var(--c);
  box-shadow:0 0 6px 2px var(--c),0 0 16px 4px var(--c)}
.pin.dest i{left:-3px;top:-3px;width:6px;height:6px;box-shadow:0 0 6px 1px var(--c)}
.pin::after{content:"";position:absolute;left:-12px;top:-12px;width:24px;height:24px;border-radius:50%;border:1px solid var(--c);opacity:.0;animation:ping 2.4s ease-out infinite}
.pin.dest::after{animation-duration:3.6s}
.pin span{position:absolute;left:12px;top:-8px;font:500 12px/1 var(--sans);color:var(--ink);white-space:nowrap;background:rgba(4,12,17,.85);border:1px solid var(--line-hi);padding:3px 6px;opacity:0;pointer-events:none}
@keyframes ping{0%{transform:scale(.3);opacity:.9}100%{transform:scale(1.6);opacity:0}}
aside{background:var(--panel);border-left:1px solid var(--line);display:flex;flex-direction:column;min-height:0;backdrop-filter:blur(6px)}
.filters{padding:14px 18px 12px;border-bottom:1px solid var(--line);display:grid;gap:10px}
.filterbox{border:1px solid var(--line)}
.filterbox summary{cursor:pointer;padding:8px 10px;font:600 13px var(--sans);color:var(--ink);list-style-position:inside}
.filterbox summary span{color:var(--accent);font-weight:500}
.filtergrid{display:grid;gap:12px;padding:4px 10px 12px}
.searchbox input{width:100%;font:500 14px var(--sans);color:var(--ink);background:var(--chip);border:1px solid var(--line-hi);padding:8px 10px 8px 32px;
  background-image:linear-gradient(transparent,transparent);outline:none}
.searchbox{position:relative}
.searchbox::before{content:"";position:absolute;left:11px;top:50%;width:9px;height:9px;margin-top:-7px;border:1.5px solid var(--muted);border-radius:50%}
.searchbox::after{content:"";position:absolute;left:20px;top:50%;width:6px;height:1.5px;margin-top:3px;background:var(--muted);transform:rotate(45deg)}
.searchbox input:focus{border-color:var(--accent)}
.searchbox input::placeholder{color:var(--dim)}
.unionhead{display:flex;align-items:center;gap:8px;margin:6px 0 4px;font-size:12.5px;color:var(--muted)}
.unionhead b{font-weight:600;color:var(--ink)}
.unionhead .clear{margin-left:auto;font-size:12px}
.estbox{display:flex;gap:8px;align-items:flex-start;font-size:12.5px;color:var(--muted)}
.reset{appearance:none;width:100%;padding:10px 12px;cursor:pointer;font:600 13px var(--sans);letter-spacing:.08em;text-transform:uppercase;
  color:#ffe9eb;background:linear-gradient(#7a1622,#5a0f19);border:1px solid #d9455a;outline:1px solid rgba(217,69,90,.35);outline-offset:3px;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.12),0 2px 0 #2b060b}
.reset:hover{background:linear-gradient(#8e1a28,#661220);border-color:#ff5f73}
.reset:active{transform:translateY(1px);box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 1px 0 #2b060b}
.reset:focus-visible{outline:2px solid #ff8a98;outline-offset:3px}
.views{display:grid;grid-template-columns:1fr 1fr 1fr;border:1px solid var(--line-hi)}
.views button{appearance:none;border:0;background:transparent;color:var(--muted);font:600 14px/1 var(--sans);padding:10px 6px;cursor:pointer}
.views button[aria-pressed="true"]{background:rgba(64,232,255,.08);color:var(--ink);box-shadow:inset 0 -2px 0 var(--accent)}
[hidden]{display:none!important}
.group h2{margin:0 0 6px;font:600 12px/1 var(--sans);color:var(--muted)}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{appearance:none;border:1px solid var(--line);background:var(--chip);color:var(--ink);padding:4px 9px 4px 7px;font:500 13px/1.3 var(--sans);cursor:pointer;display:inline-flex;align-items:center;gap:6px}
.chip[aria-pressed="false"]{opacity:.4}
.chip .sw,.sw{width:8px;height:8px;border-radius:50%;display:inline-block}
select{font:500 14px var(--sans);color:var(--ink);background:var(--chip);border:1px solid var(--line);padding:6px 8px;width:100%}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
button:focus-visible,select:focus-visible,a:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
.summary{padding:10px 18px;border-bottom:1px solid var(--line)}
.summary .sel{display:flex;justify-content:space-between;gap:8px;align-items:baseline}
.summary strong{font:600 22px/1.2 var(--sans);color:var(--ink);font-variant-numeric:tabular-nums}
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
.kind{font:600 12px/1 var(--sans);margin-bottom:5px}
.flag{font:500 11px var(--mono);border:1px dashed var(--line-hi);padding:0 5px;color:var(--muted)}
.more{display:block;margin:12px auto;appearance:none;border:1px solid var(--line-hi);background:transparent;color:var(--accent);font:500 14px var(--sans);padding:6px 14px;cursor:pointer}
.ana{padding:12px 18px 20px;display:grid;gap:22px}
.ana h3{margin:0 0 4px;font:600 15px var(--sans)}
.ana .hint{margin:0 0 10px;font-size:12.5px;color:var(--muted)}
.ana .seg{display:inline-flex;border:1px solid var(--line);margin-bottom:10px}
.ana .seg button{appearance:none;border:0;background:transparent;color:var(--muted);font:500 12.5px var(--sans);padding:5px 10px;cursor:pointer}
.ana .seg button[aria-pressed="true"]{background:rgba(64,232,255,.1);color:var(--ink)}
.ana .seg button:disabled{opacity:.4;cursor:not-allowed}
.bar{display:grid;grid-template-columns:minmax(110px,48%) 1fr auto;gap:8px;align-items:center;font-size:13px;margin:3px 0}
.bar .lbl{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--ink)}
.bar .track{height:10px;background:rgba(255,255,255,.04);position:relative}
.bar .track i{position:absolute;left:0;top:0;bottom:0}
.bar .val{font:500 12px var(--mono);color:var(--muted);min-width:64px;text-align:right}
.ov-controls{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}
.ov-controls .full{grid-column:1/-1}
.cols{display:grid;grid-template-columns:52px 1fr;gap:6px}
.yaxis{display:flex;flex-direction:column;justify-content:space-between;height:200px;font:400 11px var(--mono);color:var(--dim);text-align:right}
.plot{height:200px;display:flex;align-items:flex-end;gap:6px;border-left:1px solid var(--line-hi);border-bottom:1px solid var(--line-hi);padding:0 4px;overflow-x:auto}
.col{flex:1 0 26px;max-width:56px;display:flex;flex-direction:column;justify-content:flex-end;height:100%}
.col i{display:block;min-height:2px}
.xlabels{grid-column:2;display:flex;gap:6px;padding:0 4px;overflow:hidden}
.xlabels span{flex:1 0 26px;max-width:56px;height:88px;font-size:11px;color:var(--muted);writing-mode:vertical-rl;transform:rotate(180deg);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-align:left}
.ylabel{font-size:11px;color:var(--dim);margin-top:4px}
.col{position:relative}
.col .cnt{position:absolute;top:-16px;left:0;right:0;text-align:center;font:500 10.5px var(--mono);color:var(--muted)}
.col i + i{border-top:1px solid rgba(0,0,0,.45)}
.plot{padding-top:18px}
.xlabels.sec span{height:150px}
.stacklegend{display:flex;flex-wrap:wrap;gap:4px 12px;margin-top:8px;font-size:11.5px;color:var(--muted)}
.stacklegend i{display:inline-block;width:9px;height:9px;margin-right:5px;vertical-align:-1px}
.foot{padding:10px 18px;border-top:1px solid var(--line);font-size:12px;color:var(--muted)}
.foot summary{cursor:pointer;font-family:var(--mono);letter-spacing:.06em}
.tip{font:13px/1.4 var(--sans);background:var(--panel-solid);color:var(--ink);border:1px solid var(--line-hi);padding:8px 10px;max-width:260px;box-shadow:0 0 18px rgba(64,232,255,.15)}
.tip b{color:var(--accent)}
.maptools{position:absolute;z-index:3;right:clamp(12px,2vw,24px);bottom:clamp(14px,3vh,28px);display:flex;flex-direction:column;align-items:flex-end;gap:6px;max-width:620px}
.maptools button{appearance:none;background:rgba(4,12,17,.85);border:1px solid var(--line-hi);color:var(--ink);font:500 13px var(--sans);padding:7px 12px;cursor:pointer}
.maptools button:hover{border-color:var(--accent)}
.toolrow{display:flex;align-items:center;gap:10px}
.sources{font-size:11.5px;color:var(--dim);text-align:right;max-width:360px;line-height:1.35}
.maptools p{margin:0;font-size:12.5px;color:var(--muted);background:rgba(4,12,17,.85);border:1px solid var(--line);padding:6px 9px;text-align:right}
.flatmap{position:absolute;top:0;right:0;bottom:0;left:0;width:100%;height:100%;cursor:grab;touch-action:none;background:var(--ocean)}
.flatmap:active{cursor:grabbing}
.flatmap .land{fill:var(--land);stroke:var(--border);stroke-width:.6px;vector-effect:non-scaling-stroke}
.flatmap .land.eu{fill:var(--land-eu)}
.flatmap .land.waemu{fill:var(--land-waemu);stroke:var(--waemu-line);stroke-width:1.2px;cursor:pointer}
.flatmap .land.cemac{fill:var(--land-cemac);stroke:var(--cemac-line);stroke-width:1.2px;cursor:pointer}
.flatmap .arc{fill:none;stroke-linecap:round;stroke-dasharray:0 7;vector-effect:non-scaling-stroke;opacity:.9;cursor:pointer;animation:flow 14s linear infinite}
.flatmap .arc.sparse{stroke-dasharray:0 13;animation-duration:26s}
.flatmap .cname{fill:#ffe2b0;font:600 13px var(--sans);text-anchor:middle;paint-order:stroke;stroke:#000;stroke-width:3px;pointer-events:none}
@keyframes flow{to{stroke-dashoffset:-70}}
.flatmap .reveal{fill:none;stroke:#fff;stroke-width:40px;stroke-dasharray:1 1;stroke-dashoffset:1;animation:reveal 14s linear forwards}
@keyframes reveal{to{stroke-dashoffset:0}}
.pinlayer{position:absolute;top:0;right:0;bottom:0;left:0;pointer-events:none;overflow:hidden}
.pinlayer .pin{position:absolute;left:0;top:0}
@media (prefers-reduced-motion:reduce){.pin::after,.flatmap .arc{animation:none}}
@media (max-width:860px){
  .app{grid-template-columns:1fr;grid-template-rows:64vh auto;height:auto}
  .resizer{display:none}
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
<noscript><p style="padding:24px;font-size:16px">This tracker needs JavaScript to show the map and the deal list. Please enable JavaScript in your browser settings and reload the page.</p></noscript>
<div class="app">
  <section class="stage" aria-label="Interactive globe">
    <div id="globe"></div>
    <div class="hud title" style="position:absolute">
      <p class="code">Franc Zone tracker</p>
      <h1>European Public Investment in the Franc Zone</h1>
      <p>Where EU institutions and member states' development banks, DFIs, promotional banks and export credit agencies invest in the Franc Zone's 14 countries (WAEMU in West Africa, CEMAC in Central Africa), and the Team Europe programmes they run there. Click a line, a country or a capital.</p>
    </div>
    <div class="hud readout bracket" aria-hidden="true">
      <div>Records: <b id="r-rec"></b></div>
      <div class="r-total">Total: <b id="r-total"></b> since implementation of XOF/XAF–Euro peg</div>
      <div class="r-small" id="r-und"></div>
      <div class="r-small">Data sync <span id="r-sync"></span></div>
    </div>
    <div class="hud legend bracket" id="legend" aria-label="Legend"></div>
    <div class="maptools"><div class="toolrow"><span class="sources" id="sources"></span><button type="button" id="modebtn">Switch to 2D map</button></div><p id="mapnotice" hidden></p></div>
  </section>
  <div class="resizer" id="resizer" role="separator" aria-orientation="vertical" aria-label="Drag to resize the side panel" tabindex="0"></div>
  <aside>
    <div class="filters">
      <div class="views" role="group" aria-label="What to show">
        <button type="button" data-view="inv" aria-pressed="true">Investments</button>
        <button type="button" data-view="prog" aria-pressed="false">Programmes</button>
        <button type="button" data-view="ana" aria-pressed="false">Analysis</button>
      </div>
      <details class="filterbox" id="filterbox"><summary>Filters <span id="fcount"></span></summary><div class="filtergrid">
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
      <div class="group"><h2>Recipient country</h2><div id="f-cc"></div></div>
      <div class="group"><h2><label for="f-cap">Jump to a capital</label></h2><select id="f-cap"></select></div>
      <div class="row2" id="inv-filters-2">
        <div class="group"><h2><label for="f-ins">Instrument</label></h2><select id="f-ins"></select></div>
        <div class="group"><h2><label for="f-yr">Signed or started since</label></h2><select id="f-yr"></select></div>
      </div>
      <label class="estbox" id="est-wrap" hidden><input type="checkbox" id="f-est" checked> Include estimated amounts (equal splits of multi-country deals, published amount bands)</label>
      </div></details>
      <button type="button" class="reset" id="reset">Reset all filters</button>
      <div class="searchbox"><input type="search" id="q" placeholder="Search deals by name, client or institution" aria-label="Search deals" autocomplete="off"></div>
    </div>
    <div class="summary" aria-live="polite">
      <div class="sel"><strong id="s-total">–</strong></div>
      <p id="s-text"></p>
    </div>
    <div class="list" id="list"></div>
    <div class="foot">
      <details><summary>About the data</summary>
        <p>Coverage: the 14 Franc Zone countries of the WAEMU (Benin, Burkina Faso, Côte d'Ivoire, Guinea-Bissau, Mali, Niger, Senegal, Togo) and the CEMAC (Cameroon, Central African Republic, Chad, Republic of the Congo, Equatorial Guinea, Gabon). The Comoros are not included. "Congo" always means the Republic of the Congo (Brazzaville), never the Democratic Republic of the Congo. Both CFA francs (XOF and XAF) have been pegged to the euro since 1 January 1999. The Council of Europe Development Bank is not included: it lends only to its European member states. Data updated <span id="gen"></span>. If the globe does not appear on your device, use the "Switch to 2D map" button. Data refreshes on the 1st of every month at the same address. Amounts are commitments in euros. Multi-country deals without published country shares are split equally and marked as estimates. Regional deals that only mention a WAEMU country are listed but not counted in totals. Arcs end at each country's capital.</p>
        <p id="gaps"></p>
      </details>
    </div>
  </aside>
</div>
<script>/*__LIB_TOPOJSON__*/</script>
<script>/*__LIB_GLOBE__*/</script>
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
  AT:"Austria",ES:"Spain",IT:"Italy",PT:"Portugal",PL:"Poland",EU:"EU institution",INT:"International (EBRD)",NONEU:"Non-EU",
  CZ:"Czechia",SK:"Slovakia",HR:"Croatia",GR:"Greece",SI:"Slovenia",HU:"Hungary",RO:"Romania",BG:"Bulgaria",EE:"Estonia",LV:"Latvia",
  LT:"Lithuania",IE:"Ireland",LU:"Luxembourg"};
const SHORT = {"eu-intpa":"European Commission",afd:"AFD",proparco:"Proparco","kfw-db":"KfW",deg:"DEG",fmo:"FMO","invest-intl":"Invest International",
  dggf:"DGGF",bio:"BIO",finnfund:"Finnfund",ifu:"IFU","atradius-dsb":"Atradius DSB",eib:"EIB",ebrd:"EBRD",bgk:"BGK",kuke:"KUKE",cofides:"COFIDES",swedfund:"Swedfund",
  sace:"SACE",cdp:"CDP",eifo:"EIFO",credendo:"Credendo","bpifrance-ae":"Bpifrance Assurance Export",worldbank:"World Bank",ifc:"IFC",
  afdb:"AfDB Group",aiib:"AIIB"};
// Official capitals: arcs end here
const CAPITALS = {BJ:["Porto-Novo",6.497,2.605],BF:["Ouagadougou",12.371,-1.520],CI:["Yamoussoukro",6.827,-5.289],GW:["Bissau",11.864,-15.598],
  ML:["Bamako",12.639,-8.003],NE:["Niamey",13.512,2.112],SN:["Dakar",14.716,-17.467],TG:["Lomé",6.131,1.222],
  CM:["Yaoundé",3.848,11.502],CF:["Bangui",4.394,18.558],TD:["N'Djamena",12.134,15.056],CG:["Brazzaville",-4.263,15.242],
  GQ:["Malabo",3.755,8.774],GA:["Libreville",0.416,9.467]};
// Franc Zone countries by numeric ISO code (shapes on the map); the union decides the colour
const WAEMU_NUM = {"204":"BJ","854":"BF","384":"CI","624":"GW","466":"ML","562":"NE","686":"SN","768":"TG",
  "120":"CM","140":"CF","148":"TD","178":"CG","226":"GQ","266":"GA"};
const unionOf = cc => (DATA.countries[cc] && DATA.countries[cc].union) || "WAEMU";
const fzVar = (cc, kind) => unionOf(cc) === "CEMAC" ? (kind === "line" ? "--cemac-line" : "--land-cemac") : (kind === "line" ? "--waemu-line" : "--land-waemu");
const EU_NUM = new Set(["040","056","100","191","196","203","208","233","246","250","276","300","348","372","380","428","440","442","470","528","616","620","642","703","705","724","752"]);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const typeVar = Object.fromEntries(TYPES.map(t => [t[0], t[2]]));
const kindVar = Object.fromEntries(KINDS.map(k => [k[0], k[2]]));
const INST = Object.fromEntries(DATA.institutions.map(i => [i.institution_id, i]));
const INV = Object.fromEntries(DATA.investments.map(i => [i.investment_id, i]));
const PROG = DATA.programmes || [], PLACES = DATA.places || {};
const withData = new Set(DATA.investments.map(i => i.institution_id));
const fmt = v => v >= 1e9 ? "€" + (v/1e9).toFixed(1) + " bn" : v >= 1e6 ? "€" + (v/1e6).toFixed(v >= 1e8 ? 0 : 1) + " m" : v >= 1e3 ? "€" + Math.round(v/1e3) + " k" : "€" + Math.round(v);
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const plain = s => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "");  // the globe's 3D font has no accents
const rgba = (hex, a) => { const h = hex.replace("#",""); const n = parseInt(h.length === 3 ? h.split("").map(x => x+x).join("") : h, 16);
  return `rgba(${n>>16&255},${n>>8&255},${n&255},${a})`; };
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const partName = p => (PLACES[p] && PLACES[p].name) || p;
const ccName = cc => DATA.countries[cc].name;

const state = {view:"inv", types:new Set(TYPES.map(t => t[0])), kinds:new Set(KINDS.map(k => k[0])), part:"", ms:"", inst:"",
  cc:new Set(Object.keys(DATA.countries)), ins:"", yr:"", focus:null, shown:40,
  est:true, donorBy:"inst", ovMode:"eu", ovCC:"", ovSector:"", q:"", ovStack:"inst"};
const norm = s => String(s == null ? "" : s).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
let qTimer = null;
document.getElementById("q").addEventListener("input", e => {
  clearTimeout(qTimer);
  qTimer = setTimeout(() => { state.q = norm(e.target.value.trim()); state.focus = null; update(); }, 200);
});

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
for (const un of ["WAEMU", "CEMAC"]) {
  const members = Object.entries(DATA.countries).filter(([cc]) => unionOf(cc) === un);
  if (!members.length) continue;
  const head = document.createElement("div"); head.className = "unionhead";
  head.innerHTML = `<span class="sw" style="background:var(${un === "CEMAC" ? "--cemac-line" : "--waemu-line"})"></span><b>${un}</b>`;
  const tog = document.createElement("button"); tog.type = "button"; tog.className = "clear"; tog.textContent = "All / none";
  tog.onclick = () => {
    const allOn = members.every(([cc]) => state.cc.has(cc));
    members.forEach(([cc]) => allOn ? state.cc.delete(cc) : state.cc.add(cc));
    fCC.querySelectorAll(`.chip[data-union="${un}"]`).forEach(c => c.setAttribute("aria-pressed", state.cc.has(c.dataset.cc)));
    state.focus = null; update();
  };
  head.append(tog); fCC.append(head);
  const row = document.createElement("div"); row.className = "chips"; fCC.append(row);
  members.forEach(([cc, c]) => {
    const b = document.createElement("button"); b.className = "chip"; b.type = "button"; b.dataset.cc = cc; b.dataset.union = un;
    b.setAttribute("aria-pressed", "true"); b.textContent = c.name;
    b.onclick = () => { state.cc.has(cc) ? state.cc.delete(cc) : state.cc.add(cc); b.setAttribute("aria-pressed", state.cc.has(cc)); state.focus = null; update(); };
    row.append(b);
  });
}
function opts(el, list, all) { el.innerHTML = `<option value="">${all}</option>` + list.map(([v,l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join(""); }
const covered = DATA.institutions.filter(i => withData.has(i.institution_id));
opts(document.getElementById("f-ms"), [...new Set(covered.map(i => i.member_state))].map(m => [m, MS[m] || m]), "All");
opts(document.getElementById("f-inst"), covered.map(i => [i.institution_id, SHORT[i.institution_id] || i.name]), "All");
opts(document.getElementById("f-ins"), [...new Set(DATA.investments.map(i => i.instrument))].sort().map(x => [x,x]), "All");
const years = [...new Set(DATA.investments.map(i => i.year).filter(Boolean))].sort();
opts(document.getElementById("f-yr"), [2000,2010,2015,2020,2023,2025].filter(y => y >= +years[0]).map(y => [y, String(y)]), "Any year");
const parts = [...new Set(PROG.flatMap(p => p.participants))].filter(p => PLACES[p]).sort((a,b) => partName(a).localeCompare(partName(b)));
opts(document.getElementById("f-part"), parts.map(p => [p, partName(p)]), "All");
opts(document.getElementById("f-cap"), Object.entries(CAPITALS).map(([cc,[city]]) => [cc, `${city}, ${DATA.countries[cc].name}`]), "Choose a capital");
document.getElementById("f-cap").onchange = e => {
  const cc = e.target.value; if (!cc) return;
  const [, lat, lng] = CAPITALS[cc];
  R.focusOn(lat, lng);
  state.focus = {cc}; update(); e.target.value = "";
};
for (const [id,key] of [["f-ms","ms"],["f-inst","inst"],["f-ins","ins"],["f-yr","yr"],["f-part","part"]])
  document.getElementById(id).onchange = e => { state[key] = e.target.value; state.focus = null; update(); };
document.querySelectorAll(".views button").forEach(b => b.onclick = () => {
  state.view = b.dataset.view; state.focus = null;
  document.querySelectorAll(".views button").forEach(x => x.setAttribute("aria-pressed", x === b));
  document.getElementById("inv-filters").hidden = state.view === "prog";
  document.getElementById("inv-filters-2").hidden = state.view === "prog";
  document.getElementById("prog-filters").hidden = state.view !== "prog";
  document.getElementById("est-wrap").hidden = state.view !== "ana";
  document.getElementById("q").placeholder = state.view === "prog" ? "Search programmes by name, goal or participant" : "Search deals by name, client or institution";
  drawLegend(); update();
});
document.getElementById("reset").onclick = () => {
  Object.assign(state, {types:new Set(TYPES.map(t => t[0])), kinds:new Set(KINDS.map(k => k[0])), part:"", ms:"", inst:"",
    cc:new Set(Object.keys(DATA.countries)), ins:"", yr:"", focus:null, est:true, q:""});
  document.getElementById("q").value = "";
  document.getElementById("f-est").checked = true;
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
(() => {
  const INVY = Object.fromEntries(DATA.investments.map(i => [i.investment_id, i.year]));
  let peg = 0, und = 0;
  for (const a of DATA.allocations) {
    const y = INVY[a.investment_id], v = a.amount_attributed_eur || 0;
    if (!y) und += v; else if (+y >= (DATA.peg_year || 1999)) peg += v;
  }
  document.getElementById("r-total").textContent = fmt(peg);
  document.getElementById("r-und").textContent = und ? `plus ${fmt(und)} in undated deals` : "";
})();
document.getElementById("sources").textContent = "(Data: IATI via d-portal, EIB, Proparco, BIO, DEG, Finnfund, IFU, COFIDES, World Bank, AIIB, ECB exchange rates, curated public sources)";
document.getElementById("f-est").onchange = e => { state.est = e.target.checked; update(false); };
(() => {
  const eu = DATA.institutions.filter(i => i.type !== "Non-EU");
  const grp = c => eu.filter(i => i.coverage === c && !withData.has(i.institution_id)).map(i => SHORT[i.institution_id] || i.name).join(", ");
  const parts = [["Programme level only (no deal-level data published)", grp("programme level")],
                 ["Checked, no Franc Zone deals found in public sources", grp("checked: no Franc Zone deals found")],
                 ["Not yet found in public sources", grp("manual")]].filter(x => x[1]);
  document.getElementById("gaps").textContent = parts.map(([l, v]) => `${l}: ${v}.`).join(" ") +
    " Non-EU actors (World Bank, IFC, African Development Bank Group including the African Development Fund, AIIB) appear only in the overlap analysis and are never added to European totals.";
})();
function drawLegend() {
  const list = state.view === "prog" ? KINDS : TYPES;
  document.getElementById("legend").innerHTML = list.map(([,l,v]) => `<span><i style="color:var(${v})"></i>${l}</span>`).join("") +
    `<span class="fz"><i class="box" style="background:var(--land-waemu);border-color:var(--waemu-line)"></i>WAEMU <i class="box" style="background:var(--land-cemac);border-color:var(--cemac-line);margin-left:10px"></i>CEMAC</span>` +
    `<small>${state.view !== "prog" ? "Line weight grows with the amount invested" : "Lines link participants to the countries a programme covers"}</small>`;
}
drawLegend();

// ---------- resizable side panel
(() => {
  const app = document.querySelector(".app"), rz = document.getElementById("resizer");
  const clampW = w => Math.max(340, Math.min(w, window.innerWidth * 0.65, window.innerWidth - 320));
  const setW = w => { app.style.setProperty("--pw", clampW(w) + "px"); };
  try { const s = +localStorage.getItem("waemu-panel-w"); if (s) setW(s); } catch (e) {}
  const save = () => { try { localStorage.setItem("waemu-panel-w", parseInt(getComputedStyle(app).getPropertyValue("--pw")) || 440); } catch (e) {} };
  let drag = false;
  rz.addEventListener("pointerdown", e => { drag = true; rz.setPointerCapture(e.pointerId); });
  rz.addEventListener("pointermove", e => { if (drag) setW(window.innerWidth - e.clientX - 4); });
  rz.addEventListener("pointerup", () => { drag = false; save(); });
  rz.addEventListener("keydown", e => {
    const w = parseInt(getComputedStyle(app).getPropertyValue("--pw")) || 440;
    if (e.key === "ArrowLeft") { setW(w + 30); save(); } if (e.key === "ArrowRight") { setW(w - 30); save(); }
  });
})();

// ---------- map renderers: a 3D globe where the device can draw it, a flat 2D map otherwise
const el = document.getElementById("globe");
const features = (() => {
  // The base map (Natural Earth via world-atlas) draws Crimea inside Russia. Crimea is Ukrainian territory:
  // remove it from Russia's shape and merge it into Ukraine's, so it shows within Ukraine's internationally recognised borders.
  let ukraine = null;
  try {
    const g = WORLD.objects.countries.geometries, ru = g.find(x => x.id === "643"), ua = g.find(x => x.id === "804");
    if (ru && ua && ru.type === "MultiPolygon") {
      const ring = p => topojson.feature(WORLD, {type: "Polygon", arcs: p}).geometry.coordinates[0];
      const i = ru.arcs.findIndex(p => ring(p).every(q => q[0] > 32 && q[0] < 37 && q[1] > 44 && q[1] < 46.5));
      if (i >= 0) {
        const crimea = ru.arcs[i];
        ru.arcs = ru.arcs.filter((_, k) => k !== i);
        ukraine = topojson.merge(WORLD, [ua, {type: "Polygon", arcs: crimea}]);
      }
    }
  } catch (e) { ukraine = null; }
  const fs = topojson.feature(WORLD, WORLD.objects.countries).features.filter(f => f.id !== "010");
  if (ukraine) fs.forEach(f => { if (f.id === "804") f.geometry = ukraine; });
  return fs;
})();
let pinHover = false;
const seedOf = s => { let h = 0; for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) % 997; return h / 997; };
const cur = {textContent: ""};  // cursor readout removed
const fmtCoord = c => c ? `${Math.abs(c.lat).toFixed(2)}°${c.lat >= 0 ? "N" : "S"} ${Math.abs(c.lng).toFixed(2)}°${c.lng >= 0 ? "E" : "W"}` : "off map";
function pinElement(d) {
  const p = document.createElement("div");
  p.className = "pin" + (d.dest ? " dest" : ""); p.style.setProperty("--c", d.color);
  p.innerHTML = `<b></b><i></i><span>${esc(d.title)}</span>`;
  p.setAttribute("role", "button"); p.tabIndex = 0; p.setAttribute("aria-label", d.title);
  p.onclick = e => { e.stopPropagation(); d.onclick(); };
  p.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); d.onclick(); } };
  p.onpointerenter = () => (pinHover = true);
  p.onpointerleave = () => (pinHover = false);
  return p;
}
function webgl2Available() {
  try { const c = document.createElement("canvas"); return !!(window.WebGL2RenderingContext && c.getContext("webgl2")); } catch (e) { return false; }
}

function makeGlobe() {
  if (typeof Globe === "undefined") throw new Error("globe library not loaded");
  if (!webgl2Available()) throw new Error("WebGL 2 not available");
  const host = document.createElement("div"); host.style.cssText = "position:absolute;top:0;right:0;bottom:0;left:0"; el.append(host);
  const globe = Globe()(host)
    .backgroundColor("rgba(0,0,0,0)")
    .showGraticules(false)
    .showAtmosphere(true).atmosphereAltitude(0.12)
    .polygonsData(features)
    .polygonAltitude(f => WAEMU_NUM[f.id] ? 0.009 : 0.005).polygonSideColor(() => "rgba(0,0,0,0)").polygonsTransitionDuration(0)
    .polygonLabel(f => WAEMU_NUM[f.id] ? `<div class="tip"><b>${esc(ccName(WAEMU_NUM[f.id]))}</b><br>Click to see what reaches this country</div>`
      : `<div class="tip">${esc(f.properties.name)}</div>`)
    .onPolygonClick(f => { if (WAEMU_NUM[f.id]) { state.focus = {cc: WAEMU_NUM[f.id]}; update(); } })
    .arcStartLat(d => d.sLat).arcStartLng(d => d.sLng).arcEndLat(d => d.eLat).arcEndLng(d => d.eLng)
    .arcAltitudeAutoScale(0.38)
    .arcLabel(arcTip)
    .onArcClick(d => { if (!pinHover) arcClick(d); })
    .ringLat("lat").ringLng("lng").ringMaxRadius(d => d.r).ringPropagationSpeed(reduceMotion ? 0 : 0.9).ringRepeatPeriod(d => d.period)
    .ringColor(d => t => rgba(d.color, Math.max(0, 0.75 * (1 - t))))
    .htmlLat("lat").htmlLng("lng").htmlAltitude(0.012).htmlElement(pinElement)
    .htmlElementVisibilityModifier((elm, visible) => { elm.style.opacity = visible ? 1 : 0; elm.style.pointerEvents = visible ? "auto" : "none"; })
    .labelLat("lat").labelLng("lng").labelText("name").labelSize(1.15).labelDotRadius(0).labelAltitude(0.014).labelResolution(2);
  globe.pointOfView(el.clientWidth < 600 ? {lat: 20, lng: 4, altitude: 2.6} : {lat: 22, lng: 3, altitude: 1.9}, 0);
  const ctl = globe.controls(); ctl.autoRotate = false; ctl.enableDamping = true;
  const ro = new ResizeObserver(() => globe.width(el.clientWidth).height(el.clientHeight)); ro.observe(el);
  let growing = !reduceMotion && !grownOnce, lastArcs = null;
  if (growing) setTimeout(() => { growing = false; grownOnce = true; if (lastArcs && R && R.mode === "3d") R.arcs(lastArcs[0], lastArcs[1]); }, 14000);
  const canvas = host.querySelector("canvas");
  if (canvas) canvas.addEventListener("webglcontextlost", () => fallBack("The 3D view stopped (graphics memory). Showing the 2D map."));
  const move = e => { const r = el.getBoundingClientRect(); cur.textContent = fmtCoord(globe.toGlobeCoords(e.clientX - r.left, e.clientY - r.top)); };
  el.addEventListener("pointermove", move);
  return {
    mode: "3d",
    arcs(arcs, sparse) {
      lastArcs = [arcs, sparse];
      globe.arcsTransitionDuration(0).arcsData(arcs).arcColor(d => [rgba(d.color, 0.18), rgba(d.color, 0.95)]).arcStroke("stroke");
      if (growing) {  // one long dash slides in from the European end: the line grows to Africa in 14 s
        globe.arcDashLength(1).arcDashGap(1).arcDashInitialGap(1).arcDashAnimateTime(14000);
      } else {
        globe.arcDashLength(sparse ? 0.008 : 0.014).arcDashGap(sparse ? 0.03 : 0.02).arcDashInitialGap(d => d.seed)
          .arcDashAnimateTime(reduceMotion ? 0 : (sparse ? 26000 : 14000));
      }
    },
    pins(origins, dests) {
      globe.htmlElementsData(origins.concat(dests));
      globe.ringsData(origins.map(o => ({lat:o.lat, lng:o.lng, color:o.color, r:2.6, period:1800 + (o.seed || 0) * 900}))
        .concat(dests.map(d => ({lat:d.lat, lng:d.lng, color:d.color, r:1.4, period:3200}))));
    },
    labels(list) { globe.labelsData(list.map(l => ({...l, name: plain(l.name), lat: l.lat + 1.6}))); },
    paint() {
      const mat = globe.globeMaterial(); mat.color.set(css("--ocean"));
      if (mat.emissive) { mat.emissive.set("#031820"); mat.emissiveIntensity = 0.3; }
      globe.atmosphereColor(css("--accent"));
      globe.polygonCapColor(f => WAEMU_NUM[f.id] ? css(fzVar(WAEMU_NUM[f.id], "fill")) : EU_NUM.has(f.id) ? css("--land-eu") : css("--land"))
        .polygonStrokeColor(f => WAEMU_NUM[f.id] ? css(fzVar(WAEMU_NUM[f.id], "line")) : css("--border"));
      globe.labelColor(() => "#ffe2b0");
    },
    focusOn(lat, lng) { globe.pointOfView({lat, lng, altitude: 0.9}, reduceMotion ? 0 : 1200); },
    // returns true if the globe really drew something in the middle of the screen
    selfTest() {
      try {
        const r = globe.renderer(); r.render(globe.scene(), globe.camera());
        const gl = r.getContext(); const px = new Uint8Array(4);
        gl.readPixels(Math.floor(gl.drawingBufferWidth / 2), Math.floor(gl.drawingBufferHeight / 2), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
        return px[3] > 0 || px[0] + px[1] + px[2] > 0;
      } catch (e) { return false; }
    },
    destroy() {
      ro.disconnect(); el.removeEventListener("pointermove", move);
      try { globe.pauseAnimation(); const r = globe.renderer(); r.dispose(); r.forceContextLoss && r.forceContextLoss(); } catch (e) {}
      host.remove();
    }
  };
}

function makeFlat() {
  const NS = "http://www.w3.org/2000/svg";
  const K = 10, LAT_STRETCH = 1.25;                     // simple projection, stretched vertically to limit distortion
  const P = (lng, lat) => [lng * K, -lat * K * LAT_STRETCH];
  const inv = (x, y) => ({lng: x / K, lat: -y / (K * LAT_STRETCH)});
  const svg = document.createElementNS(NS, "svg"); svg.setAttribute("class", "flatmap"); svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Flat map of Europe and West Africa"); el.append(svg);
  const pinLayer = document.createElement("div"); pinLayer.className = "pinlayer"; el.append(pinLayer);
  let vb = {x: P(-40, 0)[0], y: P(0, 68)[1], w: (48 + 40) * K, h: (68 + 16) * K * LAT_STRETCH};
  const home = {...vb};
  function fit() {
    const ar = el.clientWidth / Math.max(1, el.clientHeight), cx = vb.x + vb.w / 2, cy = vb.y + vb.h / 2;
    if (vb.w / vb.h > ar) vb.h = vb.w / ar; else vb.w = vb.h * ar;
    vb.x = cx - vb.w / 2; vb.y = cy - vb.h / 2;
    svg.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`); placePins();
  }
  const ring = r => r.map(([lng, lat], i) => (i ? "L" : "M") + P(lng, lat).map(v => v.toFixed(1)).join(",")).join("") + "Z";
  const gLand = document.createElementNS(NS, "g"), gLabels = document.createElementNS(NS, "g"), gArcs = document.createElementNS(NS, "g");
  svg.append(gLand, gArcs, gLabels);
  for (const f of features) {
    const g = f.geometry; if (!g) continue;
    const polys = g.type === "Polygon" ? [g.coordinates] : g.coordinates;
    const path = document.createElementNS(NS, "path");
    path.setAttribute("d", polys.map(p => p.map(ring).join("")).join(""));
    path.setAttribute("class", WAEMU_NUM[f.id] ? "land " + unionOf(WAEMU_NUM[f.id]).toLowerCase() : EU_NUM.has(f.id) ? "land eu" : "land");
    const t = document.createElementNS(NS, "title"); t.textContent = WAEMU_NUM[f.id] ? ccName(WAEMU_NUM[f.id]) : f.properties.name; path.append(t);
    if (WAEMU_NUM[f.id]) path.addEventListener("click", () => { state.focus = {cc: WAEMU_NUM[f.id]}; update(); });
    gLand.append(path);
  }
  let pins = [];
  function placePins() {
    const r = el.getBoundingClientRect(), s = r.width / vb.w;
    for (const {d, node} of pins) {
      const [x, y] = P(d.lng, d.lat);
      node.style.transform = `translate(${(x - vb.x) * s}px, ${(y - vb.y) * s}px)`;
    }
  }
  // pan and zoom
  let drag = null;
  svg.addEventListener("pointerdown", e => { drag = {x: e.clientX, y: e.clientY, vx: vb.x, vy: vb.y}; svg.setPointerCapture(e.pointerId); });
  svg.addEventListener("pointerup", () => (drag = null));
  const move = e => {
    const r = el.getBoundingClientRect(), s = vb.w / r.width;
    if (drag) { vb.x = drag.vx - (e.clientX - drag.x) * s; vb.y = drag.vy - (e.clientY - drag.y) * s; fit(); }
    cur.textContent = fmtCoord(inv(vb.x + (e.clientX - r.left) * s, vb.y + (e.clientY - r.top) * s));
  };
  svg.addEventListener("pointermove", move);
  svg.addEventListener("wheel", e => {
    e.preventDefault();
    const r = el.getBoundingClientRect(), f = e.deltaY > 0 ? 1.15 : 1 / 1.15;
    const mx = vb.x + (e.clientX - r.left) / r.width * vb.w, my = vb.y + (e.clientY - r.top) / r.height * vb.h;
    const w = Math.min(home.w * 2, Math.max(home.w / 12, vb.w * f)), k = w / vb.w;
    vb = {x: mx - (mx - vb.x) * k, y: my - (my - vb.y) * k, w, h: vb.h * k}; fit();
  }, {passive: false});
  const ro = new ResizeObserver(fit); ro.observe(el);
  if (!grownOnce && !reduceMotion) setTimeout(() => { grownOnce = true; gArcs.querySelectorAll("[mask]").forEach(n => n.removeAttribute("mask")); gArcs.querySelectorAll("mask").forEach(n => n.remove()); }, 14200);
  return {
    mode: "2d",
    arcs(arcs, sparse) {
      gArcs.innerHTML = "";
      for (const d of arcs) {
        const [x1, y1] = P(d.sLng, d.sLat), [x2, y2] = P(d.eLng, d.eLat);
        const mx = (x1 + x2) / 2, my = (y1 + y2) / 2, dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy);
        const bend = 0.18 + d.seed * 0.12, cx = mx - dy / len * len * bend, cy = my + dx / len * len * bend;
        const p = document.createElementNS(NS, "path");
        p.setAttribute("d", `M${x1},${y1} Q${cx},${cy} ${x2},${y2}`);
        p.setAttribute("class", "arc" + (sparse ? " sparse" : ""));
        p.style.stroke = d.color; p.style.strokeWidth = (1 + d.stroke * 4).toFixed(2) + "px";
        p.style.animationDelay = `-${(d.seed * 20).toFixed(1)}s`;
        const t = document.createElementNS(NS, "title");
        t.textContent = d.part ? `${d.label} in ${ccName(d.cc)}: ${d.n} programme${d.n > 1 ? "s" : ""}`
          : `${d.label} to ${ccName(d.cc)}: ${d.n} deal${d.n > 1 ? "s" : ""}${d.sum ? ", " + fmt(d.sum) : ""}`;
        p.append(t); p.addEventListener("click", () => arcClick(d));
        if (!grownOnce && !reduceMotion) {  // reveal the dotted line from Europe to Africa over 14 s
          const id = "rv" + Math.random().toString(36).slice(2, 8);
          const m = document.createElementNS(NS, "mask"); m.setAttribute("id", id); m.setAttribute("maskUnits", "userSpaceOnUse");
          m.setAttribute("x", "-5000"); m.setAttribute("y", "-5000"); m.setAttribute("width", "10000"); m.setAttribute("height", "10000");
          const mp = document.createElementNS(NS, "path"); mp.setAttribute("d", p.getAttribute("d")); mp.setAttribute("class", "reveal");
          mp.setAttribute("pathLength", "1"); m.append(mp); gArcs.append(m); p.setAttribute("mask", `url(#${id})`);
        }
        gArcs.append(p);
      }
    },
    pins(origins, dests) {
      pinLayer.innerHTML = ""; pins = [];
      for (const d of origins.concat(dests)) { const node = pinElement(d); node.classList.add("flat"); pinLayer.append(node); pins.push({d, node}); }
      placePins();
    },
    labels(list) {
      gLabels.innerHTML = "";
      for (const l of list) {
        const [x, y] = P(l.lng, l.lat); const t = document.createElementNS(NS, "text");
        t.setAttribute("x", x); t.setAttribute("y", y - 14); t.setAttribute("class", "cname"); t.textContent = l.name; gLabels.append(t);
      }
    },
    paint() {},
    focusOn(lat, lng) { const [x, y] = P(lng, lat); vb = {x: x - home.w / 6, y: y - home.h / 6, w: home.w / 3, h: home.h / 3}; fit(); },
    selfTest() { return true; },
    destroy() { ro.disconnect(); svg.remove(); pinLayer.remove(); }
  };
}

const modeBtn = document.getElementById("modebtn"), notice = document.getElementById("mapnotice");
let R = null, grownOnce = false;
function savedMode() { try { return localStorage.getItem("waemu-map-mode"); } catch (e) { return null; } }
function saveMode(m) { try { localStorage.setItem("waemu-map-mode", m); } catch (e) {} }
function start(mode, why) {
  if (R) R.destroy();
  try { R = mode === "3d" ? makeGlobe() : makeFlat(); }
  catch (e) { R = makeFlat(); why = why || "Your browser cannot draw the 3D globe, so the 2D map is shown."; }
  modeBtn.textContent = R.mode === "3d" ? "Switch to 2D map" : "Switch to 3D globe";
  notice.textContent = why || ""; notice.hidden = !why;
  R.paint(); update(false);
  if (R.mode === "3d") setTimeout(() => { if (R && R.mode === "3d" && !R.selfTest()) fallBack("The 3D globe did not display on this device, so the 2D map is shown."); }, 2500);
}
function fallBack(msg) { start("2d", msg); }
modeBtn.onclick = () => { const next = R && R.mode === "3d" ? "2d" : "3d"; saveMode(next); start(next); };

function arcTip(d) {
  return d.part
    ? `<div class="tip"><b>${esc(d.label)}</b> in ${esc(ccName(d.cc))}<br>${d.n} programme${d.n>1?"s":""}</div>`
    : `<div class="tip"><b>${esc(d.label)}</b> to ${esc(ccName(d.cc))}<br>${d.n} deal${d.n>1?"s":""}${d.sum ? ", " + fmt(d.sum) : ""}</div>`;
}
function arcClick(d) { state.focus = d.part ? {part:d.part, cc:d.cc} : {inst:d.inst, cc:d.cc}; update(); }
function styleArcs(arcs, sparse) { R.arcs(arcs, sparse); }
function setPins(origins) {
  const dests = Object.entries(CAPITALS).filter(([cc]) => state.cc.has(cc)).map(([cc,[city,lat,lng]]) => ({
    lat, lng, dest:true, color: css(fzVar(cc, "line")), text: "", title: `${city}, ${ccName(cc)}`,
    onclick: () => { state.focus = {cc}; update(); }}));
  R.pins(origins, dests);
  const MAPNAME = {CF: "Central African Rep.", CG: "Rep. of Congo", GQ: "Eq. Guinea"};  // shorter names on the map only
  const LABELPOS = {GQ: [1.0, 6.4], GA: [-2.6, 11.0], CG: [1.2, 16.6]};  // keep small neighbours' labels apart
  R.labels(Object.entries(DATA.countries).filter(([cc]) => state.cc.has(cc)).map(([cc,c]) => ({name: MAPNAME[cc] || c.name, lat: (LABELPOS[cc] || [c.lat])[0], lng: (LABELPOS[cc] || [0, c.lon])[1]})));
}

// ---------- investments view
function passInv(inv) {
  const ins = INST[inv.institution_id];
  if (!state.types.has(ins.type)) return false;
  if (state.ms && ins.member_state !== state.ms) return false;
  if (state.inst && inv.institution_id !== state.inst) return false;
  if (state.ins && inv.instrument !== state.ins) return false;
  if (state.yr && !(inv.year && +inv.year >= +state.yr)) return false;
  if (state.q && !norm(inv.title + " " + inv.client + " " + (SHORT[inv.institution_id] || "") + " " + ins.name).includes(state.q)) return false;
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
function countFilters() {
  let n = 0;
  if (state.view === "prog") { n += KINDS.length - state.kinds.size; if (state.part) n++; }
  else { n += TYPES.length - state.types.size; ["ms","inst","ins","yr"].forEach(k => state[k] && n++); if (state.view === "ana" && !state.est) n++; }
  n += Object.keys(DATA.countries).length - state.cc.size;
  document.getElementById("fcount").textContent = n ? `(${n} active)` : "";
}
function update(resetList = true) {
  if (resetList) state.shown = 40;
  countFilters();
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
  if (state.view === "ana") renderAnalysis(rows); else renderDeals(rows);
}
function renderDeals(rows) {
  const total = rows.reduce((s,[a]) => s + (a.amount_attributed_eur || 0), 0);
  const deals = new Set(rows.map(([,inv]) => inv.investment_id));
  const instN = new Set(rows.map(([,inv]) => inv.institution_id));
  document.getElementById("s-total").textContent = deals.size.toLocaleString("en") + " deal" + (deals.size === 1 ? "" : "s");
  let scope = "";
  if (state.q) scope += ` Matching "${document.getElementById("q").value.trim()}".`;
  if (state.focus) scope += " Showing " + [state.focus.inst ? (SHORT[state.focus.inst] || INST[state.focus.inst].name) : "", state.focus.cc ? "in " + ccName(state.focus.cc) : ""].filter(Boolean).join(" ") + ".";
  const unk = rows.filter(([a]) => a.amount_attributed_eur == null).length;
  document.getElementById("s-text").textContent = `${fmt(total)} from ${instN.size} institution${instN.size === 1 ? "" : "s"} in this selection.` + scope +
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
  if (!list.length) { box.innerHTML = `<p class="deal">No deals match these filters${state.q ? " and search" : ""}. Try another search term, widen the year range or turn an institution type back on.</p>`; return; }
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

// ---------- analysis view
function valueOf(a, inv) {
  if (!state.est && (a.attribution_method === "equal_split_estimate" || inv.amount_basis === "band estimate")) return 0;
  return a.amount_attributed_eur || 0;
}
function bars(items, colorOf) {
  const max = Math.max(1, ...items.map(x => x[1]));
  return items.map(([k, v, label]) => `<div class="bar" title="${esc(label || k)}: ${fmt(v)}"><span class="lbl">${esc(label || k)}</span>
    <span class="track"><i style="width:${(100 * v / max).toFixed(1)}%;background:${colorOf(k)}"></i></span><span class="val">${fmt(v)}</span></div>`).join("");
}
function rank(map, top) {
  const all = [...map.entries()].filter(x => x[1] > 0).sort((a, b) => b[1] - a[1]);
  if (top && all.length > top) { const rest = all.slice(top).reduce((s, x) => s + x[1], 0); return all.slice(0, top).concat([["Others", rest]]); }
  return all;
}
function columns(items, unit) {
  if (!items.length) return `<p class="hint">Nothing matches this combination.</p>`;
  const max = Math.max(1, ...items.map(x => x.v)), f = unit === "count" ? (v => String(Math.round(v))) : fmt;
  return `<div class="cols"><div class="yaxis"><span>${f(max)}</span><span>${f(max / 2)}</span><span>${unit === "count" ? "0" : "€0"}</span></div>
    <div class="plot">${items.map(x => `<div class="col" title="${esc(x.label)}: ${f(x.v)}${x.extra ? "\n" + esc(x.extra) : ""}"><i style="height:${(100 * x.v / max).toFixed(1)}%;background:${x.color}"></i></div>`).join("")}</div>
    <div class="xlabels">${items.map(x => `<span>${esc(x.label)}</span>`).join("")}</div></div>
    <p class="ylabel">${unit === "count" ? "Y axis: number of programmes (most programmes publish no amount). Hover a column for details." : "Y axis: euros committed. X axis: actors. Hover a column for details."}</p>`;
}
const MS_PALETTE = ["#3aa6ff","#ff8c42","#2dffc8","#ffd84a","#b77dff","#ff5ba0","#7be36b","#ffb43f","#5ad1ff","#e07bff","#c3ccd1","#ff7a6b","#9be7c4","#d2b48c"];
function stackedColumns(cols) {
  if (!cols.length) return `<p class="hint">Nothing matches this combination.</p>`;
  const max = Math.max(1, ...cols.map(c => c.total));
  return `<div class="cols"><div class="yaxis"><span>${fmt(max)}</span><span>${fmt(max / 2)}</span><span>€0</span></div>
    <div class="plot">${cols.map(c => `<div class="col" title="${esc(c.label)}: ${fmt(c.total)} from ${c.segs.length} actor${c.segs.length === 1 ? "" : "s"}\n${esc(c.segs.slice(0, 8).map(s => s.name + ": " + fmt(s.v)).join("\n"))}">
      <b class="cnt">${c.segs.length}</b>${c.segs.map(s => `<i style="height:${(100 * s.v / max).toFixed(2)}%;background:${s.color}"></i>`).join("")}</div>`).join("")}</div>
    <div class="xlabels sec">${cols.map(c => `<span>${esc(c.label)}</span>`).join("")}</div></div>
    <p class="ylabel">Y axis: euros committed. X axis: sectors. Coloured blocks are the actors investing in each sector; the number on top counts them. Hover a column for details.</p>`;
}
function renderAnalysis(rows) {
  const total = rows.reduce((s, [a, inv]) => s + valueOf(a, inv), 0);
  document.getElementById("s-total").textContent = fmt(total);
  document.getElementById("s-text").textContent = "Analysis of the investments that match your filters." + (state.est ? "" : " Estimated amounts are excluded.");
  const donors = new Map(), sectors = new Map(), ctry = new Map();
  for (const [a, inv] of rows) {
    const v = valueOf(a, inv); if (!v) continue;
    const ins = INST[inv.institution_id];
    const dk = state.donorBy === "inst" ? inv.institution_id : ins.member_state;
    donors.set(dk, (donors.get(dk) || 0) + v);
    sectors.set(inv.sector_broad, (sectors.get(inv.sector_broad) || 0) + v);
    ctry.set(a.country, (ctry.get(a.country) || 0) + v);
  }
  const donorItems = rank(donors, 14).map(([k, v]) => [k, v, k === "Others" ? "Others" : state.donorBy === "inst" ? (SHORT[k] || INST[k].name) : (MS[k] || k)]);
  const sectorList = DATA.sectors || [];
  if (!state.ovSector) state.ovSector = sectorList[0] || "";
  // overlap data
  let ov = [], unit = "eur";
  if (state.ovMode === "eu") {
    const m = new Map();
    for (const [a, inv] of rows) {
      if (inv.sector_broad !== state.ovSector || (state.ovCC && a.country !== state.ovCC)) continue;
      const v = valueOf(a, inv); if (!v) continue; m.set(inv.institution_id, (m.get(inv.institution_id) || 0) + v);
    }
    ov = [...m.entries()].sort((a, b) => b[1] - a[1]).map(([k, v]) => ({label: SHORT[k] || INST[k].name, v, color: css(typeVar[INST[k].type])}));
  } else if (state.ovMode === "prog") {
    unit = "count"; const m = new Map(), names = new Map();
    for (const p of PROG) {
      if (!p.sectors.includes(state.ovSector) || (state.ovCC && !p.countries.includes(state.ovCC))) continue;
      for (const part of p.participants) { m.set(part, (m.get(part) || 0) + 1); names.set(part, (names.get(part) || []).concat(p.name)); }
    }
    ov = [...m.entries()].sort((a, b) => b[1] - a[1]).map(([k, v]) => ({label: partName(k), v, color: css("--k-tei"), extra: names.get(k).join("; ")}));
  }
  let sectorCols = [], stackLegend = "";
  if (state.ovMode === "sector") {
    const by = new Map(), msIndex = {};
    for (const [a, inv] of rows) {
      if (state.ovCC && a.country !== state.ovCC) continue;
      const v = valueOf(a, inv); if (!v) continue;
      const ins = INST[inv.institution_id];
      const key = state.ovStack === "inst" ? inv.institution_id : ins.member_state;
      const m = by.get(inv.sector_broad) || new Map(); m.set(key, (m.get(key) || 0) + v); by.set(inv.sector_broad, m);
    }
    const colorOf = k => {
      if (state.ovStack === "inst") return css(typeVar[INST[k].type]);
      if (!(k in msIndex)) msIndex[k] = Object.keys(msIndex).length;
      return MS_PALETTE[msIndex[k] % MS_PALETTE.length];
    };
    sectorCols = [...by.entries()].map(([sec, m]) => {
      const segs = [...m.entries()].filter(x => x[1] > 0).sort((x, y) => y[1] - x[1])
        .map(([k, v]) => ({name: state.ovStack === "inst" ? (SHORT[k] || INST[k].name) : (MS[k] || k), v, color: colorOf(k)}));
      return {label: sec, total: segs.reduce((s, x) => s + x.v, 0), segs};
    }).sort((x, y) => y.total - x.total);
    if (state.ovStack === "ms") stackLegend = `<div class="stacklegend">${Object.entries(msIndex).map(([k, i]) => `<span><i style="background:${MS_PALETTE[i % MS_PALETTE.length]}"></i>${esc(MS[k] || k)}</span>`).join("")}</div>`;
    else stackLegend = `<div class="stacklegend">${TYPES.map(([, l, v]) => `<span><i style="background:var(${v})"></i>${l}</span>`).join("")}</div>`;
  }
  const ccOpts = `<option value="">All countries</option>` + Object.entries(DATA.countries).map(([cc, c]) => `<option value="${cc}"${state.ovCC === cc ? " selected" : ""}>${esc(c.name)}</option>`).join("");
  const secOpts = sectorList.map(s => `<option${s === state.ovSector ? " selected" : ""}>${esc(s)}</option>`).join("");
  if (state.ovMode === "non") {
    const m = new Map(), isNon = new Set();
    for (const [a, inv] of rows) {
      if (inv.sector_broad !== state.ovSector || (state.ovCC && a.country !== state.ovCC)) continue;
      const v = valueOf(a, inv); if (!v) continue; m.set(inv.institution_id, (m.get(inv.institution_id) || 0) + v);
    }
    for (const c of (DATA.comparators || [])) {
      if (c.s !== state.ovSector || (state.ovCC && c.c !== state.ovCC) || !state.cc.has(c.c)) continue;
      if (state.yr && !(c.y && +c.y >= +state.yr)) continue;
      if (state.ins && c.n !== state.ins) continue;
      m.set(c.i, (m.get(c.i) || 0) + c.v); isNon.add(c.i);
    }
    ov = [...m.entries()].sort((a, b) => b[1] - a[1]).map(([k, v]) => ({label: SHORT[k] || INST[k].name, v,
      color: isNon.has(k) ? css("--t-non") : css(typeVar[INST[k].type]), extra: isNon.has(k) ? "Non-EU actor" : ""}));
  }
  const seg = (key, opts) => `<div class="seg">${opts.map(([v, l, dis]) => `<button type="button" data-k="${key}" data-v="${v}" aria-pressed="${state[key] === v}"${dis ? " disabled title=\"Arrives with the next data update\"" : ""}>${l}</button>`).join("")}</div>`;
  document.getElementById("list").innerHTML = `<div class="ana">
    <section><h3>Donors by capital</h3><p class="hint">Euros attributed to the Franc Zone countries in your selection, ranked.</p>
      ${seg("donorBy", [["inst", "Institutions"], ["ms", "Member states"]])}
      ${bars(donorItems, k => k === "Others" ? css("--dim") : state.donorBy === "inst" ? css(typeVar[INST[k].type]) : css("--accent"))}</section>
    <section><h3>Sectors by investment</h3><p class="hint">Ten sectors aligned with the EU's Global Gateway priorities.</p>
      ${bars(rank(sectors), () => css("--accent"))}</section>
    <section><h3>Recipient countries by capital</h3>
      ${bars(rank(ctry).map(([k, v]) => [k, v, DATA.countries[k] ? DATA.countries[k].name : k]), k => css(fzVar(k, "line")))}</section>
    <section><h3>Investment overlap</h3><p class="hint">Where several actors put money or programmes into the same sector and country. Several tall columns mean overlapping effort.${state.ovMode === "non" ? " Grey columns are non-EU actors." : ""}</p>
      ${seg("ovMode", [["sector", "By sector"], ["eu", "EU actors"], ["prog", "Programmes by sector and goal"], ["non", "With non-EU actors"]])}
      ${state.ovMode === "sector" ? seg("ovStack", [["inst", "Stack by institution"], ["ms", "Stack by member state"]]) : ""}
      <div class="ov-controls"><select id="ov-cc" aria-label="Country">${ccOpts}</select>${state.ovMode === "sector" ? "" : `<select id="ov-sec" aria-label="Sector">${secOpts}</select>`}</div>
      ${state.ovMode === "sector" ? stackedColumns(sectorCols) + stackLegend : columns(ov, unit)}</section>
  </div>`;
  document.querySelectorAll(".ana .seg button").forEach(b => b.onclick = () => { state[b.dataset.k] = b.dataset.v; renderAnalysis(filtered()); });
  document.getElementById("ov-cc").onchange = e => { state.ovCC = e.target.value; renderAnalysis(filtered()); };
  const ovSec = document.getElementById("ov-sec");
  if (ovSec) ovSec.onchange = e => { state.ovSector = e.target.value; renderAnalysis(filtered()); };
}

// ---------- programmes view
function progFiltered() {
  return PROG.filter(p => state.kinds.has(p.kind)
    && p.countries.some(c => state.cc.has(c) && (!state.focus || !state.focus.cc || c === state.focus.cc))
    && (!state.part || p.participants.includes(state.part))
    && (!state.focus || !state.focus.part || p.participants.includes(state.focus.part))
    && (!state.q || norm(p.name + " " + p.description + " " + p.participants.map(partName).join(" ")).includes(state.q)));
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
  if (!progs.length) { box.innerHTML = `<p class="deal">No programmes match these filters${state.q ? " and search" : ""}. Try another search term, turn a programme kind back on or select more countries.</p>`; return; }
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

start(savedMode() === "2d" ? "2d" : "3d");
})();
</script>
</body>
</html>
'''

if __name__ == "__main__":
    main(sys.argv[1:] or FETCH_STEPS + ["normalize", "build"])
