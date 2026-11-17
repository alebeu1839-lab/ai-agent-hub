"""Phase 8: local read-only status dashboard written as a static HTML file.

Output is not published and does not start a network server.
"""
from collections import Counter
from html import escape
from pathlib import Path

def render_dashboard(store, *, project_id=None, title="AI Agent Hub"):
    tasks=store.list_tasks(project_id)
    counts=Counter(t["state"] for t in tasks)
    rows=[]
    for t in tasks:
        parts=(t["title"],t["department"],t["state"],t.get("executor") or "-",
               t.get("output_ref") or "-")
        rows.append("<tr>"+"".join("<td>"+escape(str(p), quote=True)+"</td>" for p in parts)+"</tr>")
    cards="".join(
        "<div class='stat'><strong>"+escape(k)+"</strong><span>"+str(v)+"</span></div>"
        for k,v in sorted(counts.items()))
    if not rows:
        rows=["<tr><td colspan='5'>No tasks yet</td></tr>"]
    heading=escape(title,quote=True)
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{heading} — Status</title>
<style>
:root{{color-scheme:light dark;font:16px system-ui,sans-serif}}
body{{max-width:1100px;margin:2rem auto;padding:0 1rem}}
.stats{{display:flex;gap:.7rem;flex-wrap:wrap;margin:1.2rem 0}}
.stat{{padding:1rem;border:1px solid #8885;border-radius:12px;min-width:120px;display:flex;gap:1rem;justify-content:space-between}}
table{{width:100%;border-collapse:collapse;font-size:.9rem}}
td,th{{padding:.8rem;text-align:left;border-bottom:1px solid #8885;overflow-wrap:anywhere}}
.wrap{{overflow-x:auto}}
small{{opacity:.7}}
</style></head><body>
<h1>{heading}</h1>
<p>Local static snapshot — read only. No external calls or actions.</p>
<p><strong>Total tasks: {len(tasks)}</strong></p>
<div class="stats">{cards}</div>
<div class="wrap"><table><thead><tr>
<th>Task</th><th>Department</th><th>State</th><th>Executor</th><th>Output</th>
</tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<small>Not a live dashboard. Refresh by regenerating the file.</small>
</body></html>"""

def write_dashboard(store, path, *, project_id=None):
    destination=Path(path)
    if destination.suffix.lower() != ".html":
        raise ValueError("dashboard output must be .html")
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(render_dashboard(store,project_id=project_id),encoding="utf-8")
    return destination
