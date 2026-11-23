import sys, ast, time, collections
sys.path.insert(0, "/Users/twokrai/Project_code/Inspector_bottles")
from scripts.atlas import scan as m, store
from scripts.atlas.links import Links, _scope
from scripts.atlas.tree import Tree, resolve
S = "/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/07119c72-f5cf-4b30-8b38-35f88bc25000/scratchpad/agentR2"
tree = Tree(".", resolve(".", "HEAD"))
paths = sorted(p for p in tree.oids() if p.endswith(".py"))
con = store.connect(f"{S}/prof2.sqlite")   # warm scratch db from g2
facts = m.scan(tree, paths, cache=con).facts
lk = Links(facts)
index = m.ImportIndex(facts)

def params(sig):
    head = sig.split(" -> ")[0] if " -> " in sig else sig
    try:
        a = ast.parse(f"def _({head}): pass").body[0].args
    except SyntaxError:
        return set()
    return {x.arg for x in [*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg] if x}

defsig = {p: {d.qualname: d for d in f.defs} for p, f in facts.items()}
tot = collections.Counter(); bad = collections.defaultdict(list)
amb_names = []
for path, f in facts.items():
    from_names, modules = lk._imports(index, path, f)
    # ambiguous from-imports: same name from >1 internal target
    seen = collections.defaultdict(set)
    for rec in f.imports:
        r = index.resolve(path, rec)
        if r.status != "internal" or not rec.is_from: continue
        for tgt, names in r.targets:
            for n in names:
                if n != "*": seen[n].add(tgt)
    for n, t in seen.items():
        defining = [x for x in t if lk._top(x, n)]
        if len(defining) > 1: amb_names.append((path, n, sorted(defining)))
    for call in f.calls:
        kind = None
        if call.receiver is None:
            if lk._top(path, call.name): kind = "bare-own"
            elif call.name in from_names and lk._top(from_names[call.name][0], call.name): kind = "bare-import"
        elif call.receiver in modules and lk._top(modules[call.receiver][0], call.name):
            kind = "module-attr"
        if kind is None: continue
        tot[kind] += 1
        # shadow check along the enclosing chain
        parts = call.enclosing.split(".")
        shadow = None
        key = call.name if kind.startswith("bare") else call.receiver.split(".")[0]
        for i in range(len(parts), 0, -1):
            q = ".".join(parts[:i]); d = defsig[path].get(q)
            if d is None: continue
            if key in params(d.signature): shadow = "param"; break
            if d.kind != "class" and f"{q}.{key}" in defsig[path] and kind != "module-attr": shadow = "nested-def"; break
        if shadow:
            bad[(kind, shadow, _scope(path))].append((path, call.line, call.name, call.enclosing))
print("attributed:", dict(tot))
for k, v in bad.items():
    print("SHADOWED", k, len(v), "e.g.", v[:3])
print("ambiguous from-import names (same name, >1 targets in one file):", len(amb_names), amb_names[:4])
# unresolved internal imports (root in roots but target not found)
unres = collections.Counter(); ex = {}
for path, f in facts.items():
    for rec in f.imports:
        r = index.resolve(path, rec)
        if r.status == "unresolved":
            unres[rec.module if not rec.level else "."*rec.level+(rec.module or "")] += 1
            ex.setdefault(rec.module, (path, rec.line, rec.names))
print("unresolved total:", sum(unres.values()), unres.most_common(8))
print({k: ex[k] for k, _ in unres.most_common(4) if k in ex})
