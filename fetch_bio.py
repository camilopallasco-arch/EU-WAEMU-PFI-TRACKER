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
