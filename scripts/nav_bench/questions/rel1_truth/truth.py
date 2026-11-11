"""Независимый эталон набора rel1: отношения по ``ast`` на зафиксированном SHA (Атлас не используется).

Вход — ``spec.json`` рядом (вопрос -> отношение и цель), код — ``git archive <sha>`` репозитория ``--root``
(рабочее дерево не читается). Выход — ``truth.json``: по вопросу записи ``{path, line, symbol, how}`` и ``flagged``
(места, которые правило включения решает не механически; их сверяет человек, решение — в ``spec.json``).

    python scripts/nav_bench/questions/rel1_truth/truth.py --root . [--out truth.json] [--check ../rel1.json]

``--check`` — сверка ``expected`` набора с выводом (множества ``path:line``); расхождение — код 1.

Правила включения (записаны до разметки, общие для всех вопросов):
  * тест — путь с компонентом ``tests``/``test`` или имя ``test_*.py``, ``*_test.py``, ``conftest.py``; иное — прод;
  * разрешение имён — только статическое: ``import``/``from … import`` в ЛЮБОМ месте файла (ленивые импорты
    внутри функций тоже; области видимости не различаются), относительные импорты, цепочки реэкспорта через
    ``__init__.py`` и через модули, которые сами импортируют имя (тот же объект => то же место);
  * ``getattr``/строковые имена, ``importlib``, присваивание функции переменной — не разрешаются; такие места
    попадают в ``flagged``, если в них есть имя цели;
  * строка записи — строка токена имени: вызов ``f(``/``m.f(`` — строка имени ``f``; импорт — строка ``alias``;
    класс — строка ``class``; привязка — строка присваивания; строковый литерал — строка литерала.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOTS_ALIAS = ("", "multiprocess_framework.modules.")  # модули фреймворка импортируются и с корня modules


def is_test(path: str) -> bool:
    parts = path.split("/")
    name = parts[-1]
    return (
        "tests" in parts[:-1]
        or "test" in parts[:-1]
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
    )


def load_sources(root: Path, sha: str, exclude: list[str]) -> dict[str, str]:
    raw = subprocess.run(["git", "-C", str(root), "archive", sha], capture_output=True, check=True).stdout
    out: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
        for member in tar.getmembers():
            name = member.name
            if not member.isfile() or not name.endswith(".py"):
                continue
            if any(name == e or name.startswith(e.rstrip("/") + "/") for e in exclude):
                continue
            data = tar.extractfile(member)
            if data is not None:
                out[name] = data.read().decode("utf-8", errors="replace")
    return out


def module_name(path: str) -> str:
    mod = path[:-3].replace("/", ".")
    return mod[: -len(".__init__")] if mod.endswith(".__init__") else mod


class Repo:
    def __init__(self, sources: dict[str, str]):
        self.sources = sources
        self.trees: dict[str, ast.Module] = {}
        for path, text in sources.items():
            try:
                self.trees[path] = ast.parse(text)
            except SyntaxError:
                continue
        self.mod_to_path = {module_name(p): p for p in self.trees}
        self._bind: dict[str, dict[str, tuple[str, str | None]]] = {}

    # --- модули и привязки -------------------------------------------------------------------
    def path_of(self, mod: str) -> str | None:
        for prefix in ROOTS_ALIAS:
            if prefix + mod in self.mod_to_path:
                return self.mod_to_path[prefix + mod]
        return None

    def absolute(self, path: str, node: ast.ImportFrom) -> str:
        if not node.level:
            return node.module or ""
        pkg = module_name(path).split(".")
        if not path.endswith("__init__.py"):
            pkg = pkg[:-1]
        base = pkg[: len(pkg) - (node.level - 1)]
        return ".".join(base + ([node.module] if node.module else []))

    def bindings(self, path: str) -> dict[str, tuple[str, str | None]]:
        """Локальное имя -> (модуль, имя в модуле | None для самого модуля). Импорты в любом месте файла."""
        if path in self._bind:
            return self._bind[path]
        out: dict[str, tuple[str, str | None]] = {}
        for node in ast.walk(self.trees[path]):
            if isinstance(node, ast.ImportFrom):
                mod = self.absolute(path, node)
                for a in node.names:
                    if a.name != "*":
                        out[a.asname or a.name] = (mod, a.name)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.asname:
                        out[a.asname] = (a.name, None)
                    else:
                        out[a.name.split(".")[0]] = (a.name.split(".")[0], None)
        self._bind[path] = out
        return out

    def top_defs(self, path: str) -> dict[str, ast.AST]:
        out: dict[str, ast.AST] = {}
        for node in self.trees[path].body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out[node.name] = node
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    if isinstance(t, ast.Name):
                        out[t.id] = node
        return out

    def resolve(self, mod: str, name: str | None, depth: int = 0) -> tuple[str, str | None] | None:
        """(модуль, имя) -> (путь определения, имя | None — модуль). Следует реэкспорту."""
        if depth > 12:
            return None
        if name is None:
            p = self.path_of(mod)
            return (p, None) if p else None
        p = self.path_of(mod)
        if p is not None:
            if name in self.top_defs(p):
                return (p, name)
            bound = self.bindings(p).get(name)
            if bound is not None:
                return self.resolve(bound[0], bound[1], depth + 1)
        sub = self.path_of(f"{mod}.{name}")
        if sub is not None:
            return (sub, None)
        return None

    def resolve_expr(self, path: str, node: ast.AST) -> tuple[str, str | None] | None:
        """Name / Attribute-цепочка в файле ``path`` -> определение."""
        chain: list[str] = []
        while isinstance(node, ast.Attribute):
            chain.insert(0, node.attr)
            node = node.value
        if not isinstance(node, ast.Name):
            return None
        head = node.id
        if head in self.top_defs(path) and head not in self.bindings(path):
            cur: tuple[str, str | None] | None = (path, head)
        elif head in self.bindings(path):
            cur = self.resolve(*self.bindings(path)[head])
        else:
            return None
        for attr in chain:
            if cur is None or cur[1] is not None:
                return None  # атрибут не модуля (метод класса и т. п.) — вне статического разрешения
            cur = self.resolve(module_name(cur[0]), attr)
        return cur


def name_line(node: ast.AST) -> int:
    """Строка токена имени: у ``a.b.f`` — строка ``f`` (end_lineno атрибута)."""
    return node.end_lineno if isinstance(node, ast.Attribute) else node.lineno  # type: ignore[return-value]


def _entry(path: str, line: int, symbol: str, how: str) -> dict[str, Any]:
    return {"path": path, "line": line, "symbol": symbol, "how": how}


# --- отношения ---------------------------------------------------------------------------------
def rel_callers(repo: Repo, spec: dict[str, Any]) -> tuple[list, list]:
    target = (spec["path"], spec["name"])
    entries, flagged = [], []
    for path, tree in repo.trees.items():
        if is_test(path):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if repo.resolve_expr(path, node.func) == target:
                    entries.append(_entry(path, name_line(node.func), spec["name"], "call"))
                for arg in [*node.args, *(k.value for k in node.keywords)]:
                    if repo.resolve_expr(path, arg) == target:
                        flagged.append(_entry(path, name_line(arg), spec["name"], "passed-as-argument"))
    return entries, flagged


def rel_subclasses(repo: Repo, spec: dict[str, Any]) -> tuple[list, list]:
    found = {(spec["path"], spec["name"])}
    classes = [(p, n) for p, t in repo.trees.items() for n in ast.walk(t) if isinstance(n, ast.ClassDef)]
    entries: dict[tuple[str, str], dict] = {}
    changed = True
    while changed:
        changed = False
        for path, cls in classes:
            key = (path, cls.name)
            if key in found:
                continue
            for base in cls.bases:
                b = base.value if isinstance(base, ast.Subscript) else base
                if repo.resolve_expr(path, b) in found:
                    found.add(key)
                    changed = True
                    if not is_test(path):
                        entries[key] = _entry(path, cls.lineno, cls.name, "subclass")
                    break
    return list(entries.values()), []


def _class_members(cls: ast.ClassDef) -> set[str]:
    names = set()
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return names


def rel_structural(repo: Repo, spec: dict[str, Any]) -> tuple[list, list]:
    """Прод-классы, у которых в СВОЁМ теле или в теле прод-баз репозитория есть все члены протокола."""
    need = set(spec["members"])
    by_key = {(p, n.name): (p, n) for p, t in repo.trees.items() for n in ast.walk(t) if isinstance(n, ast.ClassDef)}

    def members(path: str, cls: ast.ClassDef, depth: int = 0) -> set[str]:
        got = _class_members(cls)
        if depth < 8:
            for base in cls.bases:
                r = repo.resolve_expr(path, base)
                if r and r in by_key:
                    got |= members(*by_key[r], depth + 1)
        return got

    entries, flagged = [], []
    for (path, name), (_, cls) in by_key.items():
        if is_test(path) or (path, name) == (spec["path"], spec["name"]):
            continue
        if any(isinstance(b, ast.Name) and b.id == "Protocol" for b in cls.bases):
            continue
        got = members(path, cls)
        if need <= got:
            entries.append(_entry(path, cls.lineno, name, "structural"))
        elif len(need & got) >= len(need) - 1:
            flagged.append(_entry(path, cls.lineno, name, f"missing {sorted(need - got)}"))
    return entries, flagged


def rel_importers(repo: Repo, spec: dict[str, Any]) -> tuple[list, list]:
    """Импорт-операторы прод-файлов вне цели, у которых МОДУЛЬ оператора — файл цели (``spec.path``) или модуль
    внутри пакета цели (``spec.package``): ``import M``, ``from M import x``, ``from P import M``. Имена, которые
    третий модуль реэкспортирует из цели, не засчитываются (оператор называет третий модуль). Запись — строка
    оператора (``from``/``import``); при ``spec.files`` — один адрес на файл с ``line: null``."""
    pkg = spec.get("package")
    target_file = spec.get("path")

    def inside(mod_path: str | None) -> bool:
        if mod_path is None:
            return False
        return mod_path.startswith(pkg.rstrip("/") + "/") if pkg else mod_path == target_file

    entries = []
    for path, tree in repo.trees.items():
        if is_test(path) or (pkg and path.startswith(pkg.rstrip("/") + "/")) or path == target_file:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = repo.absolute(path, node)
                ok = inside(repo.path_of(mod)) or any(inside(repo.path_of(f"{mod}.{a.name}")) for a in node.names)
            elif isinstance(node, ast.Import):
                ok = any(inside(repo.path_of(a.name)) for a in node.names)
            else:
                continue
            if ok:
                sym = (pkg or target_file).rstrip("/").split("/")[-1].removesuffix(".py")
                entries.append(_entry(path, node.lineno, sym, "import"))
    if spec.get("files"):
        seen: dict[str, dict] = {}
        for e in entries:
            seen.setdefault(e["path"], {**e, "line": None})
        entries = list(seen.values())
    return entries, []


def rel_threads(repo: Repo, spec: dict[str, Any]) -> tuple[list, list]:
    """Конструкторы ``threading.Thread``/``threading.Timer`` и прод-подклассов ``Thread`` в каталоге ``spec.dir``."""
    roots = {("threading", "Thread"), ("threading", "Timer")}
    subs = set()
    for path, tree in repo.trees.items():
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            for b in cls.bases:
                r = _thread_ref(repo, path, b)
                if r in roots:
                    subs.add((path, cls.name))
    entries = []
    for path, tree in repo.trees.items():
        if is_test(path) or not path.startswith(spec["dir"].rstrip("/") + "/"):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                r = _thread_ref(repo, path, node.func)
                if r in roots or repo.resolve_expr(path, node.func) in subs:
                    sym = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "?")
                    entries.append(_entry(path, name_line(node.func), sym, "thread"))
    return entries, []


def _thread_ref(repo: Repo, path: str, node: ast.AST) -> tuple[str, str] | None:
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        bound = repo.bindings(path).get(node.value.id)
        if bound == ("threading", None):
            return ("threading", node.attr)
    if isinstance(node, ast.Name):
        bound = repo.bindings(path).get(node.id)
        if bound and bound[0] == "threading" and bound[1]:
            return ("threading", bound[1])
    return None


def rel_env_reads(repo: Repo, spec: dict[str, Any]) -> tuple[list, list]:
    """Чтения ``os.environ.get(K)``, ``os.getenv(K)``, ``os.environ[K]`` (Load), ``K in os.environ``, где K —
    литерал из ``spec.names`` или имя модульной константы файла, равной такому литералу. Запись — строка литерала
    или имени в месте чтения. Запись в окружение (``os.environ[K] = …``, ``setdefault``) — ``flagged``."""
    names = set(spec["names"])
    entries, flagged = [], []
    for path, tree in repo.trees.items():
        if is_test(path):
            continue
        consts = {
            n: node.value.value
            for n, node in repo.top_defs(path).items()
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and node.value.value in names
        }

        def key_of(node: ast.AST) -> str | None:
            if isinstance(node, ast.Constant) and node.value in names:
                return node.value
            if isinstance(node, ast.Name) and node.id in consts:
                return consts[node.id]
            return None

        def is_environ(node: ast.AST) -> bool:
            return (
                isinstance(node, ast.Attribute)
                and node.attr == "environ"
                or (isinstance(node, ast.Name) and node.id == "environ")
            )

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and node.args:
                f = node.func
                k = key_of(node.args[0])
                if k is None or not isinstance(f, (ast.Attribute, ast.Name)):
                    continue
                fname = f.attr if isinstance(f, ast.Attribute) else f.id
                if fname == "getenv" or (fname == "get" and isinstance(f, ast.Attribute) and is_environ(f.value)):
                    entries.append(_entry(path, node.args[0].lineno, k, "env-read"))
                elif fname in ("setdefault", "pop") and isinstance(f, ast.Attribute) and is_environ(f.value):
                    flagged.append(_entry(path, node.args[0].lineno, k, f"env-{fname}"))
            elif isinstance(node, ast.Subscript) and is_environ(node.value):
                k = key_of(node.slice)
                if k is not None:
                    kind = "env-read" if isinstance(node.ctx, ast.Load) else "env-write"
                    (entries if kind == "env-read" else flagged).append(_entry(path, node.slice.lineno, k, kind))
            elif isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], (ast.In, ast.NotIn)):
                k = key_of(node.left)
                if k is not None and is_environ(node.comparators[0]):
                    entries.append(_entry(path, node.left.lineno, k, "env-in"))
    return entries, flagged


def rel_self_callers(repo: Repo, spec: dict[str, Any]) -> tuple[list, list]:
    """Вызовы ``self.<method>(`` в методах класса ``spec.class`` и его подклассов (любой файл, только прод).
    Вызов ``<иное>.<method>(`` — ``flagged`` (получатель статически не известен)."""
    owners = {(spec["path"], spec["class"])}
    sub_entries, _ = rel_subclasses(repo, {"path": spec["path"], "name": spec["class"]})
    owners |= {(e["path"], e["symbol"]) for e in sub_entries}
    method = spec["method"]
    entries, flagged = [], []
    for path, tree in repo.trees.items():
        if is_test(path):
            continue
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            inside = (path, cls.name) in owners
            for node in ast.walk(cls):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == method:
                    recv = node.func.value
                    if inside and isinstance(recv, ast.Name) and recv.id == "self":
                        entries.append(_entry(path, name_line(node.func), method, "self-call"))
                    else:
                        flagged.append(_entry(path, name_line(node.func), method, "other-receiver"))
    # вызовы вне классов
    seen = {(e["path"], e["line"]) for e in entries + flagged}
    for path, tree in repo.trees.items():
        if is_test(path):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == method:
                if (path, name_line(node.func)) not in seen:
                    flagged.append(_entry(path, name_line(node.func), method, "outside-class"))
    return entries, flagged


def rel_uses(repo: Repo, spec: dict[str, Any]) -> tuple[list, list]:
    """Модульные привязки (Assign/AnnAssign, не def/class), которые ЧИТАЕТ функция ``spec.path::spec.name``:
    свои константы файла и импортированные из других модулей. Запись — строка ОПРЕДЕЛЕНИЯ привязки."""
    path = spec["path"]
    func = repo.top_defs(path)[spec["name"]]
    local = {a.arg for a in ast.walk(func.args) if isinstance(a, ast.arg)}  # type: ignore[attr-defined]
    local |= {n.id for n in ast.walk(func) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    entries: dict[tuple[str, int], dict] = {}
    for node in ast.walk(func):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in local:
            if node.id in repo.bindings(path):
                r = repo.resolve(*repo.bindings(path)[node.id])
            elif node.id in repo.top_defs(path):
                r = (path, node.id)
            else:
                continue
            if r is None or r[1] is None:
                continue
            definition = repo.top_defs(r[0]).get(r[1])
            if isinstance(definition, (ast.Assign, ast.AnnAssign)):
                entries[(r[0], definition.lineno)] = _entry(r[0], definition.lineno, r[1], "module-binding")
    return list(entries.values()), []


RELATIONS = {
    "callers": rel_callers,
    "subclasses": rel_subclasses,
    "structural": rel_structural,
    "importers": rel_importers,
    "threads": rel_threads,
    "env_reads": rel_env_reads,
    "self_callers": rel_self_callers,
    "uses": rel_uses,
}


def build(root: Path, spec_doc: dict[str, Any]) -> dict[str, Any]:
    repo = Repo(load_sources(root, spec_doc["repo_sha"], spec_doc.get("exclude", [])))
    out: dict[str, Any] = {"repo_sha": spec_doc["repo_sha"], "files_parsed": len(repo.trees), "questions": {}}
    for qid, spec in spec_doc["questions"].items():
        entries, flagged = RELATIONS[spec["relation"]](repo, spec)
        drop = {(d["path"], d["line"]) for d in spec.get("manual_exclude", [])}
        add = spec.get("manual_include", [])
        scope = spec.get("scope")
        if scope:
            entries = [e for e in entries if e["path"].startswith(tuple(scope))]
        uniq: dict[tuple[str, Any], dict] = {}
        for e in entries:
            uniq.setdefault((e["path"], e["line"]), e)  # два имени на одной строке — один адрес
        entries = [e for k, e in uniq.items() if k not in drop] + add
        entries.sort(key=lambda e: (e["path"], e["line"] or 0))
        out["questions"][qid] = {"relation": spec["relation"], "entries": entries, "flagged": flagged}
    return out


def check(truth: dict[str, Any], qset: dict[str, Any]) -> list[str]:
    problems = []
    for q in qset["questions"]:
        want = {(e["path"], e["line"]) for e in truth["questions"].get(q["id"], {}).get("entries", [])}
        have = {(e["path"], e["line"]) for e in q.get("expected") or []}
        if want != have:
            problems.append(f"{q['id']}: лишние в наборе {sorted(have - want)}, нет в наборе {sorted(want - have)}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--spec", type=Path, default=HERE / "spec.json")
    ap.add_argument("--out", type=Path, default=HERE / "truth.json")
    ap.add_argument("--check", type=Path, help="набор вопросов: сверить expected с эталоном")
    args = ap.parse_args(argv)
    truth = build(args.root, json.loads(args.spec.read_text(encoding="utf-8")))
    args.out.write_text(json.dumps(truth, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for qid, q in truth["questions"].items():
        print(f"{qid} {q['relation']}: записей {len(q['entries'])}, flagged {len(q['flagged'])}")
    if args.check:
        problems = check(truth, json.loads(args.check.read_text(encoding="utf-8")))
        for p in problems:
            print(f"РАСХОЖДЕНИЕ: {p}")
        print(f"check: расхождений {len(problems)}")
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
