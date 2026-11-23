"""Анализ defs.json: пп. 1-6 задания. Печатает таблицы; пишет meas/analysis.json."""

import json
from collections import Counter, defaultdict
from pathlib import Path

H = Path(__file__).resolve().parent
data = json.loads((H / "defs.json").read_text())
rows = data["rows"]
print("sha", data["sha"], "files", data["files_total"], "rows", len(rows))

# ---- п.1
kinds = Counter(r["kind"] for r in rows)
print("\n== п.1 виды ==")
for k in ("function", "nested_function", "class", "method", "module_binding", "class_binding"):
    prod = sum(1 for r in rows if r["kind"] == k and r["scope"] == "prod")
    print(f"{k:16} {kinds[k]:6} (prod {prod}, test {kinds[k]-prod})")
print("total", len(rows), "prod", sum(1 for r in rows if r["scope"] == "prod"))
# вложенные классы (qualname с точкой, kind class)
print("class с точкой в qualname:", sum(1 for r in rows if r["kind"] == "class" and "." in r["qualname"]))
# 'function' вне класса, qualname без точки — топ-уровень
print("top-level function:", sum(1 for r in rows if r["kind"] == "function"))


def last(q):
    return q.rsplit(".", 1)[-1]


def cls(r):
    """Пул кандидата для имени-хвоста: def_exact / bind_exact / def_tail / bind_tail (по отношению к last(qualname))."""
    dotted = "." in r["qualname"]
    isdef = r["kind"] in ("function", "nested_function", "class", "method")
    if isdef:
        return "def_tail" if dotted else "def_exact"
    return "bind_tail" if dotted else "bind_exact"


by_name = defaultdict(list)
for r in rows:
    by_name[last(r["qualname"])].append(r)
names = len(by_name)
print("\nуникальных голых имён (последний сегмент):", names)

# сколько определений-только (без привязок) имён
def_names = {n for n, rs in by_name.items() if any(cls(r) in ("def_exact", "def_tail") for r in rs)}
print("имён с хотя бы одним определением def/class/method:", len(def_names))


def bucket(n):
    if n == 1:
        return "1"
    if n == 2:
        return "2"
    if n <= 5:
        return "3-5"
    if n <= 10:
        return "6-10"
    if n <= 30:
        return "11-30"
    return ">30"


ORDER = ["1", "2", "3-5", "6-10", "11-30", ">30"]


def dist(counter_by_name, label):
    c = Counter(bucket(n) for n in counter_by_name.values() if n > 0)
    tot = sum(c.values())
    print(f"{label:60} " + " ".join(f"{b}:{c[b]}" for b in ORDER) + f"  всего имён {tot}")
    return c


# уникальные id кандидатов (path::qualname) — совпадающие id (дубли в файле) считаются один раз
def ids(rs):
    return {(r["path"], r["qualname"]) for r in rs}


print("\n== п.2 распределение числа кандидатов на имя (правило «хвост = имя», плоское) ==")
flat_all = {n: len(ids(rs)) for n, rs in by_name.items()}
dist(flat_all, "A: все (def+binding), все файлы")
flat_defs = {n: len(ids([r for r in rs if cls(r).startswith("def")])) for n, rs in by_name.items()}
dist({k: v for k, v in flat_defs.items() if v}, "B: только def/class/method (без привязок)")
dup_ids = sum(len(rs) - len(ids(rs)) for rs in by_name.values())
print("повторных строк с тем же path::qualname (условные redefs, property setter):", dup_ids)

print("\nтоп-25 имён по числу кандидатов (id) — плоское, все:")
top = sorted(flat_all.items(), key=lambda kv: (-kv[1], kv[0]))[:25]
for n, c in top:
    rs = by_name[n]
    pc = Counter(cls(r) for r in rs)
    sc = Counter(r["scope"] for r in rs)
    print(f"  {n:28} {c:5}  prod={sum(1 for x in ids([r for r in rs if r['scope']=='prod']))} test={len(ids([r for r in rs if r['scope']=='test']))}  pools={dict(pc)}")
for n in ("__init__", "run", "build", "get", "name", "main", "setUp", "start", "stop", "close"):
    print("  >>", n, flat_all.get(n))

# ---- п.3 тиры
print("\n== п.3 тировое правило: exact def -> (exact binding) -> tail ==")


def tier_candidates(rs, variant):
    """variant R1: tiers [def_exact], [bind_exact], [def_tail+bind_tail]  (первый непустой)
       variant R2: tiers [def_exact+bind_exact], [def_tail+bind_tail]
       variant R0: today = [def_exact] без хвоста
       variant R3: плоско всё"""
    g = defaultdict(list)
    for r in rs:
        g[cls(r)].append(r)
    if variant == "R0":
        return g["def_exact"]
    if variant == "R1":
        for t in (g["def_exact"], g["bind_exact"], g["def_tail"] + g["bind_tail"]):
            if t:
                return t
        return []
    if variant == "R2":
        for t in (g["def_exact"] + g["bind_exact"], g["def_tail"] + g["bind_tail"]):
            if t:
                return t
        return []
    if variant == "R3":
        return rs
    raise ValueError


def prod_rule(cands):
    """один продовый кандидат (по id) при смеси -> он; иначе все как есть"""
    prod = [r for r in cands if r["scope"] == "prod"]
    if len(ids(prod)) == 1 and len(ids(cands)) > 1:
        return prod
    return cands


def resolve_stats(variant, use_prod):
    out = {}
    for n, rs in by_name.items():
        c = tier_candidates(rs, variant)
        if use_prod:
            c = prod_rule(c)
        out[n] = len(ids(c))
    return out


res = {}
for v in ("R0", "R1", "R2", "R3"):
    for up in (False, True):
        s = resolve_stats(v, up)
        uniq = sum(1 for x in s.values() if x == 1)
        amb = sum(1 for x in s.values() if x > 1)
        nf = sum(1 for x in s.values() if x == 0)
        res[(v, up)] = s
        print(f"{v} prod_rule={up!s:5}: однозначных {uniq:6} ({uniq/names:.1%}) неоднозначных {amb:6} ({amb/names:.1%}) not found {nf}")

# только продовые кандидаты (отфильтровать тесты вообще)
only_prod = Counter()
for n, rs in by_name.items():
    pr = [r for r in rs if r["scope"] == "prod"]
    only_prod[n] = len(ids(pr))
print("\nесли ВООБЩЕ игнорировать тестовых кандидатов (плоско): ", end="")
dist({n: c for n, c in only_prod.items() if c > 0}, "flat prod only")
names_with_prod = sum(1 for c in only_prod.values() if c > 0)
print("имён, у которых нет ни одного прод-кандидата (только тесты):", names - names_with_prod)

# Покрытие: какая доля имён с >=1 кандидатом разрешается (в 1 кандидата)
print("\nдоля имён, разрешённых до 1 кандидата, из имён с >=1 кандидатом (R1+prod):")
s = res[("R1", True)]
tot = sum(1 for x in s.values() if x > 0)
print(f"  {sum(1 for x in s.values() if x==1)}/{tot} = {sum(1 for x in s.values() if x==1)/tot:.1%}")

# ---- п.4 регрессии
print("\n== п.4 регрессии относительно сегодняшнего ==")
today = {n: tier_candidates(rs, "R0") for n, rs in by_name.items()}
today_unique = {n for n, c in today.items() if len(ids(c)) == 1}
print("имён, однозначных сегодня (ровно 1 точное совпадение def):", len(today_unique))
print("имён, неоднозначных сегодня (>=2):", sum(1 for c in today.values() if len(ids(c)) > 1))
print("имён not found сегодня (0 точных def):", sum(1 for c in today.values() if len(ids(c)) == 0))
reg = {}
for v in ("R1", "R2", "R3"):
    for up in (False, True):
        bad = []
        for n in today_unique:
            c = tier_candidates(by_name[n], v)
            if up:
                c = prod_rule(c)
            if ids(c) != ids(today[n]):
                bad.append((n, len(ids(c))))
        reg[(v, up)] = bad
        print(f"{v} prod_rule={up!s:5}: изменился результат у {len(bad)} из {len(today_unique)} сегодня-однозначных")
for v in ("R2", "R3"):
    bad = sorted(reg[(v, False)], key=lambda x: (-x[1], x[0]))[:10]
    print(f"  примеры {v}:")
    for n, c in bad:
        rs = by_name[n]
        print(f"    {n}: было 1 ({sorted(ids(today[n]))[0][0]}::{n}); стало {c}; пулы {dict(Counter(cls(r) for r in rs))}")

# как изменяются сегодня неоднозначные при prod_rule (не регрессия — улучшение, но смена выдачи)
print("\nсегодня неоднозначные и ставшие однозначными только за счёт прод-правила (R0+prod):")
chg = [n for n, c in today.items() if len(ids(c)) > 1 and len(ids(prod_rule(c))) == 1]
print("  ", len(chg), "из", sum(1 for c in today.values() if len(ids(c)) > 1))
print("  примеры:", chg[:10])
# сегодня однозначное, но единственный кандидат — тест-файл (не регрессия, фиксируем)
print("сегодня-однозначных, где единственный кандидат — тест:", sum(1 for n in today_unique if today[n][0]["scope"] == "test"))

# пересечение: имя имеет def_exact==1 и bind_exact>=1 (контрпример для R2)
cnt = 0
ex = []
for n in today_unique:
    g = Counter(cls(r) for r in by_name[n])
    if g["bind_exact"]:
        cnt += 1
        ex.append(n)
print("def_exact==1 и есть module_binding того же имени:", cnt, ex[:10])
cnt2 = sum(1 for n in today_unique if Counter(cls(r) for r in by_name[n])["def_tail"] or Counter(cls(r) for r in by_name[n])["bind_tail"])
print("def_exact==1 и есть хвостовые кандидаты (методы/вложенные/class-привязки) — именно они ломаются при плоском R3:", cnt2)

# ---- п.5 выбор N
print("\n== п.5 N: какой N покрывает целиком p% неоднозначных имён ==")
for v, up, lab in (("R1", True, "R1+prod (рекомендуемое)"), ("R1", False, "R1 без прод-правила"), ("R3", False, "плоский хвост, всё"), ("R0", False, "сегодняшнее (точный def)")):
    s = res[(v, up)] if (v, up) in res else None
    vals = sorted(x for x in s.values() if x > 1)
    if not vals:
        continue
    out = []
    for p in (0.90, 0.95, 0.99):
        import math

        k = math.ceil(p * len(vals)) - 1
        out.append(f"{int(p*100)}%->N={vals[k]}")
    cov = {N: sum(1 for x in vals if x <= N) / len(vals) for N in (3, 5, 8, 10, 15, 20, 30)}
    print(f"{lab}: неоднозначных {len(vals)}; " + ", ".join(out) + "; max=" + str(vals[-1]))
    print("    покрытие при N: " + ", ".join(f"{N}:{c:.1%}" for N, c in cov.items()))

(H / "analysis.json").write_text(json.dumps({f"{v}/{up}": s for (v, up), s in res.items()}))
