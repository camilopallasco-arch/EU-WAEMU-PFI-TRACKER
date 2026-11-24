"""EU-CFA Network tracker: network, overlap and events views built from the EU-CFA Public finance tracker's data.

Run:  python network.py
Reads the tracker's data (TRACKER_DATA_URL below, or data/tracker.json) and data/events.csv; writes site/index.html.
"""
import csv, json, re, pathlib, urllib.request, datetime, unicodedata, collections

# ---------------------------------------------------------------- settings you can edit
# Address of your EU-CFA Public finance tracker website, for example "https://yourname.github.io/EU-WAEMU-PFI-TRACKER/".
# This one setting connects the two sites: the network then reads the tracker's own data file (published next to its page)
# at every build, so both sites always show the same totals.
TRACKER_SITE_URL = ""
# Optional: a different address for the tracker's data file. Leave empty to use TRACKER_SITE_URL + "tracker.json".
TRACKER_DATA_URL = ""

ROOT = pathlib.Path(__file__).resolve().parent
# Placed in the tracker's repository (next to tracker.py), the network is built in the same run from the tracker's own data
# and published at the tracker's address + "network/": always in sync, nothing to configure.
IN_TRACKER = (ROOT / "tracker.py").exists() and (ROOT / "data" / "tracker.json").exists()
if IN_TRACKER:
    DATA, SITE, REF = ROOT / "data" / "network", ROOT / "site" / "network", ROOT / "ref" / "network"
    TRACKER_FILE = ROOT / "data" / "tracker.json"
else:
    DATA, SITE, REF = ROOT / "data", ROOT / "site", ROOT / "ref"
    TRACKER_FILE = DATA / "tracker.json"
for d in (DATA, SITE, REF):
    d.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (EU-CFA network tracker)"}
TODAY = datetime.date.today()
warnings = []

# ---------------------------------------------------------------- 1. load the tracker's data
def get(url, timeout=120):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()

DATA_URL = "" if IN_TRACKER else (TRACKER_DATA_URL or (TRACKER_SITE_URL.rstrip("/") + "/tracker.json" if TRACKER_SITE_URL else ""))
data_status = "live" if IN_TRACKER else "saved"          # "live" when this build reads the tracker's current data
if IN_TRACKER:
    print("built inside the tracker repository from", TRACKER_FILE)
elif DATA_URL:
    try:
        raw = get(DATA_URL)
        json.loads(raw)
        (DATA / "tracker.json").write_bytes(raw)
        data_status = "live"
        print("downloaded tracker data from", DATA_URL)
    except Exception as e:
        warnings.append(f"Could not download the tracker data from {DATA_URL} ({e}); the last saved copy is used, so totals may differ from the tracker.")
else:
    warnings.append("Not connected to the tracker: set TRACKER_SITE_URL in network.py. Until then a saved copy of the tracker data is used, so totals may differ from the tracker.")
if not TRACKER_FILE.exists():
    raise SystemExit("No tracker data: set TRACKER_DATA_URL in network.py or upload data/tracker.json")

# ---------------------------------------------------------------- 1b. synchronisation with the tracker
# The automation checks every day. A scheduled check rebuilds only if the tracker's data has changed since the last build
# (or the last build is more than 31 days old, to refresh the AFD contracts, EBRD pages and event links).
# A commit or a manual run always rebuilds.
import hashlib, os, sys
_state = DATA / "last_build.json"
_hash = hashlib.sha256(TRACKER_FILE.read_bytes()).hexdigest()
_prev = json.load(open(_state)) if _state.exists() else {}
_age = (TODAY - datetime.date.fromisoformat(_prev["built"])).days if _prev.get("built") else 999
if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and _prev.get("hash") == _hash and _age < 31 and (SITE / "index.html").exists():
    print(f"Tracker data unchanged since the last build ({_prev.get('generated')}); nothing to rebuild.")
    sys.exit(0)
T = json.load(open(TRACKER_FILE, encoding="utf-8"))
generated = T.get("generated", "")

# ---------------------------------------------------------------- 2. scope: EU public financial institutions and EU-financed World Bank trust funds
INCLUDED_TYPES = {"DFI", "Bilateral development bank", "NPB", "ECA", "EU institution", "World Bank trust fund", "Multilateral"}
EBRD_EU_SHARE = 0.544   # EU (3.03%), EIB (3.03%) and EU27 member states (ca. 48.4%): European Commission, COM(2024)42
EBRD_SHARE_SRC = "https://eumonitor.eu/9353000/1/j4nvirkkkr58fyw_j9vvik7m1c3gyxp/vma3gbgih4zm"
INST = {i["institution_id"]: i for i in T["institutions"] if i["type"] in INCLUDED_TYPES}
COUNTRIES = T["countries"]
MS_NAMES = {"FR": "France", "DE": "Germany", "NL": "Netherlands", "BE": "Belgium", "FI": "Finland", "DK": "Denmark", "SE": "Sweden",
            "AT": "Austria", "ES": "Spain", "IT": "Italy", "PT": "Portugal", "PL": "Poland", "CZ": "Czechia", "SK": "Slovakia",
            "HR": "Croatia", "GR": "Greece", "SI": "Slovenia", "HU": "Hungary", "RO": "Romania", "BG": "Bulgaria", "EE": "Estonia",
            "LV": "Latvia", "LT": "Lithuania", "IE": "Ireland", "LU": "Luxembourg", "EU": "European Union", "WBTF": "World Bank trust funds"}
inv_by_id = {i["investment_id"]: i for i in T["investments"] if i["institution_id"] in INST}

# deals with their Franc Zone allocations
deals = {}
for a in T["allocations"]:
    inv = inv_by_id.get(a["investment_id"])
    if not inv:
        continue
    d = deals.setdefault(inv["investment_id"], {"id": inv["investment_id"], "i": inv["institution_id"], "t": inv["title"][:160],
                                                "y": inv.get("year") or "", "n": inv.get("instrument", ""), "s": inv.get("sector_broad", ""),
                                                "u": inv.get("source_url", ""), "g": inv.get("impl_agency", ""), "gm": inv.get("impl_ms", ""), "v": 0.0, "c": [], "e": False})
    d["v"] += a.get("amount_attributed_eur") or 0
    d["c"].append(a["country"])
    if a.get("attribution_method") == "equal_split_estimate":
        d["e"] = True
deals = {k: v for k, v in deals.items()}

# ---------------------------------------------------------------- 2b. EBRD: which projects involve EU or member-state money (from the EBRD's project summary pages)
EU_ACTORS = [("eu-intpa", r"European Union|\bEU\b|EU's|Africa Investment Platform|\bAIP\b|EFSD|Global Gateway|European Commission|Team Europe"),
             ("eib", r"European Investment Bank|\bEIB\b"), ("afd", r"Agence Fran[cç]aise|\bAFD\b"), ("proparco", r"Proparco"),
             ("kfw-db", r"\bKfW\b"), ("deg", r"\bDEG\b"), ("fmo", r"\bFMO\b"), ("bio", r"\bBIO\b"), ("finnfund", r"Finnfund"),
             ("swedfund", r"Swedfund"), ("ifu", r"\bIFU\b|Impact Fund Denmark"), ("cofides", r"COFIDES"), ("oeeb", r"OeEB")]
MONEY = re.compile(r"co-?financ|grant|loan|fund|financ|guarantee|provided|contribut|blend|investment from|support from|alongside|parallel", re.I)
STANDARD_ONLY = re.compile(r"Directive|Taxonomy|Best Available|in line with the requirements|EU standards|EU requirements|EU regulation", re.I)
psd_cache = DATA / "ebrd_psd.json"
psd = json.load(open(psd_cache, encoding="utf-8")) if psd_cache.exists() else {}
def html_text(s):
    return re.sub(r"\s+", " ", re.sub("<[^>]+>", " ", re.sub(r"<script.*?</script>|<style.*?</style>", "", s, flags=re.S)))
for d in deals.values():
    if d["i"] != "ebrd":
        continue
    m = re.search(r"EBRD-(\d+)", d["id"])
    if not m:
        continue
    pid = m.group(1)
    try:
        t = html_text(get(f"https://www.ebrd.com/work-with-us/projects/psd/{pid}.html", 60).decode("utf-8", "replace"))
        import html as _h
        t = _h.unescape(t)
        start = t.find("Project Description")            # read only the project's own text, not the site's menus
        t = t[start:] if start >= 0 else ""
        found = {}
        for sent in re.split(r"(?<=[.;])\s+", t):
            if len(sent) > 450 or not MONEY.search(sent) or STANDARD_ONLY.search(sent):
                continue
            for iid, rx in EU_ACTORS:
                if re.search(rx, sent) and iid not in found:
                    found[iid] = sent.strip()[:320]
        psd[pid] = {"url": f"https://www.ebrd.com/work-with-us/projects/psd/{pid}.html", "eu": found, "checked": TODAY.isoformat()}
    except Exception as e:
        warnings.append(f"EBRD project page {pid} could not be read ({e}); the last saved reading is used.")
    if pid in psd:
        d["eu"] = psd[pid]["eu"]; d["psd"] = psd[pid]["url"]
json.dump(psd, open(psd_cache, "w", encoding="utf-8"), ensure_ascii=False, indent=0)

# ---------------------------------------------------------------- 3. network: nodes and weighted links
nodes, links = {}, collections.defaultdict(lambda: {"v": 0.0, "n": 0})
def node(nid, kind, label, **kw):
    if nid not in nodes:
        nodes[nid] = {"id": nid, "k": kind, "l": label, "v": 0.0, **kw}
    return nodes[nid]
for d in deals.values():
    ins = INST[d["i"]]
    node("i:" + d["i"], "institution", ins["name"], t=ins["type"], ms=ins["member_state"])
    nodes["i:" + d["i"]]["v"] += d["v"]
    share = d["v"] / max(1, len(d["c"]))
    for cc in d["c"]:
        node("c:" + cc, "country", COUNTRIES[cc]["name"], u=COUNTRIES[cc].get("union", ""))
        nodes["c:" + cc]["v"] += share
        l = links[("i:" + d["i"], "c:" + cc)]; l["v"] += share; l["n"] += 1
    if d["s"]:
        node("s:" + d["s"], "sector", d["s"])
        nodes["s:" + d["s"]]["v"] += d["v"]
        l = links[("i:" + d["i"], "s:" + d["s"])]; l["v"] += d["v"]; l["n"] += 1
    if d["g"] and ins["type"] == "EU institution":  # EU money entrusted to an implementing agency
        node("a:" + d["g"], "agency", d["g"], ms=d.get("gm", ""))
        nodes["a:" + d["g"]]["v"] += d["v"]
        l = links[("i:" + d["i"], "a:" + d["g"])]; l["v"] += d["v"]; l["n"] += 1
for nid, n in list(nodes.items()):
    if n["k"] == "institution" and n.get("ms"):
        owner = "EU" if n["ms"] in ("WBTF", "INT") else n["ms"]   # World Bank trust funds and the EBRD hang off the EU, not a separate ball
        node("m:" + owner, "memberstate", MS_NAMES.get(owner, owner))
        share = EBRD_EU_SHARE if n["ms"] == "INT" else 1.0          # the EBRD: only the EU-held share of its capital (54.4%)
        nodes["m:" + owner]["v"] += n["v"] * share
        l = links[("m:" + owner, nid)]; l["v"] += n["v"] * share; l["n"] += 1
        if n["ms"] == "INT":
            l["own"] = round(EBRD_EU_SHARE * 100, 1)
# each implementing agency belongs to a member state: a "belongs to" link without amount (the money it implements is EU money)
for nid, n in list(nodes.items()):
    if n["k"] == "agency" and n.get("ms") and n["ms"] != "EU":
        node("m:" + n["ms"], "memberstate", MS_NAMES.get(n["ms"], n["ms"]))
        links[("m:" + n["ms"], nid)]["n"] += 1
# EBRD co-financing: a dashed link to each EU institution its project pages name as a source of money
for d in deals.values():
    for iid in (d.get("eu") or {}):
        if ("i:" + iid) in nodes and "i:ebrd" in nodes:
            l = links[("i:ebrd", "i:" + iid)]; l["n"] += 1; l["co"] = True
# frameworks (programmes): participants and countries, no amounts added up
for p in T.get("programmes", []):
    fid = "f:" + p["programme_id"]
    parts = [("i:" + x) if ("i:" + x) in nodes else ("m:" + x) if ("m:" + x) in nodes else None for x in p["participants"]]
    parts = [x for x in parts if x]
    ccs = ["c:" + c for c in p["countries"] if ("c:" + c) in nodes]
    if not parts or not ccs:
        continue
    node(fid, "framework", p["name"][:90], fk=p["kind"], src=p.get("source_url", ""))
    for x in parts:
        links[(x, fid)]["n"] += 1
    for c in ccs:
        links[(fid, c)]["n"] += 1

# euros each country receives per sector (shown when a country is clicked)
csec = collections.defaultdict(lambda: collections.defaultdict(float))
for d in deals.values():
    if d["s"]:
        for cc in d["c"]:
            csec[cc][d["s"]] += d["v"] / max(1, len(d["c"]))
csec = {cc: {k: round(v) for k, v in sorted(m.items(), key=lambda x: -x[1]) if v > 0} for cc, m in csec.items()}

# ---------------------------------------------------------------- 3b. contractors: European firms that won AFD-financed contracts
# Source: AFD open data, "Liste des marchés financés par l'AFD avec la participation financière de l'Union européenne"
AFD_CONTRACTS = ("https://opendata.afd.fr/api/explore/v2.1/catalog/datasets/"
                 "liste-des-marches-finances-par-lafd-avec-la-participation-financiere-de-lunion-e/exports/json?limit=-1")
try:
    raw = get(AFD_CONTRACTS)
    json.loads(raw)
    (DATA / "afd_contracts.json").write_bytes(raw)
except Exception as e:
    warnings.append(f"Could not download AFD's contract list ({e}); the last saved copy is used.")
EU_NAT = {"FRANCE": "FR", "FRANCAISE": "FR", "ALLEMAGNE": "DE", "ALLEMANDE": "DE", "BELGIQUE": "BE", "BELGE": "BE", "ESPAGNE": "ES", "ESPAGNOLE": "ES",
          "ITALIE": "IT", "ITALIENNE": "IT", "PORTUGAL": "PT", "PORTUGAISE": "PT", "PAYS-BAS": "NL", "PAYS BAS": "NL", "NEERLANDAISE": "NL",
          "LUXEMBOURG": "LU", "LUXEMBOURGEOISE": "LU", "AUTRICHE": "AT", "AUTRICHIENNE": "AT", "DANEMARK": "DK", "DANOISE": "DK", "SUEDE": "SE",
          "SUEDOISE": "SE", "FINLANDE": "FI", "FINLANDAISE": "FI", "IRLANDE": "IE", "IRLANDAISE": "IE", "GRECE": "GR", "GRECQUE": "GR",
          "POLOGNE": "PL", "POLONAISE": "PL", "REPUBLIQUE TCHEQUE": "CZ", "TCHEQUIE": "CZ", "SLOVAQUIE": "SK", "HONGRIE": "HU", "ROUMANIE": "RO",
          "BULGARIE": "BG", "CROATIE": "HR", "SLOVENIE": "SI", "ESTONIE": "EE", "LETTONIE": "LV", "LITUANIE": "LT", "CHYPRE": "CY", "MALTE": "MT"}
FZ_NAMES = [("BJ", r"benin"), ("BF", r"burkina"), ("CI", r"cote d.?ivoire"), ("GW", r"guinee[- ]bissau"), ("ML", r"\bmali\b"), ("NE", r"\bniger\b"),
            ("SN", r"senegal"), ("TG", r"\btogo\b"), ("CM", r"cameroun"), ("CF", r"centrafrique|centrafricaine"), ("TD", r"tchad"),
            ("GQ", r"guinee equatoriale"), ("GA", r"gabon"), ("CG", r"\bcongo\b")]
def plain(t):
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().upper().strip()
def fz_code(country):
    c = plain(country).lower()
    if re.search(r"democratique|\brdc\b|kinshasa|conakry", c):
        return None
    if re.fullmatch(r"\s*guinee\s*", c):
        return None
    for cc, rx in FZ_NAMES:
        if re.search(rx, c):
            return cc
    return None
def contract_date(t):
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t or "") or None
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", t or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""
# European parent groups: subsidiaries and brand names that appear in contract awards -> (group, member state)
PARENTS = [(r"EIFFAGE|CLEMESSY", "Eiffage", "FR"), (r"SOGEA|SATOM|VINCI|EUROVIA|CEGELEC|OMEXOM|ENTREPOSE", "Vinci (Sogea-Satom)", "FR"),
           (r"\bSUEZ\b|DEGREMONT", "Suez", "FR"), (r"VEOLIA|\bOTV\b|\bSADE\b", "Veolia", "FR"), (r"BOUYGUES|\bCOLAS\b|\bETDE\b", "Bouygues (Colas)", "FR"),
           (r"RAZEL|FAYAT", "Fayat (Razel-Bec)", "FR"), (r"\bENGIE\b|COFELY|INEO", "Engie", "FR"), (r"\bSPIE\b", "Spie", "FR"),
           (r"SCHNEIDER", "Schneider Electric", "FR"), (r"SAGEMCOM", "Sagemcom", "FR"), (r"VERGNET", "Vergnet", "FR"), (r"\bEGIS\b", "Egis", "FR"),
           (r"ARTELIA", "Artelia", "FR"), (r"\bSETEC\b", "Setec", "FR"), (r"\bBRL\b", "BRL Ingénierie", "FR"), (r"BOLLORE", "Bolloré", "FR"),
           (r"\bRMT\b", "RMT Industrie & Elektrotechnik", "DE"), (r"SIEMENS", "Siemens", "DE"), (r"STRABAG", "Strabag", "AT"),
           (r"BESIX", "Besix", "BE"), (r"JAN DE NUL", "Jan De Nul", "BE"), (r"\bDEME\b", "DEME", "BE"), (r"TRACTEBEL", "Tractebel (Engie)", "BE"),
           (r"BOSKALIS", "Boskalis", "NL"), (r"VAN OORD", "Van Oord", "NL"), (r"HASKONING", "Royal HaskoningDHV", "NL"), (r"ARCADIS", "Arcadis", "NL"),
           (r"\bSENER\b", "Sener", "ES"), (r"ELECNOR", "Elecnor", "ES"), (r"ISOLUX", "Isolux Corsán", "ES"),
           (r"SALINI|WEBUILD|IMPREGILO", "Webuild", "IT"), (r"GHELLA", "Ghella", "IT"), (r"MOTA[- ]ENGIL", "Mota-Engil", "PT")]
def contract_members(name, eu_ms, plain):
    """Split a consortium name into its partners; return ([(group, member state), ...], number of partners).
    Partners found in PARENTS get their group and nationality; a single firm not in PARENTS keeps its name and the dataset's nationality."""
    clean = re.sub(r"\b(GROUPEMENT|GPT|CONSORTIUM|JOINT VENTURE|JV)\b\s*:?", " ", plain(name))
    parts = [p.strip() for p in re.split(r"\s*/\s*|\s+\+\s+|\s+-\s+|;|\s+ET\s+", clean) if p.strip()]
    found = []
    for p in parts:
        hit = next(((g, m) for rx, g, m in PARENTS if re.search(rx, p)), None)
        if hit and hit not in found:
            found.append(hit)
    if found:
        return found, max(len(parts), len(found))
    return [(re.sub(r"\s+", " ", name.strip())[:90], eu_ms)], 1

contracts = []
cpath = DATA / "afd_contracts.json"
if cpath.exists():
    for r in json.load(open(cpath, encoding="utf-8")):
        cc = fz_code(r.get("pays_beneficiaire"))
        if not cc:
            continue
        nats = [p.strip() for p in re.split(r"[/,;]| ET | - ", plain(r.get("nationalite_de_l_attributaire")))]
        ms = next((EU_NAT[p] for p in nats if p in EU_NAT), None)
        if not ms:
            continue
        try:
            k = float(r.get("montant_en_keur") or 0)
        except ValueError:
            k = 0
        # The column is in thousand euros, but some services were entered in euros: a study or technical assistance
        # worth tens of millions is implausible. Such amounts are read as euros and flagged.
        what = plain((r.get("nature_et_finalite_du_marche") or "") + " " + (r.get("titre_du_contrat_marche_titre_du_projet") or "")).lower()
        service = re.search(r"etude|study|assistance|appui|support|preparation|avant-projet|structuration|coordination|tor\b|termes de reference|"
                            r"capacit|roadmap|formation|conseil|expertise|audit|evaluation|supervision|controle|maitrise d.oeuvre|analyse|capitalisation|diagnostic|"
                            r"cartographie|recherche|communication|animation|accompagnement", what)
        flagged = k > 100000 or (k > 10000 and bool(service))
        eur = k if flagged else k * 1000
        firm = re.sub(r"\s+", " ", (r.get("nom_de_l_attributaire") or "").strip())
        contracts.append({"f": firm[:90], "ms": ms, "nat": (r.get("nationalite_de_l_attributaire") or "").strip()[:40], "c": cc,
                          "p": (r.get("titre_du_contrat_marche_titre_du_projet") or "")[:140], "o": (r.get("nature_et_finalite_du_marche") or "")[:160],
                          "d": contract_date(r.get("date_signature_du_contrat")), "v": round(eur), "flag": flagged, "proj": r.get("id_projet") or ""})
    flagged_n = sum(1 for c in contracts if c["flag"])
    if flagged_n:
        warnings.append(f"AFD contract list: {flagged_n} amount(s) in the 'thousand euro' column were read as euros (studies or technical assistance entered in euros, or values above 100,000); each is flagged in the contractor's panel.")
# contractor nodes: one per firm, linked to AFD (financier), to the country of the contract and to the firm's member state
firm_key = lambda f: "x:" + re.sub(r"[^a-z0-9]+", "-", plain(f).lower()).strip("-")[:60]
for ct in contracts:
    members, n_parts = contract_members(ct["f"], ct["ms"], plain)
    ct["g"] = [[g, m] for g, m in members]; ct["share"] = round(1 / n_parts, 4); ct["parts"] = n_parts
    for g, m in members:
        fid = firm_key(g)
        node(fid, "contractor", g, ms=m)
        val = ct["v"] / n_parts
        nodes[fid]["v"] += val
        if "i:afd" in nodes:
            l = links[("i:afd", fid)]; l["v"] += val; l["n"] += 1
        if ("c:" + ct["c"]) in nodes:
            l = links[(fid, "c:" + ct["c"])]; l["v"] += val; l["n"] += 1
for nid, n in list(nodes.items()):
    if n["k"] == "contractor" and n.get("ms"):
        node("m:" + n["ms"], "memberstate", MS_NAMES.get(n["ms"], n["ms"]))
        links[("m:" + n["ms"], nid)]["n"] += 1

# ---------------------------------------------------------------- 4. overlap: shared countries and sectors, co-financed projects
cs = collections.defaultdict(lambda: collections.defaultdict(float))  # institution -> (country, sector) -> euros
for d in deals.values():
    for cc in d["c"]:
        cs[d["i"]][(cc, d["s"])] += d["v"] / max(1, len(d["c"]))
top = sorted(cs, key=lambda i: -sum(cs[i].values()))[:24]
matrix = []
for a in top:
    row = []
    for b in top:
        if a == b:
            row.append(round(sum(cs[a].values())))
        else:
            row.append(round(sum(min(v, cs[b].get(k, 0)) for k, v in cs[a].items() if k in cs[b])))
    matrix.append(row)
# overlap %: share of the country-sector combinations where at least one of the two is active in which both are active
cells = collections.defaultdict(set)   # institution -> {(country, sector)}, counting deals whose amounts are not published too
for d in deals.values():
    for cc in d["c"]:
        cells[d["i"]].add((cc, d["s"]))
mjac, mco, pairn = [], [], {}
co_pairs = collections.Counter()
for a in top:
    row = []
    for b in top:
        if a == b:
            row.append(100)
        else:
            inter, union = len(cells[a] & cells[b]), len(cells[a] | cells[b])
            row.append(round(100 * inter / union) if union else 0)
            pairn[f"{a}|{b}"] = [inter, union]
    mjac.append(row)
pair_detail = {}
for ai, a in enumerate(top):
    for bi, b in enumerate(top):
        if bi <= ai:
            continue
        shared = [(k, cs[a][k], cs[b][k]) for k in cs[a] if k in cs[b] and cs[a][k] > 0 and cs[b][k] > 0]
        shared.sort(key=lambda x: -min(x[1], x[2]))
        if shared:
            pair_detail[f"{a}|{b}"] = [[k[0], k[1], round(x), round(y)] for k, x, y in shared[:25]]

STOP = set("""projet project programme program programa support appui appuis renforcement strengthening financement financing development developpement
du des les la le de et pour and the for of in au aux en dans sur with par loan pret grant investment investissement phase facility fund fonds
national nationale regional services service capacite capacity sector secteur public publique additional additionnel contrat convention
contribution agreement tranche force mise oeuvre urgence budgetaire budget sectoriel sectoriels activity under preparation assistance technique
technical emergency corona covid jeunesse youth formation professionnelle insertion women femmes gestion management access acces
objectifs durable sustainable flagship initiative""".split())
# place names: shared place names say nothing about a shared project
PLACES = set("""africa afrique ouest west central centrale sahel ghana nigeria guinee guinea mauritanie mauritania gambie gambia liberia sierra leone
dakar abidjan bamako ouagadougou niamey cotonou porto novo lome bissau yaounde douala bangui ndjamena brazzaville pointe noire libreville malabo kribi
kayes koulikoro sikasso segou mopti tombouctou timbuktu kidal menaka taoudeni tillaberi tahoua maradi zinder dosso agadez diffa sahel kaya bobo dioulasso
koudougou boucle mouhoun centre nord sud est ziguinchor casamance thies kaolack saint louis tambacounda matam kolda sedhiou kedougou fatick louga
diourbel kaffrine yamoussoukro bouake korhogo daloa san pedro man atlantique borgou alibori atacora donga zou collines mono couffo plateau oueme
kara savanes maritime centrale extreme garoua maroua ngaoundere bertoua ebolowa bamenda buea logone chari ouaddai kanem moyen ogooue franceville
port gentil oyem""".split())
def toks(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return {w for w in re.findall(r"[a-z]{4,}", t) if w not in STOP and w not in PLACES}
country_words = {w for c in COUNTRIES.values() for w in toks(c["name"])}
df = collections.Counter(w for d in deals.values() for w in toks(d["t"]))
by_cc = collections.defaultdict(list)
for d in deals.values():
    if d["v"] > 0:
        for cc in d["c"]:
            by_cc[cc].append(d)
# a pair of deals from different institutions is a candidate when, in the same country and within three years,
# their titles share one very distinctive word (a dam, railway or company name) or two distinctive words.
groups = collections.defaultdict(dict)   # (country, key word) -> {deal id: deal}
evidence = collections.defaultdict(set)
for cc, ds in by_cc.items():
    for x in range(len(ds)):
        for y in range(x + 1, len(ds)):
            p, q = ds[x], ds[y]
            if p["i"] == q["i"]:
                continue
            if p["y"] and q["y"] and abs(int(p["y"]) - int(q["y"])) > 3:
                continue
            shared = (toks(p["t"]) & toks(q["t"])) - country_words
            rare = sorted((w for w in shared if df[w] <= 5 and len(w) >= 6), key=lambda w: df[w])
            fairly = [w for w in shared if df[w] <= 15]
            if not rare and len(fairly) < 2:
                continue
            key = (cc, rare[0] if rare else " ".join(sorted(fairly)[:2]))
            groups[key][p["id"]] = p; groups[key][q["id"]] = q
            evidence[key].update(rare or fairly)
cofin = []
for key, members in groups.items():
    ms = sorted(members.values(), key=lambda d: -d["v"])
    if len({m["i"] for m in ms}) < 2 or len(ms) > 10:
        continue
    cofin.append({"w": sorted(evidence[key])[:5], "c": [key[0]],
                  "m": [[m["i"], m["t"], m["y"], round(m["v"]), m["u"]] for m in ms], "v": round(sum(m["v"] for m in ms))})
# the same project can surface under two key words: keep one entry per set of deals
seen_sets, uniq = set(), []
for c in sorted(cofin, key=lambda x: -x["v"]):
    sig = frozenset(m[1] + m[0] for m in c["m"])
    if sig in seen_sets:
        continue
    seen_sets.add(sig); uniq.append(c)
cofin = uniq
co_count = collections.Counter()
for c in cofin:
    ins = sorted({m[0] for m in c["m"]})
    for x in range(len(ins)):
        for y in range(x + 1, len(ins)):
            co_count[(ins[x], ins[y])] += 1
mco = [[0 if a == b else co_count.get(tuple(sorted((a, b))), 0) for b in top] for a in top]

# ---------------------------------------------------------------- 4b. monthly review: the deals each tracker update added
# The network compares this version of the tracker's data with the previous one it saw, and records the new deals.
known_path, review_path = DATA / "known_deals.json", DATA / "monthly_review.json"
review = json.load(open(review_path, encoding="utf-8")) if review_path.exists() else []
SEED_KNOWN = "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"   # deals already known on 2026-10-27
import zlib as _zlib, base64 as _b64
known = json.load(open(known_path, encoding="utf-8")) if known_path.exists() else json.loads(_zlib.decompress(_b64.b64decode(SEED_KNOWN)))
current_ids = sorted(deals)
if known is None:
    review.append({"generated": generated, "baseline": True, "n": len(current_ids), "total": round(sum(d["v"] for d in deals.values()))})
elif known.get("generated") != generated:
    new = [deals[i] for i in set(current_ids) - set(known.get("ids", []))]
    new.sort(key=lambda d: -d["v"])
    review = [r for r in review if r.get("generated") != generated]
    review.append({"generated": generated, "baseline": False, "n": len(new), "total": round(sum(d["v"] for d in new)),
                   "top": [[d["i"], d["t"], d["c"], d["y"], round(d["v"]), d["u"], d["n"], d["s"]] for d in new[:15]],
                   "since": known.get("generated", "")})
json.dump({"generated": generated, "ids": current_ids}, open(known_path, "w"))
json.dump(review, open(review_path, "w", encoding="utf-8"), ensure_ascii=False)

# ---------------------------------------------------------------- 5. timeline: yearly commitments by type and by country
years = list(range(1999, TODAY.year + 1))
series = collections.defaultdict(lambda: collections.defaultdict(float))
for d in deals.values():
    if not d["y"] or not d["y"].isdigit() or int(d["y"]) < 1999:
        continue
    t = INST[d["i"]]["type"]
    share = d["v"] / max(1, len(d["c"]))
    for cc in d["c"]:
        series["ALL|" + t][int(d["y"])] += share
        series[cc + "|" + t][int(d["y"])] += share
timeline = {k: [round(v.get(y, 0)) for y in years] for k, v in series.items()}

# ---------------------------------------------------------------- 6. events (data/events.csv), with a source check
events = []
EVENTS_DEFAULT = r'''date,end_date,status,category,countries,title,description,source_url
1999-01-01,,past,Monetary,ALL,"CFA francs pegged to the euro","The West African (XOF) and Central African (XAF) CFA francs move from the French franc to a fixed euro peg at the same rate, guaranteed by the French Treasury.",https://en.wikipedia.org/wiki/CFA_franc
2000-04-03,2000-04-04,past,EU–Africa policy,ALL,"First Africa–EU Summit (Cairo)","First summit of European and African heads of state and government.",https://en.wikipedia.org/wiki/Africa-EU_Summit
2000-06-23,,past,EU–Africa policy,ALL,"Cotonou Agreement signed","Twenty-year partnership agreement between the EU and the ACP states, framing European Development Fund aid and EIB lending.",https://en.wikipedia.org/wiki/Cotonou_Agreement
2007-12-08,2007-12-09,past,EU–Africa policy,ALL,"Second Africa–EU Summit (Lisbon) and Joint Africa-EU Strategy","Adoption of the Joint Africa-EU Strategy; the EU-Africa Infrastructure Trust Fund starts approving grants the same year.",https://en.wikipedia.org/wiki/Africa-EU_Summit
2015-11-12,,past,Financing instrument,ALL,"EU Emergency Trust Fund for Africa launched (Valletta)","Created at the Valletta summit on migration; its Sahel and Lake Chad window covers seven Franc Zone countries.",https://en.wikipedia.org/wiki/Valletta_Summit_on_Migration
2017-03-01,,past,Financing instrument,CI|SN,"Côte d'Ivoire and Senegal join the G20 Compact with Africa","Germany-initiated G20 initiative; Benin, Burkina Faso and Togo join in 2017–2018.",https://www.compactwithafrica.org/en/programs/g20-compact-with-africa
2017-11-29,2017-11-30,past,EU–Africa policy,ALL,"Fifth AU–EU Summit (Abidjan)","Summit hosted in Côte d'Ivoire, focused on youth and investment.",https://en.wikipedia.org/wiki/Africa-EU_Summit
2019-12-21,,past,Monetary,BJ|BF|CI|GW|ML|NE|SN|TG,"Reform of the West African CFA franc announced","France and the WAEMU announce the planned 'Eco', the end of the obligation to deposit half of reserves with the French Treasury and France's withdrawal from BCEAO governing bodies; the euro peg is kept.",https://en.wikipedia.org/wiki/Eco_(currency)
2020-08-18,,past,Politics & security,ML,"Coup d'état in Mali","President Ibrahim Boubacar Keïta is overthrown; a second coup follows in May 2021.",https://en.wikipedia.org/wiki/2020_Malian_coup_d%27%C3%A9tat
2021-05-24,,past,Politics & security,ML,"Second coup d'état in Mali","The transitional president and prime minister are arrested; Colonel Assimi Goïta takes power.",https://en.wikipedia.org/wiki/2021_Malian_coup_d%27%C3%A9tat
2021-12-01,,past,EU–Africa policy,ALL,"Global Gateway launched","The European Commission presents Global Gateway, a strategy to mobilise up to €300 billion for infrastructure worldwide by 2027.",https://ec.europa.eu/commission/presscorner/detail/en/ip_21_6433
2022-01-24,,past,Politics & security,BF,"Coup d'état in Burkina Faso (January)","President Roch Marc Christian Kaboré is overthrown; a second coup follows in September 2022.",https://en.wikipedia.org/wiki/January_2022_Burkina_Faso_coup_d%27%C3%A9tat
2022-02-17,2022-02-18,past,EU–Africa policy,ALL,"Sixth EU–AU Summit and Africa-Europe Investment Package","Brussels summit; the EU announces €150 billion for the Africa-Europe Investment Package, half of Global Gateway.",https://www.csis.org/analysis/global-gateways-infrastructure-plan-africa-announced-eu-au-summit
2022-09-30,,past,Politics & security,BF,"Second coup d'état in Burkina Faso","Captain Ibrahim Traoré takes power.",https://en.wikipedia.org/wiki/September_2022_Burkina_Faso_coup_d%27%C3%A9tat
2022-09-01,,past,Financing instrument,GW|GQ,"Lusophone Compact guarantee agreement","Portugal and the African Development Bank sign a guarantee of up to €400 million for private-sector projects in Portuguese-speaking African countries, including Guinea-Bissau and Equatorial Guinea.",https://clubofmozambique.com/news/afdb-and-portugal-sign-eur-400-million-guarantee-agreement-to-underpin-lusophone-compact/
2023-06-22,,past,Financing instrument,SN,"Senegal Just Energy Transition Partnership","International partners, including the EU, France and Germany, announce €2.5 billion to raise renewables in Senegal's power mix.",https://international-partnerships.ec.europa.eu/countries/senegal_en
2023-07-26,,past,Politics & security,NE,"Coup d'état in Niger","President Mohamed Bazoum is overthrown by the presidential guard led by General Abdourahamane Tiani.",https://en.wikipedia.org/wiki/2023_Nigerien_coup_d%27%C3%A9tat
2023-07-29,,past,EU–Africa policy,NE,"EU suspends budget support and security cooperation with Niger","The EU High Representative announces the immediate end of budget support and the indefinite suspension of security cooperation.",https://www.aljazeera.com/news/2023/7/29/blinken-offers-nigers-ousted-leader-bazoum-unflagging-support
2023-08-30,,past,Politics & security,GA,"Coup d'état in Gabon","President Ali Bongo Ondimba is overthrown after a disputed election; General Brice Oligui Nguema takes power.",https://en.wikipedia.org/wiki/2023_Gabonese_coup_d%27%C3%A9tat
2024-01-29,,past,Financing instrument,CI|CG,"Italy presents the Mattei Plan for Africa (Rome summit)","Italy's Africa strategy, delivered through CDP, SIMEST and SACE; Côte d'Ivoire and the Republic of the Congo are among the first priority countries.",https://www.ilviaggiomagazine.it/piano-mattei-sogno-o-realta-il-viceministro-cirielli-tracciata-la-strada-ora-velocizziamo-i-progetti/
2025-01-29,,past,Politics & security,BF|ML|NE,"Burkina Faso, Mali and Niger leave ECOWAS","The withdrawal of the three Sahel states, which have formed the Alliance of Sahel States, becomes effective.",https://www.aljazeera.com/amp/news/2025/1/29/military-governments-lead-west-african-trio-out-of-ecowas-regional-bloc
2025-11-24,2025-11-25,past,EU–Africa policy,ALL,"Seventh AU–EU Summit (Luanda)","Summit in Angola on connectivity, Global Gateway, debt sustainability and coordination with national plans such as Italy's Mattei Plan.",https://en.wikipedia.org/wiki/7th_European_Union%E2%80%93African_Union_Summit
2027-04-12,2027-04-18,upcoming,Summit / meeting,ALL,"IMF–World Bank Spring Meetings (Washington)","Finance ministers and central bankers, including those of the BCEAO and BEAC countries, meet on debt, concessional lending and development finance.",https://www.worldbank.org/en/meetings/splash/about
2027-06-08,2027-06-09,to be confirmed,Summit / meeting,ALL,"Third Global Gateway Forum (Brussels)","Announced for 8–9 June 2027; the EU's investment target is reported to rise to €400 billion. No official date has been published yet.",https://hellenicaid.mfa.gr/en/global-gateway-forum-2027-brussels-8-9-june-2027/
2027-10-04,2027-10-09,upcoming,Summit / meeting,ALL,"IMF–World Bank Annual Meetings (Washington)","Annual meetings of the IMF and World Bank Group boards of governors.",https://www.worldbank.org/en/meetings/splash/about
'''
if not (DATA / "events.csv").exists():
    (DATA / "events.csv").write_text(EVENTS_DEFAULT, encoding="utf-8")
for r in csv.DictReader(open(DATA / "events.csv", encoding="utf-8-sig")):
    r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
    if not r.get("date") or not r.get("title"):
        continue
    status = r.get("status") or ("upcoming" if r["date"] > TODAY.isoformat() else "past")
    if status == "upcoming" and r["date"] < TODAY.isoformat():
        status = "past"
    try:
        code = urllib.request.urlopen(urllib.request.Request(r["source_url"], headers=UA), timeout=40).status if r.get("source_url") else "no source"
    except Exception as e:
        code = getattr(e, "code", None) or str(e)[:40]
    if code != 200:
        warnings.append(f"Event \u201c{r['title']}\u201d: source did not answer normally ({code}); check it by hand.")
    events.append({"d": r["date"], "e": r.get("end_date", ""), "st": status, "cat": r.get("category", ""),
                   "cc": r.get("countries", "ALL").split("|"), "t": r["title"], "x": r.get("description", ""), "u": r.get("source_url", "")})
events.sort(key=lambda e: e["d"])

TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>EU-CFA Network tracker</title>
<meta name="description" content="Network, overlap and events of European public financial institutions in the CFA franc zone (WAEMU and CEMAC) since 1999.">
<meta property="og:title" content="EU-CFA Network tracker">
<meta property="og:description" content="How European public financial institutions connect, overlap and react to events in the CFA franc zone.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#040a0f; --panel:#08151d; --panel2:#0a1c26; --ink:#d9f4ff; --muted:#8db1c0; --dim:#56798a; --line:#163746; --line-hi:#2a6a80;
  --accent:#40e8ff; --waemu:#ffbf5c; --cemac:#ff9a7a;
  --t-dfi:#3aa6ff; --t-bdb:#ff8c42; --t-npb:#2dffc8; --t-eca:#ff3d8e; --t-eu:#ffd84a; --t-wbtf:#e0c8a0; --t-mdb:#b77dff;
  --k-ms:#ffffff; --k-sec:#7be3c0; --k-ag:#d8b4ff; --k-fw:#9fb4c4; --k-ct:#ff9e6b;
  --c-mon:#ffd84a; --c-pol:#ff6b6b; --c-eu:#40e8ff; --c-fin:#7be36b; --c-meet:#c592ff;
  --mono:"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace; --sans:"IBM Plex Sans","Segoe UI",system-ui,-apple-system,sans-serif;
  color-scheme:dark;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark}}
:root[data-theme="dark"]{color-scheme:dark}
:root{box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
*,*::before,*::after{box-sizing:inherit}
html,body{height:100%;margin:0}
body{background:var(--bg);color:var(--ink);font:400 15px/1.5 var(--sans);display:flex;flex-direction:column}
header{display:flex;align-items:center;gap:20px;padding:12px 22px;border-bottom:1px solid var(--line);flex-wrap:wrap}
header .code{font:500 12px var(--mono);color:var(--muted);letter-spacing:.06em}
header h1{margin:0;font-size:20px;font-weight:600}
nav{display:flex;border:1px solid var(--line-hi);margin-left:auto}
nav button{appearance:none;border:0;background:transparent;color:var(--muted);font:600 14px var(--sans);padding:9px 18px;cursor:pointer}
nav button[aria-pressed="true"]{background:rgba(64,232,255,.08);color:var(--ink);box-shadow:inset 0 -2px 0 var(--accent)}
nav button:focus-visible,button:focus-visible,select:focus-visible,a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
main{flex:1;min-height:0;position:relative}
.view{position:absolute;top:0;right:0;bottom:0;left:0;display:grid;grid-template-columns:minmax(0,1fr) 400px}
.view[hidden]{display:none}
.stage{position:relative;min-height:0;overflow:hidden}
aside{border-left:1px solid var(--line);background:var(--panel);overflow:auto;padding:16px 18px}
aside h2{margin:0 0 4px;font-size:17px}
aside h3{margin:16px 0 6px;font-size:13px;color:var(--muted);font-weight:600}
.hint{font-size:13px;color:var(--muted);margin:4px 0 10px}
.tools{position:absolute;left:14px;top:12px;z-index:2;display:flex;flex-wrap:wrap;gap:6px;max-width:calc(100% - 150px)}
#netstage .tools{max-width:calc(100% - 390px)}
.chip{appearance:none;border:1px solid var(--line);background:rgba(4,12,17,.85);color:var(--ink);padding:5px 10px;font:500 12.5px var(--sans);cursor:pointer;display:inline-flex;gap:6px;align-items:center}
.chip[aria-pressed="false"]{opacity:.4}
.sw{width:9px;height:9px;border-radius:50%;display:inline-block}
.legend{position:absolute;left:14px;bottom:12px;z-index:2;background:rgba(4,12,17,.85);border:1px solid var(--line);padding:8px 10px;font-size:12px;color:var(--muted);display:flex;flex-wrap:wrap;gap:4px 12px;max-width:calc(100% - 28px)}
.legend span{display:inline-flex;align-items:center;gap:5px}
.zoom{position:absolute;right:14px;top:12px;z-index:2;display:flex;gap:4px}
.zoom button{appearance:none;border:1px solid var(--line-hi);background:rgba(4,12,17,.85);color:var(--ink);width:32px;height:32px;font:600 16px var(--sans);cursor:pointer}
select,input[type=range]{font:500 13px var(--sans);color:var(--ink);background:var(--panel2);border:1px solid var(--line);padding:5px 7px}
label.ctl{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;color:var(--muted);background:rgba(4,12,17,.85);border:1px solid var(--line);padding:3px 8px}
#net{position:absolute;top:0;left:0;width:100%;height:100%;display:block;cursor:grab}
#net3d{position:absolute;top:0;left:0;width:100%;height:100%;display:none}
.use3d #net3d{display:block}
.use3d #net{display:none}
#v-net:fullscreen{background:var(--bg);width:100vw;height:100vh}
#v-net:fullscreen .stage{height:100vh}
.nsearch{position:absolute;right:14px;top:52px;z-index:3;width:min(340px,calc(100% - 28px))}
.nsearch input{width:100%;font:500 13.5px var(--sans);color:var(--ink);background:rgba(4,12,17,.92);border:1px solid var(--line-hi);padding:8px 10px;outline:none}
.nsearch input:focus{border-color:var(--accent)}
.nresults{margin-top:2px;background:var(--panel2);border:1px solid var(--line-hi);max-height:340px;overflow:auto}
.nresults button{display:block;width:100%;text-align:left;appearance:none;border:0;border-bottom:1px solid var(--line);background:transparent;color:var(--ink);padding:7px 10px;font:500 13px var(--sans);cursor:pointer}
.nresults button:hover,.nresults button:focus{background:rgba(64,232,255,.08);outline:none}
.nresults .k{display:block;font-size:11.5px;color:var(--muted);font-weight:400}
.nresults .grp{padding:5px 10px;font:600 11px var(--mono);color:var(--dim);text-transform:uppercase;letter-spacing:.06em}
.zoom button.fs{width:auto;padding:0 10px;font-size:13px;display:inline-flex;align-items:center;gap:6px}
.scene-tooltip:empty{display:none}
.scene-tooltip{font:500 12.5px var(--sans)!important;color:var(--ink)!important;background:rgba(10,28,38,.92)!important;border:1px solid var(--line-hi);padding:6px 9px!important;border-radius:0!important}
.modenote{position:absolute;right:14px;bottom:12px;z-index:2;font-size:12px;color:var(--muted);background:rgba(4,12,17,.85);border:1px solid var(--line);padding:5px 9px}
svg text{font-family:var(--sans)}
.node{cursor:pointer}
.node text{fill:var(--ink);font-size:10.5px;pointer-events:none;paint-order:stroke;stroke:#000;stroke-width:3px}
.link{stroke-opacity:.35}
.faded{opacity:.08}
.tip{position:fixed;z-index:20;pointer-events:none;background:var(--panel2);border:1px solid var(--line-hi);padding:7px 9px;font-size:12.5px;max-width:300px;box-shadow:0 0 18px rgba(64,232,255,.12)}
.tip b{color:var(--accent)}
.deal{border-top:1px solid var(--line);padding:8px 0;font-size:13px}
.deal a{color:var(--accent)}
.meta{color:var(--muted);font-size:12px}
.amt{font:500 12px var(--mono);color:var(--ink)}
.bar{display:grid;grid-template-columns:minmax(100px,46%) 1fr auto;gap:8px;align-items:center;font-size:12.5px;margin:3px 0}
.bar .track{height:9px;background:rgba(255,255,255,.05);position:relative}
.bar .track i{position:absolute;left:0;top:0;bottom:0}
.bar .val{font:500 11.5px var(--mono);color:var(--muted)}
.big{font:600 24px var(--sans)}
.matrix{overflow:auto;padding:58px 18px 18px;height:100%}
.matrix table{border-collapse:collapse;font-size:11px}
.matrix th{font-weight:500;color:var(--muted);white-space:nowrap;padding:2px 4px}
.matrix th.col{height:150px;vertical-align:bottom}
.matrix th.col div{writing-mode:vertical-rl;transform:rotate(180deg)}
.matrix td{width:28px;height:24px;border:1px solid #0d2430;text-align:center;font:500 9.5px var(--mono);color:#fff;cursor:pointer}
.matrix td.diag{outline:1px solid var(--line-hi)}
.events{padding:58px 18px 18px;height:100%;overflow:auto}
#evmain{padding-top:112px}
.revm{display:inline-flex;margin:4px 0 8px}
.revwrap{overflow-x:auto;margin:6px 0 4px}
.revtab{border-collapse:collapse;font-size:12.5px;width:100%;min-width:620px}
.revtab th,.revtab td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
.revtab th{color:var(--muted);font-weight:600}
.revtab td.amt{text-align:right;white-space:nowrap}
.revtab a{color:var(--ink)}
.ev{border-top:1px solid var(--line);padding:9px 0;display:grid;grid-template-columns:120px 1fr;gap:10px;font-size:13px}
.ev .d{font:500 12px var(--mono);color:var(--muted)}
.ev .badge{font:600 11px var(--sans);padding:1px 6px;border:1px solid var(--line-hi);margin-right:6px}
.ev.up .badge{border-color:var(--accent);color:var(--accent)}
.ev a{color:var(--accent);font-size:12.5px}
.warn{font-size:12px;color:#ffc9a8;border:1px dashed #6b3a28;padding:6px 8px;margin-top:8px}
.about{padding:24px 32px;overflow:auto;height:100%}
.about > p,.about > ul:not(.actors),.about > h2:not(#actors){max-width:860px}
.actors{list-style:none;padding:0;margin:4px 0 14px;columns:4 300px;column-gap:36px}
.actors li{break-inside:avoid;padding:3px 0;border-bottom:1px solid var(--line);font-size:13px;display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.actors li .amt{margin-left:auto}
.about p,.about li{color:var(--muted)}
.about h2{margin-top:22px}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
@media (max-width:900px){
  .view{grid-template-columns:1fr;grid-template-rows:62vh auto;position:static}
  main{overflow:auto}
  aside{border-left:0;border-top:1px solid var(--line)}
  nav{margin-left:0}
}
</style>
</head>
<body>
<noscript><p style="padding:24px">This tracker needs JavaScript to draw the network.</p></noscript>
<header>
  <div><div class="code">EU-CFA network tracker</div><h1>European public finance in the CFA franc zone: network, overlap, events</h1></div>
  <nav aria-label="Views">
    <button data-v="net" aria-pressed="true">Network</button><button data-v="ovl" aria-pressed="false">Overlap</button>
    <button data-v="evt" aria-pressed="false">Events</button><button data-v="src" aria-pressed="false">Sources</button><button data-v="abt" aria-pressed="false">About</button>
  </nav>
</header>
<main>
  <section class="view" id="v-net">
    <div class="stage" id="netstage">
      <div class="tools" id="layers"></div>
      <div class="zoom"><button id="zin" aria-label="Zoom in">+</button><button id="zout" aria-label="Zoom out">−</button><button id="zreset" aria-label="Reset view">↺</button>
        <button id="fs" class="fs" aria-label="Full screen" title="Full screen (Esc to leave)"><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M1 5V1h4M9 1h4v4M13 9v4H9M5 13H1V9" fill="none" stroke="currentColor" stroke-width="1.6"/></svg><span>Full screen</span></button></div>
      <div class="nsearch"><input id="nsearch" type="search" placeholder="Search an actor or a deal" autocomplete="off" aria-label="Search an actor, an institution or a deal"><div id="nresults" class="nresults" hidden></div></div>
      <svg id="net" role="img" aria-label="Network of European public financial institutions, countries, sectors and agencies"></svg>
      <div id="net3d" aria-label="Three-dimensional network: drag to rotate, scroll to zoom"></div>
      <div class="modenote" id="modenote" hidden></div>
      <div class="legend" id="netlegend"></div>
    </div>
    <aside id="netpanel"></aside>
  </section>
  <section class="view" id="v-ovl" hidden>
    <div class="stage"><div class="tools"><label class="ctl">Measure <select id="ovm"><option value="jac" selected>Overlap %</option><option value="co">Co-financed projects</option></select></label><label class="ctl">Institutions shown <select id="ovn"><option>12</option><option selected>18</option><option>24</option></select></label>
      </div><div class="matrix" id="matrix"></div></div>
    <aside id="ovlpanel"></aside>
  </section>
  <section class="view" id="v-evt" hidden>
    <div class="stage"><div class="tools" id="evtools"></div><div class="events" id="evmain"></div></div>
    <aside id="evpanel"></aside>
  </section>
  <section class="view" id="v-src" hidden><div class="about" id="sources" style="grid-column:1/-1;max-width:1000px"></div></section>
  <section class="view" id="v-abt" hidden><div class="about" id="about" style="grid-column:1/-1"></div></section>
</main>
<div class="tip" id="tip" hidden></div>
<script>/*__D3__*/</script>
<script>/*__THREE__*/</script>
<script>/*__FG3D__*/</script>
<script>const DATA = /*__DATA__*/null;</script>
<script>
(() => {
const D = DATA, $ = s => document.querySelector(s);
const HAS_WEBGL = (() => { try { const c = document.createElement("canvas"); return !!(window.WebGLRenderingContext && (c.getContext("webgl2") || c.getContext("webgl"))); } catch (e) { return false; } })();
const USE3D = HAS_WEBGL && typeof ForceGraph3D === "function" && typeof THREE !== "undefined";

const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt = v => v >= 1e9 ? "€" + (v/1e9).toFixed(1) + " bn" : v >= 1e6 ? "€" + (v/1e6).toFixed(v >= 1e8 ? 0 : 1) + " m" : v >= 1e3 ? "€" + Math.round(v/1e3) + " k" : "€" + Math.round(v || 0);
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const TYPEVAR = {"DFI":"--t-dfi","Bilateral development bank":"--t-bdb","NPB":"--t-npb","ECA":"--t-eca","EU institution":"--t-eu","World Bank trust fund":"--t-wbtf","Multilateral":"--t-mdb"};
const TYPELABEL = {"DFI":"DFI","Bilateral development bank":"Development bank","NPB":"Promotional bank","ECA":"Export credit agency","EU institution":"EU institution","World Bank trust fund":"World Bank trust fund (EU-financed)","Multilateral":"EBRD (EU-majority multilateral)"};
const instName = id => (D.inst[id] || {}).n || id;
const tip = $("#tip");
function showTip(e, html) { tip.innerHTML = html; tip.hidden = false; tip.style.left = Math.min(e.clientX + 14, innerWidth - 320) + "px"; tip.style.top = (e.clientY + 14) + "px"; }
function hideTip() { tip.hidden = true; }

// ---------- views
document.querySelectorAll("nav button").forEach(b => b.onclick = () => {
  document.querySelectorAll("nav button").forEach(x => x.setAttribute("aria-pressed", x === b));
  ["net","ovl","evt","src","abt"].forEach(v => $("#v-" + v).hidden = v !== b.dataset.v);
  if (b.dataset.v === "ovl") drawMatrix(); if (b.dataset.v === "evt") drawEvents();
});

// ---------- NETWORK
const KIND = {institution:{c:t => css(TYPEVAR[t] || "--t-dfi"), label:"Institution"}, country:{c:(t,u) => css(u === "CEMAC" ? "--cemac" : "--waemu"), label:"Country"},
  memberstate:{c:() => css("--k-ms"), label:"Member state"}, sector:{c:() => css("--k-sec"), label:"Sector"}, agency:{c:() => css("--k-ag"), label:"Implementing agency (EU funds)"},
  framework:{c:() => css("--k-fw"), label:"Framework (no amounts)"}, contractor:{c:() => css("--k-ct"), label:"Contractor (European firm, AFD-financed contract)"}};
const layers = {memberstate:true, sector:false, agency:false, framework:false, contractor:false};
const typeOn = Object.fromEntries(Object.keys(TYPEVAR).map(t => [t, true]));
const lay = $("#layers");
function chip(label, color, on, fn, key) { const b = document.createElement("button"); b.className = "chip"; if (key) b.dataset.key = key; b.setAttribute("aria-pressed", on);
  b.innerHTML = `<span class="sw" style="background:${color}"></span>${label}`; b.onclick = () => { fn(); b.setAttribute("aria-pressed", b.getAttribute("aria-pressed") !== "true"); }; lay.append(b); }
Object.keys(TYPEVAR).forEach(t => chip(TYPELABEL[t], css(TYPEVAR[t]), true, () => { typeOn[t] = !typeOn[t]; buildGraph(); }, "t:" + t));
[["memberstate","Member states"],["agency","Implementing agencies"],["contractor","Contractors"],["sector","Sectors"],["framework","Frameworks"]].forEach(([k,l]) =>
  chip(l, KIND[k].c(), layers[k], () => { layers[k] = !layers[k]; buildGraph(); }, "l:" + k));
const minWrap = document.createElement("label"); minWrap.className = "ctl";
minWrap.innerHTML = `Since <select id="since"><option value="0" selected>All years (1999 onward)</option>${Array.from({length: new Date().getFullYear() - 1998}, (_, i) => 1999 + i).map(y => `<option value="${y}">${y}</option>`).join("")}</select>`;
lay.append(minWrap); $("#since").onchange = e => { SINCE = +e.target.value; buildGraph(); if (!selected) netIntro(); };
$("#netlegend").innerHTML = Object.entries(KIND).map(([k,v]) => `<span><i class="sw" style="background:${k === "country" ? css("--waemu") : v.c()}"></i>${v.label}</span>`).join("") +
  (USE3D ? `<span>Drag to rotate, scroll to zoom, hover to light up an actor, click for details. Grey lines: amount not published.</span>` : `<span>Size and line width follow euros. Drag a dot to pin it, double-click to release.</span>`);

const svg = d3.select("#net"), g = svg.append("g"), gl = g.append("g"), gn = g.append("g");
const zoom = d3.zoom().scaleExtent([0.2, 6]).on("zoom", e => g.attr("transform", e.transform));
svg.call(zoom).on("dblclick.zoom", null);
const cam = f => { const p = G3.cameraPosition(); G3.cameraPosition({x: p.x * f, y: p.y * f, z: p.z * f}, undefined, reduce ? 0 : 400); };
$("#zin").onclick = () => USE3D && G3 ? cam(0.72) : svg.transition().duration(reduce ? 0 : 250).call(zoom.scaleBy, 1.4);
$("#zout").onclick = () => USE3D && G3 ? cam(1.38) : svg.transition().duration(reduce ? 0 : 250).call(zoom.scaleBy, 1 / 1.4);
$("#zreset").onclick = () => USE3D && G3 ? G3.zoomToFit(reduce ? 0 : 800, 30) : svg.transition().duration(reduce ? 0 : 250).call(zoom.transform, d3.zoomIdentity);
let sim = null, selected = null, focusCountry = null;
// ---------- 3D nebula (falls back to the 2D network when the computer cannot draw 3D)
if (USE3D) $("#netstage").classList.add("use3d");
else { $("#modenote").hidden = false; $("#modenote").textContent = "This computer cannot draw the 3D view, so the 2D network is shown."; }
let G3 = null, hovered = null, nbrs = new Set(), hotLinks = new Set();
// left to right: (1) member states and EU institutions, (2) national public financial institutions, (3) countries, (4) a clicked country's sectors;
// implementing agencies float above, frameworks below
const GROUP_POS = {owners: [-520, 0, 0], pfi: [0, 0, 0], country: [520, 0, 0], sector: [900, 0, 0], agency: [-260, 480, 0], framework: [0, -480, 0], contractor: [260, -500, 0]};
const GROUP_COL = {owners: "#e8d27a", pfi: "#3a8cff", country: "#ffb648", sector: "#3fd9b0", agency: "#b77dff", framework: "#7f98aa", contractor: "#ff8a52"};
function groupOf(d) {
  if (d.k === "memberstate" || (d.k === "institution" && d.t === "EU institution")) return "owners";
  if (d.k === "institution") return "pfi";
  return d.k;
}
function glowTexture() {
  const c = document.createElement("canvas"); c.width = c.height = 128; const g = c.getContext("2d");
  const gr = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  gr.addColorStop(0, "rgba(255,255,255,1)"); gr.addColorStop(0.18, "rgba(255,255,255,.7)"); gr.addColorStop(0.45, "rgba(255,255,255,.18)"); gr.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = gr; g.fillRect(0, 0, 128, 128); return new THREE.CanvasTexture(c);
}
let GLOW = null;
function textSprite(text, color) {
  const c = document.createElement("canvas"), g = c.getContext("2d"), fs = 44;
  g.font = `600 ${fs}px IBM Plex Sans, Segoe UI, sans-serif`; const w = Math.ceil(g.measureText(text).width) + 24;
  c.width = w; c.height = fs + 22; g.font = `600 ${fs}px IBM Plex Sans, Segoe UI, sans-serif`;
  g.lineWidth = 8; g.strokeStyle = "rgba(0,0,0,.85)"; g.strokeText(text, 12, fs); g.fillStyle = color; g.fillText(text, 12, fs);
  const s = new THREE.Sprite(new THREE.SpriteMaterial({map: new THREE.CanvasTexture(c), transparent: true, depthWrite: false}));
  s.scale.set(c.width / 3.6, c.height / 3.6, 1); return s;
}
function shellForce(alpha) {  // pulls each actor towards the centre of its group's cloud
  for (const n of shellForce.nodes || []) {
    const [tx, ty, tz] = GROUP_POS[groupOf(n)] || [0, 0, 0];
    n.vx += (tx - (n.x || 0)) * alpha * 0.22;
    n.vy += (ty - (n.y || 0)) * alpha * 0.018;
    n.vz += (tz - (n.z || 0)) * alpha * 0.018;
  }
}
shellForce.initialize = ns => { shellForce.nodes = ns; };
const CLOUDS = {};
function nodeColor(d) { return d.k === "framework" ? css("--k-fw") : KIND[d.k].c(d.t, d.u); }
function render3D(nodes, ls, rn, labelled) {
  if (!GLOW) GLOW = glowTexture();
  const el = $("#net3d"), stage = $("#netstage");
  const prev = G3 ? Object.fromEntries(G3.graphData().nodes.map(n => [n.id, n])) : {};
  nodes.forEach(n => { const p = prev[n.id]; if (p && p.x !== undefined) { n.x = n.fx = p.x; n.y = n.fy = p.y; n.z = n.fz = p.z; } });
  const hub = nodes.filter(n => groupOf(n) === "pfi").sort((a, b) => b.v - a.v)[0];   // the largest national institution (AFD) sits at the centre
  if (hub) { const [cx, cy, cz] = GROUP_POS.pfi; hub.x = hub.fx = cx; hub.y = hub.fy = cy; hub.z = hub.fz = cz; }
  ls.forEach(l => { const s = nodeById[l.source], t = nodeById[l.target]; l.col = l.co ? "#f2e6ff" : (!l.v && !l.cs && !(t && t.k === "framework") && !(s && s.k === "memberstate" && t && t.k === "agency")) ? "#7f8c96" : l.cs ? css("--k-sec") : s && s.k === "institution" ? KIND.institution.c(s.t) : (s && s.k === "memberstate" && t && t.k === "agency") ? css("--k-ag") : "#6f8f9c"; });
  if (!G3) {
    G3 = ForceGraph3D({controlType: "orbit"})(el)
      .backgroundColor("#02060b").showNavInfo(false)
      .nodeThreeObject(d => {
        const col = nodeColor(d), size = Math.max(2.2, rn(d) * 1.3), grp = new THREE.Group();
        const glow = new THREE.Sprite(new THREE.SpriteMaterial({map: GLOW, color: col, transparent: true, opacity: 0.7, blending: THREE.AdditiveBlending, depthWrite: false}));
        glow.scale.set(size * 4, size * 4, 1);
        const core = new THREE.Mesh(new THREE.SphereGeometry(size * 0.42, 18, 14), new THREE.MeshBasicMaterial({color: col, transparent: true, opacity: 0.95}));
        grp.add(glow); grp.add(core);
        if (labelled(d)) { const s = textSprite(d.k === "institution" ? shortName(d.l) : d.l.length > 30 ? d.l.slice(0, 28) + "…" : d.l, "#e9f8ff"); s.position.set(0, size * 1.1 + 4, 0); grp.add(s); d.__label = s; }
        d.__glow = glow; d.__core = core; d.__size = size; return grp;
      })
      .nodeLabel(d => `<b>${esc(d.l)}</b><br>${esc(KIND[d.k].label)}${d.v ? "<br>" + fmt(d.v) + " in the Franc Zone" : ""}`)
      .linkColor(l => l.col).linkOpacity(0.2).linkWidth(l => hotLinks.has(l) ? 0.9 : 0)
      .linkVisibility(l => !hovered || hotLinks.has(l))
      .linkDirectionalParticles(l => (!reduce && hotLinks.has(l)) ? 3 : 0).linkDirectionalParticleWidth(1.8).linkDirectionalParticleSpeed(0.007)
      .onNodeHover(n => { el.style.cursor = n ? "pointer" : "grab"; setHover(n); })
      .onNodeClick(n => clickNode(n))
      .onBackgroundClick(() => { selected = null; dealFocus = null; const had = focusCountry; focusCountry = null; setHover(null); if (had) buildGraph(); netIntro(); })
      .d3Force("shell", shellForce).d3VelocityDecay(0.35).cooldownTicks(reduce ? 0 : 300);
    G3.d3Force("charge").strength(-260).distanceMax(300);
    G3.d3Force("link").distance(120).strength(0.004);
    // a faint star field for the nebula look
    const pts = [], N = 2200;
    for (let i = 0; i < N; i++) { const r = 900 + Math.random() * 1500, a = Math.random() * Math.PI * 2, b = Math.acos(2 * Math.random() - 1); pts.push(r * Math.sin(b) * Math.cos(a), r * Math.sin(b) * Math.sin(a), r * Math.cos(b)); }
    const geo = new THREE.BufferGeometry(); geo.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    G3.scene().add(new THREE.Points(geo, new THREE.PointsMaterial({color: 0x7fb8d8, size: 1.6, transparent: true, opacity: 0.55, depthWrite: false})));
    // coloured clouds of light: the nebula
    for (const [g, [x, y, z]] of Object.entries(GROUP_POS)) {
      const grp = new THREE.Group();
      for (let i = 0; i < 4; i++) {
        const m = new THREE.Sprite(new THREE.SpriteMaterial({map: GLOW, color: GROUP_COL[g], transparent: true, opacity: 0.09 + i * 0.015, blending: THREE.AdditiveBlending, depthWrite: false}));
        const sc = 620 - i * 100;
        m.position.set(x + (Math.random() - 0.5) * 60, y + (Math.random() - 0.5) * 60, z + (Math.random() - 0.5) * 60); m.scale.set(sc, sc, 1); m.renderOrder = -1;
        grp.add(m);
      }
      CLOUDS[g] = grp; G3.scene().add(grp);
    }
    if (!reduce) (function pulse(t) { if (hovered && hovered.__glow) { const s = hovered.__size * (7.5 + Math.sin(t / 260) * 1.4); hovered.__glow.scale.set(s, s, 1); } requestAnimationFrame(pulse); })(0);
    G3.cameraPosition({x: 60, y: 40, z: 1150}, {x: 60, y: 0, z: 0}, 0);
    setTimeout(() => G3.zoomToFit(reduce ? 0 : 900, 10), 2600);
  }
  const biggest = {};
  nodes.forEach(n => { const g = groupOf(n); if (!biggest[g] || (n.v || 0) > (biggest[g].v || 0)) biggest[g] = n; });
  Object.entries(biggest).forEach(([g, n]) => { const [x, y, z] = GROUP_POS[g] || [0, 0, 0]; if (!prev[n.id]) { n.x = n.fx = x; n.y = n.fy = y; n.z = n.fz = z; } });
  nodes.forEach(n => { if (n.k === "sector" && !prev[n.id]) { n.fx = n.fy = n.fz = undefined; } });   // sectors are not pinned: they settle together with the rest
  const present = new Set(nodes.map(groupOf));
  Object.entries(CLOUDS).forEach(([g, c]) => { c.visible = present.has(g); });
  G3.width(stage.clientWidth).height(stage.clientHeight).graphData({nodes, links: ls});
  if (selected) { const n = G3.graphData().nodes.find(x => x.id === selected); if (n) setTimeout(() => setHover(n, true), 50); }
}
let dealFocus = null;   // a deal opened from the search: light up its institution and only its countries
function dealSets(d, links) {
  const inst = "i:" + d.i, keep = new Set([inst, ...d.c.map(c => "c:" + c)]), hot = new Set();
  links.forEach(l => { const s = l.source.id || l.source, t = l.target.id || l.target; if (s === inst && keep.has(t)) hot.add(l); });
  return {inst, keep, hot};
}
function setHover(n, sticky) {
  if (!G3) return;
  if (dealFocus && (!n || (sticky && n.id === "i:" + dealFocus.i))) {
    const g = G3.graphData(), ds = dealSets(dealFocus, g.links);
    hovered = g.nodes.find(x => x.id === ds.inst) || null; nbrs = ds.keep; hotLinks = ds.hot;
  } else {
  hovered = n || (selected ? G3.graphData().nodes.find(x => x.id === selected) : null);
  nbrs = new Set(); hotLinks = new Set();
  }
  if (hovered && !(dealFocus && hovered.id === "i:" + dealFocus.i && (!n || sticky))) { nbrs.add(hovered.id); G3.graphData().links.forEach(l => { const s = l.source.id || l.source, t = l.target.id || l.target; if (s === hovered.id || t === hovered.id) { nbrs.add(s); nbrs.add(t); hotLinks.add(l); } }); }
  G3.graphData().nodes.forEach(d => {
    if (!d.__core) return;
    const on = !hovered || nbrs.has(d.id), me = hovered && d.id === hovered.id;
    d.__core.material.opacity = on ? 0.95 : 0.12;
    d.__glow.material.opacity = me ? 1 : on ? (hovered ? 0.85 : 0.7) : 0.05;
    const s = d.__size * (me ? 7.5 : 4); d.__glow.scale.set(s, s, 1);
    if (d.__label) d.__label.material.opacity = on ? 1 : 0.15;
  });
  G3.linkWidth(G3.linkWidth()).linkVisibility(G3.linkVisibility()).linkDirectionalParticles(G3.linkDirectionalParticles());
}
function clickNode(n) {
  dealFocus = null;
  selected = n.id;
  if (n.k === "country") { const was = focusCountry; focusCountry = n.id.slice(2); if (was !== focusCountry) buildGraph(); }
  panel(nodeById[n.id] || n); setHover(n, true);   // highlight and details only: the camera stays where it is
}
// full screen: the network and its panel together
$("#fs").onclick = () => { const v = $("#v-net"); if (!document.fullscreenElement) (v.requestFullscreen ? v.requestFullscreen() : v.webkitRequestFullscreen && v.webkitRequestFullscreen()); else document.exitFullscreen(); };
document.addEventListener("fullscreenchange", () => {
  $("#fs span").textContent = document.fullscreenElement ? "Exit full screen" : "Full screen";
  setTimeout(() => { if (USE3D && G3) G3.width($("#netstage").clientWidth).height($("#netstage").clientHeight); else buildGraph(); }, 120);
});
const nodeById = Object.fromEntries(D.nodes.map(n => [n.id, n]));
const COL = {country: 0.86, memberstate: 0.06, institution: 0.34, agency: 0.6, sector: 0.6, framework: 0.97, contractor: 0.7};
function visibleNode(n) {
  if (n.k === "institution") return typeOn[n.t];
  if (n.k === "country") return true;
  if (n.k === "sector" && focusCountry) return true;  // a clicked country shows its sectors
  return layers[n.k];
}
// ---------- "Since": the network recalculated from the deals and contracts of the chosen period
let SINCE = 0;
const ALL_LINKS = D.links.slice(), ORIG_V = Object.fromEntries(D.nodes.map(n => [n.id, n.v]));
const xkey = g => "x:" + g.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60);
const dealOk = d => !SINCE || (d.y && +d.y >= SINCE);
function derive() {
  if (!SINCE) return {links: ALL_LINKS, v: ORIG_V, inst: null};
  const L = new Map(), V = {}, inst = new Set();
  const add = (s, t, v) => { const k = s + "|" + t, o = L.get(k) || {s, t, v: 0, n: 0}; o.v += v; o.n++; L.set(k, o); };
  const addV = (id, v) => { V[id] = (V[id] || 0) + v; };
  for (const d of D.deals) {
    if (!dealOk(d)) continue;
    const iid = "i:" + d.i, sh = d.v / Math.max(1, d.c.length); inst.add(d.i); addV(iid, d.v);
    d.c.forEach(c => { add(iid, "c:" + c, sh); addV("c:" + c, sh); });
    if (d.s) { add(iid, "s:" + d.s, d.v); addV("s:" + d.s, d.v); }
    if (d.g && (D.inst[d.i] || {}).t === "EU institution") { add(iid, "a:" + d.g, d.v); addV("a:" + d.g, d.v); }
  }
  inst.forEach(i => { const ms = (D.inst[i] || {}).ms, owner = (ms === "WBTF" || ms === "INT") ? "EU" : ms, f = ms === "INT" ? D.ebrd.share : 1, v = (V["i:" + i] || 0) * f;
    add("m:" + owner, "i:" + i, v); addV("m:" + owner, v); });
  for (const c of (D.contracts || [])) {
    const yr = +String(c.d || "").slice(0, 4); if (!yr || yr < SINCE) continue;
    for (const [g, m] of (c.g || [])) { const x = xkey(g), val = c.v / (c.parts || 1); addV(x, val); add("i:afd", x, val); add(x, "c:" + c.c, val); if (!L.has("m:" + m + "|" + x)) L.set("m:" + m + "|" + x, {s: "m:" + m, t: x, v: 0, n: 1}); }
  }
  // links without amounts stay: frameworks, agencies' member states, EBRD co-financing (if the EBRD has deals in the period)
  ALL_LINKS.filter(l => l.s.startsWith("f:") || l.t.startsWith("f:") || (l.s.startsWith("m:") && l.t.startsWith("a:")) || (l.co && inst.has("ebrd")))
    .forEach(l => { if (!L.has(l.s + "|" + l.t)) L.set(l.s + "|" + l.t, Object.assign({}, l)); });
  return {links: [...L.values()], v: V, inst};
}
function csecNow(cc) {
  if (!SINCE) return D.csec[cc] || {};
  const m = {}; D.deals.filter(d => dealOk(d) && d.s && d.c.includes(cc)).forEach(d => { m[d.s] = (m[d.s] || 0) + d.v / Math.max(1, d.c.length); }); return m;
}
function buildGraph() {
  const der = derive();
  D.links = der.links; D.nodes.forEach(n => { n.v = der.v[n.id] || 0; });   // panels read the current period
  const ns = D.nodes.filter(visibleNode).filter(n => !(der.inst && n.k === "institution" && !der.inst.has(n.id.slice(2)))).map(n => Object.assign({}, n));
  const ok = new Set(ns.map(n => n.id));
  let ls = D.links.filter(l => ok.has(l.s) && ok.has(l.t))
    .filter(l => !(focusCountry && !layers.sector && l.t.startsWith("s:")))   // in country focus, sectors connect to that country only
    .map(l => ({source:l.s, target:l.t, v:l.v, n:l.n, co:l.co, own:l.own}));
  if (focusCountry) Object.entries(csecNow(focusCountry)).forEach(([sec, v]) => { if (ok.has("s:" + sec)) ls.push({source:"c:" + focusCountry, target:"s:" + sec, v, n:0, cs:true}); });
  const used = new Set(ls.flatMap(l => [l.source, l.target]));
  const nodes = ns.filter(n => used.has(n.id) || n.k === "country" || n.k === "memberstate" || n.k === "institution");
  const W = $("#netstage").clientWidth, H = $("#netstage").clientHeight;
  const r0 = d3.scaleSqrt().domain([0, d3.max(nodes, n => n.v) || 1]).range([1.6, 30]);   // area proportional to euros
  const r = v => r0(v); const rn = d => r0(d.v || 0);
  if (USE3D) {
    const instV = nodes.filter(n => n.k === "institution").map(n => n.v).sort((a, b) => b - a), cut = instV[Math.min(14, instV.length - 1)] || 0;
    render3D(nodes, ls, rn, d => d.k === "country" || d.k === "memberstate" || d.k === "institution" || d.k === "agency" || d.k === "contractor" || (d.k === "sector" && focusCountry));
    return;
  }
  const w = d3.scaleSqrt().domain([0, d3.max(ls, l => l.v) || 1]).range([0.4, 6]);
  gl.selectAll("*").remove(); gn.selectAll("*").remove();
  const link = gl.selectAll("line").data(ls).join("line").attr("class", "link")
    .attr("stroke", l => { if (l.cs) return css("--k-sec"); const s = nodeById[l.source]; return s && s.k === "institution" ? KIND.institution.c(s.t) : "#5f7f8c"; })
    .attr("stroke-width", l => l.v ? w(l.v) : 0.6).attr("stroke-dasharray", l => l.v ? null : "3 3");
  const node = gn.selectAll("g").data(nodes, n => n.id).join("g").attr("class", "node")
    .call(d3.drag().on("start", (e, d) => { if (!e.active) sim.alphaTarget(0.2).restart(); d.fx = d.x; d.fy = d.y; })
      .on("drag", (e, d) => { d.fx = e.x; d.fy = e.y; }).on("end", (e) => { if (!e.active) sim.alphaTarget(0); }))
    .on("dblclick", (e, d) => { d.fx = null; d.fy = null; sim.alpha(0.3).restart(); })
    .on("mousemove", (e, d) => showTip(e, `<b>${esc(d.l)}</b><br>${esc(KIND[d.k].label)}${d.v ? "<br>" + fmt(d.v) + " in the Franc Zone" : ""}`))
    .on("mouseleave", hideTip).on("click", (e, d) => { dealFocus = null;
      selected = d.id;
      if (d.k === "country") { const was = focusCountry; focusCountry = d.id.slice(2); if (was !== focusCountry) { buildGraph(); } }
      highlight(); panel(nodeById[d.id] || d);
    });
  const csz = focusCountry ? d3.scaleSqrt().domain([0, d3.max(Object.values(csecNow(focusCountry))) || 1]).range([4, 16]) : null;
  if (csz) nodes.forEach(d => { if (d.k === "sector" && !layers.sector) d.fv = csecNow(focusCountry)[d.id.slice(2)] || 0; });
  node.append("circle").attr("r", d => d.k === "framework" ? 5 : (csz && d.k === "sector" && !layers.sector) ? csz(d.fv) : rn(d))
    .attr("fill", d => d.k === "framework" ? "none" : KIND[d.k].c(d.t, d.u)).attr("stroke", d => d.k === "framework" ? css("--k-fw") : "#000")
    .attr("stroke-width", d => d.k === "framework" ? 1.5 : 0.8);
  node.filter(d => d.k !== "framework" && (d.k !== "sector" || d.v > 0)).append("text")
    .attr("text-anchor", d => d.k === "sector" ? "end" : "start").attr("dx", d => d.k === "sector" ? -(rn(d) + 3) : rn(d) + 3).attr("dy", 3.5)
    .text(d => d.k === "institution" ? shortName(d.l) : d.l.length > 28 ? d.l.slice(0, 26) + "…" : d.l);
  if (sim) sim.stop();
  sim = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(ls).id(d => d.id).distance(110).strength(0.06))
    .force("charge", d3.forceManyBody().strength(d => -90 - rn(d) * 9))
    .force("x", d3.forceX(d => W * (d.k === "sector" && focusCountry && !layers.sector ? 0.93 : groupOf(d) === "owners" ? 0.08 : (COL[d.k] ?? 0.5))).strength(0.55))
    .force("y", d3.forceY(H / 2).strength(0.04))
    .force("collide", d3.forceCollide(d => rn(d) + 9).strength(0.9))
    .on("tick", () => {
      link.attr("x1", l => l.source.x).attr("y1", l => l.source.y).attr("x2", l => l.target.x).attr("y2", l => l.target.y);
      node.attr("transform", d => `translate(${d.x},${d.y})`);
    });
  if (reduce) { sim.stop(); for (let i = 0; i < 300; i++) sim.tick(); link.attr("x1", l => l.source.x).attr("y1", l => l.source.y).attr("x2", l => l.target.x).attr("y2", l => l.target.y); node.attr("transform", d => `translate(${d.x},${d.y})`); }
  window._net = {node, link, ls};
  highlight();
}
const SHORT_ID = {"eu-intpa":"European Commission","eu-eutf":"EU Trust Fund for Africa","edfi-mc":"ElectriFI / AgriFI","eu-blending":"EU blending grants",
  "eu-aitf":"EU-AITF","wbtf":"World Bank trust funds","eib":"EIB","afd":"AFD","kfw-db":"KfW","proparco":"Proparco","deg":"DEG","fmo":"FMO","bio":"BIO",
  "invest-intl":"Invest International","dggf":"DGGF","finnfund":"Finnfund","ifu":"Impact Fund Denmark","atradius-dsb":"Atradius DSB","bgk":"BGK","kuke":"KUKE",
  "cofides":"COFIDES","swedfund":"Swedfund","sace":"SACE","cdp":"CDP","eifo":"EIFO","credendo":"Credendo","bpifrance-ae":"Bpifrance Assurance Export","oeeb":"OeEB"};
const SHORTS = Object.fromEntries(Object.entries(SHORT_ID).filter(([id]) => D.inst[id]).map(([id, s]) => [D.inst[id].n, s]));
function shortName(n) { if (SHORTS[n]) return SHORTS[n]; const m = n.match(/\(([^)]+)\)\s*$/); return m && m[1].length < 26 ? m[1] : n.split(" – ")[0].slice(0, 26); }
function highlight() {
  if (!window._net) return; const {node, link, ls} = window._net;
  if (dealFocus) { const ds = dealSets(dealFocus, ls); node.classed("faded", d => !ds.keep.has(d.id)); link.classed("faded", l => !ds.hot.has(l)); return; }
  if (!selected) { node.classed("faded", false); link.classed("faded", false); return; }
  const nb = new Set([selected]); ls.forEach(l => { const s = l.source.id || l.source, t = l.target.id || l.target; if (s === selected) nb.add(t); if (t === selected) nb.add(s); });
  node.classed("faded", d => !nb.has(d.id)); link.classed("faded", l => (l.source.id || l.source) !== selected && (l.target.id || l.target) !== selected);
}
svg.on("click", e => { if (e.target === svg.node()) { selected = null; dealFocus = null; const had = focusCountry; focusCountry = null; if (had) buildGraph(); highlight(); netIntro(); } });
function bars(items, color) { const max = Math.max(1, ...items.map(x => x[1]));
  return items.map(([l, v]) => `<div class="bar"><span>${esc(l)}</span><span class="track"><i style="width:${(100 * v / max).toFixed(1)}%;background:${color}"></i></span><span class="val">${fmt(v)}</span></div>`).join(""); }
function dealList(ds, n = 12) { return ds.filter(dealOk).sort((a, b) => b.v - a.v).slice(0, n).map(d => `<div class="deal">${esc(d.t)}<div class="meta">${esc(shortName(instName(d.i)))}, ${d.c.map(c => esc((D.countries[c] || {}).n || c)).join(", ")}${d.y ? ", " + esc(d.y) : ""}, ${esc(d.n)} · <span class="amt">${fmt(d.v)}</span>${d.e ? " (estimated share)" : ""} <a href="${esc(d.u)}" target="_blank" rel="noopener">source</a></div></div>`).join(""); }
function panel(n) {
  const id = n.id.slice(2), p = $("#netpanel");
  const nb = D.links.filter(l => l.s === n.id || l.t === n.id).map(l => [nodeById[l.s === n.id ? l.t : l.s], l]).filter(x => x[0]);
  let html = `<h2>${esc(n.l)}</h2><div class="meta">${esc(KIND[n.k].label)}${n.t ? " · " + esc(TYPELABEL[n.t]) : ""}</div>`;
  if (n.v) html += `<div class="big">${fmt(n.v)}</div><div class="hint">attributed to Franc Zone countries since 1999</div>`;
  const grp = k => nb.filter(([m, l]) => m.k === k && l.v).sort((a, b) => b[1].v - a[1].v).slice(0, 10).map(([m, l]) => [m.l.length > 40 ? m.l.slice(0, 38) + "…" : m.l, l.v]);
  if (n.k === "institution" && id === "ebrd") {
    const ds = D.deals.filter(d => d.i === "ebrd"), withEU = ds.filter(d => d.eu && Object.keys(d.eu).length), noEU = ds.filter(d => !(d.eu && Object.keys(d.eu).length));
    html += `<h3>EU capital in the EBRD</h3><p class="hint">The EU (3.03%), the EIB (3.03%) and the 27 member states (about 48.4%) together hold ${(D.ebrd.share * 100).toFixed(1)}% of the EBRD's capital, which backs all its lending. The link to the European Union is weighted by that share: ${fmt(n.v * D.ebrd.share)} of ${fmt(n.v)}, an estimate based on shareholding. <a href="${esc(D.ebrd.src)}" target="_blank" rel="noopener" style="color:var(--accent)">Source</a></p>
      <h3>Projects naming EU or member-state money (${withEU.length})</h3>` + (withEU.length ? withEU.map(d => `<div class="deal"><b>${esc(d.t)}</b> <span class="amt">${fmt(d.v)}</span><div class="meta">EU side named: ${Object.keys(d.eu).map(k => esc(shortName(instName(k)))).join(", ")}</div>` +
        [...new Set(Object.values(d.eu))].slice(0, 2).map(q => `<div class="meta">“${esc(q)}”</div>`).join("") + `<div class="meta"><a href="${esc(d.psd)}" target="_blank" rel="noopener">EBRD project page</a></div></div>`).join("") : `<p class="hint">None.</p>`) +
      `<h3>Projects with no EU money named (${noEU.length})</h3><p class="hint">Financed from the EBRD's own resources; EU capital is involved only through the shareholding above.</p>` + dealList(noEU, 20);
  } else if (n.k === "institution") {
    const ds = D.deals.filter(d => d.i === id);
    html += `<h3>Countries</h3>${bars(grp("country"), css("--waemu"))}<h3>Sectors</h3>${bars(grp("sector"), css("--k-sec"))}`;
    if (grp("agency").length) html += `<h3>EU funds entrusted to implementing agencies</h3>${bars(grp("agency"), css("--k-ag"))}`;
    const co = D.cofin.filter(c => c.m.some(m => m[0] === id)).slice(0, 6);
    if (co.length) html += `<h3>Co-financed projects</h3>` + co.map(c => `<div class="deal">${c.m.map(m => esc(shortName(instName(m[0])))).filter((v,i,a) => a.indexOf(v) === i).join(" + ")} <span class="meta">(shared words: ${esc(c.w.join(", "))})</span></div>`).join("");
    html += `<h3>Largest deals (${ds.length})</h3>${dealList(ds)}`;
  } else if (n.k === "country") {
    const secs = Object.entries(csecNow(id)).sort((a, b) => b[1] - a[1]);
    html += `<h3>Sectors it receives money in</h3>` + (secs.length ? bars(secs.slice(0, 11).map(([s, v]) => [s, v]), css("--k-sec")) : `<p class="hint">No sector recorded.</p>`) +
      `<p class="hint">Shown as green links on the graph. Click empty space to hide them.</p>` +
      `<h3>Institutions</h3>${bars(grp("institution"), css("--t-dfi"))}<h3>Largest deals</h3>${dealList(D.deals.filter(d => d.c.includes(id)))}`;
  } else if (n.k === "memberstate") {
    html += `<h3>Institutions</h3>${bars(grp("institution"), css("--t-dfi"))}`;
    const ags = nb.filter(([m]) => m.k === "agency").map(([m]) => m);
    if (ags.length) html += `<h3>Its agencies implementing EU funds</h3>` + ags.map(m => `<div class="deal">${esc(m.l)} <span class="meta">implements ${fmt(m.v)} of EU money in the Franc Zone, counted under the EU, not under ${esc(n.l)}</span></div>`).join("");
  } else if (n.k === "sector") {
    html += `<h3>Institutions</h3>${bars(grp("institution"), css("--t-dfi"))}<h3>Largest deals</h3>${dealList(D.deals.filter(d => d.s === id))}`;
  } else if (n.k === "agency") {
    const msn = nb.find(([m]) => m.k === "memberstate");
    html += `<p class="hint">${msn ? `A public agency of ${esc(msn[0].l)}. ` : ""}EU money (Commission, EU Trust Fund for Africa, blending, EU-AITF) entrusted to this agency to implement; counted under the EU, not under ${msn ? esc(msn[0].l) : "the member state"}. Its own national budget is not in this network.</p><h3>From</h3>${bars(grp("institution"), css("--t-eu"))}<h3>Largest EU-funded deals it implements</h3>${dealList(D.deals.filter(d => d.g === id))}`;
  } else if (n.k === "contractor") {
    const key = g => "x:" + g.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60);
    const cs = (D.contracts || []).filter(c => (c.g || []).some(([g]) => key(g) === n.id));
    const ctry = [...new Set(cs.map(c => (D.countries[c.c] || {}).n || c.c))];
    html += `<p class="hint">${esc(n.l)} won ${cs.length} contract${cs.length === 1 ? "" : "s"} financed by AFD (with EU financial participation) in ${ctry.map(esc).join(", ")}, alone or in consortia; subsidiaries are grouped under their parent company.</p><h3>Contracts</h3>` +
      cs.sort((a, b) => b.v - a.v).map(c => `<div class="deal">${esc(c.o || c.p)}<div class="meta">${esc((D.countries[c.c] || {}).n || c.c)}${c.d ? ", signed " + esc(c.d) : ""} · project ${esc(c.p)} (${esc(c.proj)})</div>
        <div class="meta">Contract holder: ${esc(c.f)} · <span class="amt">${fmt(c.v)}</span>${c.parts > 1 ? ` · ${c.parts} partners: share credited here ${fmt(c.v / c.parts)} (estimate)` : ""}${c.flag ? " · amount read as euros (entered in the thousand-euro column)" : ""}</div></div>`).join("") +
      `<p class="hint">Source: AFD open data, contracts financed by AFD with EU financial participation. This dataset does not cover contracts financed by other lenders (for example the AfDB).</p>`;
  } else if (n.k === "framework") {
    html += `<p class="hint">${esc(n.fk)}. Frameworks carry no amounts in this network: the money appears in the deals of the institutions involved.</p><h3>Linked to</h3>` +
      nb.map(([m]) => `<div class="deal">${esc(m.l)} <span class="meta">${esc(KIND[m.k].label)}</span></div>`).join("") + (n.src ? `<p><a href="${esc(n.src)}" target="_blank" rel="noopener">Source</a></p>` : "");
  }
  p.innerHTML = html;
}
function netIntro() {
  const inPeriod = D.deals.filter(dealOk), tot = inPeriod.reduce((s, d) => s + d.v, 0);
  $("#netpanel").innerHTML = `<h2>The network</h2><p class="hint">European public financial institutions (development banks, DFIs, promotional banks, export credit agencies, EU institutions) and World Bank trust funds financed by European donors, linked to the 14 CFA franc countries they finance since 1999, to their member states, and to the agencies that implement EU funds.</p>
    <div class="big">${fmt(tot)}</div><div class="hint">${inPeriod.length.toLocaleString("en")} deals from ${new Set(inPeriod.map(d => d.i)).size} institutions in scope${SINCE ? ", signed or started since " + SINCE + " (undated deals left out)" : ""}</div>
    <div class="hint">Same total and rules as the tracker's header (investment and development finance since 1999; EU humanitarian aid and foreign-policy grants excluded). ${D.data_status === "live"
      ? `Tracker data of ${esc(D.generated)}, read at this build.`
      : `<span style="color:#ffc9a8">Using a saved copy of the tracker data of ${esc(D.generated)}: this site is not connected to the tracker, so its total may differ. Set TRACKER_SITE_URL in network.py.</span>`}</div>
    <h3>How to read it</h3><p class="hint">Click any dot for its details and sources. Click a country to see the sectors it receives money in. Click empty space to clear. Use the buttons to add sectors or frameworks, "Since" to look at a period, and the search box to find an actor or a deal.</p>
    ${D.site ? `<p><a href="${esc(D.site)}" target="_blank" rel="noopener" style="color:var(--accent)">Open the EU-CFA Public finance tracker</a></p>` : ""}`;
}
netIntro();

// ---------- SEARCH
const NS = $("#nsearch"), NR = $("#nresults");
const fold = s => String(s || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
const KLAB = {institution: "Institution", memberstate: "Member state", country: "Country", sector: "Sector", agency: "Implementing agency", contractor: "Contractor", framework: "Framework"};
const setChip = (key, on) => { const c = document.querySelector(`#layers .chip[data-key="${key}"]`); if (c) c.setAttribute("aria-pressed", String(on)); };
function revealNode(id, keepPanel) {
  if (!keepPanel) dealFocus = null;
  const n = D.nodes.find(x => x.id === id); if (!n) return;
  let changed = false;
  if (n.k === "institution" && !typeOn[n.t]) { typeOn[n.t] = true; setChip("t:" + n.t, true); changed = true; }
  if (["agency", "contractor", "sector", "framework"].includes(n.k) && !layers[n.k]) { layers[n.k] = true; setChip("l:" + n.k, true); changed = true; }
  if (SINCE && !n.v && n.k !== "memberstate") { SINCE = 0; $("#since").value = "0"; changed = true; }   // not active in the chosen period: show all years
  if (changed) buildGraph();
  selected = id;
  if (!keepPanel) panel(nodeById[id] || n);
  if (USE3D && G3) { const g = G3.graphData().nodes.find(x => x.id === id); if (g) setHover(g, true); } else highlight();
}
function dealPanel(d) {
  $("#netpanel").innerHTML = `<h2>${esc(d.t)}</h2><div class="meta">Deal · ${esc(instName(d.i))}</div><div class="big">${fmt(d.v)}</div>
    <div class="hint">${d.c.map(c => esc((D.countries[c] || {}).n || c)).join(", ")} · ${d.y ? esc(d.y) : "no date"} · ${esc(d.n)}${d.s ? " · " + esc(d.s) : ""}${d.e ? " · estimated share" : ""}</div>
    ${d.eu && Object.keys(d.eu).length ? `<h3>EU or member-state money named</h3>` + [...new Set(Object.values(d.eu))].slice(0, 2).map(q => `<div class="meta">“${esc(q)}”</div>`).join("") : ""}
    <p><a href="${esc(d.u)}" target="_blank" rel="noopener" style="color:var(--accent)">Source record</a></p>
    <p class="hint">On the network, the institution and the country${d.c.length === 1 ? "" : "s"} of this deal are lit up. Click empty space to clear.</p>`;
  dealFocus = d;
  revealNode("i:" + d.i, true);
  if (USE3D && G3) setHover(null); else highlight();
}
let stimer;
NS.addEventListener("input", () => { clearTimeout(stimer); stimer = setTimeout(runSearch, 120); });
NS.addEventListener("keydown", e => { if (e.key === "Escape") { NR.hidden = true; NS.blur(); } if (e.key === "Enter") { const b = NR.querySelector("button"); if (b) b.click(); } });
document.addEventListener("click", e => { if (!e.target.closest(".nsearch")) NR.hidden = true; });
function runSearch() {
  const q = fold(NS.value.trim()); if (q.length < 2) { NR.hidden = true; return; }
  const rank = (a, b, la, lb, va, vb) => (fold(la).startsWith(q) ? 0 : 1) - (fold(lb).startsWith(q) ? 0 : 1) || vb - va;
  const actors = D.nodes.filter(n => fold(n.l).includes(q)).sort((a, b) => rank(a, b, a.l, b.l, ORIG_V[a.id] || 0, ORIG_V[b.id] || 0)).slice(0, 8);
  const deals = D.deals.filter(d => fold(d.t).includes(q)).sort((a, b) => b.v - a.v).slice(0, 8);
  NR.innerHTML = (!actors.length && !deals.length) ? `<div class="grp">No match</div>` :
    (actors.length ? `<div class="grp">Actors</div>` + actors.map(n => `<button data-a="${esc(n.id)}">${esc(n.l)}<span class="k">${esc(KLAB[n.k] || n.k)}${n.t ? " · " + esc(TYPELABEL[n.t] || n.t) : ""}</span></button>`).join("") : "") +
    (deals.length ? `<div class="grp">Deals</div>` + deals.map(d => `<button data-d="${esc(d.id)}">${esc(d.t.slice(0, 90))}<span class="k">${esc(shortName(instName(d.i)))} · ${d.c.map(c => esc((D.countries[c] || {}).n || c)).join(", ")}${d.y ? " · " + esc(d.y) : ""} · ${fmt(d.v)}</span></button>`).join("") : "");
  NR.hidden = false;
  NR.querySelectorAll("button[data-a]").forEach(b => b.onclick = () => { NR.hidden = true; revealNode(b.dataset.a); });
  NR.querySelectorAll("button[data-d]").forEach(b => b.onclick = () => { NR.hidden = true; const d = D.deals.find(x => x.id === b.dataset.d); if (d) dealPanel(d); });
}

// ---------- OVERLAP
function drawMatrix() {
  const n = +$("#ovn").value, ids = D.top.slice(0, n), jac = $("#ovm").value === "jac", M = jac ? D.mjac : D.mco;
  const max = Math.max(1, ...ids.flatMap((a, i) => ids.map((b, j) => i === j ? 0 : M[i][j])));
  const col = v => `rgba(64,232,255,${(0.1 + 0.9 * (v / max)).toFixed(3)})`;
  let h = `<p class="hint" style="max-width:760px;margin:0 0 10px">${jac
    ? "Overlap %: of all the country–sector combinations where at least one of the two institutions is active, the share where both are. 0% = never in the same place on the same topic; 100% = always."
    : "Co-financed projects: the number of projects both institutions finance, found by matching their deal titles in the same country (evidence in the panel)."}</p>`;
  h += `<table><tr><th></th>${ids.map(b => `<th class="col"><div>${esc(shortName(instName(b)))}</div></th>`).join("")}</tr>`;
  ids.forEach((a, i) => { h += `<tr><th style="text-align:right">${esc(shortName(instName(a)))}</th>` + ids.map((b, j) => {
      const v = M[i][j];
      if (i === j) return `<td class="diag" style="background:${css(TYPEVAR[(D.inst[a] || {}).t] || "--t-dfi")};color:#000" title="${esc(instName(a))}">●</td>`;
      const pn = D.pairn[a + "|" + b] || [0, 0];
      const tip = jac ? `${shortName(instName(a))} and ${shortName(instName(b))}: ${v}% overlap (both active in ${pn[0]} of the ${pn[1]} country–sector combinations where either is active)`
                      : `${shortName(instName(a))} and ${shortName(instName(b))}: ${v} co-financed project${v === 1 ? "" : "s"}`;
      return `<td data-a="${a}" data-b="${b}" style="background:${v ? col(v) : "transparent"}" title="${esc(tip)}">${v ? v : ""}</td>`; }).join("") + "</tr>"; });
  $("#matrix").innerHTML = h + "</table>";
  $("#matrix").querySelectorAll("td[data-a]").forEach(td => td.onclick = () => pairPanel(td.dataset.a, td.dataset.b));
}
$("#ovm").onchange = drawMatrix;
$("#ovn").onchange = drawMatrix;
function pairPanel(a, b) {
  const key = D.pairs[a + "|" + b] ? a + "|" + b : b + "|" + a, rows = D.pairs[key] || [], flip = key !== a + "|" + b;
  const co = D.cofin.filter(c => c.m.some(m => m[0] === a) && c.m.some(m => m[0] === b));
  $("#ovlpanel").innerHTML = `<h2>${esc(shortName(instName(a)))} and ${esc(shortName(instName(b)))}</h2>
    <div class="big">${(D.pairn[a + "|" + b] || [0, 0])[1] ? Math.round(100 * D.pairn[a + "|" + b][0] / D.pairn[a + "|" + b][1]) : 0}% overlap</div>
    <p class="hint">Both are active in ${(D.pairn[a + "|" + b] || [0])[0]} of the ${(D.pairn[a + "|" + b] || [0, 0])[1]} country–sector combinations where at least one of them works. They co-finance ${co.length} project${co.length === 1 ? "" : "s"} (listed below).</p>
    <h3>Shared countries and sectors</h3>` + (rows.length ? rows.map(r => `<div class="deal">${esc((D.countries[r[0]] || {}).n || r[0])}, ${esc(r[1])}<div class="meta">${esc(shortName(instName(flip ? b : a)))} <span class="amt">${fmt(r[2])}</span>, ${esc(shortName(instName(flip ? a : b)))} <span class="amt">${fmt(r[3])}</span></div></div>`).join("") : `<p class="hint">None.</p>`) +
    `<h3>Co-financed projects</h3>` + (co.length ? co.map(cofinHtml).join("") : `<p class="hint">No project found in both records.</p>`);
}
function cofinHtml(c) { return `<div class="deal"><b>${c.m.map(m => esc(shortName(instName(m[0])))).filter((v,i,a) => a.indexOf(v) === i).join(" + ")}</b>, ${c.c.map(x => esc((D.countries[x] || {}).n || x)).join(", ")}
  <div class="meta">Evidence: both records name ${esc(c.w.join(", "))}</div>` + c.m.map(m => `<div class="meta">· ${esc(shortName(instName(m[0])))}: ${esc(m[1])}${m[2] ? " (" + esc(m[2]) + ")" : ""} <span class="amt">${fmt(m[3])}</span> <a href="${esc(m[4])}" target="_blank" rel="noopener">source</a></div>`).join("") + `</div>`; }
function ovlIntro() {
  $("#ovlpanel").innerHTML = `<h2>Overlap</h2><p class="hint">Two measures, chosen with "Measure": the overlap %, the share of the country–sector combinations where at least one of two institutions is active in which both are; and the number of projects both co-finance. The diagonal marks each institution. Click a cell for the shared countries and sectors and the projects both finance.</p>
    <h3>Co-financed projects (${D.cofin.length})</h3><p class="hint">Deals from different institutions in the same country, within three years, whose titles share distinctive words (for example a dam or company name). The evidence is shown with each match; check the sources before citing.</p>` + D.cofin.slice(0, 25).map(cofinHtml).join("");
}
ovlIntro();

// ---------- EVENTS
const CATVAR = {"Monetary":"--c-mon","Politics & security":"--c-pol","EU–Africa policy":"--c-eu","Financing instrument":"--c-fin","Summit / meeting":"--c-meet"};
const catOn = Object.fromEntries(Object.keys(CATVAR).map(c => [c, true]));
let evCountry = "ALL";
const evt = $("#evtools");
evt.innerHTML = `<label class="ctl">Country <select id="evc"><option value="ALL">All 14 countries</option>${Object.entries(D.countries).filter(([k]) => k.length === 2 && k !== "XW" && k !== "XC").map(([k, c]) => `<option value="${k}">${esc(c.n)}</option>`).join("")}</select></label>`;
Object.keys(CATVAR).forEach(c => { const b = document.createElement("button"); b.className = "chip"; b.setAttribute("aria-pressed", "true");
  b.innerHTML = `<span class="sw" style="background:${css(CATVAR[c])}"></span>${c}`; b.onclick = () => { catOn[c] = !catOn[c]; b.setAttribute("aria-pressed", catOn[c]); drawEvents(); }; evt.append(b); });
$("#evc").onchange = e => { evCountry = e.target.value; drawEvents(); };
// ---------- monthly review: the biggest deals each tracker update added
let reviewMonth = null;
function monthlyReview() {
  const R = D.review || [], base = R.find(r => r.baseline), months = {};
  R.filter(r => !r.baseline).forEach(r => { const k = r.generated.slice(0, 7), o = months[k] || (months[k] = {n: 0, total: 0, top: [], dates: []});
    o.n += r.n; o.total += r.total; o.top.push(...(r.top || [])); o.dates.push(r.generated); });
  const keys = Object.keys(months).sort().reverse();
  const head = `<h2 style="margin:0 0 4px">Monthly review: biggest deals added to the tracker</h2>`;
  if (!keys.length) return head + `<p class="hint">The review starts with the tracker's next update. Starting point recorded with the tracker data of ${esc(base ? base.generated : D.generated)}: ${(base ? base.n : D.deals.length).toLocaleString("en")} deals, ${fmt(base ? base.total : D.deals.reduce((s, d) => s + d.v, 0))}. Each later update will show how many deals it added, their total amount and the 15 largest.</p>`;
  if (!reviewMonth || !months[reviewMonth]) reviewMonth = keys[0];
  const m = months[reviewMonth], top = m.top.slice().sort((a, b) => b[4] - a[4]).slice(0, 15);
  const label = k => new Date(k + "-01T00:00:00").toLocaleDateString("en-GB", {month: "long", year: "numeric"});
  return head + `<label class="ctl revm">Month <select id="revm">${keys.map(k => `<option value="${k}"${k === reviewMonth ? " selected" : ""}>${label(k)}</option>`).join("")}</select></label>
    <p><span class="big">${fmt(m.total)}</span> <span class="hint">added in ${m.n.toLocaleString("en")} new deal${m.n === 1 ? "" : "s"} by the tracker update${m.dates.length > 1 ? "s" : ""} of ${m.dates.map(esc).join(", ")}. New to the tracker, whatever their signing year (a new source can add older deals).</span></p>` +
    (top.length ? `<div class="revwrap"><table class="revtab"><tr><th>#</th><th>Deal</th><th>Institution</th><th>Countries</th><th>Year</th><th>Amount</th></tr>` +
      top.map((t, i) => `<tr><td>${i + 1}</td><td><a href="${esc(t[5])}" target="_blank" rel="noopener">${esc(t[1])}</a></td><td>${esc(shortName(instName(t[0])))}</td><td>${t[2].map(c => esc((D.countries[c] || {}).n || c)).join(", ")}</td><td>${esc(t[3] || "–")}</td><td class="amt">${fmt(t[4])}</td></tr>`).join("") + `</table></div>`
      : `<p class="hint">No new deals in this update.</p>`);
}
function drawEvents() {
  const evs = D.events.filter(e => catOn[e.cat] !== false && (evCountry === "ALL" || e.cc.includes("ALL") || e.cc.includes(evCountry)));
  const types = Object.keys(TYPEVAR), key = evCountry === "ALL" ? "ALL" : evCountry;
  const ys = D.years, stack = ys.map((y, i) => types.map(t => ((D.timeline[key + "|" + t] || [])[i]) || 0));
  const W = Math.max(600, $("#evmain").clientWidth - 40), H = 260, pad = {l: 56, r: 10, t: 14, b: 26};
  const x = d3.scaleBand().domain(ys).range([pad.l, W - pad.r]).padding(0.15), ymax = d3.max(stack, s => d3.sum(s)) || 1;
  const y = d3.scaleLinear().domain([0, ymax]).nice().range([H - pad.b, pad.t]);
  let svgs = `<svg width="${W}" height="${H}" role="img" aria-label="European commitments per year with events">`;
  y.ticks(4).forEach(t => svgs += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y(t)}" y2="${y(t)}" stroke="#163746"/><text x="${pad.l - 6}" y="${y(t) + 4}" text-anchor="end" fill="#8db1c0" font-size="11">${fmt(t)}</text>`);
  ys.forEach((yr, i) => { let acc = 0; types.forEach((t, j) => { const v = stack[i][j]; if (!v) return;
    svgs += `<rect x="${x(yr)}" width="${x.bandwidth()}" y="${y(acc + v)}" height="${y(acc) - y(acc + v)}" fill="${css(TYPEVAR[t])}"><title>${yr}, ${TYPELABEL[t]}: ${fmt(v)}</title></rect>`; acc += v; });
    if (i % 3 === 0) svgs += `<text x="${x(yr) + x.bandwidth() / 2}" y="${H - 8}" text-anchor="middle" fill="#8db1c0" font-size="11">${yr}</text>`; });
  evs.forEach(e => { const yr = +e.d.slice(0, 4); if (!ys.includes(yr)) return; const cx = x(yr) + x.bandwidth() * ((+e.d.slice(5, 7) || 6) / 12);
    svgs += `<line x1="${cx}" x2="${cx}" y1="${pad.t}" y2="${H - pad.b}" stroke="${css(CATVAR[e.cat] || "--accent")}" stroke-dasharray="2 3"><title>${esc(e.d)}: ${esc(e.t)}</title></line><circle cx="${cx}" cy="${pad.t + 2}" r="4" fill="${css(CATVAR[e.cat] || "--accent")}"><title>${esc(e.d)}: ${esc(e.t)}</title></circle>`; });
  svgs += `</svg>`;
  const up = evs.filter(e => e.st !== "past"), past = evs.filter(e => e.st === "past").reverse();
  const reviewHtml = monthlyReview();
  const row = e => `<div class="ev ${e.st !== "past" ? "up" : ""}"><div class="d">${esc(e.d)}${e.e ? "<br>to " + esc(e.e) : ""}</div><div><span class="badge" style="border-color:${css(CATVAR[e.cat] || "--line-hi")}">${esc(e.cat)}</span>${e.st !== "past" ? `<span class="badge">${esc(e.st)}</span>` : ""}<b>${esc(e.t)}</b><div class="meta">${esc(e.x)}</div><div class="meta">${e.cc.includes("ALL") ? "All countries" : e.cc.map(c => esc((D.countries[c] || {}).n || c)).join(", ")} · <a href="${esc(e.u)}" target="_blank" rel="noopener">source</a></div></div></div>`;
  $("#evmain").innerHTML = reviewHtml + `<h2 style="margin:26px 0 4px">European commitments per year${evCountry === "ALL" ? "" : " in " + esc(D.countries[evCountry].n)}, with events</h2>
    <p class="hint">Bars: euros committed by the institutions in scope, by year of signature or start (undated deals left out). Dashed lines: events, coloured by category; hover for details.</p>${svgs}
    <h2>Coming up (${up.length})</h2>${up.map(row).join("") || `<p class="hint">No upcoming event in this selection.</p>`}<h2>Past events (${past.length})</h2>${past.map(row).join("")}`;
  const rv = $("#revm"); if (rv) rv.onchange = e => { reviewMonth = e.target.value; drawEvents(); };
  const tot = ys.map((yr, i) => [yr, d3.sum(stack[i])]);
  const before = (y0, y1) => d3.sum(tot.filter(([yr]) => yr >= y0 && yr <= y1), t => t[1]);
  $("#evpanel").innerHTML = `<h2>Events</h2><p class="hint">Summits, monetary reforms, coups and sanctions, and new financing instruments since the 1999 euro peg, plus scheduled meetings. Every event links its source; the list lives in data/events.csv and can be edited on GitHub.</p>
    <h3>Commitments by period${evCountry === "ALL" ? "" : " (" + esc(D.countries[evCountry].n) + ")"}</h3>` +
    bars([["1999–2009", before(1999, 2009)], ["2010–2019", before(2010, 2019)], ["2020–2022", before(2020, 2022)], ["2023 onward", before(2023, 2100)]], css("--accent")) +
    (D.warnings.length ? `<h3>Build warnings</h3>` + D.warnings.map(w => `<div class="warn">${esc(w)}</div>`).join("") : "");
}

// ---------- SOURCES
(() => {
  const row = s => `<div class="deal"><b>${esc(s.name)}</b><div class="meta">${esc(s.provider)} · ${esc(s.method)}${s.records ? " · " + s.records.toLocaleString("en") + " deals" : ""}</div>
    <div class="meta">${esc(s.provides)}</div><div class="meta">Licence: ${esc(s.licence)}${s.url ? ` · <a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.url.replace(/^https?:\/\//, "").slice(0, 70))}</a>` : ""}</div></div>`;
  const TS = D.tracker_sources || [], roles = ["Figures", "Regional layer", "Programmes", "Reference", "Recommended next"];
  const evBad = D.warnings.filter(w => w.startsWith("Event"));
  const LC = D.tracker_checks || {};
  $("#sources").innerHTML = `<h2>Sources</h2>
    <p>Every deal in this network comes from the EU-CFA Public finance tracker and links to the record it came from: click any dot, then "source". Events link their own sources. Below: this site's own sources, then the tracker's full source register.</p>
    <h2>This site</h2>${D.own_sources.map(row).join("")}
    <h3>Event sources checked at this build: ${D.events.length - evBad.length} of ${D.events.length} answered normally</h3>${evBad.map(w => `<div class="warn">${esc(w)}</div>`).join("")}
    <h2>The tracker's sources</h2>` + (TS.length ? roles.map(r => { const rs = TS.filter(s => s.role === r); return rs.length ? `<h3>${esc(r)}</h3>` + rs.map(row).join("") : ""; }).join("") +
    (LC.checked ? `<h3>Tracker link check: ${LC.ok} of ${LC.checked} cited links answered normally</h3>` + (LC.problems || []).map(([u, c, used]) => `<div class="warn">${esc(c)}: <a href="${esc(u)}" target="_blank" rel="noopener" style="color:inherit">${esc(u.slice(0, 80))}</a> (${esc(used.join("; "))})</div>`).join("") +
      `<p class="hint">Some sites refuse automated checks (403) but open in a browser; Capacity4dev pages need a login.</p>` : "")
    : `<p class="hint">The tracker's source register appears here once the tracker has run with its new Sources feature.</p>`);
})();

// ---------- ALL ACTORS, by category and in alphabetical order
function noAmount(n) {   // why an actor shows no euro amount
  const out = D.links.filter(l => l.s === n.id).map(l => (D.nodes.find(x => x.id === l.t) || {}).k).filter(k => k !== "framework");
  if (n.k === "memberstate" && out.length && out.every(k => k === "agency")) return "linked through its implementing agency only (it implements EU money)";
  if (n.k === "memberstate" || n.k === "institution") return "deals recorded, amounts not published";
  return "no amount published";
}
function actorDirectory() {
  const MSN = {FR:"France",DE:"Germany",NL:"Netherlands",BE:"Belgium",FI:"Finland",DK:"Denmark",SE:"Sweden",AT:"Austria",ES:"Spain",IT:"Italy",PT:"Portugal",
    PL:"Poland",CZ:"Czechia",SK:"Slovakia",HR:"Croatia",GR:"Greece",SI:"Slovenia",HU:"Hungary",RO:"Romania",BG:"Bulgaria",EE:"Estonia",LV:"Latvia",LT:"Lithuania",
    IE:"Ireland",LU:"Luxembourg",EU:"European Union",INT:"Multilateral (EU-majority)",WBTF:"World Bank trust funds"};
  const abc = (a, b) => a.l.localeCompare(b.l, "fr", {sensitivity: "base"});
  const N = D.nodes;
  const cats = [
    ["Member states and the European Union", "Owners of the institutions below; amounts are the total of their institutions (for the EBRD, the EU-held 54.4%).", N.filter(n => n.k === "memberstate")],
    ["EU institutions", "", N.filter(n => n.k === "institution" && n.t === "EU institution")],
    ["Development banks", "", N.filter(n => n.k === "institution" && n.t === "Bilateral development bank")],
    ["Development finance institutions (DFIs)", "", N.filter(n => n.k === "institution" && n.t === "DFI")],
    ["Promotional banks", "", N.filter(n => n.k === "institution" && n.t === "NPB")],
    ["Export credit agencies", "", N.filter(n => n.k === "institution" && n.t === "ECA")],
    ["Multilateral bank with an EU majority", "", N.filter(n => n.k === "institution" && n.t === "Multilateral")],
    ["World Bank trust funds financed by European donors", "", N.filter(n => n.k === "institution" && n.t === "World Bank trust fund")],
    ["Implementing agencies (EU funds)", "Member-state agencies entrusted with EU money; amounts are EU funds they implement, counted under the EU.", N.filter(n => n.k === "agency")],
    ["Contractors (European firms)", "Firms of EU nationality that won contracts under AFD projects co-financed by the EU; amounts are contract values, not added to any total.", N.filter(n => n.k === "contractor")],
    ["Recipient countries", "", N.filter(n => n.k === "country")]];
  return `<h2 id="actors">All actors</h2><p>Every actor in this network, by category and in alphabetical order.</p>` + cats.filter(c => c[2].length).map(([title, note, list]) =>
    `<h3>${esc(title)} (${list.length})</h3>${note ? `<p class="hint">${esc(note)}</p>` : ""}<ul class="actors">` +
    list.slice().sort(abc).map(n => `<li><b>${esc(n.l)}</b>${n.ms && n.k !== "memberstate" ? ` <span class="meta">${esc(MSN[n.ms] || n.ms)}</span>` : ""}${n.v ? ` <span class="amt">${fmt(n.v)}</span>` : ` <span class="meta">${esc(noAmount(n))}</span>`}</li>`).join("") + `</ul>`).join("");
}

// ---------- ABOUT
$("#about").innerHTML = `<h2>About this tracker</h2>
  <p>The EU-CFA Network tracker shows how European public financial institutions connect, overlap and respond to events in the 14 countries of the CFA franc zone: the eight WAEMU countries in West Africa and the six CEMAC countries in Central Africa (the Comoros are not covered). It is a companion to the EU-CFA Public finance tracker and reads that tracker's data, so both always show the same deals.</p>
  <h2>Scope</h2><ul><li>Included: European development banks and DFIs, national promotional banks, export credit agencies, EU institutions (the EIB, the European Commission, the EU Trust Fund for Africa, EU blending grants, the EU-Africa Infrastructure Trust Fund, ElectriFI and AgriFI), and World Bank-managed trust funds financed only by European donors.</li>
  <li>Not included: the EBRD, EU humanitarian aid and foreign-policy instruments, and non-European financiers.</li></ul>
  <h2>Method</h2><ul><li>Network: links are weighted by euros attributed to Franc Zone countries since 1999. EU money implemented by a member-state agency (AFD, GIZ, Expertise France, Enabel and others) is linked from the EU institution to that agency and counted under the EU.</li>
  <li>Overlap %: for two institutions, the share of the country–sector combinations where at least one of them is active in which both are (0% to 100%; deals with unpublished amounts count as activity). Co-financed projects: the number of projects both finance, found by matching their deal titles (see below).</li>
  <li>Co-financed projects: deals by different institutions in the same country, within three years of each other, whose titles share distinctive words. The shared words are shown as evidence. This is a rule-based match: check the sources before citing a project as co-financed.</li>
  <li>Events: hand-checked, each with its source; the build tests every source link and lists any that fail under Events.</li></ul>
  <h2>Data</h2><p>Tracker data dated ${esc(D.generated)}; this page built on ${esc(D.built)}. Every deal links to its source record.</p>` + actorDirectory();

buildGraph();
addEventListener("resize", () => { clearTimeout(window._rz); window._rz = setTimeout(buildGraph, 300); });
})();
</script>
</body>
</html>
'''

try:
    TEMPLATE
except NameError:  # during development the page template is a separate file
    TEMPLATE = (ROOT / "template.html").read_text(encoding="utf-8")

# ---------------------------------------------------------------- 7. write the page
own_sources = [
    {"name": "EU-CFA Public finance tracker data", "provider": "Your tracker (data/tracker.json)", "url": TRACKER_DATA_URL or TRACKER_SITE_URL,
     "method": "Read at every build" if TRACKER_DATA_URL else "Saved copy in data/tracker.json", "licence": "Same as the tracker's sources (see below)",
     "provides": f"All deals, institutions, countries and programmes, data of {generated}. Each deal links to its original record."},
    {"name": "Event log", "provider": "data/events.csv", "url": "", "method": "Hand-checked; every link tested at build",
     "licence": "Per event", "provides": f"{len(events)} events, each with its own source (listed in the Events tab)."},
    {"name": "Contracts financed by AFD with EU financial participation", "provider": "AFD open data (opendata.afd.fr)",
     "url": "https://opendata.afd.fr/explore/dataset/liste-des-marches-finances-par-lafd-avec-la-participation-financiere-de-lunion-e/",
     "method": "Data feed, read at every build", "licence": "Licence Ouverte / Etalab 2.0",
     "provides": f"Winning firm, its nationality, amount, date and project for each contract; {len(contracts)} contracts won by European firms in Franc Zone countries are shown as the contractors layer."},
    {"name": "D3.js graphics library", "provider": "Mike Bostock and contributors", "url": "https://d3js.org", "method": "Downloaded once and embedded",
     "licence": "ISC", "provides": "Draws the network, the matrix and the timeline."}]
bundle = {"generated": generated, "built": TODAY.isoformat(), "site": TRACKER_SITE_URL or ("../" if IN_TRACKER else ""), "data_status": data_status,
          "own_sources": own_sources, "tracker_sources": T.get("sources", []), "tracker_checks": T.get("link_checks", {}),
          "inst": {k: {"n": v["name"], "t": v["type"], "ms": v["member_state"]} for k, v in INST.items()},
          "countries": {k: {"n": v["name"], "u": v.get("union", "")} for k, v in COUNTRIES.items()},
          "nodes": list(nodes.values()), "links": [{"s": a, "t": b, **v} for (a, b), v in links.items()],
          "deals": list(deals.values()), "csec": csec, "ebrd": {"share": EBRD_EU_SHARE, "src": EBRD_SHARE_SRC}, "contracts": contracts, "mjac": mjac, "mco": mco, "pairn": pairn, "top": top, "matrix": matrix, "pairs": pair_detail, "cofin": cofin[:150],
          "years": years, "timeline": timeline, "events": events, "warnings": warnings, "review": review}
d3 = REF / "d3.min.js"
if not d3.exists():
    d3.write_bytes(get("https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js"))
LIBS = {"three.min.js": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.min.js",
        "3d-force-graph.min.js": "https://cdn.jsdelivr.net/npm/3d-force-graph@1.73.4/dist/3d-force-graph.min.js"}
for name, url in LIBS.items():
    if not (REF / name).exists():
        (REF / name).write_bytes(get(url))
html = (TEMPLATE.replace("/*__DATA__*/null", json.dumps(bundle, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
                .replace("/*__D3__*/", d3.read_text(encoding="utf-8"))
                .replace("/*__THREE__*/", (REF / "three.min.js").read_text(encoding="utf-8").replace("console.warn('Scripts", "void('Scripts", 1))
                .replace("/*__FG3D__*/", (REF / "3d-force-graph.min.js").read_text(encoding="utf-8")))
(SITE / "index.html").write_text(html, encoding="utf-8")
json.dump({"hash": _hash, "generated": generated, "built": TODAY.isoformat()}, open(_state, "w"))
print(f"site/index.html {len(html.encode()) / 1e6:.2f} MB | {len(nodes)} nodes, {len(links)} links, {len(deals)} deals, "
      f"{len(cofin)} co-financed projects, {len(events)} events, {len(warnings)} warnings")
for w in warnings:
    print("warning:", w)
