"""Inline data/tracker.json and the world map into the page template -> site/index.html
The template can sit either in site/template.html or at the top level as template.html."""
import json, pathlib
root = pathlib.Path(__file__).parent
tpl_path = next((p for p in [root / "site" / "template.html", root / "template.html"] if p.exists()), None)
if tpl_path is None:
    raise SystemExit("template.html not found: upload it to the top level of the repository")
tpl = tpl_path.read_text(encoding="utf-8")
data = json.dumps(json.load(open(root / "data" / "tracker.json", encoding="utf-8")), ensure_ascii=False, separators=(",", ":"))
world = (root / "ref" / "countries-110m.json").read_text(encoding="utf-8")
safe = lambda s: s.replace("</", "<\\/")
html = tpl.replace("/*__DATA__*/null", safe(data)).replace("/*__WORLD__*/null", safe(world))
(root / "site").mkdir(exist_ok=True)
(root / "site" / "index.html").write_text(html, encoding="utf-8")
print("site/index.html", round(len(html.encode()) / 1e6, 2), "MB, template:", tpl_path.relative_to(root))
