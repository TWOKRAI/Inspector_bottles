"""Вид `brief`: блок FACTS задачи между маркерами с sha ревизии (Task 1.9b, ADR-ATL-004 §2.5).

Purpose: строка факта `- <что> — `<команда>` → `<литерал>`` — вывод видов pack/card/ref, вызванных в процессе теми же
    аргументами, что записаны в команде. `write` кладёт блок в `<план>/tasks/<id>.md` (каркас, замена между
    маркерами, вставка перед DESIGN, концы строк сохраняются); `check` без сборки и SQLite сверяет рабочее дерево
    с ревизией маркера по входам блока. Живые строки (ветки, радиус тестов) — только на HEAD.
Public API: brief, check, marker, task_file, write.
Stability: lite
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

from scripts.atlas import reference, views
from scripts.atlas.adapters.modules import modules_for
from scripts.atlas.adapters.plans import _DATE_PREFIX
from scripts.atlas.build import build
from scripts.atlas.codemap import USAGE_UNKNOWN, is_test
from scripts.atlas.modules import resolve as module_of
from scripts.atlas.tree import AtlasError, Tree, git_z, resolve, run_git
from scripts.plans_ledger import _brief_label_positions

__all__ = ["brief", "check", "marker", "task_file", "write"]

_OPEN = re.compile(r"^<!-- atlas:facts ([0-9a-f]{7}) -->$")
_CLOSE = "<!-- /atlas:facts -->"
_symbols = reference._code_symbols
_FACT = re.compile(r"^[ \t]*- .+? — `(?P<cmd>[^`]+)` → (?:`(?P<lit>[^`]+)`|exit \d+)$")
_MEMBER = re.compile(r"\S  :\d+$")
_USE = re.compile(r"^  (\S+):(\d+)  (?:импорт|вызов)$")
_TEST_USE = re.compile(r"^    (\S+):\d+  импорт, тестов \d+$")
_SECTION = re.compile(r"^    (Не проверено|Осталось|Для следующего брифа|Открыто для лида)\b")
_TASK_ID = re.compile(r"^  \S+#(\S+) \(")
(TASK, IFACE, OBJECT, CAND, TESTS, USERS, STATIC, VIA, TAILS, FOUND, NEAR, LIVE) = range(12)  # порядок блока (п. 5)
_LABELS = ("DESIGN (decided by the lead):", "FILES:", "REDS:", "ACCEPTANCE:", "TESTS:", "OUT OF SCOPE:")


def _lit(line: str) -> str | None:
    """Самый длинный элемент строки между обратными кавычками (без краевых пробелов); короче 8 знаков — None."""
    lit = max((part.strip() for part in line.strip().split("`")), key=len)
    return lit if len(lit) >= 8 else None


def _from(lines: list[str], prefix: str) -> list[str]:
    return next((lines[i:] for i, x in enumerate(lines) if x.startswith(prefix)), [])


def _body(lines: list[str], cap: int | None = None) -> list[str]:
    rest = lines[1:]
    stop = next((i for i, x in enumerate(rest) if not x.startswith("  ") or x.strip().startswith("…")), len(rest))
    return rest[:stop][:cap]


def _usage(lines: list[str]) -> list[str]:
    use = _from(lines, "Кто использует")
    return use if use and use[0] != USAGE_UNKNOWN else []


def _enclosing(tree: Tree, path: str, line: int) -> str | None:
    """Публичное определение верхнего уровня, объемлющее строку файла ревизии (AST)."""
    try:
        body = ast.parse(tree.read(path).decode("utf-8", "replace").removeprefix("﻿")).body
    except (FileNotFoundError, SyntaxError, ValueError):
        return None
    return next(
        (
            n.name
            for n in body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and n.name[0] != "_"
            and n.lineno <= line <= n.end_lineno
        ),
        None,
    )


def _live(root: Path, main_ref: str, paths: list[str], targets: list[str], add) -> None:
    """Ветки модулей и радиус тестов; сбой — строки нет, причина в stderr."""
    args = ["log", "--oneline", "--source", "--branches", "--not", main_ref, "--", *paths]
    rows = [ln.split() for ln in run_git(root, *args).stdout.decode("utf-8", "replace").splitlines()]
    for name in list(dict.fromkeys(r[1].removeprefix("refs/heads/") for r in rows if len(r) > 1))[:5]:
        add(LIVE, "ветка трогает модуль", "git " + " ".join(args), name, False)
    tests = ["--collect-only", "-q", "-p", "no:cacheprovider", *targets]
    try:
        run = subprocess.run([sys.executable, "-m", "pytest", *tests], cwd=root, capture_output=True,
                             encoding="utf-8", errors="replace", timeout=120, check=False)  # fmt: skip
        found = re.search(r"\d+ tests? collected", run.stdout)
        if run.returncode != 0 or found is None:
            raise AtlasError(f"код {run.returncode}, {(run.stdout + run.stderr).strip()[-200:]}")
        add(LIVE, "радиус тестов", "python -m pytest " + " ".join(tests), found[0], False)
    except (AtlasError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"brief: радиус тестов не посчитан — {exc}", file=sys.stderr)


def brief(
    con, root: Path, ref: str, main_ref: str, task: str, modules: list[str], symbol: str | None, main_ref_given: bool
) -> list[str]:
    """Строки блока: метка FACTS, открывающий маркер, факты, закрывающий маркер."""
    sha = resolve(root, ref)
    slug, _, tid = task.partition("#")
    tail = f" --ref {sha[:7]}" + (f" --main-ref {main_ref}" if main_ref_given else "")
    tree, facts = Tree(root, sha), []
    rows, files = modules_for(tree), tree.files()

    def run(args: str, fn, *a) -> tuple[str, list[str]]:
        return f"python -m scripts.atlas {args}{tail}", fn(con, root, sha, main_ref, *a)

    def add(stage: int, what: str, cmd: str, line: str, floor: bool = True) -> None:
        lit = _lit(line) if floor else line
        if lit and (row := (stage, what, cmd, lit)) not in facts:
            facts.append(row)

    def pack(mods: list[str]) -> tuple[str, list[str]]:
        return run(f"pack {task}" + "".join(f" --module {m}" for m in mods), views.pack, task, mods)

    cmd0, first = pack(modules)
    add(TASK, "задача", cmd0, first[0])
    add(TASK, "модули задачи", cmd0, first[1])
    listed = re.match(r"Модули: (.+) \(", first[1])
    chosen = modules or [m for m in (listed[1].split(", ") if listed else []) if m != "—"]
    text_files, owner, section = [], None, None
    for cmd, lines in [(cmd0, first), *([pack(chosen)] if chosen and not modules else [])]:
        for line in _body(_from(lines, "Файлы-кандидаты в FILES")):
            from_text = line.endswith(" — из текста задачи")
            add(CAND, "кандидат в FILES из " + ("текста" if from_text else "прошлой задачи"), cmd, line)
            text_files += [line.strip().split(" — ")[0]] * from_text
    for line in first:  # хвосты прошлых задач: тела разделов, до 10
        owner = m[1] if (m := _TASK_ID.match(line)) else owner
        if m := _SECTION.match(line):
            section = m[1].lower()
        elif not line.startswith("      "):
            section = None
        elif section and sum(f[0] == TAILS for f in facts) < 10:
            add(TAILS, f"хвост {owner}, {section}", cmd0, line)
    for module in chosen:
        cmd, card = run(f"card {module}", views.card, module)
        found = _from(card, "Находки (")
        add(IFACE, f"интерфейсы модуля {module}", cmd, (_from(card, "API (") or [""])[0])
        add(FOUND, f"находки модуля {module}", cmd, (found or [""])[0])
        for line in _body(found, 5):
            add(FOUND, f"находка модуля {module}", cmd, line)
        for line in [x for x in _body(_from(card, "Открытые задачи")) if not x.startswith(f"  {slug} — ")][:5]:
            add(NEAR, f"сосед по модулю {module}", cmd, line)
    plan = re.search(r", план (\S+)$", first[0])
    text = re.search(
        rf"^- Task {re.escape(tid)}:.*?(?=^- Task|^## |\Z)", tree.read(plan[1]).decode("utf-8", "replace"), re.S | re.M
    )
    wanted = [symbol] if symbol else list(dict.fromkeys(re.findall(r"`([A-Za-z_]\w*)`", text[0] if text else "")))
    names = {}  # публичный символ -> модуль; считается, только если есть кого искать
    for module in chosen if wanted else []:
        sql = "SELECT id FROM nodes WHERE build_id = ? AND kind = 'interface' AND substr(id, 1, ?) = ?"
        own = [f for f in files if f.endswith(".py") and not is_test(f) and module_of(f, rows) == module]
        ifaces = con.execute(sql, (build(con, root, sha, main_ref), len(module) + 1, module + ":"))
        code = [n.name for _, nodes in _symbols(root, sha, own) for n in nodes]
        names.update({n: module for n in [i.partition(":")[2] for (i,) in ifaces] + code if n not in names})
    if symbol and symbol not in names:
        raise AtlasError(f"brief: символ {symbol} не найден в модулях {', '.join(chosen) or '—'}")
    objects = [(names[i], i) for i in wanted if i in names][:3]
    if not objects and not symbol:  # публичные символы файлов «из текста задачи»
        objects = [(module_of(p, rows), n.name) for p, ns in _symbols(root, sha, text_files) for n in ns][:3]
    if not objects:
        print("brief: объект задачи не найден — задать --symbol", file=sys.stderr)
    seen, uses, test_files = set(objects), [], []
    for module, name in objects:
        cmd, lines = run(f"ref {module} --symbol {name}", reference.ref, module, name)
        k, use, end = 2 if lines[1] in files else 1, _usage(lines), len(lines) - len(_from(lines, "Кто использует"))
        if k == 2:
            add(OBJECT, f"файл объекта {name}", cmd, lines[1])
        add(OBJECT, f"объект задачи {name}", cmd, lines[k])
        for line in [x for x in lines[k + 1 : end] if _MEMBER.search(x)][:8]:
            add(OBJECT, f"член {name}", cmd, line)
        add(STATIC, "не видно статикой", cmd, (use or [""])[0])
        for line in use:
            if m := _TEST_USE.match(line):
                add(TESTS, f"тест объекта {name}", cmd, line)
                test_files.append(m[1])
            elif m := _USE.match(line):
                add(USERS, f"потребитель {name} в коде", cmd, line)
                uses.append((m[1], int(m[2])))
    linked = 0
    for path, line in uses:  # второе звено: объемлющее определение потребителя и его потребители
        via, mod = _enclosing(tree, path, line), module_of(path, rows)
        if via is None or (mod, via) in seen or linked == 3:
            continue
        seen.add((mod, via))
        try:
            cmd, lines = run(f"ref {mod} --symbol {via}", reference.ref, mod, via)
        except AtlasError:
            continue
        linked += 1
        for x in filter(_USE.match, _usage(lines)):
            add(VIA, f"потребитель через {via}", cmd, x)
    if sha == resolve(root, "HEAD") and chosen:
        tests = {(f[: ("/" + f).find("/tests/") + 5] if "/tests/" in "/" + f else f.rpartition("/")[0] or f)
                 for f in files if is_test(f) and module_of(f, rows) in chosen}  # fmt: skip
        paths = [p for r in rows if r["id"] in chosen for p in r["paths"]]
        _live(root, main_ref, paths, sorted(tests) + list(dict.fromkeys(test_files)), add)
    label = f"FACTS (generated by python -m scripts.atlas brief {task}; edit DESIGN, not this block):"
    body = [f"- {w} — `{c}` → `{x}`" for _, w, c, x in sorted(facts, key=lambda row: row[0])]
    return [label, f"<!-- atlas:facts {sha[:7]} -->", *body, _CLOSE]


def marker(text: str) -> str | None:
    """sha7 открывающего маркера FACTS при наличии закрывающего, иначе None."""
    lines = text.splitlines()
    opens = [(i, m[1]) for i, x in enumerate(lines) if (m := _OPEN.match(x))]
    return opens[0][1] if opens and _CLOSE in lines[opens[0][0] + 1 :] else None


def task_file(root: Path, task: str) -> Path:
    """`<каталог плана>/tasks/<id>.md`; каталога плана с `plan.md` и этим slug нет -> AtlasError."""
    slug, sep, tid = task.partition("#")
    if not (sep and slug and re.fullmatch(views.TASK_ID_PATTERN, tid, re.ASCII)):
        raise AtlasError("atlas: task must be <slug>#<id>")
    plan = next((p for p in sorted(root.glob("plans/*/plan.md")) if _DATE_PREFIX.sub("", p.parent.name) == slug), None)
    if plan is None:
        raise AtlasError(f"brief: нет плана {slug} с каталогом tasks/ (путь плана должен кончаться на /plan.md)")
    return plan.parent / "tasks" / f"{tid}.md"


def _skeleton(root: Path, task_path: Path) -> list[str]:
    tid, plan = task_path.stem, task_path.parent.parent / "plan.md"
    text = plan.read_text(encoding="utf-8") if plan.is_file() else ""
    row = re.search(rf"^- Task {re.escape(tid)}:(.*?)(?: — |$)", text, re.M)
    title, rel = (row[1].strip() if row else "")[:80], plan.relative_to(root).as_posix()
    head = [f"# Task {tid} — {title}", "", f"Основание: строка Task {tid} в `{rel}`.", "", "## Открыто для лида", "",
            "| № | вопрос | замер | умолчание брифа |", "|---|---|---|---|", "",
            f"TASK: {tid} — {title}", "ROLE: developer", "CHAIN:"]  # fmt: skip
    return [*head, *(x for label in _LABELS for x in ("", label)), ""]


def write(root: Path, task_path: Path, block: list[str]) -> str:
    """Блок в файл задачи: каркас, замена между маркерами или вставка перед DESIGN; концы строк сохраняются."""
    old = task_path.read_bytes().decode("utf-8") if task_path.exists() else None
    eol = "\r\n" if old and "\r\n" in old else "\n"
    lines = _skeleton(root, task_path) if old is None else old.replace("\r\n", "\n").split("\n")
    start = next((i for i, x in enumerate(lines) if _OPEN.match(x)), None)
    end = next((i for i, x in enumerate(lines) if start is not None and i > start and x == _CLOSE), None)
    if end is not None:
        start -= 1 if start and lines[start - 1].startswith("FACTS") else 0
        lines[start : end + 1] = block
    else:
        labels = _brief_label_positions("\n".join(lines))
        if any(name == "FACTS" for _, name in labels):
            raise AtlasError("brief: метка FACTS без маркеров — заменить блок вручную или убрать метку")
        if (design := next((i for i, name in labels if name == "DESIGN"), None)) is None:
            raise AtlasError("brief: в файле нет метки DESIGN — блок некуда вставить")
        lines[design:design] = [*block, ""]
    task_path.parent.mkdir(parents=True, exist_ok=True)
    task_path.write_bytes(eol.join(lines).encode("utf-8"))
    return f"brief --write: {task_path.relative_to(root).as_posix()}"


def check(root: Path, task_path: Path) -> tuple[int, list[str]]:
    """Рабочее дерево против ревизии маркера по входам блока: (0, свежий) | (1, отстал) | AtlasError (2)."""
    if not task_path.is_file():
        raise AtlasError(f"brief --check: нет файла {task_path.relative_to(root).as_posix()}")
    text = task_path.read_bytes().decode("utf-8")
    if (sha7 := marker(text)) is None:
        raise AtlasError("brief --check: в файле нет маркеров FACTS")
    tree = Tree(root, resolve(root, sha7))
    by_id, present, inputs = {r["id"]: r["paths"] for r in modules_for(tree)}, set(tree.files()), set()
    for line in text.split(_CLOSE)[0].rpartition("<!-- atlas:facts ")[2].splitlines():
        if not (m := _FACT.match(line)) or not m["cmd"].startswith("python -m scripts.atlas "):
            continue
        args = m["cmd"].split()[3:]
        mods = [b for a, b in zip(args, args[1:]) if a == "--module"] if args[0] == "pack" else args[1:2]
        inputs.update(p for mod in mods for p in by_id.get(mod, []))
        for item in (m["lit"] or "").split():
            item = re.sub(r":\d+$", "", item.strip(",;()"))
            inputs.update([item] * ("/" in item and item in present))
    paths = sorted(p for p in inputs if not p.startswith("plans/"))
    changed = git_z(root, "diff", "--name-only", "-z", sha7, "--", *paths) if paths else []
    if not changed:
        return 0, [f"brief --check: свежий ({sha7})"]
    return 1, [f"brief --check: отстал от {sha7}, файлов {len(changed)}", *(f"  {p}" for p in changed[:10])]
