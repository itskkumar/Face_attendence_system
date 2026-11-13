"""Cross-check: every api(...) call in frontend/src has a matching route in backend/app.py. Run from the repo root."""
import re, sys, glob
sys.path.insert(0, "frontend")
back = open("backend/app.py").read()
routes = set()
for m in re.finditer(r'@app\.(get|post|put|patch|delete|websocket)\("([^"]+)"', back):
    routes.add((m.group(1).upper(), re.sub(r"\{[^}]+\}", "{}", m.group(2))))
front = set()
for f in glob.glob("frontend/src/**/*.ts*", recursive=True):
    t = open(f).read()
    for m in re.finditer(r'api(?:<[^>]*>)?\(\s*[`"\']([^`"\']+)[`"\'](?:\s*,\s*\{([^}]*)\})?', t):
        path = m.group(1).split("?")[0]
        meth = re.search(r'method:\s*"(\w+)"', m.group(2) or "")
        front.add(((meth.group(1) if meth else "GET"), "/api" + re.sub(r"\$\{[^}]+\}", "{}", path), f.split("src/")[1]))
missing = [(m, p, f) for m, p, f in sorted(front) if (m, p) not in routes]
print("frontend calls:", len(front), "| backend routes:", len(routes))
for x in missing: print("NO BACKEND ROUTE:", x)
