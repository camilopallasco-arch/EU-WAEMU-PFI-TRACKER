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
SEED_KNOWN = "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"   # deals known on 2026-10-27, with their titles
import zlib as _zlib, base64 as _b64
seed = json.loads(_zlib.decompress(_b64.b64decode(SEED_KNOWN)))
known = json.load(open(known_path, encoding="utf-8")) if known_path.exists() else seed
def deal_key(d):   # institution + title: recognises a deal that its source re-published under a new identifier
    return [d["i"], re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKD", d["t"]).encode("ascii", "ignore").decode().lower()).strip()]
current_ids = sorted(deals)
def review_entry(prev):
    prev_ids, prev_keys = set(prev.get("ids", [])), prev.get("keys", {})
    gone = {tuple(prev_keys[i]) for i in prev_ids - set(current_ids) if i in prev_keys}
    fresh = [deals[i] for i in set(current_ids) - prev_ids]
    reid = [d for d in fresh if tuple(deal_key(d)) in gone]            # same deal, new identifier: not new money
    new = sorted((d for d in fresh if tuple(deal_key(d)) not in gone), key=lambda d: -d["v"])
    yr = int(generated[:4]) if generated[:4].isdigit() else TODAY.year
    recent = lambda d: bool(d["y"]) and d["y"].isdigit() and int(d["y"]) >= yr - 1
    return {"generated": generated, "baseline": False, "since": prev.get("generated", ""), "n": len(new),
            "total": round(sum(d["v"] for d in new)), "recent_n": sum(1 for d in new if recent(d)),
            "recent_total": round(sum(d["v"] for d in new if recent(d))), "reid": len(reid),
            "top": [[d["i"], d["t"], d["c"], d["y"], round(d["v"]), d["u"], d["n"], d["s"], recent(d)] for d in new[:15]]}
if known is None:
    review.append({"generated": generated, "baseline": True, "n": len(current_ids), "total": round(sum(d["v"] for d in deals.values()))})
elif known.get("generated") != generated:
    review = [r for r in review if r.get("generated") != generated]
    review.append(review_entry(known))
# reviews made before identifier changes were recognised: recompute them against the saved starting point
for k, r in enumerate(review):
    if not r.get("baseline") and "reid" not in r and r.get("generated") == generated and r.get("since") == seed.get("generated"):
        review[k] = review_entry(seed)
json.dump({"generated": generated, "ids": current_ids, "keys": {i: deal_key(deals[i]) for i in current_ids}}, open(known_path, "w"))
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
lay.append(minWrap); $("#since").onchange = e => { SINCE = +e.target.value; buildGraph(); refreshPanel(); };
// the right-hand panel always shows the chosen period: an actor's figures are recalculated, a deal stays as it is
function refreshPanel() {
  if (dealFocus) return;                                   // a deal's own amount does not depend on the period
  if (selected && nodeById[selected]) panel(nodeById[selected]); else netIntro();
}
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
  const period = SINCE ? `since ${SINCE} (deals without a date left out)` : "since 1999";
  if (n.v) html += `<div class="big">${fmt(n.v)}</div><div class="hint">attributed to Franc Zone countries ${period}</div>`;
  else if (SINCE && ORIG_V[n.id]) html += `<div class="big">€0</div><div class="hint">no deals with a published amount ${period}; all years: ${fmt(ORIG_V[n.id])}</div>`;
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
      `<p class="hint">To see sectors on the network, switch on the Sectors button.</p>` +
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
    <h3>How to read it</h3><p class="hint">Click any dot for its details and sources. Click a country to see, in this panel, the sectors it receives money in. Click empty space to clear. Use the buttons to add sectors or frameworks, "Since" to look at a period, and the search box to find an actor or a deal.</p>
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
    o.n += r.n; o.total += r.total; o.top.push(...(r.top || [])); o.dates.push(r.generated);
    o.rn = (o.rn || 0) + (r.recent_n || 0); o.rt = (o.rt || 0) + (r.recent_total || 0); o.reid = (o.reid || 0) + (r.reid || 0); });
  const keys = Object.keys(months).sort().reverse();
  const head = `<h2 style="margin:0 0 4px">Monthly review: biggest deals added to the tracker</h2>`;
  if (!keys.length) return head + `<p class="hint">The review starts with the tracker's next update. Starting point recorded with the tracker data of ${esc(base ? base.generated : D.generated)}: ${(base ? base.n : D.deals.length).toLocaleString("en")} deals, ${fmt(base ? base.total : D.deals.reduce((s, d) => s + d.v, 0))}. Each later update will show how many deals it added, their total amount and the 15 largest.</p>`;
  if (!reviewMonth || !months[reviewMonth]) reviewMonth = keys[0];
  const m = months[reviewMonth], top = m.top.slice().sort((a, b) => b[4] - a[4]).slice(0, 15);
  const label = k => new Date(k + "-01T00:00:00").toLocaleDateString("en-GB", {month: "long", year: "numeric"});
  return head + `<label class="ctl revm">Month <select id="revm">${keys.map(k => `<option value="${k}"${k === reviewMonth ? " selected" : ""}>${label(k)}</option>`).join("")}</select></label>
    <p><span class="big">${fmt(m.total)}</span> <span class="hint">added in ${m.n.toLocaleString("en")} new deal${m.n === 1 ? "" : "s"} by the tracker update${m.dates.length > 1 ? "s" : ""} of ${m.dates.map(esc).join(", ")}:
      <b>${fmt(m.rt || 0)}</b> in ${m.rn || 0} recently signed deal${m.rn === 1 ? "" : "s"} (signed this year or last), and ${fmt(m.total - (m.rt || 0))} in ${m.n - (m.rn || 0)} older deal${m.n - (m.rn || 0) === 1 ? "" : "s"} that their source published only now.
      ${m.reid ? `${m.reid} record${m.reid === 1 ? " that its source" : "s that their sources"} merely re-published under a new identifier ${m.reid === 1 ? "is" : "are"} not counted.` : ""}</span></p>` +
    (top.length ? `<div class="revwrap"><table class="revtab"><tr><th>#</th><th>Deal</th><th>Institution</th><th>Countries</th><th>Year</th><th>Type</th><th>Amount</th></tr>` +
      top.map((t, i) => `<tr><td>${i + 1}</td><td><a href="${esc(t[5])}" target="_blank" rel="noopener">${esc(t[1])}</a></td><td>${esc(shortName(instName(t[0])))}</td><td>${t[2].map(c => esc((D.countries[c] || {}).n || c)).join(", ")}</td><td>${esc(t[3] || "–")}</td><td>${t[8] === undefined ? "" : t[8] ? "Recently signed" : "Older, newly published"}</td><td class="amt">${fmt(t[4])}</td></tr>`).join("") + `</table></div>`
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
