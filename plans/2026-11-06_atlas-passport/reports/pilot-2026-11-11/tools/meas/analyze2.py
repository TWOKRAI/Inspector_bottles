"""Дополнение к п.3-п.6: срезы популяции, правило R4 (прод вперёд тиров), тайбрейки сортировки."""
import json, math
from collections import Counter, defaultdict
from pathlib import Path
H = Path(__file__).resolve().parent
rows = json.loads((H / "defs.json").read_text())["rows"]
SIDE = ("docs/", "plans/", ".claude/")
def isdef(r): return r["kind"] in ("function", "nested_function", "class", "method")
def cls(r):
    d = "." in r["qualname"]
    return ("def_tail" if d else "def_exact") if isdef(r) else ("bind_tail" if d else "bind_exact")
by = defaultdict(list)
for r in rows: by[r["qualname"].rsplit(".", 1)[-1]].append(r)
def ids(rs): return {(r["path"], r["qualname"]) for r in rs}
def prod_rule(c):
    p = [r for r in c if r["scope"] == "prod"]
    return p if len(ids(p)) == 1 and len(ids(c)) > 1 else c
def R1(rs):
    g = defaultdict(list)
    for r in rs: g[cls(r)].append(r)
    for t in (g["def_exact"], g["bind_exact"], g["def_tail"] + g["bind_tail"]):
        if t: return t
    return []
def R4(rs):  # прод-вперёд: тиры внутри прод, потом внутри тестов
    for sc in ("prod", "test"):
        c = R1([r for r in rs if r["scope"] == sc])
        if c: return c
    return []
def R0(rs): return [r for r in rs if isdef(r) and "." not in r["qualname"]]
def stats(pop, rule, label, with_prod=True):
    s = {}
    for n in pop:
        c = rule(by[n])
        if with_prod: c = prod_rule(c)
        s[n] = len(ids(c))
    tot = len(s); u = sum(1 for x in s.values() if x == 1); a = sum(1 for x in s.values() if x > 1); nf = sum(1 for x in s.values() if x == 0)
    vals = sorted(x for x in s.values() if x > 1)
    cut = {p: (vals[math.ceil(p*len(vals))-1] if vals else 0) for p in (.9, .95, .99)}
    cov = {N: sum(1 for x in vals if x <= N)/max(len(vals),1) for N in (3,5,8,10,15,20,30)}
    print(f"{label:50} имён {tot:6} ед {u:6} ({u/tot:.1%}) неод {a:5} ({a/tot:.1%}) нет {nf:5} | N90={cut[.9]} N95={cut[.95]} N99={cut[.99]} max={vals[-1] if vals else 0} | " + " ".join(f"{N}:{c:.0%}" for N,c in cov.items()))
    return s
allp = sorted(by)
prodn = [n for n in allp if any(r["scope"]=="prod" for r in by[n])]
pubprod = [n for n in prodn if not n.startswith("_") and n not in ("__all__","__init__")]
pubdef = [n for n in pubprod if any(isdef(r) and r["scope"]=="prod" for r in by[n])]
print("популяции: все", len(allp), "; с прод-кандидатом", len(prodn), "; публичные прод", len(pubprod), "; публичные прод с def/class/method", len(pubdef))
for pop, pl in ((allp,"все имена"),(prodn,"имена с прод-кандидатом"),(pubprod,"публичные имена с прод-кандидатом"),(pubdef,"публичные def-имена с прод-кандидатом")):
    print("--", pl)
    for rule, rl in ((R0,"R0 сегодня"),(R1,"R1 тиры"),(R4,"R4 прод-вперёд")):
        for wp in (False, True):
            if rule is R4 and wp: continue
            stats(pop, rule, f"{rl}{' +прод-правило' if wp else ''}", wp)
# регрессия R4 vs сегодня
today = {n: R0(by[n]) for n in allp}
uniq = [n for n in allp if len(ids(today[n])) == 1]
chg = [n for n in uniq if ids(R4(by[n])) != ids(today[n])]
print("\nR4: из сегодня-однозначных (", len(uniq), ") изменилось:", len(chg), "примеры:", chg[:8])
chg_t = [n for n in chg if today[n][0]["scope"]=="test"]
print("   из них единственным кандидатом сегодня был ТЕСТ, а прод-кандидат есть:", len(chg_t))
# тайбрейки: имена с >=2 кандидатов в одном файле (R1+prod)
same_path = 0; amb = 0; ties_pl = 0
for n in allp:
    c = prod_rule(R1(by[n])); idset = sorted(ids(c))
    if len(idset) > 1:
        amb += 1
        cp = Counter(p for p, _ in idset)
        if max(cp.values()) > 1: same_path += 1
        # ключ (путь, строка, qualname): различает всех?
        keys = [(r["path"], r["line"], r["qualname"]) for r in {(r["path"], r["qualname"]): r for r in c}.values()]
        if len(set(keys)) != len(keys): ties_pl += 1
print(f"R1+прод: неоднозначных имён {amb}; из них с >=2 кандидатов в ОДНОМ файле (сортировка только по пути даёт ничью): {same_path}; ничьи у ключа (путь,строка,qualname): {ties_pl}")
# строка-ничьи: два разных id на одной (path,line)?
byloc = defaultdict(set)
for r in rows:
    byloc[(r["path"], r["line"])].add(r["qualname"])
print("(путь,строка) с >1 разными qualname во всём наборе:", sum(1 for v in byloc.values() if len(v)>1))
ex = [(k, sorted(v)) for k, v in byloc.items() if len(v) > 1][:5]
print("   примеры:", ex)
# ключ групп
def grp(r): return 2 if r["scope"]=="test" else 1 if r["path"].startswith(SIDE) else 0
# насколько порядок по пути-только vs ключ с группами различается в первых N для топ-неоднозначных
def key_old(r): return (r["path"], r["line"], r["qualname"])
def key_new(r): return (grp(r), r["path"], r["line"], r["qualname"])
test_first = 0; tot = 0
for n in allp:
    c = R1(by[n]); u = list({(r["path"], r["qualname"]): r for r in c}.values())
    if len(u) > 5:
        tot += 1
        a = sorted(u, key=key_old)[:5]; b = sorted(u, key=key_new)[:5]
        if sum(1 for r in a if r["scope"]=="test") > sum(1 for r in b if r["scope"]=="test"): test_first += 1
print(f"имён с >5 кандидатами (R1): {tot}; из них где порядок только по пути ставит в первые 5 больше тестов, чем порядок с группами: {test_first}")
# доля тестов в первых 10 по пути для 'run'
for n in ("run","close","start","main","build"):
    c = R1(by[n]); u = list({(r["path"], r["qualname"]): r for r in c}.values())
    a = sorted(u, key=key_old)[:10]; b = sorted(u, key=key_new)[:10]
    print(n, "кандидатов", len(u), "тестов в первых 10: по пути", sum(1 for r in a if r["scope"]=="test"), "; с группами", sum(1 for r in b if r["scope"]=="test"), "; .claude/docs/plans в первых 10 по пути:", sum(1 for r in a if r["path"].startswith(SIDE)))
# дубли id (одинаковый path::qualname)
d = Counter((r["path"], r["qualname"], r["kind"]) for r in rows); dd = [(k, v) for k, v in d.items() if v > 1]
print("повторяющихся (path,qualname,kind):", len(dd), dd[:5])
d2 = Counter((r["path"], r["qualname"]) for r in rows); print("повторяющихся (path,qualname) любого вида:", sum(1 for v in d2.values() if v>1))
ex2 = [k for k, v in d2.items() if v > 1][:12]; print(ex2)

print("\nТОП-20 имён по числу кандидатов при R1+прод-правило:")
res = sorted(((len(ids(prod_rule(R1(by[n])))), n) for n in allp), key=lambda x: (-x[0], x[1]))[:20]
for c, n in res:
    t = R1(by[n]); print(f"  {n:22} {c:5} (в тире {len(ids(t))}, тир={cls(t[0])})")
print("то же только публичные прод def-имена:")
res = sorted(((len(ids(prod_rule(R1(by[n])))), n) for n in pubdef), key=lambda x: (-x[0], x[1]))[:20]
for c, n in res: print(f"  {n:22} {c:5}")
for n in ("run","build","get","name","__init__","main","start"):
    print(n, "R0:", len(ids(R0(by[n]))), "R1+прод:", len(ids(prod_rule(R1(by[n])))), "плоско:", len(ids(by[n])))
# R4: итог по 85 изменившимся
ch = [n for n in allp if len(ids(R0(by[n]))) == 1 and ids(R4(by[n])) != ids(R0(by[n]))]
print("R4 изменённых", len(ch), "-> однозначных прод:", sum(1 for n in ch if len(ids(R4(by[n])))==1), "; неоднозначных:", sum(1 for n in ch if len(ids(R4(by[n])))>1))

hid = []
for n in allp:
    g = defaultdict(list)
    for r in by[n]: g[cls(r)].append(r)
    if g["def_exact"] and (g["def_tail"] or g["bind_tail"]):
        hid.append((n, len(ids(g["def_exact"])), len(ids(g["def_tail"] + g["bind_tail"]))))
print("\nимён, где точный def есть И есть хвостовые кандидаты (их R1 скрывает):", len(hid), "из", sum(1 for n in allp if any(cls(r)=="def_exact" for r in by[n])), "имён с точным def")
big = sorted(hid, key=lambda x: -x[2])[:10]
print("  топ скрытых:", big)
print("  из них скрыто >=5 хвостовых кандидатов:", sum(1 for x in hid if x[2] >= 5), "; >=1 хвостовых при одном точном:", sum(1 for x in hid if x[1] == 1))
