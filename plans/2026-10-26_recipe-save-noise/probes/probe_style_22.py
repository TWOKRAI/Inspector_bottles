# ruff: noqa
import sys, tempfile, pathlib, copy, collections, io

sys.path.insert(0, sys.argv[2])  # oldpkg dir
import yaml as py
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
import multiprocess_framework.modules.recipe.yaml_io as new
import oldrecipe.yaml_io as old

REPO = pathlib.Path(sys.argv[1])
RECIPES = REPO / "multiprocess_prototype" / "recipes"
print("new:", new.__file__)
print("old:", old.__file__)
rt = YAML()


def flow_map(text):
    """path -> ('flow'|'block', len) for every container of the ruamel-loaded text."""
    doc = rt.load(text)
    res = {}

    def walk(n, path):
        if isinstance(n, (CommentedMap, CommentedSeq)):
            res[path] = ("flow" if n.fa.flow_style() else "block", len(n))
            it = n.items() if isinstance(n, CommentedMap) else enumerate(n)
            for k, v in it:
                walk(v, path + (k,))

    walk(doc, ())
    return res


def containers(node, path=()):
    if isinstance(node, dict):
        if node and path:
            yield path, node
        for k, v in node.items():
            yield from containers(v, path + (k,))
    elif isinstance(node, list):
        if node and path:
            yield path, node
        for i, v in enumerate(node):
            yield from containers(v, path + (i,))


def get(root, path):
    for p in path:
        root = root[p]
    return root


def mutations(before):
    for path, node in [c for c in containers(before) if len(c[0]) <= 3]:
        a = copy.deepcopy(before)
        par = get(a, path[:-1])
        par[path[-1]] = type(node)()
        yield ("empty", path), a
        if isinstance(node, dict):
            a = copy.deepcopy(before)
            par = get(a, path[:-1])
            par[path[-1]] = {"knew": 1}
            yield ("newkeys", path), a
        else:
            a = copy.deepcopy(before)
            par = get(a, path[:-1])
            par[path[-1]] = ["snew"]
            yield ("newitems", path), a
        a = copy.deepcopy(before)
        par = get(a, path[:-1])
        if isinstance(node, dict):
            del par[path[-1]][next(iter(node))]
        else:
            del par[path[-1]][0]
        yield ("delfirst", path), a


def run(mod, raw, before, after):
    d = pathlib.Path(tempfile.mkdtemp())
    p = d / "r.yaml"
    p.write_bytes(raw)
    try:
        mod.patch_yaml_preserving(p, before, after)
    except Exception as e:
        return ("EXC", type(e).__name__), None
    return None, p.read_bytes().decode("utf-8")


def untouched(before, after, mpath):
    """paths of containers equal in before and after, not on/under/above the mutated path"""
    for path, node in containers(before):
        if path[: len(mpath)] == mpath[: len(path)]:
            continue  # ancestor/descendant of mutation
        try:
            if get(after, path) == node:
                yield path
        except Exception:
            pass


stats = collections.Counter()
ex = collections.defaultdict(list)
for f in sorted(RECIPES.glob("*.yaml")):
    raw = f.read_bytes().replace(b"\r\n", b"\n")
    text = raw.decode("utf-8")
    before = py.safe_load(text)
    src_style = flow_map(text)
    for (kind, mpath), after in mutations(before):
        for label, mod in (("new", new), ("old", old)):
            err, out = run(mod, raw, before, after)
            if err:
                stats[f"{label}:{err[1]}"] += 1
                ex[f"{label}:{err[1]}"].append((f.name, kind, mpath))
                continue
            try:
                ok = py.safe_load(out) == after
            except Exception:
                ok = False
            if not ok:
                stats[f"{label}:INVALID/MISMATCH"] += 1
                ex[f"{label}:INVALID"].append((f.name, kind, mpath))
                continue
            stats[f"{label}:ok"] += 1
            out_style = flow_map(out)
            # style of untouched containers
            for p in untouched(before, after, mpath):
                s, o = src_style.get(p), out_style.get(p)
                if s and o and s[1] and o[1] and s[0] != o[0]:
                    stats[f"{label}:untouched-style-change"] += 1
                    ex[f"{label}:untouched-style"].append((f.name, kind, mpath, p, s[0], o[0]))
            # style of the mutated container itself when refilled
            if kind in ("newkeys", "newitems"):
                s, o = src_style.get(mpath), out_style.get(mpath)
                if s and o and s[1] and o[1] and s[0] != o[0]:
                    stats[f"{label}:refilled-style-change"] += 1
                    ex[f"{label}:refilled-style"].append((f.name, kind, mpath, s[0], o[0]))
for k in sorted(stats):
    print(k, stats[k])
for k, v in ex.items():
    if k.endswith(":ok"):
        continue
    print("---", k, len(v))
    for x in v[:6]:
        print("   ", x)
