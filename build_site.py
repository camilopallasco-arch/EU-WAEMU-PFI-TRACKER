"""Inline data/tracker.json and the world map into site/template.html -> site/index.html"""
import json, pathlib
root = pathlib.Path(__file__).parent
tpl = (root / "site" / "template.html").read_text(encoding="utf-8")
data = json.dumps(json.load(open(root / "data" / "tracker.json", encoding="utf-8")), ensure_ascii=False, separators=(",", ":"))
world = (root / "ref" / "countries-110m.json").read_text(encoding="utf-8")
safe = lambda s: s.replace("</", "<\\/")
html = tpl.replace("/*__DATA__*/null", safe(data)).replace("/*__WORLD__*/null", safe(world))
(root / "site" / "index.html").write_text(html, encoding="utf-8")
print("site/index.html", round(len(html.encode()) / 1e6, 2), "MB")
