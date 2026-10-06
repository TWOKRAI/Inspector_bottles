"""Одноразовый инструмент 2.4g.3: применить TSV-разметку памяти к дереву.

    python apply_2.4g.py --root DIR --tsv FILE [--collisions FILE] [--dry-run]

TSV: `file<TAB>module<TAB>mechanism<TAB>description` (module/mechanism — id через запятую, module может быть пуст).
Коллизии: `loser<TAB>winner`. Пути абсолютные внутри `--root`.

Что делает:
- коллизии первыми: проигравший `git mv` в `docs/claude/memory/_archive/` (при занятом имени — суффикс `-<role>`),
  победителю в frontmatter добавляется `merged_from: [<имя проигравшего>]`;
- уроки ролей `git mv` в корень канона; у каждого урока переписывается ТОЛЬКО frontmatter (description/module/
  mechanism/role), тело после закрывающей `---` копируется байт в байт, концы строк сохраняются;
- в каждом каталоге роли `.claude/agent-memory/<role>/` пишется `MEMORY.md` из 3 строк;
- в конце — `scripts/memory/tags.py --check --root DIR`; код выхода только печатается.

Любое нарушение входа (нет файла, путь вне корня, неизвестный id, tab/перевод строки в description) — выход 2
и НИЧЕГО не меняется на диске: сначала строится весь план в памяти, потом он применяется.
"""

from __future__ import annotations

import argparse
import re
import subprocess  # nosec B404 — одноразовый инструмент, фиксированные аргументы
import sys
from dataclasses import dataclass, field
from pathlib import Path

# scripts/memory лежит в репо инструмента, а не в --root (у тестовой фикстуры его нет)
SCRIPTS_MEMORY = Path(__file__).resolve().parents[4] / "scripts" / "memory"
sys.path.insert(0, str(SCRIPTS_MEMORY))

import _lessons  # noqa: E402
import tags  # noqa: E402

REMOVED_KEYS = ("module", "mechanism", "role", "description")
ARCHIVE = "_archive"
ROLE_MEMORY_LINES = (
    "Lessons of every role live in docs/claude/memory/ (main checkout); this directory holds no lessons.",
    'Search: python "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/memory/search.py" <3-5 words>',
    "New lesson: a MEMORY LESSON <name>.md block in your final report; the lead files it.",
)


class Refuse(Exception):
    """Вход нарушает контракт: выход 2, диск не тронут."""


@dataclass
class Row:
    path: Path
    modules: list[str]
    mechanisms: list[str]
    description: str


@dataclass
class Plan:
    moves: list[tuple[Path, Path]] = field(default_factory=list)
    writes: dict[Path, bytes] = field(default_factory=dict)  # итоговый путь -> байты
    notes: list[str] = field(default_factory=list)
    role_dirs: list[Path] = field(default_factory=list)


# --------------------------------------------------------------------------- frontmatter


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _split_bytes(data: bytes) -> list[bytes]:
    """Строки с их концами; режем только по \\n, чтобы \\r\\n оставался при строке."""
    return re.findall(rb"[^\n]*\n|[^\n]+", data)


def _edit_frontmatter(data: bytes, edit) -> bytes:
    """Применить `edit(lines, eol) -> lines` к строкам frontmatter; всё после него — байты оригинала."""
    lines = _split_bytes(data)
    bom = b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b""
    if not lines or lines[0][len(bom) :].decode("utf-8", "replace").rstrip() != "---":
        raise Refuse("no frontmatter")
    close = next((i for i in range(1, len(lines)) if lines[i].decode("utf-8", "replace").rstrip() == "---"), None)
    if close is None:
        raise Refuse("frontmatter is not closed")
    eol = "\r\n" if lines[0].endswith(b"\r\n") else "\n"
    try:
        head = [ln.decode("utf-8").rstrip("\r\n") for ln in lines[1:close]]
    except UnicodeDecodeError:
        raise Refuse("frontmatter is not valid UTF-8") from None
    new_head = edit(head, eol)
    return lines[0] + "".join(ln + eol for ln in new_head).encode("utf-8") + b"".join(lines[close:])


def _strip_keys(head: list[str], keys: tuple[str, ...]) -> tuple[list[str], dict[str, str], bool]:
    """Убрать ключи (верх и под `metadata:`) с продолжением; вернуть (строки, значения убранных, был ли вложенный)."""
    out: list[str] = []
    in_meta = False
    skip_indent: int | None = None
    removed_nested = False
    removed_lines: dict[str, str] = {}
    for ln in head:
        if skip_indent is not None:
            continues = ln.strip() != "" and (
                _indent(ln) > skip_indent or (_indent(ln) == skip_indent and ln.lstrip().startswith("- "))
            )
            if continues:
                continue
            skip_indent = None
        m = _lessons._KEY_LINE.match(ln)
        if m:
            key, ind = m["key"], len(m["indent"])
            if ind == 0:
                in_meta = key == "metadata"
            if key in keys and (ind == 0 or in_meta):
                skip_indent = ind
                removed_nested = removed_nested or ind > 0
                removed_lines[key] = m["value"]
                continue
        out.append(ln)
    return out, removed_lines, removed_nested


def _drop_empty_metadata(head: list[str]) -> list[str]:
    """`metadata:` без детей (мы вынули всё вложенное) убирается: пустой блок парсится как null."""
    for i, ln in enumerate(head):
        m = _lessons._KEY_LINE.match(ln)
        if m and not m["indent"] and m["key"] == "metadata" and not m["value"].strip():
            if i + 1 >= len(head) or _indent(head[i + 1]) == 0 or head[i + 1].strip() == "":
                return head[:i] + head[i + 1 :]
    return head


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _flow(values: list[str]) -> str:
    return "[" + ", ".join(values) + "]"


def retag_bytes(data: bytes, *, description: str, modules: list[str], mechanisms: list[str], role: str | None) -> bytes:
    def edit(head: list[str], eol: str) -> list[str]:
        stripped, _, removed_nested = _strip_keys(head, REMOVED_KEYS)
        if removed_nested:
            stripped = _drop_empty_metadata(stripped)
        new = [f"description: {_quote(description)}"]
        if modules:
            new.append(f"module: {_flow(modules)}")
        if mechanisms:
            new.append(f"mechanism: {_flow(mechanisms)}")
        if role:
            new.append(f"role: {role}")
        at = 0
        for i, ln in enumerate(stripped):
            m = _lessons._KEY_LINE.match(ln)
            if m and not m["indent"] and m["key"] == "name":
                at = i + 1
                break
        return stripped[:at] + new + stripped[at:]

    return _edit_frontmatter(data, edit)


def add_merged_from(data: bytes, stems: list[str]) -> bytes:
    def edit(head: list[str], eol: str) -> list[str]:
        stripped, removed, _ = _strip_keys(head, ("merged_from",))
        merged = list(_lessons._split_list(removed.get("merged_from", "")))
        merged += [s for s in stems if s not in merged]
        return [*stripped, f"merged_from: {_flow(merged)}"]

    return _edit_frontmatter(data, edit)


# --------------------------------------------------------------------------- вход


def _read_tsv(path: Path, columns: int, what: str) -> list[list[str]]:
    if not path.is_file():
        raise Refuse(f"{what} file does not exist: {path}")
    rows = []
    for n, raw in enumerate(path.read_bytes().decode("utf-8-sig").split("\n"), 1):
        line = raw.rstrip("\r")
        if not line.strip():
            continue
        cols = line.split("\t")
        if n == 1 and cols[0] in ("file", "loser"):
            continue  # строка-заголовок
        if len(cols) != columns:
            raise Refuse(f"{what} line {n}: expected {columns} columns, got {len(cols)} (tab/newline in a value?)")
        rows.append(cols)
    return rows


def _lesson_path(root: Path, raw: str) -> tuple[Path, str | None]:
    """Путь урока внутри корня -> (абсолютный путь, роль-источник или None для канона)."""
    p = Path(raw)
    p = (p if p.is_absolute() else root / p).resolve()
    try:
        rel = p.relative_to(root)
    except ValueError:
        raise Refuse(f"path is outside root: {raw}") from None
    if not p.is_file():
        raise Refuse(f"file does not exist: {raw}")
    parts, name = rel.parts, p.name
    if parts[:3] == ("docs", "claude", "memory") and len(parts) == 4:
        if name in _lessons.NON_LESSONS or name.startswith(_lessons.CRAFT_PREFIX) or p.suffix != ".md":
            raise Refuse(f"not a lesson file: {raw}")
        return p, None
    if parts[:2] == (".claude", "agent-memory") and len(parts) == 4:
        if name == "MEMORY.md" or p.suffix != ".md":
            raise Refuse(f"not a lesson file: {raw}")
        return p, parts[2]
    raise Refuse(f"path is not a canon or role lesson: {raw}")


def _ids_from(items) -> set[str]:
    return set(tags._ids(items))


def _split_ids(cell: str) -> list[str]:
    return [v.strip() for v in cell.split(",") if v.strip()]


def build_plan(root: Path, tsv: Path, collisions: Path | None) -> Plan:
    modules = _ids_from((tags._load_yaml(root / "modules.yaml") or {}).get("modules"))
    mechanisms = _ids_from((tags._load_yaml(root / _lessons.MEMORY_REL / "TAGS.yaml") or {}).get("mechanisms"))

    rows: dict[Path, tuple[Row, str | None]] = {}
    for file, mods, mechs, desc in _read_tsv(tsv, 4, "TSV"):
        path, role = _lesson_path(root, file)
        if path in rows:
            raise Refuse(f"file listed twice in TSV: {file}")
        row = Row(path, _split_ids(mods), _split_ids(mechs), desc)
        for kind, vocab, values in (("module", modules, row.modules), ("mechanism", mechanisms, row.mechanisms)):
            for v in values:
                if v not in vocab:
                    raise Refuse(f"unknown {kind} id {v!r} in {file}")
        rows[path] = (row, role)

    pairs: list[tuple[Path, Path, str | None]] = []
    if collisions is not None:
        for loser_raw, winner_raw in _read_tsv(collisions, 2, "collisions"):
            loser, loser_role = _lesson_path(root, loser_raw)
            winner, _ = _lesson_path(root, winner_raw)
            pairs.append((loser, winner, loser_role))

    plan = Plan()
    canon = root / _lessons.MEMORY_REL
    content: dict[Path, bytes] = {}
    final: dict[Path, Path] = {}  # исходный путь -> где лежит после переноса
    taken: set[Path] = set()  # цели, уже занятые планом

    def load(p: Path) -> bytes:
        if p not in content:
            content[p] = p.read_bytes()
        return content[p]

    losers = {loser for loser, _, _ in pairs}
    for loser, winner, loser_role in pairs:
        dest = canon / ARCHIVE / loser.name
        if dest.exists() or dest in taken:
            dest = dest.with_name(f"{loser.stem}-{loser_role or 'canon'}{loser.suffix}")
        if dest.exists() or dest in taken:
            raise Refuse(f"archive name is taken even with the role suffix: {dest.name}")
        taken.add(dest)
        plan.moves.append((loser, dest))
        content[winner] = add_merged_from(load(winner), [loser.stem])
        final.setdefault(winner, winner)
        plan.notes.append(f"COLLISION {loser} -> {dest}; merged_from [{loser.stem}] into {winner}")

    for path, (row, role) in rows.items():
        if path in losers:
            plan.notes.append(f"SKIP {path} (collision loser)")
            continue
        dst = canon / path.name if role else path
        if role:
            if dst.exists() or dst in taken:
                raise Refuse(f"canon already has {dst.name}; cannot move {path}")
            taken.add(dst)
            plan.moves.append((path, dst))
        if any(c in row.description for c in "\t\n\r"):
            raise Refuse(f"description has a tab or newline: {path}")
        content[path] = retag_bytes(
            load(path), description=row.description, modules=row.modules, mechanisms=row.mechanisms, role=role
        )
        final[path] = dst
        plan.notes.append(
            f"{'MOVE+RETAG' if role else 'RETAG'} {path}"
            f"{' -> ' + str(dst) if role else ''} module={_flow(row.modules)} mechanism={_flow(row.mechanisms)}"
            f"{' role=' + role if role else ''}"
        )

    for src, dst in final.items():
        plan.writes[dst] = content[src]

    agent_memory = root / ".claude" / "agent-memory"
    plan.role_dirs = sorted(d for d in agent_memory.glob("*") if d.is_dir()) if agent_memory.is_dir() else []
    return plan


# --------------------------------------------------------------------------- применение


def _git_mv(root: Path, src: Path, dst: Path) -> None:
    cp = subprocess.run(["git", "-C", str(root), "mv", str(src), str(dst)], capture_output=True, check=False)  # nosec B603 B607
    if cp.returncode != 0:
        raise SystemExit(f"git mv {src} {dst} failed: {cp.stderr.decode('utf-8', 'replace').strip()}")


def apply_plan(root: Path, plan: Plan) -> None:
    (root / _lessons.MEMORY_REL / ARCHIVE).mkdir(parents=True, exist_ok=True)
    for src, dst in plan.moves:
        _git_mv(root, src, dst)
    for path, data in plan.writes.items():
        path.write_bytes(data)
    for d in plan.role_dirs:
        (d / "MEMORY.md").write_bytes(("\n".join(ROLE_MEMORY_LINES) + "\n").encode("utf-8"))


def run_check(root: Path) -> int:
    cmd = [sys.executable, str(SCRIPTS_MEMORY / "tags.py"), "--check", "--root", str(root)]
    cp = subprocess.run(cmd, capture_output=True, check=False)  # nosec B603
    out = cp.stdout.decode("utf-8", "replace")
    sys.stdout.write(out)
    print(
        f"tags.py --check exit code: {cp.returncode} ({len([ln for ln in out.splitlines() if ln.strip()])} error lines)"
    )
    return cp.returncode


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Apply the 2.4g.3 memory tagging TSV (one-off).")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--tsv", type=Path, required=True)
    parser.add_argument("--collisions", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    try:
        plan = build_plan(root, args.tsv, args.collisions)
    except Refuse as e:
        sys.stderr.write(f"refused: {e}\n")
        return 2

    for note in plan.notes:
        print(note)
    for d in plan.role_dirs:
        print(f"WRITE {d / 'MEMORY.md'} (3 lines)")
    if args.dry_run:
        print("dry-run: nothing changed")
        return 0

    apply_plan(root, plan)
    run_check(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
