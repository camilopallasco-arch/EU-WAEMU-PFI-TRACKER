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
