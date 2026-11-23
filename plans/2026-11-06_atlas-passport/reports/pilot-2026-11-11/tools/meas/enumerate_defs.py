"""Перечисление всех определений и привязок репозитория (SHA пилота, исключения пилота) через Python API атласа.
Пишет meas/defs.json: список {path, qualname, kind, line, scope}. kind: class|function|method|nested_function|
module_binding|class_binding. Запуск: python3 enumerate_defs.py  (корень стенда задан ниже)."""

import ast
import json
import sys
from pathlib import Path

SRC = Path("/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/869199f2-e18c-4258-a517-1084ab45a695/scratchpad/atlas-src")
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))

from scripts.atlas import passport as P  # noqa: E402
from scripts.atlas.links import _scope  # noqa: E402

pilot = ast.parse((SRC / "pilot_atlas.py").read_text())
SHA = EXCLUDE = None
for node in pilot.body:
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
        if node.targets[0].id == "SHA":
            SHA = ast.literal_eval(node.value)
        if node.targets[0].id == "EXCLUDE":
            EXCLUDE = ast.literal_eval(node.value)

ctx = P._Ctx.open(SRC, SHA, tuple(EXCLUDE), with_links=False)
rows = []
files_total = len(ctx.facts)
files_err = 0
for path in sorted(ctx.facts):
    f = ctx.facts[path]
    if f.error is not None or f.v2_error is not None:
        files_err += 1
    sc = _scope(path)
    for d in f.defs:
        kind = d.kind
        if kind == "function" and "." in d.qualname:
            kind = "nested_function"
        rows.append(dict(path=path, qualname=d.qualname, kind=kind, line=d.line, scope=sc))
    if f.error is not None or f.v2_error is not None:
        continue
    mod = ctx._module_ast(path)
    if mod is None:
        continue
    for name, (line, _) in P._body_bindings(mod.body).items():
        rows.append(dict(path=path, qualname=name, kind="module_binding", line=line, scope=sc))
    for d in f.defs:
        if d.kind != "class":
            continue
        node = P._find_node(mod, d.qualname, d.line)
        if isinstance(node, ast.ClassDef):
            for name, (line, _) in P._body_bindings(node.body).items():
                rows.append(dict(path=path, qualname=f"{d.qualname}.{name}", kind="class_binding", line=line, scope=sc))
(OUT / "defs.json").write_text(json.dumps(dict(sha=SHA, files_total=files_total, files_err=files_err, rows=rows)))
print("files", files_total, "err", files_err, "rows", len(rows))
