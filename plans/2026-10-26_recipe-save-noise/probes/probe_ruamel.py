# ruff: noqa  -- одноразовая проба расследования C-30, не код проекта
import io
import difflib
import sys
import ruamel.yaml
from multiprocess_framework.modules.recipe.yaml_io import _make_yaml

print("ruamel", ruamel.yaml.__version__)
y = _make_yaml()


def dump(d):
    b = io.StringIO()
    y.dump(d, b)
    return b.getvalue()


def diff(a, b):
    return [
        l
        for l in difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=0)
        if l[:1] in "+-" and not l.startswith(("+++", "---"))
    ]


SYN = """\
procs:
  # --- A: comment above A (header of list) ---
  - name: a
    v: 1
    # --- B: comment about item b (sits after a's last key) ---
  - name: b
    v: 2
    sub:
      k: 1
      # --- C: comment about item c (after b's deepest leaf) ---
  - name: c
    v: 3
  # --- D ---
  - name: d
    v: 4
tail: 1
"""
doc = y.load(SYN)
print("roundtrip id:", dump(doc) == SYN)
for i in (0, 1, 2, 3):
    doc = y.load(SYN)
    del doc["procs"][i]
    out = dump(doc)
    print(f"--- del procs[{i}] ---")
    print("\n".join(diff(SYN, out)))
# delete middle element of fixture lists
fx = open(sys.argv[1], encoding="utf-8").read()
for path, idx in (
    (("blueprint", "processes"), 1),
    (("blueprint", "processes"), 2),
    (("displays",), 1),
    (("devices",), 0),
    (("devices",), 1),
):
    doc = y.load(fx)
    node = doc
    for p in path:
        node = node[p]
    del node[idx]
    out = dump(doc)
    d = diff(fx, out)
    removed = [l for l in d if l.startswith("-")]
    added = [l for l in d if l.startswith("+")]
    cm = [l for l in removed if l[1:].lstrip().startswith("#")]
    print(f"del {'.'.join(path)}[{idx}]: removed={len(removed)} added={len(added)} removed-comment-lines={cm[:6]}")
# insert in the middle
doc = y.load(fx)
doc["displays"].insert(1, {"id": "zz", "enabled": True})
out = dump(doc)
d = diff(fx, out)
print("insert displays[1]: removed", sum(l.startswith("-") for l in d), "added", sum(l.startswith("+") for l in d))
# key-delete trap on mapping
doc = y.load(fx)
del doc["blueprint"]["processes"][2]["protected"]
d = diff(fx, dump(doc))
print("del camera_0.protected:", d)
# CRLF feasibility: text-mode read, dump, replace
crlf = fx.replace("\n", "\r\n")
open(sys.argv[2], "wb").write(crlf.encode("utf-8"))
with open(sys.argv[2], "r", encoding="utf-8") as f:
    doc = y.load(f)
doc["displays"][3]["enabled"] = True
out = dump(doc).replace("\n", "\r\n").encode("utf-8")
b0 = crlf.encode("utf-8")
print(
    "CRLF: lf-only count after:",
    out.count(b"\n") - out.count(b"\r\n"),
    "diff lines:",
    diff(b0.decode().replace("\r\n", "\n"), out.decode().replace("\r\n", "\n")),
)
# bytes input: does ruamel keep \r\n inside comments?
doc = y.load(b0)
o2 = dump(doc)
print("bytes-load roundtrip == LF-normalised:", o2 == fx, " has \r in dump:", "\r" in o2)
