"""Виды для агента: `card`, `pack`, `log` (Task 1.6, ADR-ATL-001 §1-3).

Purpose: `card` и `pack` читают SQLite реестра по build_id (ленивая сборка через build) и git ревизии;
    `log` реестра не строит: modules.yaml ревизии main-ref и `git log`. Вид возвращает список строк;
    соединение приходит от вызывающего, `store.connect` здесь не зовётся.
Public API: TASK_ID_PATTERN, card, log, pack.
Stability: lite
"""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from scripts.atlas.adapters.modules import modules_for
from scripts.atlas.build import build
from scripts.atlas.modules import OTHER, resolve as module_of
from scripts.atlas.tree import AtlasError, Tree, resolve, run_git
from scripts.validate_commit.validate_commit import TASK_ID_PATTERN

__all__ = ["TASK_ID_PATTERN", "card", "log", "pack"]

_OPEN = ("pending", "in_progress", "blocked")
_SEVERITY = {"blocking": 0, "warning": 1, "info": 2}
_NO_README = "нет README в docs: modules.yaml"
_TASK_LINE = re.compile(r"Task:[ \t]*([a-z0-9][a-z0-9-]*#(?:" + TASK_ID_PATTERN + r"))[ \t]*", re.ASCII)
_SKIP = ("#", "---", "|", ">", "<", "!", "-", "*", "[")


def _natural(text: str) -> list[tuple[int, int, str]]:
    """Ключ натурального порядка: числа < слова, числа по значению, остальное как строки."""
    return [(0, int(c), "") if c.isdecimal() else (1, 0, c) for c in re.findall(r"\d+|[A-Za-z]+|[^\dA-Za-z]+", text)]


def _git(root: Path, *args: str, input: bytes | None = None) -> bytes:
    proc = run_git(root, *args, input=input)
    if proc.returncode != 0:
        raise AtlasError(f"atlas: git {args[0]} failed: {proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc.stdout


def _by_sha(root: Path, shas: list[str], *flags: str) -> bytes:
    """`git log --no-walk=unsorted` по списку SHA (порядок входа сохраняется)."""
    return _git(root, "log", "--no-walk=unsorted", "--stdin", *flags, input="".join(f"{s}\n" for s in shas).encode())


def _short(subject: str) -> str:
    return subject if len(subject) <= 90 else subject[:89] + "…"


def _date(seconds: int | None) -> str:
    return datetime.fromtimestamp(seconds or 0, timezone.utc).strftime("%Y-%m-%d")


def _module_row(rows: list[dict], module: str) -> dict:
    for row in rows:
        if row["id"] == module:
            return row
    raise AtlasError("atlas: module not found")


def _purpose(tree: Tree, row: dict) -> str:
    readme = next((d for d in row["docs"] if isinstance(d, str) and d.endswith("README.md")), None)
    try:
        text = tree.read(readme).decode("utf-8", "replace") if readme else ""
    except FileNotFoundError:
        return _NO_README
    fenced = False
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("```"):
            fenced = not fenced
        elif line and not fenced and not line.startswith(_SKIP):
            return line if len(line) <= 160 else line[:159] + "…"
    return _NO_README


def _open_tasks(con: sqlite3.Connection, bid: int, shas: set[str]) -> list[str]:
    """Строки секции «Открытые задачи»: связь плана с модулем — коммит `touches` + `refs` на план или `implements`."""
    plan_of: dict[str, str] = {}
    pairs: list[tuple[str, str, str]] = []
    for kind, src, dst in con.execute(
        "SELECT kind, src, dst FROM edges WHERE build_id = ? AND kind IN ('refs', 'implements', 'in_plan')", (bid,)
    ):
        if kind == "in_plan":
            plan_of[src[5:]] = dst[5:]
        elif src[7:] in shas:
            pairs.append((kind, src[7:], dst[5:]))
    linked: dict[str, set[str]] = defaultdict(set)
    for kind, sha, target in pairs:
        slug = target if kind == "refs" else plan_of.get(target)
        if slug is not None:
            linked[slug].add(sha)
    open_ids: dict[str, list[str]] = defaultdict(list)
    marks = ", ".join("?" * len(_OPEN))
    for (task,) in con.execute(
        f"SELECT id FROM nodes WHERE build_id = ? AND kind = 'task' AND status IN ({marks})", (bid, *_OPEN)
    ):
        if plan_of.get(task) in linked:
            open_ids[plan_of[task]].append(task.partition("#")[2])
    if not open_ids:
        return ["Открытые задачи: нет"]
    plans = sorted(open_ids, key=lambda s: (-len(linked[s]), s))
    lines = [f"Открытые задачи ({len(plans)} планов, {sum(map(len, open_ids.values()))} задач):"]
    for slug in plans[:5]:
        ids = sorted(open_ids[slug], key=_natural)
        more = f", … ещё {len(ids) - 6}" if len(ids) > 6 else ""
        lines.append(f"  {slug} — {len(ids)}: {', '.join(ids[:6])}{more}")
    return lines + ([f"  … ещё {len(plans) - 5} планов"] if len(plans) > 5 else [])


def card(con: sqlite3.Connection, root: Path, ref: str, main_ref: str, module: str) -> list[str]:
    """Карточка модуля: назначение, API, открытые задачи, последние коммиты, находки (без доказанности)."""
    tree = Tree(root, resolve(root, ref))
    row = _module_row(modules_for(tree), module)
    bid = build(con, root, ref, main_ref)
    prefix = f"{module}:"
    names = sorted(
        i[len(prefix) :]
        for (i,) in con.execute(
            "SELECT id FROM nodes WHERE build_id = ? AND kind = 'interface' AND substr(id, 1, ?) = ?",
            (bid, len(prefix), prefix),
        )
    )
    api = ", ".join(names[:20]) + (f", … ещё {len(names) - 20}" if len(names) > 20 else "") if names else "—"
    commits = con.execute(
        "SELECT DISTINCT n.id, n.time FROM edges e JOIN nodes n ON n.build_id = e.build_id AND n.kind = 'commit' "
        "AND n.id = substr(e.src, 8) WHERE e.build_id = ? AND e.kind = 'touches' AND e.dst = ? "
        "ORDER BY n.time DESC, n.id",
        (bid, f"module:{module}"),
    ).fetchall()
    last = commits[:5]
    subjects = _by_sha(root, [s for s, _ in last], "-z", "--format=%s") if last else b""
    topics = [t.decode("utf-8", "replace") for t in subjects.split(b"\0")]
    found = con.execute(
        "SELECT severity, code, node, detail FROM findings WHERE build_id = ? AND (node = ? OR substr(node, 1, ?) = ?)",
        (bid, f"module:{module}", len(module) + 11, f"interface:{module}:"),
    ).fetchall()
    found.sort(key=lambda f: (_SEVERITY.get(f[0], 3), f[1], f[2], f[3]))
    tier = row["tier"] if row["tier"] is not None else "—"
    lines = [
        f"Модуль {module} — {row['layer']}, ярус {tier}",
        f"Назначение: {_purpose(tree, row)}",
        f"API ({len(names)}): {api}",
        *_open_tasks(con, bid, {s for s, _ in commits}),
        f"Коммиты ({len(commits)} всего, последние {len(last)}):",
        *(f"  {s[:7]} {_date(t)} {_short(topics[i])}" for i, (s, t) in enumerate(last)),
        f"Находки ({len(found)}):",
        *(f"  {sev} {code} {node} {detail or '-'}" for sev, code, node, detail in found[:10]),
    ]
    return lines + ([f"  … ещё {len(found) - 10}"] if len(found) > 10 else [])


def _plan_commits(root: Path, sha: str, slug: str) -> tuple[dict[str, list[str]], dict[str, int], dict[str, list[str]]]:
    """Коммиты плана из git: SHA -> id задач, SHA -> %ct, SHA -> пути (дифф против первого родителя)."""
    grep = "^Task: " + re.sub(r"([.^$*+?()\[\]{}|\\])", r"\\\1", slug) + "#"
    raw = _git(root, "log", sha, "--no-merges", "-E", "--grep", grep, "--format=%H%x00%ct%x00%B%x02")
    tasks: dict[str, list[str]] = {}
    times: dict[str, int] = {}
    for entry in raw.decode("utf-8", "replace").split("\x02"):
        head = entry.lstrip("\n").split("\0", 2)
        if len(head) < 3:
            continue
        ids = [
            m.group(1).partition("#")[2]
            for m in map(_TASK_LINE.fullmatch, head[2].split("\n"))
            if m and m.group(1).startswith(f"{slug}#")
        ]
        if ids:
            tasks[head[0]], times[head[0]] = ids, int(head[1])
    paths: dict[str, list[str]] = defaultdict(list)
    if tasks:
        current, fresh = "", False
        for token in _by_sha(
            root, list(tasks), "-m", "--first-parent", "--no-renames", "--name-only", "-z", "--format=%x01%H"
        ).split(b"\0"):
            text = token.decode("utf-8", "replace")
            if text.startswith("\x01"):
                current, fresh = text[1:], True
                continue
            text, fresh = (text.lstrip("\n") if fresh else text), False
            if text:
                paths[current].append(text)
    return tasks, times, paths


def _section(lines: list[str], title: str) -> list[str] | None:
    """Строки раздела `## title` либо абзаца `**title.**` (после strip, непустые); None — раздела нет."""
    marker = f"**{title}.**"
    for i, line in enumerate(lines):
        if line.rstrip() == f"## {title}":
            body = []
            for nxt in lines[i + 1 :]:
                if nxt.startswith("## "):
                    break
                body.append(nxt.strip())
            return [b for b in body if b]
        if line.strip().startswith(marker):
            body = [line.strip()[len(marker) :].strip()]
            for nxt in lines[i + 1 :]:
                if not nxt.strip() or nxt.strip().startswith("**"):
                    break
                body.append(nxt.strip())
            return [" ".join(b for b in body if b)] if any(body) else []
    return None


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _text(tree: Tree, path: str) -> str:
    return tree.read(path).decode("utf-8", "replace")


def _result_parts(path: str, text: str) -> list[str]:
    lines = text.split("\n")
    parts: list[str] = []
    sections = {title: _section(lines, title) for title in ("Осталось", "Не проверено")}
    if all(s is None for s in sections.values()):
        parts.append(f"    итог без разделов формы 0.7: {path}")
    for title, body in sections.items():
        if body and not (len(body) == 1 and re.sub(r"^[-*]\s+", "", body[0]) == "нет"):
            parts += [f"    {title}:", *(f"      {b}" for b in body)]
    rows: list[str] = []
    in_table = False
    for line in lines:
        if not line.strip().startswith("|"):
            in_table = False
            continue
        cells = _cells(line)
        if cells[:1] == ["инъекция"] and [c[:11] for c in cells[1:3]] == ["предсказано", "наблюдалось"]:  # 11 знаков
            in_table = True
        elif in_table and len(cells) >= 3 and all(c.isdecimal() for c in cells[1:3]) and int(cells[1]) != int(cells[2]):
            rows.append(f"      {cells[0]} — предсказано {cells[1]}, наблюдалось {cells[2]}")
    if rows:
        parts += [f"    Инъекции, где предсказано ≠ наблюдалось ({len(rows)}):", *rows]
    return parts


def _lead_parts(text: str) -> list[str]:
    rows: list[str] = []
    inside = False
    for line in text.split("\n"):
        if line.startswith("## "):
            inside = line.startswith("## Открыто для лида")
        elif inside and line.strip().startswith("|"):
            cells = _cells(line)
            if len(cells) >= 2 and re.fullmatch(r"О[0-9]+", cells[0]):
                rows.append(f"      {cells[0]}: {cells[1]}")
    return [f"    Открыто для лида ({len(rows)}):", *rows] if rows else []


def _tails(
    tree: Tree,
    slug: str,
    plan_path: str,
    own: str,
    status_of: dict[str, str],
    mods: dict[str, set[str]],
    wanted: list[str],
) -> list[str]:
    if not plan_path.endswith("/plan.md"):
        return ["Хвосты прошлых задач плана: у плана нет каталога tasks/"]
    folder = plan_path[: -len("plan.md")] + "tasks/"
    names = {p[len(folder) :] for p in tree.files() if p.startswith(folder) and "/" not in p[len(folder) :]}
    ids = {n.removesuffix(".result.md").removesuffix(".md") for n in names if n.endswith(".md")}
    blocks: list[tuple[str, str | None, list[str]]] = []
    for tid in sorted(ids, key=_natural):
        if tid == own or not re.fullmatch(TASK_ID_PATTERN, tid, re.ASCII):
            continue
        if wanted and mods.get(tid) and not mods[tid] & set(wanted):
            continue
        status = status_of.get(tid)
        parts: list[str] = []
        if f"{tid}.result.md" in names:
            parts += _result_parts(f"{folder}{tid}.result.md", _text(tree, f"{folder}{tid}.result.md"))
        if f"{tid}.md" in names and status != "done":
            parts += _lead_parts(_text(tree, f"{folder}{tid}.md"))
        if parts:
            blocks.append((tid, status, parts))
    return [f"Хвосты прошлых задач плана ({len(blocks)} задач):"] + [
        line for tid, status, parts in blocks for line in (f"  {slug}#{tid} ({status or '—'}):", *parts)
    ]


def pack(con: sqlite3.Connection, root: Path, ref: str, main_ref: str, task: str, modules: list[str]) -> list[str]:
    """Бриф задачи: модули, файлы-кандидаты в FILES (из git), хвосты прошлых задач плана."""
    slug, sep, tid = task.partition("#")
    if not (sep and slug and tid and re.fullmatch(TASK_ID_PATTERN, tid, re.ASCII)):
        raise AtlasError("atlas: task must be <slug>#<id>")
    sha = resolve(root, ref)
    tree = Tree(root, sha)
    rows = modules_for(tree)
    for module in modules:
        _module_row(rows, module)
    bid = build(con, root, ref, main_ref)
    node = con.execute(
        "SELECT status, path FROM nodes WHERE build_id = ? AND kind = 'task' AND id = ?", (bid, task)
    ).fetchone()
    if node is None:
        raise AtlasError("atlas: task not found")
    tasks, times, paths = _plan_commits(root, sha, slug)
    mods: dict[str, set[str]] = defaultdict(set)  # id задачи -> модули её коммитов (без other)
    latest: dict[str, int] = {}  # id задачи -> время самого позднего коммита, тронувшего модуль
    owners: dict[str, set[str]] = defaultdict(set)  # путь -> id задач плана
    for s, ids in tasks.items():
        found = {module_of(p, rows) for p in paths.get(s, [])} - {OTHER}
        for t in ids:
            mods[t] |= found
            if found:
                latest[t] = max(latest.get(t, 0), times[s])
            for p in paths.get(s, []):
                owners[p].add(t)
    if modules:
        chosen, source = sorted(modules), "--module"
    elif mods.get(tid):
        chosen, source = sorted(mods[tid]), "коммиты задачи"
    elif latest:
        newest = max(latest, key=lambda t: (latest[t], _natural(t)))
        chosen, source = sorted(mods[newest]), f"последняя задача плана с модулями — {newest}"
    else:
        chosen, source = [], ""
    present = set(tree.files())
    files = sorted(p for p in owners if p in present and module_of(p, rows) in chosen)
    head = f"{slug}#"
    status_of = {
        i[len(head) :]: st
        for i, st in con.execute(
            "SELECT id, status FROM nodes WHERE build_id = ? AND kind = 'task' AND substr(id, 1, ?) = ?",
            (bid, len(head), head),
        )
    }
    return [
        f"Задача {task} — статус {node[0]}, план {node[1]}",
        f"Модули: {', '.join(chosen)} ({source})" if chosen else "Модули: — (у плана нет коммитов с модулями)",
        f"Файлы-кандидаты в FILES ({len(files)}):",
        *(f"  {p} — {', '.join(sorted(owners[p], key=_natural))}" for p in files),
        *_tails(tree, slug, node[1], tid, status_of, mods, chosen),
    ]


def log(root: Path, main_ref: str, module: str, limit: int) -> list[str]:
    """Лог модуля: first-parent `main-ref` по путям модуля, группы по `Task:` (с боковой веткой слияния)."""
    sha = resolve(root, main_ref)
    rows = modules_for(Tree(root, sha))
    row = _module_row(rows, module)
    own = row["paths"]
    inner = [
        e
        for r in rows
        if r is not row
        for e in r["paths"]
        if any(o.endswith("/") and e.startswith(o) and len(e) > len(o) for o in own)
    ]
    spec = ["--", *(f":(literal){e}" for e in own), *(f":(exclude,literal){e}" for e in inner)]
    entries: list[tuple[str, int, str, list[str]]] = []
    raw = (
        _git(root, "log", "--first-parent", "-n", str(limit), sha, "--format=%H%x00%P%x00%ct%x00%B%x02", *spec)
        if own
        else b""
    )
    for entry in raw.decode("utf-8", "replace").split("\x02"):
        head = entry.lstrip("\n").split("\0", 3)
        if len(head) < 4:
            continue
        body = [head[3]]
        parents = head[1].split()
        if len(parents) > 1:
            side = _git(root, "log", *parents[1:], f"^{parents[0]}", "--format=%B%x02", *spec)
            body.append(side.decode("utf-8", "replace"))
        keys = dict.fromkeys(m.group(1) for m in map(_TASK_LINE.fullmatch, "\n".join(body).split("\n")) if m)
        entries.append((head[0], int(head[2]), head[3].split("\n", 1)[0].strip(), list(keys)))
    groups: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    for s, t, subject, keys in entries:
        for key in keys or ["(без Task)"]:
            groups[key].append((s, t, subject))
    order = sorted(
        (k for k in groups if k != "(без Task)"), key=lambda k: (-max(t for _, t, _ in groups[k]), _natural(k))
    )
    lines = [f"Лог модуля {module} — first-parent {main_ref}, записей {len(entries)}"]
    for key in [*order, *(["(без Task)"] if "(без Task)" in groups else [])]:
        label = key if key == "(без Task)" else f"Task {key}"
        lines += [
            f"{label} ({len(groups[key])}):",
            *(f"  {s[:7]} {_date(t)} {_short(subj)}" for s, t, subj in groups[key]),
        ]
    return lines
