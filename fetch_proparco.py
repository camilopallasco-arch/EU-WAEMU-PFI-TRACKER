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
