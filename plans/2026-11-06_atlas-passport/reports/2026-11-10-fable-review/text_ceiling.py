"""Потолок набора по ТЕКСТУ паспорта (то, что видит агент), а не по JSON без среза.

Адрес достижим, если в тексте есть `путь:строка` в окне line±tolerance (line null — любой адрес пути или сам путь).
Строки членов вида `имя(...)  :N` относятся к пути из заголовка паспорта.
"""
import json, re, sys

def addresses(text):
    out = set(); cur = None
    for line in text.splitlines():
        m = re.match(r"^== (?:unit |file )?(.+?) ==$", line)
        if m:
            ident = m.group(1); cur = ident.split("::")[0] if ("/" in ident and ident.split("::")[0].endswith(".py")) else None
            if cur: out.add((cur, None))
            continue
        for p, n in re.findall(r"([\w./\-]+\.[A-Za-z]+):(\d+)", line):
            out.add((p, int(n)))
        for p in re.findall(r"([\w./\-]+/[\w.\-]+\.py)\b", line):
            out.add((p, None))
        m = re.search(r"\s:(\d+)\s*$", line)
        if m and cur:
            out.add((cur, int(m.group(1))))
    return out

def reachable(item, addrs):
    path = item["path"]; line = item.get("line"); tol = item.get("tolerance", 3)
    for p, n in addrs:
        if p != path: continue
        if line is None: return True
        if n is not None and abs(n - line) <= tol: return True
    return False

qs = json.load(open(sys.argv[1])); addrs = addresses(open(sys.argv[2]).read())
k = n = 0
for q in qs["questions"]:
    if not q.get("scored", True) or not q.get("expected"): continue
    n += 1
    flags = [reachable(e, addrs) for e in q["expected"]]
    ok = all(flags) if q.get("require", "any") == "all" else any(flags)
    k += ok
    miss = [f'{e["path"].split("/")[-1]}:{e.get("line")}' for e, f in zip(q["expected"], flags) if not f]
    print(f'{q["id"]} reachable={"yes" if ok else "no"}' + (f'  нет: {", ".join(miss)}' if miss and not ok else ""))
print(f"text-ceiling: {k}/{n}")
