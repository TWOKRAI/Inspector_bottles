"""Independent count of bindings per Task 4.6 rules at a git revision (reads blobs via git, not atlas)."""
import ast, subprocess, sys
from collections import Counter

repo, rev = sys.argv[1], sys.argv[2]
ls = subprocess.run(["git", "-C", repo, "ls-tree", "-r", "-z", "--name-only", rev], capture_output=True, check=True).stdout
paths = [p.decode() for p in ls.split(b"\0") if p.endswith(b".py")]
FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)


def names_of(stmt):
    if isinstance(stmt, ast.Assign):
        return [t.id for t in stmt.targets if isinstance(t, ast.Name)]
    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        return [stmt.target.id]
    if isinstance(stmt, ast.TypeAlias):
        return [stmt.name.id]
    return []


total = Counter()
out = []
for path in paths:
    data = subprocess.run(["git", "-C", repo, "cat-file", "blob", f"{rev}:{path}"], capture_output=True).stdout
    if len(data) > 1_048_576:
        total["skip_big"] += 1
        continue
    try:
        tree = ast.parse(data.decode("utf-8").removeprefix("﻿"))
    except Exception:
        total["skip_err"] += 1
        continue
    defs = {}  # qualname -> (kind, node) first in pre-order
    def walk(node, prefix, owner_kind):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (*FUNCS, ast.ClassDef)):
                q = prefix + ch.name
                defs.setdefault(q, ch)
                walk(ch, q + ".", "class" if isinstance(ch, ast.ClassDef) else "def")
            else:
                walk(ch, prefix, owner_kind)
    walk(tree, "", None)
    def body_bindings(body, prefix, kind):
        seen = {}
        for stmt in body:
            for n in names_of(stmt):
                seen.setdefault(n, stmt.lineno)
        for n, line in seen.items():
            q = prefix + n
            if q in defs:
                total[f"{kind}_shadowed_by_def"] += 1
                continue
            total[kind] += 1
            out.append(f"{path}::{q}\t{line}")
    body_bindings(tree.body, "", "module")
    for q, node in defs.items():
        if isinstance(node, ast.ClassDef):
            body_bindings(node.body, q + ".", "class")
    # nested-in-compound module statements (not counted by rule; reported only)
    for stmt in tree.body:
        if isinstance(stmt, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
            for sub in ast.walk(stmt):
                if isinstance(sub, (ast.Assign, ast.AnnAssign)) and names_of(sub):
                    total["module_compound_stmts"] += 1
total["files"] = len(paths)
print(dict(total))
open(sys.argv[3], "w").write("\n".join(out) + "\n")
