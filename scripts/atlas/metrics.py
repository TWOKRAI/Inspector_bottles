"""`atlas metrics`: таблица M1-M4 по брифам плана (Task 1.9f, ADR-ATL-004 §7).

Purpose: по колонкам `<slug>#<id>` посчитать M1 (доля фактов Атласа в блоке FACTS брифа), M2 (blocker+major
    отчёта стадии 0 раунда 1 по классам), M3 (раундов до APPROVED), M4 (коммитов с трейлером задачи после
    DONE-коммита) и напечатать markdown-таблицу. Читает рабочее дерево репозитория, не ревизию; без реестра и SQLite.
    Нарушение формы отчёта или хеш DONE вне репозитория — `?` в ячейке и строка в блоке «нарушения формы».
    U1/U2 не считаются: журнала нет (Task 1.10b).
Public API: run.
Stability: lite
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from scripts.atlas import lint_brief, views
from scripts.atlas.adapters.plans import _DATE_PREFIX
from scripts.atlas.review_form import CLASSES, Review, parse
from scripts.atlas.tree import AtlasError, resolve, run_git

__all__ = ["run"]

_LABELS = (
    "M1 доля фактов Атласа",
    "M2 blocker+major р.1 по классам",
    "M2 из них fact+dryrun+form",
    "M3 раундов до APPROVED",
    "M4 коммитов после DONE",
)
_LAST = "U1/U2: не считаются — журнала нет (Task 1.10b)"
_ATLAS_CMD = "python -m scripts.atlas "
_DONE_GROUP = re.compile(r"\[DONE\b[^\]]*\]")
# хеш в обратных кавычках — любой состав; голый — с цифрой и буквой, границы не буква и не цифра
_HASH = re.compile(r"`(?P<q>[0-9a-f]{7,40})`|(?<![^\W_])(?P<b>[0-9a-f]{7,40})(?![^\W_])")
_TYPE = re.compile(r"^([a-z]+)(\([^)]*\))?!?:")
_CHEAP = ("fact", "dryrun", "form")


@dataclass(frozen=True)
class _Col:
    slug: str
    task: str
    plan: Path  # каталог плана

    @property
    def title(self) -> str:
        return f"{self.slug}#{self.task}"


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8-sig", "replace")  # байты как есть: CRLF разбирает splitlines


def _plan_dir(root: Path, slug: str) -> Path:
    """Единственный `plans/<slug>/` или `plans/<YYYY-MM-DD>_<slug>/` с plan.md."""
    plans = root / "plans"
    found = [d for d in sorted(plans.iterdir()) if d.is_dir() and (d / "plan.md").is_file()] if plans.is_dir() else []
    found = [d for d in found if d.name == slug or _DATE_PREFIX.sub("", d.name) == slug]
    if len(found) != 1:
        raise AtlasError(f"atlas metrics: план {slug!r}: найдено каталогов с plan.md: {len(found)}")
    return found[0]


def _task_line(plan: Path, task: str) -> str | None:
    line = re.compile(rf"^- Task {re.escape(task)}:")
    return next((ln for ln in _read(plan / "plan.md").splitlines() if line.match(ln)), None)


def _reports(col: _Col) -> list[tuple[int, Path]]:
    """Отчёты стадии 0 `reports/<id>.review-r<N>.md` по возрастанию N (имя целиком, review-code не берётся)."""
    name = re.compile(re.escape(col.task) + r"\.review-r(\d+)\.md")
    folder = col.plan / "reports"
    found = [(int(m.group(1)), p) for p in folder.glob("*.md") if p.is_file() and (m := name.fullmatch(p.name))]
    return sorted(found)


def _columns(root: Path, spec: str) -> list[_Col]:
    slug, hashed, task = spec.partition("#")
    if not slug or (hashed and not re.fullmatch(views.TASK_ID_PATTERN, task)):
        raise AtlasError(f"atlas metrics: spec {spec!r}: нужен <slug> или <slug>#<id>")
    plan = _plan_dir(root, slug)
    if not hashed:
        stems = [p.name.removesuffix(".md") for p in (plan / "tasks").glob("*.md")]
        ids = sorted((s for s in stems if re.fullmatch(views.TASK_ID_PATTERN, s)), key=views._natural)
        if not ids:
            raise AtlasError(f"atlas metrics: в плане {slug!r} нет tasks/<id>.md")
        return [_Col(slug, i, plan) for i in ids]
    col = _Col(slug, task, plan)
    if not ((plan / "tasks" / f"{task}.md").is_file() or _reports(col) or _task_line(plan, task)):
        raise AtlasError(f"atlas metrics: {spec}: нет брифа, отчётов и строки `- Task {task}:` в plan.md")
    return [col]


def _m1(col: _Col) -> str:
    path = col.plan / "tasks" / f"{col.task}.md"
    if not path.is_file():
        return "—"
    lines = _read(path).splitlines()
    start = next((i for i, ln in enumerate(lines) if lint_brief._OPEN.match(ln)), None)
    end = (
        next((i for i in range(start + 1, len(lines)) if lines[i] == lint_brief._CLOSE), None)
        if start is not None
        else None
    )
    if start is None or end is None:
        return "—"
    block = [ln for ln in lines[start + 1 : end] if ln.lstrip().startswith("- ")]
    facts = [lint_brief._FACT.match(ln) for ln in block]
    atlas = sum(1 for m in facts if m and m.group("cmd").startswith(_ATLAS_CMD))
    if not block:
        return "—"
    return f"{(200 * atlas + len(block)) // (2 * len(block))}% ({atlas}/{len(block)})"


def _m2(review: Review) -> tuple[str, str]:
    parts = []
    for severity in ("blocker", "major"):
        counts = Counter(klass for sev, klass in review.findings if sev == severity)
        if counts:
            parts.append(f"{severity} " + ", ".join(f"{c} {counts[c]}" for c in CLASSES if counts[c]))
    cheap = sum(1 for sev, klass in review.findings if sev in ("blocker", "major") and klass in _CHEAP)
    return "; ".join(parts) or "0", str(cheap)


class _Reader:
    """Чтение рабочего дерева с общим кэшем: один отчёт разбирается раз, нарушение печатается раз."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.violations: dict[tuple[str, str], None] = {}  # (путь, текст) в порядке первого появления
        self._reports: dict[Path, Review | None] = {}
        self._commits: dict[str, dict[str, list[str]]] = {}
        self._head: str | None = None

    def violate(self, path: Path, text: str) -> None:
        self.violations[(path.relative_to(self.root).as_posix(), text)] = None

    def report(self, path: Path) -> Review | None:
        if path not in self._reports:
            review, errors = parse(_read(path))
            for text in errors:
                self.violate(path, text)
            self._reports[path] = review
        return self._reports[path]

    def m2(self, col: _Col) -> tuple[str, str]:
        first = next((p for n, p in _reports(col) if n == 1), None)
        if first is None:
            return "—", "—"
        review = self.report(first)
        return ("?", "?") if review is None else _m2(review)

    def m3(self, col: _Col) -> str:
        rounds = [(n, self.report(p)) for n, p in _reports(col)]
        if not rounds:
            return "—"
        if any(review is None for _, review in rounds):
            return "?"
        approved = [n for n, review in rounds if review and review.verdict == "APPROVED"]
        return str(approved[0]) if approved else f"нет (раундов {len(rounds)})"

    def m4(self, col: _Col) -> str | tuple[str, set[str]]:
        """Строка-итог или (полный хеш DONE, коммиты задачи после него) — формат ячейки после чтения тем."""
        line = _task_line(col.plan, col.task)
        group = _DONE_GROUP.search(line) if line else None
        if not group:
            return "—"
        token = next(
            (
                m.group("q") or m.group("b")
                for m in _HASH.finditer(group.group(0))
                if m.group("q") or (re.search(r"\d", m.group("b")) and re.search("[a-f]", m.group("b")))
            ),
            None,
        )
        if token is None:
            return "— (DONE без хеша)"
        proc = run_git(self.root, "rev-parse", "--verify", "-q", f"{token}^{{commit}}")
        if proc.returncode != 0:
            self.violate(col.plan / "plan.md", f"задача {col.task}: хеш DONE {token} не найден")
            return "?"
        done = proc.stdout.decode().strip()
        if self._head is None:
            self._head = resolve(self.root, "HEAD")
        if col.slug not in self._commits:
            self._commits[col.slug] = views._plan_commits(self.root, self._head, col.slug)[0]
        mine = {sha for sha, ids in self._commits[col.slug].items() if col.task in ids}
        listed = run_git(self.root, "rev-list", "--no-merges", f"{done}..HEAD")
        if listed.returncode != 0:
            raise AtlasError(f"atlas metrics: git rev-list {done}..HEAD: {listed.stderr.decode('utf-8', 'replace')}")
        return done, mine & set(listed.stdout.decode().split())

    def subjects(self, shas: set[str]) -> dict[str, str]:
        """Темы коммитов одним `git log --no-walk`."""
        if not shas:
            return {}
        proc = run_git(
            self.root,
            "log",
            "--no-walk=unsorted",
            "--stdin",
            "--format=%H%x00%s",
            input="\n".join(sorted(shas)).encode(),
        )
        if proc.returncode != 0:
            raise AtlasError(f"atlas metrics: git log: {proc.stderr.decode('utf-8', 'replace').strip()}")
        pairs = (ln.split("\0", 1) for ln in proc.stdout.decode("utf-8", "replace").splitlines() if "\0" in ln)
        return {sha: subject for sha, subject in pairs}


def _table(titles: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| метрика | " + " | ".join(titles) + " |", "|" + "---|" * (len(titles) + 1)]
    return lines + ["| " + " | ".join([label, *cells]) + " |" for label, cells in zip(_LABELS, rows)]


def run(root: Path, specs: list[str], base: list[str]) -> tuple[int, list[str]]:
    """Таблица M1-M4 по колонкам `base` (метка «база») и `specs` («сейчас», если база есть) -> (код, строки)."""
    cols = [(c, "база ") for spec in base for c in _columns(root, spec)]
    cols += [(c, "сейчас " if base else "") for spec in specs for c in _columns(root, spec)]
    reader = _Reader(root)
    cells: list[list[str | tuple[str, set[str]]]] = []
    for col, _ in cols:
        m2, cheap = reader.m2(col)
        cells.append([_m1(col), m2, cheap, reader.m3(col), reader.m4(col)])
    subjects = reader.subjects({sha for column in cells if isinstance(column[4], tuple) for sha in column[4][1]})
    for column in cells:
        if isinstance(column[4], tuple):
            done, shas = column[4]
            not_docs = sum(
                1 for sha in shas if (m := _TYPE.match(subjects.get(sha, ""))) is None or m.group(1) != "docs"
            )
            column[4] = f"{len(shas)} (не docs {not_docs}) после {done[:7]}"
    titles = [prefix + col.title for col, prefix in cols]
    lines = _table(titles, [[str(column[i]) for column in cells] for i in range(len(_LABELS))])
    if reader.violations:
        lines += ["", f"нарушения формы ({len(reader.violations)}):"]
        lines += [f"  {path}: {text}" for path, text in reader.violations]
    lines.append(_LAST)
    return (1 if any("?" in column for column in cells) else 0), lines
