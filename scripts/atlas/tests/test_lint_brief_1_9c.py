"""Приёмка Task 1.9c: `python -m scripts.atlas lint-brief <файл>` и хук `lint-brief.sh` (RED до кода).

Purpose: слепые тесты по брифу `plans/2026-10-04_atlas/tasks/1.9c.tester.md`. Контракт — ADR-ATL-004 §2-3
    (`scripts/atlas/DECISIONS.md`) и шаблон `.claude/plugins/dev/templates/task-brief.md`; реализация не читалась.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Вызов — `atlas(repo, "lint-brief", <файл>, ...)` из `conftest.py` (cwd = временный репозиторий) или `python -m`
из корня. Вывод читается так: строка находки `<путь>[:<N>]: error|warning <КОД> <текст>`, затем строки
`  не сверено (вне allow-list): <команда>`, последняя строка — итог `lint-brief: ошибок E, предупреждений W, сверено V,
вне allow-list O`. Каждый сценарий сначала требует итоговую строку: «подкоманды нет» не даёт ложного зелёного ни
в тесте, который проверяет отсутствие находки.

Ожидаемые значения — литералы. Номер строки находки (`<N>`) не проверяется нигде: в брифе он не описан.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, RepoFactory, run_with_deadline

__all__: list[str] = []

_ROOT = Path(__file__).resolve().parents[3]
_HOOK = _ROOT / ".claude" / "plugins" / "dev" / "hooks" / "lint-brief.sh"
_FIXTURES = Path("scripts") / "atlas" / "tests" / "briefs_1_9c"
_PIN = "24a229e66"

_SUMMARY_RE = re.compile(r"^lint-brief: ошибок (\d+), предупреждений (\d+), сверено (\d+), вне allow-list (\d+)$")
_FINDING_RE = re.compile(
    r"^(?P<path>.+?)(?::(?P<n>\d+))?: (?P<sev>error|warning) (?P<code>[A-Z][A-Z_0-9]+) (?P<text>.*)$"
)
_OFF_PREFIX = "  не сверено (вне allow-list): "

_REL = "plans/p/tasks/1.2.md"
_REL_ROLE = "plans/p/tasks/1.2.tester.md"
_REL_INJ = "plans/p/tasks/1.2.injections.json"
_FORM = ("--no-replay", "--no-fresh")

_MAIN_LABELS = ("TASK", "ROLE", "CHAIN", "FACTS", "DESIGN", "FILES", "REDS", "ACCEPTANCE", "TESTS", "OUT OF SCOPE")
_ROLE_LABELS = ("TASK", "ROLE", "CHAIN", "DESIGN", "FILES", "REDS", "TESTS", "OUT OF SCOPE")

# --- разбор вывода -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Res:
    code: Any
    out: str
    err: str


@dataclass(frozen=True)
class _Finding:
    path: str
    n: int | None
    sev: str
    code: str
    text: str


@dataclass(frozen=True)
class _Run:
    code: Any
    out: str
    err: str
    findings: list[_Finding]
    counts: tuple[int, int, int, int]
    off_list: list[str]
    last: str

    def of(self, code: str) -> list[_Finding]:
        return [f for f in self.findings if f.code == code]

    def codes(self) -> list[str]:
        return [f.code for f in self.findings]

    def errors(self) -> list[_Finding]:
        return [f for f in self.findings if f.sev == "error"]

    def where(self) -> str:
        return f"код={self.code}, stdout={self.out!r}, stderr={self.err!r}"


def _parse(res: Any) -> _Run:
    lines = res.out.splitlines()
    nonempty = [ln for ln in lines if ln.strip()]
    assert nonempty, f"stdout пуст: код={res.code}, stderr={res.err!r}"
    summary = _SUMMARY_RE.match(nonempty[-1])
    assert summary, f"последняя строка — не итог lint-brief: {nonempty[-1]!r} (код={res.code}, stderr={res.err!r})"
    findings: list[_Finding] = []
    for ln in lines:
        m = _FINDING_RE.match(ln)
        if m:
            n = m.group("n")
            findings.append(
                _Finding(m.group("path"), int(n) if n else None, m.group("sev"), m.group("code"), m.group("text"))
            )
    off = [ln[len(_OFF_PREFIX) :] for ln in lines if ln.startswith(_OFF_PREFIX)]
    counts = tuple(int(g) for g in summary.groups())
    run = _Run(res.code, res.out, res.err, findings, counts, off, nonempty[-1])  # type: ignore[arg-type]
    n_err = len(run.errors())
    n_warn = len(findings) - n_err
    assert (n_err, n_warn, len(off)) == (counts[0], counts[1], counts[3]), (
        f"итог {nonempty[-1]!r} не сходится: error {n_err}, warning {n_warn}, не сверено {len(off)}\n{res.out}"
    )
    return run


# --- сборка брифа ------------------------------------------------------------------------------------------------

_FACT_EXIT = "- репозиторий жив — `git rev-parse --verify HEAD` → exit 0"
_FACT_LIT = "- файл на месте — `git ls-files README.md` → `README.md`"


def _fact(what: str, cmd: str, lit: str | None = None, exit_code: int | None = None) -> str:
    tail = f"`{lit}`" if lit is not None else f"exit {exit_code}"
    return f"- {what} — `{cmd}` → {tail}"


class _Brief:
    """Бриф по секциям: метка -> строки (первая — строка метки)."""

    def __init__(self, kind: str = "main", sha: str = "abcdef0") -> None:
        self.kind = kind
        self.tail: list[str] = []
        s: dict[str, list[str]] = {
            "TASK": ["TASK: 1.2 — проба формы   PLAN: plans/p/plan.md"],
            "ROLE": ["ROLE: developer" if kind == "main" else "ROLE: tester"],
            "CHAIN": ["CHAIN: tester -> developer -> lead"],
        }
        if kind == "main":
            self.head = ["# Task 1.2 — проба формы", "", "Основание: проба.", ""]
            s["FACTS"] = [
                "FACTS (generated by python -m scripts.atlas brief p#1.2; edit DESIGN, not this block):",
                f"<!-- atlas:facts {sha} -->",
                _FACT_EXIT,
                _FACT_LIT,
                "<!-- /atlas:facts -->",
            ]
        else:
            self.head = ["# 1.2 — бриф tester", ""]
        s["DESIGN"] = [
            "DESIGN (decided by the lead — you type it, you do not derive it):",
            "  1. первое",
            "  2. второе",
            "  3. третье",
        ]
        s["FILES"] = [
            "FILES (complete list — nothing else; need another file -> stop and ask the lead):",
            "  1. src/a.py — правка",
        ]
        s["REDS"] = ["REDS (predicted red tests):", "  n/a — тесты пишет tester"]
        if kind == "main":
            s["ACCEPTANCE"] = ["ACCEPTANCE (every number with its command):", "  " + _FACT_EXIT]
        s["TESTS"] = ["TESTS: python -m pytest tests -q"]
        s["OUT OF SCOPE"] = ["OUT OF SCOPE: всё остальное"]
        self.sections = s

    def lines(self) -> list[str]:
        out = list(self.head)
        for sec in self.sections.values():
            out += sec
            out.append("")
        return out + self.tail

    def text(self, eol: str = "\n") -> str:
        return eol.join(self.lines()) + eol

    def drop(self, label: str) -> _Brief:
        del self.sections[label]
        return self

    def body(self, label: str, *lines: str) -> _Brief:
        self.sections[label].extend(lines)
        return self

    def set_body(self, label: str, *lines: str) -> _Brief:
        self.sections[label] = [self.sections[label][0], *lines]
        return self

    def set_facts(self, *facts: str, sha: str = "abcdef0") -> _Brief:
        self.sections["FACTS"] = [
            self.sections["FACTS"][0],
            f"<!-- atlas:facts {sha} -->",
            *facts,
            "<!-- /atlas:facts -->",
        ]
        return self

    def add_fact_line(self, line: str) -> _Brief:
        self.sections["FACTS"].insert(-1, line)
        return self


def _put(repo: GitRepo, rel: str, text: str | bytes) -> None:
    """Запись байт в байт (GitRepo.write на Windows переводит LF в CRLF)."""
    target = repo.path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))


def _init(repo: GitRepo) -> str:
    _put(repo, "README.md", "readme\n")
    return repo.commit("init")


def _lint(atlas: Any, repo: GitRepo, rel: str, *flags: str, cwd: Path | None = None) -> _Run:
    return _parse(atlas(repo, "lint-brief", rel, *flags, cwd=cwd))


def _form(atlas: Any, repo: GitRepo, brief: _Brief, rel: str = _REL, flags: tuple[str, ...] = _FORM) -> _Run:
    _put(repo, rel, brief.text())
    return _lint(atlas, repo, rel, *flags)


@pytest.fixture
def slow_atlas(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    """Как `atlas`, но дедлайн свой (повтор команд дольше 60 с фикстуры) и без PYTHONPATH у процесса."""
    monkeypatch.delenv("PYTHONPATH", raising=False)

    def run(target: GitRepo, *argv: str, seconds: float = 150.0) -> _Res:
        monkeypatch.chdir(target.path)
        capsys.readouterr()

        def call() -> Any:
            from scripts.atlas.__main__ import main

            try:
                return main(list(argv))
            except SystemExit as exc:
                return exc.code if isinstance(exc.code, int) else 1

        code = run_with_deadline(call, seconds)
        captured = capsys.readouterr()
        return _Res(code, captured.out, captured.err)

    return run


def _cli(argv: list[str], cwd: Path, *, timeout: float, extra_env: dict[str, str] | None = None) -> _Res:
    env = {**os.environ, "PYTHONPATH": str(_ROOT), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", **(extra_env or {})}

    def call() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "scripts.atlas", *argv],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )

    proc = run_with_deadline(call, timeout + 30)
    return _Res(proc.returncode, proc.stdout, proc.stderr)


# --- РЕДЫ 1-2: приёмка на данных лида -----------------------------------------------------------------------------


def _require_pin() -> None:
    probe = subprocess.run(
        ["git", "cat-file", "-e", f"{_PIN}^{{commit}}"], cwd=_ROOT, capture_output=True, text=True, check=False
    )
    if probe.returncode != 0:
        pytest.skip(f"в репозитории нет коммита-пина {_PIN}: приёмка на брифе K0 1.2 невозможна")


def test_pin_names_the_wrong_numbers() -> None:
    _require_pin()
    res = _cli(["lint-brief", (_FIXTURES / "pin" / "1.2.md").as_posix(), "--no-fresh"], _ROOT, timeout=180)
    run = _parse(res)

    assert run.code == 1, run.where()
    assert run.last == "lint-brief: ошибок 4, предупреждений 0, сверено 7, вне allow-list 0", run.last
    assert "FACT_MISMATCH литерал не найден в выводе: tools/watcher.py:81:" in res.out, res.out
    assert "FACT_MISMATCH литерал не найден в выводе: os.fsync" in res.out, res.out
    assert "FACT_MISMATCH литерал не найден в выводе: 37 строк" in res.out, res.out
    assert "LITERAL_TIMING" in res.out, res.out
    assert len(run.of("FACT_MISMATCH")) == 3, run.codes()
    assert len(run.of("LITERAL_TIMING")) == 1, run.codes()
    assert [f.sev for f in run.findings] == ["error"] * 4, run.codes()


def test_fixed_brief_exits_zero() -> None:
    _require_pin()
    res = _cli(["lint-brief", (_FIXTURES / "fixed" / "1.2.md").as_posix(), "--no-fresh"], _ROOT, timeout=180)
    run = _parse(res)

    assert run.code == 0, run.where()
    assert run.last == "lint-brief: ошибок 0, предупреждений 0, сверено 8, вне allow-list 0", run.last
    assert run.findings == [], run.out


# --- РЕД 3: форма -------------------------------------------------------------------------------------------------


def test_form_labels_and_body_rules(repo: GitRepo, atlas: Any) -> None:
    _init(repo)

    clean = _form(atlas, repo, _Brief())
    assert clean.code == 0, clean.where()
    assert clean.findings == [], clean.out
    assert clean.counts[:2] == (0, 0), clean.last

    role_clean = _form(atlas, repo, _Brief("role"), _REL_ROLE)
    assert role_clean.code == 0, role_clean.where()
    assert role_clean.findings == [], role_clean.out  # у роли без FACTS и ACCEPTANCE ошибки нет

    # H1
    b = _Brief()
    b.head[0] = "# Задача 1.2 — без слова Task"
    run = _form(atlas, repo, b)
    assert run.code == 1, run.where()
    assert [f.sev for f in run.of("H1")] == ["error"], run.out
    b = _Brief("role")
    b.head[0] = "# Task 1.2 — роль под главным заголовком"
    run = _form(atlas, repo, b, _REL_ROLE)
    assert run.code == 1, run.where()
    assert [f.sev for f in run.of("H1")] == ["error"], run.out

    # LABEL_MISSING: каждая обязательная метка названа в находке
    wrong: list[str] = []
    for label in _MAIN_LABELS:
        run = _form(atlas, repo, _Brief().drop(label))
        hits = [f for f in run.of("LABEL_MISSING") if label in f.text]
        if run.code != 1 or len(hits) != 1 or hits[0].sev != "error":
            wrong.append(f"main/{label}: {run.where()}")
    for label in _ROLE_LABELS:
        run = _form(atlas, repo, _Brief("role").drop(label), _REL_ROLE)
        hits = [f for f in run.of("LABEL_MISSING") if label in f.text]
        if run.code != 1 or len(hits) != 1 or hits[0].sev != "error":
            wrong.append(f"role/{label}: {run.where()}")
    assert wrong == [], "LABEL_MISSING не назван или код не 1:\n" + "\n".join(wrong)

    # LABEL_UNKNOWN: warning, код 0; известные добавки — без находки
    run = _form(atlas, repo, _Brief().body("OUT OF SCOPE", "NOTES: заметка вне набора"))
    assert [f.sev for f in run.of("LABEL_UNKNOWN")] == ["warning"], run.out
    assert run.code == 0, run.where()
    assert run.counts[:2] == (0, 1), run.last

    known = _Brief()
    known.tail = [
        "TRAPS: ловушка",
        "HANDOFF IN: none",
        "FORBIDDEN PATHS (no edits): src/x.py",
        "GUARDS: охрана",
        "COMMIT: do not commit",
        "REPORT: STATUS first",
        "BRIEF-OVERRIDE: причина",
    ]
    run = _form(atlas, repo, known)
    assert run.of("LABEL_UNKNOWN") == [], run.out
    assert run.code == 0, run.where()
    assert run.counts[:2] == (0, 0), run.last

    # LABEL_DUPLICATE: warning, код 0
    dup = _Brief()
    dup.tail = ["TESTS: вторая строка той же метки"]
    run = _form(atlas, repo, dup)
    assert [f.sev for f in run.of("LABEL_DUPLICATE")] == ["warning"], run.out
    assert run.code == 0, run.where()

    # метки внутри fenced-блока не считаются
    fenced = _Brief().body("OUT OF SCOPE", "```", "NOTES: a", "NOTES: b", "TESTS: z", "```")
    run = _form(atlas, repo, fenced)
    assert run.of("LABEL_UNKNOWN") == [], run.out
    assert run.of("LABEL_DUPLICATE") == [], run.out
    assert run.code == 0, run.where()

    # BODY_LABEL: строка тела, открывающая чужую метку; ровно одна находка на строку
    wrong = []
    cases = [
        ("DESIGN", "ВАЖНО: z"),
        ("DESIGN", "  - API: x"),
        ("DESIGN", "- **Итог:** x"),
        ("FILES", "ВАЖНО: z"),
        ("REDS", "ВАЖНО: z"),
        ("ACCEPTANCE", "ВАЖНО: z"),
    ]
    for label, line in cases:
        run = _form(atlas, repo, _Brief().body(label, line))
        hits = run.of("BODY_LABEL")
        if run.code != 1 or len(hits) != 1 or hits[0].sev != "error":
            wrong.append(f"{label} <- {line!r}: {run.where()}")
    assert wrong == [], "BODY_LABEL: нет ровно одной ошибки:\n" + "\n".join(wrong)

    # DESIGN_SHORT: считаются непустые строки тела
    run = _form(atlas, repo, _Brief().set_body("DESIGN", "  1. a", "  2. b"))
    assert [f.sev for f in run.of("DESIGN_SHORT")] == ["error"], run.out
    assert run.code == 1, run.where()
    run = _form(atlas, repo, _Brief().set_body("DESIGN", "  1. a", "", "  2. b", ""))
    assert [f.sev for f in run.of("DESIGN_SHORT")] == ["error"], run.out
    run = _form(atlas, repo, _Brief().set_body("DESIGN", "  1. a", "", "  2. b", "  3. c"))
    assert run.of("DESIGN_SHORT") == [], run.out
    assert run.code == 0, run.where()

    # FILES_TOO_MANY: 7 — ошибка, 6 — нет
    run = _form(atlas, repo, _Brief().set_body("FILES", *[f"  {i}. src/f{i}.py — x" for i in range(1, 8)]))
    assert [f.sev for f in run.of("FILES_TOO_MANY")] == ["error"], run.out
    assert run.code == 1, run.where()
    run = _form(atlas, repo, _Brief().set_body("FILES", *[f"  {i}. src/f{i}.py — x" for i in range(1, 7)]))
    assert run.of("FILES_TOO_MANY") == [], run.out
    assert run.code == 0, run.where()

    # REDS_TOO_MANY: 11 — ошибка; 10 — нет; `n/a` первой непустой строкой — нет
    def reds_brief(n: int, na_first: bool = False) -> _Brief:
        items = [f"  - tests/test_a.py::test_{i}" for i in range(1, n + 1)]
        lines = (["  n/a — тестов нет"] if na_first else []) + items
        return _Brief().set_body("FILES", "  1. tests/test_a.py — x").set_body("REDS", *lines)

    run = _form(atlas, repo, reds_brief(11))
    assert [f.sev for f in run.of("REDS_TOO_MANY")] == ["error"], run.out
    assert run.code == 1, run.where()
    run = _form(atlas, repo, reds_brief(10))
    assert run.of("REDS_TOO_MANY") == [], run.out
    assert run.code == 0, run.where()
    run = _form(atlas, repo, reds_brief(11, na_first=True))
    assert run.of("REDS_TOO_MANY") == [], run.out
    assert run.code == 0, run.where()


# --- РЕД 4: грамматика FACTS / ACCEPTANCE, маркеры, время ---------------------------------------------------------


def test_facts_grammar_marker_timing(repo: GitRepo, atlas: Any) -> None:
    _init(repo)

    # чистый бриф и пустая строка между фактами; CRLF разбирается как LF
    spaced = _Brief().add_fact_line("")
    run = _form(atlas, repo, spaced)
    assert run.code == 0, run.where()
    assert run.findings == [], run.out
    for eol, name in (("\n", "LF"), ("\r\n", "CRLF")):
        _put(repo, _REL, _Brief().text(eol))
        run = _lint(atlas, repo, _REL, *_FORM)
        assert run.code == 0, f"{name}: {run.where()}"
        assert run.last.startswith("lint-brief: ошибок 0, "), f"{name}: {run.last}"

    # FACTS_MARKER: нет открывающего, нет закрывающего; без метки FACTS маркеров не требуют
    no_open = _Brief()
    del no_open.sections["FACTS"][1]
    run = _form(atlas, repo, no_open)
    assert [f.sev for f in run.of("FACTS_MARKER")] == ["error"], run.out
    assert run.code == 1, run.where()
    no_close = _Brief()
    del no_close.sections["FACTS"][-1]
    run = _form(atlas, repo, no_close)
    assert [f.sev for f in run.of("FACTS_MARKER")] == ["error"], run.out
    assert run.code == 1, run.where()
    run = _form(atlas, repo, _Brief().drop("FACTS"))
    assert run.of("FACTS_MARKER") == [], run.out
    assert len(run.of("LABEL_MISSING")) == 1, run.out

    # FACT_FORM: ровно одна находка на каждую строку не по грамматике §2.5
    bad_facts = {
        "дефис вместо тире": "- x - `git rev-parse HEAD` → exit 0",
        "стрелка ->": "- x — `git rev-parse HEAD` -> exit 0",
        "нет команды": "- x — → exit 0",
        "нет литерала": "- x — `git rev-parse HEAD` →",
        "обратная кавычка в литерале": "- x — `git rev-parse HEAD` → `a`b`",
        "пункт N.": "1. x — `git rev-parse HEAD` → exit 0",
        "проза между маркерами": "просто текст между маркерами",
    }
    bad_acceptance = {
        "ACCEPTANCE: пункт N.": "  1. x — `git rev-parse HEAD` → exit 0",
        "ACCEPTANCE: дефис вместо тире": "  - x - `git rev-parse HEAD` → exit 0",
    }
    wrong: list[str] = []
    for name, line in bad_facts.items():
        run = _form(atlas, repo, _Brief().add_fact_line(line))
        hits = run.of("FACT_FORM")
        if run.code != 1 or len(hits) != 1 or hits[0].sev != "error":
            wrong.append(f"FACTS/{name}: {run.where()}")
    for name, line in bad_acceptance.items():
        run = _form(atlas, repo, _Brief().body("ACCEPTANCE", line))
        hits = run.of("FACT_FORM")
        if run.code != 1 or len(hits) != 1 or hits[0].sev != "error":
            wrong.append(f"{name}: {run.where()}")
    assert wrong == [], "FACT_FORM: нет ровно одной ошибки:\n" + "\n".join(wrong)

    # LITERAL_TIMING: литерал со временем — ошибка (и FACTS, и ACCEPTANCE); `2steps`, `tests 2` — не время
    wrong = []
    for lit in ("8,2 с", "8 с", "0.25 с", "in 1.5s", "120 ms"):
        run = _form(atlas, repo, _Brief().add_fact_line(_fact("замер", "git rev-parse HEAD", lit=lit)))
        hits = run.of("LITERAL_TIMING")
        if run.code != 1 or len(hits) != 1 or hits[0].sev != "error":
            wrong.append(f"FACTS/{lit!r}: {run.where()}")
    run = _form(atlas, repo, _Brief().body("ACCEPTANCE", "  " + _fact("замер", "git rev-parse HEAD", lit="8,2 с")))
    if run.code != 1 or len(run.of("LITERAL_TIMING")) != 1:
        wrong.append(f"ACCEPTANCE/'8,2 с': {run.where()}")
    assert wrong == [], "LITERAL_TIMING: нет ровно одной ошибки:\n" + "\n".join(wrong)
    for lit in ("2steps", "tests 2"):
        run = _form(atlas, repo, _Brief().add_fact_line(_fact("счёт", "git rev-parse HEAD", lit=lit)))
        assert run.of("LITERAL_TIMING") == [], f"{lit!r}: {run.out}"
        assert run.code == 0, f"{lit!r}: {run.where()}"


# --- РЕД 5: повтор команд, allow-list, без shell ------------------------------------------------------------------


def _replay_repo(repo: GitRepo) -> tuple[str, str]:
    _put(repo, "src/a.py", "alpha = 1\nbeta = 2\n")
    _put(repo, "README.md", "readme\n")
    first = repo.commit("first commit")
    _put(repo, "src/a.py", "alpha = 1\nbeta = 3\n")
    _put(repo, "data/w.txt", b"x\r\ny\r\nz")  # два перевода строки в файле, три строки текста
    _put(repo, "tests/test_ok.py", "def test_ok():\n    open('ran_marker', 'w').close()\n")
    _put(repo, "keep_rm", "keep\n")
    second = repo.commit("second commit")
    return first, second


def test_replay_allow_list_and_no_shell(repo: GitRepo, slow_atlas: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    c1, c2 = _replay_repo(repo)
    bad_literal = "no-such-subject"
    facts_ok = [
        _fact("тема", "git log -1 --format=%s", lit="second commit"),
        _fact("grep", "git grep -n alpha -- src/a.py", lit="src/a.py:1:alpha = 1"),
        _fact("diff", f"git diff {c1} {c2}", lit="+beta = 3"),
        _fact("cat-file", f"git cat-file -p {c2}:src/a.py", lit="beta = 3"),
        _fact("ветка", "git rev-parse --abbrev-ref HEAD", lit="main"),
        _fact("ls-files", "git ls-files src", lit="src/a.py"),
        _fact("ls-tree", f"git ls-tree -r --name-only {c2}", lit="src/a.py"),
        _fact("show", f"git show --stat --format=%s {c2}", lit="second commit"),
        _fact("stderr", "git rev-parse --verify no-such-ref", lit="Needed a single revision"),
        _fact("код", "git rev-parse --verify no-such-ref", exit_code=128),
        _fact("wc", "wc -l data/w.txt", lit="2 data/w.txt"),
        _fact("atlas", "python -m scripts.atlas log no_such_module", exit_code=2),
        _fact("сбор", "python -m pytest --collect-only -q -p no:cacheprovider tests/test_ok.py", lit="::test_ok"),
    ]
    facts_bad = [
        _fact("тема, чужой литерал", "git log -1 --format=%s", lit=bad_literal),
        _fact("код не тот", "git rev-parse --verify no-such-ref", exit_code=0),
        _fact("wc не тот", "wc -l data/w.txt", lit="3 data/w.txt"),
        _fact("atlas не тот код", "python -m scripts.atlas log no_such_module", exit_code=1),
    ]
    off_cmds = [
        "rm keep_rm",
        "touch made_by_touch",
        "python -c \"open('made_by_c', 'w').close()\"",
        "python -m pytest tests/test_ok.py -q",
        "git -c core.pager=x log -1 --format=%s",
        "git log --output=made_by_output -1",
        "python -m pytest --collect-only -q --junitxml=made_by_junit tests/test_ok.py",
        "python -m scripts.atlas lint-brief plans/p/tasks/1.2.md",
    ]
    off_facts = [
        _fact("rm", off_cmds[0], exit_code=0),
        _fact("touch", off_cmds[1], exit_code=0),
        _fact("python -c", off_cmds[2], exit_code=0),
        _fact("pytest без collect-only", off_cmds[3], exit_code=0),
        _fact("git -c", off_cmds[4], lit="WRONG_IF_RUN"),
        _fact("git log --output", off_cmds[5], exit_code=0),
        _fact("junitxml", off_cmds[6], lit="WRONG_IF_RUN"),
        _fact("lint-brief", off_cmds[7], lit="WRONG_IF_RUN"),
    ]
    brief = (
        _Brief().set_facts(*facts_ok, *facts_bad, sha=c2[:7]).set_body("ACCEPTANCE", *["  " + ln for ln in off_facts])
    )
    _put(repo, _REL, brief.text())

    res = slow_atlas(repo, "lint-brief", _REL, "--no-fresh")
    run = _parse(res)

    assert run.code == 1, run.where()
    assert run.last == f"lint-brief: ошибок 4, предупреждений 0, сверено 17, вне allow-list {len(off_cmds)}", run.last
    mismatches = run.of("FACT_MISMATCH")
    assert len(mismatches) == 4, run.out
    assert all(f.sev == "error" for f in mismatches), run.out
    texts = [f.text for f in mismatches]
    assert any(t.endswith(f"литерал не найден в выводе: {bad_literal}") for t in texts), texts
    assert any(t.endswith("литерал не найден в выводе: 3 data/w.txt") for t in texts), texts
    # вердикт на каждую из двух строк с одной командой: верная строка не названа
    assert not any(t.endswith("литерал не найден в выводе: second commit") for t in texts), texts
    assert sorted(run.codes()) == ["FACT_MISMATCH"] * 4, run.codes()

    # вне allow-list: напечатано, ошибки нет, ничего не запущено
    assert sorted(run.off_list) == sorted(off_cmds), run.off_list
    for cmd in off_cmds:
        assert f"{_OFF_PREFIX}{cmd}" in res.out.splitlines(), cmd
    for made in ("made_by_touch", "made_by_c", "made_by_output", "made_by_junit", "ran_marker"):
        assert not (repo.path / made).exists(), f"команда вне allow-list запущена: создан {made}"
    assert (repo.path / "keep_rm").exists(), "`rm keep_rm` выполнен"

    # --no-replay: тот же бриф с заведомо неверными литералами — без ошибки
    res = slow_atlas(repo, "lint-brief", _REL, "--no-replay", "--no-fresh")
    skipped = _parse(res)
    assert skipped.of("FACT_MISMATCH") == [], skipped.out
    assert skipped.code == 0, skipped.where()

    # токен-метасимвол при разрешённом начале — не через shell
    shell_facts = [
        _fact("redirect", "git rev-parse HEAD > made_by_redirect", exit_code=0),
        _fact("and", "git rev-parse HEAD && touch made_by_and", exit_code=0),
        _fact("semi", "git rev-parse HEAD; touch made_by_semi", exit_code=0),
        _fact("pipe", "git rev-parse HEAD | touch made_by_pipe", exit_code=0),
    ]
    _put(repo, _REL, _Brief().set_facts(*shell_facts, sha=c2[:7]).text())
    shell_run = _parse(slow_atlas(repo, "lint-brief", _REL, "--no-fresh"))
    assert shell_run.code in (0, 1), shell_run.where()
    for made in ("made_by_redirect", "made_by_and", "made_by_semi", "made_by_pipe"):
        assert not (repo.path / made).exists(), f"строка прогнана через shell: создан {made}"

    # stdin подпроцесса открыт: команда не получает его и не зависает
    _assert_open_stdin_does_not_hang(repo, c2)

    # таймаут: зависший модуль при сборе — FACT_TIMEOUT, вызов возвращается быстро
    _put(repo, "tests/test_slow.py", "import time\n\ntime.sleep(30)\n\n\ndef test_s():\n    pass\n")
    slow_fact = _fact("медленный сбор", "python -m pytest --collect-only -q tests/test_slow.py", exit_code=0)
    _put(repo, _REL, _Brief().set_facts(slow_fact, sha=c2[:7]).text())
    monkeypatch.setenv("ATLAS_REPLAY_TIMEOUT", "2")
    started = time.monotonic()
    timeout_res = slow_atlas(repo, "lint-brief", _REL, "--no-fresh", seconds=20.0)
    elapsed = time.monotonic() - started
    timeout_run = _parse(timeout_res)
    assert len(timeout_run.of("FACT_TIMEOUT")) == 1, timeout_run.out
    assert elapsed < 20.0, f"вызов занял {elapsed:.1f} с"


def _assert_open_stdin_does_not_hang(repo: GitRepo, c2: str) -> None:
    """Подпроцесс lint-brief с открытым stdin не зависает на `git log --stdin`."""
    fact = _fact("stdin", "git log --stdin -1 --format=%h", exit_code=0)
    _put(repo, _REL, _Brief().set_facts(fact, sha=c2[:7]).text())
    env = {
        **os.environ,
        "PYTHONPATH": str(_ROOT),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "ATLAS_REPLAY_TIMEOUT": "5",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "scripts.atlas", "lint-brief", _REL, "--no-fresh"],
        cwd=repo.path,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:

        def finish() -> int | None:
            try:
                return proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                return None

        code = run_with_deadline(finish, 90)
        out = proc.stdout.read() if proc.stdout else ""
        err = proc.stderr.read() if proc.stderr else ""
    finally:
        if proc.poll() is None:
            proc.kill()
        if proc.stdin:
            proc.stdin.close()
    assert code is not None, "подпроцесс не завершился за 60 с при открытом stdin"
    run = _parse(_Res(code, out, err))
    assert run.of("FACT_TIMEOUT") == [], run.out
    assert run.code == 0, run.where()
    assert run.last.startswith("lint-brief: ошибок 0, "), run.last


# --- РЕД 6: REDS --------------------------------------------------------------------------------------------------


def test_reds_checks(repo: GitRepo, slow_atlas: Any) -> None:
    _put(repo, "README.md", "readme\n")
    _put(repo, "tests/test_has.py", "def test_present():\n    pass\n")
    _put(repo, "tests/test_has2.py", "def test_present():\n    pass\n")
    _put(repo, "tests/test_broken.py", "def test_x(:\n    pass\n")
    repo.commit("init")
    role = _Brief("role").set_body("FILES", "  1. tests/test_has2.py — x", "  2. tests/future_role.py — x")
    _put(repo, _REL_ROLE, role.text())

    def reds(item: str, files: list[str] | None = None, na: bool = False) -> _Brief:
        b = _Brief()
        if files is not None:
            b.set_body("FILES", *[f"  {i}. {p} — x" for i, p in enumerate(files, 1)])
        b.set_body("REDS", "  n/a — тестов нет" if na else f"  - {item}")
        return b

    def run_of(b: _Brief, *flags: str) -> _Run:
        _put(repo, _REL, b.text())
        return _parse(slow_atlas(repo, "lint-brief", _REL, "--no-fresh", *flags))

    def reds_codes(run: _Run) -> list[str]:
        return sorted(c for c in run.codes() if c.startswith("REDS_"))

    # нет файла и его нет в FILES -> REDS_NO_FILE; с --no-replay — тоже
    run = run_of(reds("tests/nowhere.py::test_a", ["src/a.py"]))
    assert reds_codes(run) == ["REDS_NO_FILE"], run.out
    assert run.code == 1, run.where()
    run = run_of(reds("tests/nowhere.py::test_a", ["src/a.py"]), "--no-replay")
    assert reds_codes(run) == ["REDS_NO_FILE"], run.out

    # файл есть, имя собрано — ошибки нет
    run = run_of(reds("tests/test_has.py::test_present", ["src/a.py"]))
    assert reds_codes(run) == [], run.out
    assert run.code == 0, run.where()

    # файл есть, имени нет, файла нет в FILES -> REDS_NOT_COLLECTED; с --no-replay сборки нет
    run = run_of(reds("tests/test_has.py::test_absent", ["src/a.py"]))
    assert reds_codes(run) == ["REDS_NOT_COLLECTED"], run.out
    assert run.code == 1, run.where()
    run = run_of(reds("tests/test_has.py::test_absent", ["src/a.py"]), "--no-replay")
    assert reds_codes(run) == [], run.out
    assert run.code == 0, run.where()

    # имени нет, файл в FILES брифа — разрешено (новое имя в планируемом файле)
    run = run_of(reds("tests/test_has.py::test_absent", ["tests/test_has.py"]))
    assert reds_codes(run) == [], run.out
    assert run.code == 0, run.where()

    # имени нет, файл в FILES файла роли рядом — разрешено
    run = run_of(reds("tests/test_has2.py::test_absent", ["src/a.py"]))
    assert reds_codes(run) == [], run.out
    assert run.code == 0, run.where()

    # файла нет, но он назван в FILES брифа / в FILES файла роли — REDS_NO_FILE нет
    run = run_of(reds("tests/future.py::test_f", ["tests/future.py"]))
    assert reds_codes(run) == [], run.out
    assert run.code == 0, run.where()
    run = run_of(reds("tests/future_role.py::test_r", ["src/a.py"]))
    assert reds_codes(run) == [], run.out
    assert run.code == 0, run.where()

    # файл не собирается -> REDS_COLLECT_FAILED
    run = run_of(reds("tests/test_broken.py::test_x", ["src/a.py"]))
    assert reds_codes(run) == ["REDS_COLLECT_FAILED"], run.out
    assert run.code == 1, run.where()

    # `n/a — …`: проверок нет
    run = run_of(reds("", ["src/a.py"], na=True))
    assert reds_codes(run) == [], run.out
    assert run.code == 0, run.where()


# --- РЕД 7: инъекции, PROBE, RACE_WITHOUT_PROBE -------------------------------------------------------------------

_RED_ONE = "tests/test_planned.py::test_red_one"


def _inj(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "inj-1",
        "prop": "свойство одной строкой",
        "file": "src/code.py",
        "old": "value = 1",
        "new": "value = 9",
        "forecast": [_RED_ONE],
        "observed": None,
        "test": "tests/test_planned.py -k red",
    }
    base.update(over)
    return base


def _put_json(repo: GitRepo, data: Any) -> None:
    _put(repo, _REL_INJ, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _inj_brief() -> _Brief:
    b = _Brief().set_body("FILES", "  1. src/code.py — x", "  2. src/crlf.py — x", "  3. tests/test_planned.py — новый")
    return b.set_body("REDS", f"  - {_RED_ONE}")


def test_injections_and_probe_checks(repo: GitRepo, atlas: Any, slow_atlas: Any) -> None:
    _put(repo, "README.md", "readme\n")
    _put(repo, "src/code.py", "value = 1\nother = 2\ndup = 3\ndup = 3\n")
    _put(repo, "src/crlf.py", b"a = 1\r\nb = 2\r\n")
    _put(repo, "tests/test_has.py", "def test_present():\n    pass\n")
    repo.commit("init")
    _put(repo, _REL_ROLE, _Brief("role").set_body("FILES", "  1. tests/test_other.py — x").text())
    _put(repo, _REL, _inj_brief().text())

    def inj_run(data: Any, *flags: str) -> _Run:
        _put_json(repo, data)
        return _lint(atlas, repo, _REL, *(flags or _FORM))

    def inj_codes(run: _Run) -> list[str]:
        return sorted(c for c in run.codes() if c.startswith("INJ_"))

    # допустимое: новое имя в планируемом файле, forecast из FILES роли, `[]`, многострочный old в файле с CRLF
    valid = [
        _inj(forecast=[_RED_ONE, "tests/test_planned.py::test_new_name"]),
        _inj(id="inj-2", forecast=["tests/test_other.py::test_q"]),
        _inj(id="inj-3", file="src/crlf.py", old="a = 1\nb = 2", new="a = 0", forecast=[]),
    ]
    run = inj_run(valid)
    assert inj_codes(run) == [], run.out
    assert run.code == 0, run.where()

    # путь находки — путь JSON-файла
    run = inj_run([_inj(file="src/nofile.py")])
    assert inj_codes(run) == ["INJ_FILE_MISSING"], run.out
    assert run.of("INJ_FILE_MISSING")[0].sev == "error", run.out
    assert run.of("INJ_FILE_MISSING")[0].path.endswith("1.2.injections.json"), run.out
    assert run.code == 1, run.where()

    run = inj_run([_inj(old="такого текста нет")])
    assert inj_codes(run) == ["INJ_OLD_MISSING"], run.out
    assert run.of("INJ_OLD_MISSING")[0].path.endswith("1.2.injections.json"), run.out
    assert run.code == 1, run.where()

    run = inj_run([_inj(old="dup = 3")])
    assert inj_codes(run) == ["INJ_OLD_AMBIGUOUS"], run.out
    assert run.of("INJ_OLD_AMBIGUOUS")[0].path.endswith("1.2.injections.json"), run.out
    assert run.code == 1, run.where()

    # INJ_FORM: текст начинается с `inj-<n>:`; хороший объект находки не имеет
    bad = [
        _inj(extra="лишний ключ"),
        {k: v for k, v in _inj(id="inj-2").items() if k != "test"},
        _inj(id="inj-3", old=""),
        _inj(id="inj-4", forecast=["test_x"]),
        _inj(id="inj-5", forecast=_RED_ONE),
        _inj(id="inj-6"),
    ]
    run = inj_run(bad)
    form = run.of("INJ_FORM")
    prefixes = sorted({f.text.split(" ", 1)[0] for f in form})
    assert prefixes == ["inj-1:", "inj-2:", "inj-3:", "inj-4:", "inj-5:"], (prefixes, run.out)
    assert all(f.sev == "error" and f.path.endswith("1.2.injections.json") for f in form), run.out
    assert run.code == 1, run.where()

    run = inj_run([_inj(), _inj(id="inj-3")])  # id не по порядку
    assert len(run.of("INJ_FORM")) >= 1, run.out
    assert run.code == 1, run.where()
    run = inj_run(_inj())  # не массив
    assert len(run.of("INJ_FORM")) >= 1, run.out
    assert run.code == 1, run.where()

    # forecast: неизвестный nodeid; существующий и собранный допустим только без --no-replay
    run = inj_run([_inj(forecast=["tests/unlisted.py::test_zz"])])
    assert inj_codes(run) == ["INJ_FORECAST_UNKNOWN"], run.out
    assert run.code == 1, run.where()
    collected = [_inj(forecast=["tests/test_has.py::test_present"])]
    run = inj_run(collected, "--no-replay", "--no-fresh")
    assert inj_codes(run) == ["INJ_FORECAST_UNKNOWN"], run.out
    _put_json(repo, collected)
    full = _parse(slow_atlas(repo, "lint-brief", _REL, "--no-fresh"))
    assert [c for c in full.codes() if c.startswith("INJ_")] == [], full.out
    assert full.code == 0, full.where()

    # PROBE: файла нет ни от корня, ни от каталога плана
    (repo.path / _REL_INJ).unlink()

    def probe(*lines: str) -> _Run:
        b = _Brief()
        b.tail = list(lines)
        return _form(atlas, repo, b)

    run = probe("PROBE: reports/9.9.probe.md")
    assert [f.sev for f in run.of("PROBE_MISSING")] == ["error"], run.out
    assert run.code == 1, run.where()
    run = probe("PROBE:")
    assert len(run.of("PROBE_MISSING")) == 1, run.out
    assert run.code == 1, run.where()
    _put(repo, "reports/9.9.probe.md", "проба\n")  # от корня
    run = probe("PROBE: reports/9.9.probe.md")
    assert run.of("PROBE_MISSING") == [], run.out
    assert run.code == 0, run.where()
    _put(repo, "plans/p/reports/8.8.probe.md", "проба\n")  # от каталога плана (родитель tasks/)
    run = probe("PROBE: reports/8.8.probe.md")
    assert run.of("PROBE_MISSING") == [], run.out
    assert run.code == 0, run.where()
    run = probe("PROBE:", "  reports/8.8.probe.md")  # путь в теле метки
    assert run.of("PROBE_MISSING") == [], run.out
    assert run.code == 0, run.where()

    # RACE_WITHOUT_PROBE: warning, код 0
    def design_with(text: str) -> _Brief:
        return _Brief().set_body("DESIGN", f"  1. {text}", "  2. второе", "  3. третье")

    for word, line in (
        ("гонка", "гонка между таймером и записью"),
        ("race", "race между потоками"),
        ("lost-wakeup", "lost-wakeup в очереди"),
        ("одновременно", "два потока одновременно пишут"),
    ):
        run = _form(atlas, repo, design_with(line))
        assert [f.sev for f in run.of("RACE_WITHOUT_PROBE")] == ["warning"], f"DESIGN/{word}: {run.out}"
        assert run.code == 0, f"DESIGN/{word}: {run.where()}"
        assert run.counts[:2] == (0, 1), f"DESIGN/{word}: {run.last}"
    traps = _Brief()
    traps.tail = ["TRAPS: возможна гонка при записи"]
    run = _form(atlas, repo, traps)
    assert [f.sev for f in run.of("RACE_WITHOUT_PROBE")] == ["warning"], run.out
    assert run.code == 0, run.where()
    for name, line in (("обратные кавычки", "вызов `гонка` в кавычках"), ("внутри слова", "читать traceback из лога")):
        run = _form(atlas, repo, design_with(line))
        assert run.of("RACE_WITHOUT_PROBE") == [], f"{name}: {run.out}"
        assert run.code == 0, f"{name}: {run.where()}"
    with_probe = design_with("гонка между таймером и записью")
    with_probe.tail = ["PROBE: reports/9.9.probe.md"]
    run = _form(atlas, repo, with_probe)
    assert run.of("RACE_WITHOUT_PROBE") == [], run.out
    assert run.code == 0, run.where()


# --- РЕД 8: свежесть, флаги, ввод ---------------------------------------------------------------------------------


def test_freshness_flags_and_usage(repo: GitRepo, repo_factory: RepoFactory, atlas: Any, tmp_path: Path) -> None:
    _put(repo, "README.md", "readme\n")
    _put(repo, "src/m.py", "v = 1\n")
    sha7 = repo.commit("init")[:7]
    fact = _fact("значение", 'git grep -n "v = 1" -- src/m.py', lit="src/m.py:1:")
    brief = _Brief().set_facts(fact, sha=sha7)
    _put(repo, _REL, brief.text())

    # контроль: дерево совпадает с коммитом маркера — свежо (и подкоманда существует)
    run = _lint(atlas, repo, _REL, "--no-replay")
    assert run.of("FACTS_STALE") == [], run.out
    assert run.code == 0, run.where()

    # файл, названный литералом, изменён в рабочем дереве относительно <sha7> -> FACTS_STALE
    _put(repo, "src/m.py", "v = 2\n")
    run = _lint(atlas, repo, _REL, "--no-replay")
    assert [f.sev for f in run.of("FACTS_STALE")] == ["error"], run.out
    assert run.code == 1, run.where()
    run = _lint(atlas, repo, _REL, "--no-replay", "--no-fresh")
    assert run.of("FACTS_STALE") == [], run.out
    assert run.code == 0, run.where()

    # неизвестный sha — ошибка, не молчание; --no-fresh её снимает
    _put(repo, _REL, _Brief().set_facts(fact, sha="0000000").text())
    run = _lint(atlas, repo, _REL, "--no-replay")
    assert [f.sev for f in run.of("FACTS_STALE")] == ["error"], run.out
    assert run.code == 1, run.where()
    run = _lint(atlas, repo, _REL, "--no-replay", "--no-fresh")
    assert run.of("FACTS_STALE") == [], run.out
    assert run.code == 0, run.where()

    # код 2: имя файла вне формы, нет файла, файл вне репозитория / вне корня вызова
    good = _Brief().text()
    for name in ("1.2.result.md", "1.2.injections.json", "1.2.txt"):
        rel = f"plans/p/tasks/{name}"
        _put(repo, rel, good)
        res = atlas(repo, "lint-brief", rel, *_FORM)
        assert res.code == 2, f"{name}: код {res.code}, stdout={res.out!r}, stderr={res.err!r}"
    res = atlas(repo, "lint-brief", "plans/p/tasks/9.9.md", *_FORM)
    assert res.code == 2, f"нет файла: код {res.code}, stdout={res.out!r}, stderr={res.err!r}"

    outside = tmp_path / "outside" / "1.2.md"
    outside.parent.mkdir()
    outside.write_bytes(good.encode("utf-8"))
    res = atlas(repo, "lint-brief", str(outside), *_FORM)
    assert res.code == 2, f"вне git: код {res.code}, stdout={res.out!r}, stderr={res.err!r}"

    other = repo_factory.create("other")
    _put(other, "1.2.md", good)
    res = atlas(repo, "lint-brief", str(other.path / "1.2.md"), *_FORM)
    assert res.code == 2, f"в чужом репозитории: код {res.code}, stdout={res.out!r}, stderr={res.err!r}"


# --- РЕД 9: хук использует ту же функцию --------------------------------------------------------------------------


def _git_bash() -> str | None:
    git = shutil.which("git")
    for parent in Path(git).resolve().parents if git else []:
        if (parent / "bin" / "bash.exe").is_file():
            return str(parent / "bin" / "bash.exe")
    return shutil.which("bash") if sys.platform != "win32" else None


def _prompt(
    *, design: int | None = 3, files: int = 1, reds: int = 1, reds_na: bool = False, report: bool = True
) -> str:
    lines = ["TASK: 1.2 — проба   PLAN: plans/p/plan.md", "ROLE: developer", "CHAIN: tester -> developer"]
    if design is not None:
        lines.append("DESIGN (decided by the lead — you type it, you do not derive it):")
        lines += [f"  {i}. шаг {i}" for i in range(1, design + 1)]
    lines.append("FILES (complete list — nothing else):")
    lines += [f"  {i}. src/f{i}.py — правка" for i in range(1, files + 1)]
    lines.append("REDS (predicted red tests):")
    if reds_na:
        lines.append("  n/a — тестов нет")
    lines += [f"  - tests/test_a.py::test_{i}" for i in range(1, reds + 1)]
    lines += ["TESTS: python -m pytest tests -q", "OUT OF SCOPE: всё остальное"]
    if report:
        lines.append("REPORT: STATUS first")
    return "\n".join(lines) + "\n"


def _run_hook(bash: str, project: Path, prompt: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["CLAUDE_PYTHON_BIN"] = sys.executable
    env["CLAUDE_PROJECT_DIR"] = str(project)
    payload = {"tool_name": "Agent", "tool_input": {"subagent_type": "developer", "prompt": prompt}}
    return subprocess.run(
        [bash, _HOOK.as_posix()],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=str(project),
        timeout=60,
        check=False,
    )


def _deny_reason(proc: subprocess.CompletedProcess[str]) -> str | None:
    """Причина отказа или None; код выхода хука всегда 0, stdout — только JSON отказа."""
    assert proc.returncode == 0, f"код хука {proc.returncode}: {proc.stderr}"
    if not proc.stdout.strip():
        return None
    data = json.loads(proc.stdout)
    out = data["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny", proc.stdout
    return out["permissionDecisionReason"]


def test_spawn_hook_uses_the_same_function(tmp_path: Path, repo: GitRepo, atlas: Any) -> None:
    bash = _git_bash()
    if bash is None:
        pytest.skip("нет Git Bash: хук lint-brief.sh не запустить")

    # те же нарушения лимитов файл-режим называет кодами
    _init(repo)
    b = _Brief().set_body("FILES", "  1. tests/test_a.py — x", *[f"  {i}. src/f{i}.py — x" for i in range(2, 8)])
    b.set_body("REDS", *[f"  - tests/test_a.py::test_{i}" for i in range(1, 12)])
    run = _form(atlas, repo, b)
    assert [f.sev for f in run.of("FILES_TOO_MANY")] == ["error"], run.out
    assert [f.sev for f in run.of("REDS_TOO_MANY")] == ["error"], run.out
    assert run.code == 1, run.where()

    # проект с модулем: тексты отказов хука
    cases = [
        (_prompt(reds=11), "REDS lists 11 tests"),
        (_prompt(design=2), "DESIGN has 2 non-empty line(s) (need >= 3)"),
        (_prompt(files=7), "FILES lists 7 paths (max 6)"),
        (_prompt(report=False), "REPORT block missing"),
        (_prompt(design=None), "DESIGN block missing"),
    ]
    for prompt, expected in cases:
        reason = _deny_reason(_run_hook(bash, _ROOT, prompt))
        assert reason is not None and expected in reason, (expected, reason)
    for name, prompt in (
        ("REDS n/a первой строкой", _prompt(reds=11, reds_na=True)),
        ("DESIGN из 3 строк", _prompt(design=3)),
        ("FILES из 6 пунктов", _prompt(files=6)),
    ):
        assert _deny_reason(_run_hook(bash, _ROOT, prompt)) is None, name

    # проект без модуля `scripts.atlas.lint_brief`: проверка как раньше
    empty = tmp_path / "empty"
    empty.mkdir()
    pkgs = tmp_path / "pkgs"
    (pkgs / "scripts" / "atlas").mkdir(parents=True)
    (pkgs / "scripts" / "__init__.py").write_text("", encoding="utf-8")
    (pkgs / "scripts" / "atlas" / "__init__.py").write_text("", encoding="utf-8")
    for name, project in (("пустой каталог", empty), ("пакеты без lint_brief", pkgs)):
        reason = _deny_reason(_run_hook(bash, project, _prompt(reds=11)))
        assert reason is not None and "REDS lists 11 tests" in reason, (name, reason)
        assert _deny_reason(_run_hook(bash, project, _prompt())) is None, name

    # модуль есть, но падает при импорте: общая функция недоступна — хук молчит (не запасная проверка)
    broken = tmp_path / "broken"
    (broken / "scripts" / "atlas").mkdir(parents=True)
    (broken / "scripts" / "__init__.py").write_text("", encoding="utf-8")
    (broken / "scripts" / "atlas" / "__init__.py").write_text("", encoding="utf-8")
    (broken / "scripts" / "atlas" / "lint_brief.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    proc = _run_hook(bash, broken, _prompt(reds=11))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "", f"хук отказал при сломанном модуле (запасная проверка): {proc.stdout!r}"
