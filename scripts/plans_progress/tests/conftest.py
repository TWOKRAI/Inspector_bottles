# ruff: noqa: E501  -- литералы-фикстуры планов и ожидания в одну строку, форматтер их не переносит
"""Общие хелперы приёмочных тестов plans_progress / plans_ledger (слепой тестер).

Всё доступно через фикстуры, а не через `import conftest`: так набор не зависит
от режима импорта pytest и от соседних conftest.py.

Тесты ходят только через CLI в subprocess (timeout=60 на вызов): ни один тест
не импортирует реализацию, и зависший скрипт не вешает набор.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import pytest

# .../scripts/plans_progress/tests/conftest.py -> корень репозитория / worktree
REPO_ROOT = Path(__file__).resolve().parents[3]
LEDGER = REPO_ROOT / "scripts" / "plans_ledger.py"
PROGRESS = REPO_ROOT / "scripts" / "plans_progress" / "plans_progress.py"
REAL_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "real"

CALL_TIMEOUT = 60


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Запуск CLI; stdout/stderr читаются как utf-8 (консоль Windows — cp866)."""
    return subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        timeout=CALL_TIMEOUT,
        env=_env(),
        cwd=str(cwd) if cwd else None,
        encoding="utf-8",
        errors="replace",
    )


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        timeout=CALL_TIMEOUT,
        env=_env(),
    )


class _TagCollector(HTMLParser):
    """Разбор HTML страницы: порядок планов, ячейки по планам, архив, ссылки."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, dict[str, str | None]]] = []
        self.plans: list[str] = []  # data-plan в порядке документа
        self.plan_cells: dict[str, list[str]] = {}  # data-plan -> [data-status ячеек]
        self.plan_in_archive: dict[str, bool] = {}
        self.plan_progress: dict[str, dict[str, str | None]] = {}  # <progress> внутри <summary>
        self.plan_has_summary_progress: dict[str, bool] = {}
        self.external_refs: list[str] = []
        self.style_text: list[str] = []
        self._in_style = False

    # ---- helpers
    def _current_plan(self) -> str | None:
        for tag, attrs in reversed(self.stack):
            if tag == "details" and "plan" in (attrs.get("class") or "").split():
                return attrs.get("data-plan")
        return None

    def _in_archive(self) -> bool:
        return any(tag == "details" and attrs.get("id") == "archive" for tag, attrs in self.stack)

    def _in_summary(self) -> bool:
        return any(tag == "summary" for tag, _ in self.stack)

    # ---- events
    def handle_starttag(self, tag, attrs):  # noqa: D401
        a = dict(attrs)
        for key in ("src", "href"):
            val = (a.get(key) or "").strip().lower()
            if val.startswith(("http://", "https://", "//")):
                self.external_refs.append(f"{tag}[{key}]={a.get(key)}")
        if tag == "style":
            self._in_style = True
        if tag not in ("br", "meta", "link", "img", "input", "hr"):
            self.stack.append((tag, a))
        if tag == "details" and "plan" in (a.get("class") or "").split():
            name = a.get("data-plan") or ""
            self.plans.append(name)
            self.plan_cells.setdefault(name, [])
            self.plan_in_archive[name] = self._in_archive()
        plan = self._current_plan()
        if plan is not None:
            if tag == "span" and "cell" in (a.get("class") or "").split():
                self.plan_cells[plan].append(a.get("data-status") or "")
            if tag == "progress" and self._in_summary():
                self.plan_has_summary_progress[plan] = True
                self.plan_progress[plan] = a

    def handle_endtag(self, tag):
        if tag == "style":
            self._in_style = False
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self._in_style:
            self.style_text.append(data)


def _norm_key(name: str) -> str:
    """`x.md` и `x` — один и тот же план (в плане не уточнено, с суффиксом или без)."""
    return name[:-3] if name.endswith(".md") else name


@pytest.fixture
def real_root(tmp_path: Path) -> Path:
    """Корень с реальными снимками: layer-render, 2026-09-22_gui-service, queue/ORDER.md."""
    root = tmp_path / "real_root"
    shutil.copytree(REAL_FIXTURES / "plans", root / "plans")
    return root


@pytest.fixture
def make_root(tmp_path: Path):
    """make_root({"plans/x/plan.md": text, ...}, name="r") -> Path корня (файлы utf-8, LF)."""
    counter = {"n": 0}

    def _make(files: dict[str, str], name: str | None = None) -> Path:
        counter["n"] += 1
        root = tmp_path / (name or f"root{counter['n']}")
        (root / "plans").mkdir(parents=True, exist_ok=True)
        for rel, text in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(text.encode("utf-8"))
        return root

    return _make


@pytest.fixture
def make_git_root(make_root):
    """То же, что make_root, плюс `git init` и коммит (для `close`: он делает git mv)."""

    def _make(files: dict[str, str], name: str | None = None) -> Path:
        root = make_root(files, name)
        _git(root, "init", "-q")
        _git(root, "config", "user.email", "t@example.invalid")
        _git(root, "config", "user.name", "tester")
        _git(root, "config", "core.autocrlf", "false")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "init")
        return root

    return _make


@pytest.fixture
def progress():
    """progress(root, *flags) -> CompletedProcess; --root подставляется сам."""

    def _call(root: Path, *flags: str) -> subprocess.CompletedProcess:
        return _run([str(PROGRESS), "--root", str(root), *flags])

    return _call


@pytest.fixture
def plans_json(progress):
    """plans_json(root, *extra) -> {имя_плана_без_.md: запись}; падает, если stdout не JSON-список."""

    def _call(root: Path, *extra: str) -> dict[str, dict]:
        cp = progress(root, "--json", *extra)
        assert cp.returncode == 0, (
            f"--json exit {cp.returncode}\nstdout={cp.stdout[:400]!r}\nstderr={cp.stderr[:400]!r}"
        )
        data = json.loads(cp.stdout)
        assert isinstance(data, list), f"--json должен печатать список, получено {type(data).__name__}"
        return {_norm_key(rec["plan"]): rec for rec in data}

    return _call


@pytest.fixture
def one_plan(plans_json):
    """one_plan(root, name) -> запись плана по имени (в JSON обязан быть)."""

    def _call(root: Path, name: str, *extra: str) -> dict:
        plans = plans_json(root, *extra)
        key = _norm_key(name)
        assert key in plans, f"плана {key!r} нет в --json; есть: {sorted(plans)}"
        return plans[key]

    return _call


def status_key(task: dict) -> str:
    """Статус задачи в канон: нижний регистр, пробел -> `_` (`IN PROGRESS` == `in_progress`)."""
    return str(task["status"]).strip().lower().replace(" ", "_").replace("-", "_")


@pytest.fixture
def statuses():
    """statuses(rec) -> {id: канонический статус}."""

    def _call(rec: dict) -> dict[str, str]:
        return {t["id"]: status_key(t) for t in rec["tasks"]}

    return _call


@pytest.fixture
def parse_html():
    """parse_html(text) -> _TagCollector."""

    def _call(text: str) -> _TagCollector:
        c = _TagCollector()
        c.feed(text)
        c.close()
        return c

    return _call


@pytest.fixture
def norm_key():
    return _norm_key


@pytest.fixture
def ledger():
    """Фасад над CLI plans_ledger.py: status/close; counts() читает `N/M` из текста status."""

    def status(root: Path, *flags: str) -> subprocess.CompletedProcess:
        return _run([str(LEDGER), "status", "--root", str(root), *flags])

    def close(root: Path, plan: str, *flags: str) -> subprocess.CompletedProcess:
        return _run([str(LEDGER), "close", plan, "--root", str(root), *flags])

    def counts(root: Path, plan_prefix: str) -> tuple[int, int]:
        """(done, total) из строки `<plan_prefix>...: N/M, ...` вывода `status`."""
        import re

        cp = status(root)
        assert cp.returncode in (0, 1), f"status exit {cp.returncode}: {cp.stderr[:300]!r}"
        pat = re.compile(r"^" + re.escape(plan_prefix) + r"[^\s:]*:\s+(\d+)/(\d+)", re.MULTILINE)
        m = pat.search(cp.stdout)
        assert m, f"в выводе status нет строки плана {plan_prefix!r}:\n{cp.stdout[:800]}"
        return int(m.group(1)), int(m.group(2))

    return SimpleNamespace(status=status, close=close, counts=counts)


@pytest.fixture
def order_md():
    """order_md(tier41=[..], tier42=[..], tier43=[..]) -> текст ORDER.md с таблицами §4.1–§4.3.

    Строки таблиц повторяют реальный формат: `| [имя](../имя/plan.md) | Полоса | ... |`.
    """

    def row(name: str, lane: str = "С") -> str:
        return f"| [{name}](../{name}/plan.md) | {lane} | статус | следующий шаг |"

    def _build(tier41=(), tier42=(), tier43=(), extra_41_rows=()):
        out = ["# Порядок работ и контроль планов", "", "## 4. Контроль планов", ""]
        out += ["### 4.1 Активные — в работе или следующие", ""]
        out += ["| План | Полоса | Статус | Следующий шаг |", "|---|---|---|---|"]
        out += [row(n) for n in tier41]
        out += list(extra_41_rows)
        out += ["", "### 4.2 Ждут триггера — не трогать до условия", ""]
        out += ["| План | Остаток | Триггер |", "|---|---|---|"]
        out += [f"| [{n}](../{n}/plan.md) | остаток | триггер |" for n in tier42]
        out += ["", "### 4.3 Закрыты или поглощены — кандидаты в `_archive/`", ""]
        out += ["| План | Факт |", "|---|---|"]
        out += [f"| [{n}](../{n}/plan.md) | DONE |" for n in tier43]
        out += [""]
        return "\n".join(out)

    return _build
