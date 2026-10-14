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
