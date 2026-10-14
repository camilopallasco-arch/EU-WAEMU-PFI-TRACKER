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
