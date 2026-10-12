"""Тесты автора `atlas metrics` (Task 1.9f): свойства, которых нет у слепых тестов tester.

Purpose: id с дефисом в имени отчёта и в трейлере; два хеша в группе DONE; хеш из одних цифр в обратных кавычках;
    `--main-ref` до подкоманды и после; один spec в `--base` и среди текущих; CRLF в брифе M1. Ожидаемые значения —
    литералы, пересчитанные вручную; вход строится из чисел, а не из кода под проверкой.
Public API: тесты test_*; публичных имён нет.
Stability: lite
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from scripts.atlas.tests.conftest import GitRepo, run_with_deadline

__all__: list[str] = []

Cli = Callable[..., tuple[int, str, str]]

_OPEN_SECTION = "## Что я оставил открытым / ненадёжным"


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Cli:
    def run(cwd: Path, *argv: str) -> tuple[int, str, str]:
        monkeypatch.chdir(cwd)
        capsys.readouterr()

        def call() -> int:
            from scripts.atlas.__main__ import main

            try:
                return main(list(argv))
            except SystemExit as exc:
                return exc.code if isinstance(exc.code, int) else 1

        code = run_with_deadline(call)
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return run


def _put(repo: GitRepo, rel: str, data: bytes) -> None:
    path = repo.path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _report(task: str, verdict: str, rnd: int, findings: list[tuple[str, str]]) -> bytes:
    """Валидный отчёт §5: Итог и Классы пишутся руками по входу (степени и классы пунктов — аргумент)."""
    sev = [sum(1 for s, _ in findings if s == n) for n in ("blocker", "major", "minor", "nit")]
    names = ("fact", "dryrun", "form", "context", "design", "scope", "process")
    cls = [sum(1 for _, c in findings if c == n) for n in names]
    lines = [
        f"# {task} — ревью стадии 0, раунд {rnd}",
        f"Вердикт: {verdict}",
        "Итог: blocker %d, major %d, minor %d, nit %d" % tuple(sev),
        "Классы: " + ", ".join(f"{n} {c}" for n, c in zip(names, cls)),
        "",
        "## Замечания",
        *(f"- [{s}/{c}] замечание: вход → наблюдение." for s, c in findings),
        "",
        _OPEN_SECTION,
        "- Ничего сверх перечисленного.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def _commit(repo: GitRepo, name: str, message: str) -> str:
    _put(repo, f"files/{name}.txt", (name + "\n").encode())
    return repo.commit(message)


def _cell(out: str, label: str) -> str:
    rows = [ln for ln in out.splitlines() if ln.startswith(f"| {label} |")]
    assert len(rows) == 1, out
    return rows[0].removeprefix(f"| {label} | ").removesuffix(" |")


def test_dashed_id_in_report_name_and_trailer(repo: GitRepo, cli: Cli) -> None:
    task = "0.5a-pre"
    _put(repo, "plans/p/plan.md", b"# plan\n")
    _put(repo, f"plans/p/tasks/{task}.md", f"# Task {task}\n".encode())
    reports = f"plans/p/reports/{task}.review-r"
    _put(repo, f"{reports}1.md", _report(task, "CHANGES REQUESTED", 1, [("major", "form")]))
    _put(repo, f"{reports}2.md", _report(task, "APPROVED", 2, [("nit", "form")]))
    _commit(repo, "init", "chore: init")
    done = _commit(repo, "done", f"feat: готово\n\nTask: p#{task}")
    _commit(repo, "after", f"fix(core): правка\n\nTask: p#{task}")
    _commit(repo, "notes", f"docs(plans): запись\n\nTask: p#{task}")
    _put(repo, "plans/p/plan.md", f"# plan\n\n- Task {task}: x [DONE 2026-10-12 — `{done}`]\n".encode())

    code, out, err = cli(repo.path, "metrics", f"p#{task}")
    assert code == 0, (out, err)
    assert _cell(out, "M2 blocker+major р.1 по классам") == "major form 1"
    assert _cell(out, "M3 раундов до APPROVED") == "2"
    assert _cell(out, "M4 коммитов после DONE") == f"2 (не docs 1) после {done[:7]}"


def test_two_hashes_in_done_group_first_wins(repo: GitRepo, cli: Cli) -> None:
    _put(repo, "plans/p/plan.md", b"# plan\n")
    _put(repo, "plans/p/tasks/1.1.md", b"# Task 1.1\n")
    _commit(repo, "init", "chore: init")
    first = _commit(repo, "first", "feat: первый\n\nTask: p#1.1")
    second = _commit(repo, "second", "fix: второй\n\nTask: p#1.1")
    _commit(repo, "third", "fix: третий\n\nTask: p#1.1")
    line = f"- Task 1.1: x [DONE 2026-10-12 — `{first}`, слияние `{second}`]\n"
    _put(repo, "plans/p/plan.md", ("# plan\n\n" + line).encode())

    code, out, err = cli(repo.path, "metrics", "p#1.1")
    assert code == 0, (out, err)
    assert _cell(out, "M4 коммитов после DONE") == f"2 (не docs 2) после {first[:7]}"


def test_digit_only_backticked_hash_is_a_violation(repo: GitRepo, cli: Cli) -> None:
    _put(repo, "plans/p/plan.md", "# plan\n\n- Task 1.1: x [DONE 2026-10-12 — `1234567`]\n".encode("utf-8"))
    _put(repo, "plans/p/tasks/1.1.md", b"# Task 1.1\n")
    code, out, _ = cli(repo.path, "metrics", "p#1.1")
    assert code == 1, out
    assert _cell(out, "M4 коммитов после DONE") == "?"
    assert "  plans/p/plan.md: задача 1.1: хеш DONE 1234567 не найден" in out.splitlines()


def test_main_ref_before_subcommand_accepted_after_rejected(repo: GitRepo, cli: Cli) -> None:
    _put(repo, "plans/p/plan.md", b"# plan\n")
    _put(repo, "plans/p/tasks/1.1.md", b"# Task 1.1\n")
    _commit(repo, "init", "chore: init")
    code, out, err = cli(repo.path, "--main-ref", "main", "metrics", "p#1.1")
    assert code == 0, (out, err)
    code, _, err = cli(repo.path, "metrics", "p#1.1", "--main-ref", "main")
    assert code == 2
    assert "unrecognized arguments" in err


def test_same_spec_in_base_and_current_reports_violation_once(repo: GitRepo, cli: Cli) -> None:
    _put(repo, "plans/p/plan.md", b"# plan\n")
    _put(repo, "plans/p/tasks/1.1.md", b"# Task 1.1\n")
    broken = _report("1.1", "CHANGES REQUESTED", 1, [("nit", "form")]).decode("utf-8")
    broken = broken.replace("Вердикт: CHANGES REQUESTED", "Вердикт: ?").encode("utf-8")
    _put(repo, "plans/p/reports/1.1.review-r1.md", broken)
    code, out, _ = cli(repo.path, "metrics", "p#1.1", "--base", "p#1.1")
    assert code == 1, out
    header = next(ln for ln in out.splitlines() if ln.startswith("| метрика |"))
    assert header == "| метрика | база p#1.1 | сейчас p#1.1 |"
    assert out.count("нарушения формы (1):") == 1
    assert sum(1 for ln in out.splitlines() if ln.startswith("  plans/p/reports/1.1.review-r1.md: ")) == 1


def test_m1_reads_brief_with_crlf_bytes(repo: GitRepo, cli: Cli) -> None:
    _put(repo, "plans/p/plan.md", b"# plan\n")
    crlf = "\r\n"
    brief = crlf.join(
        [
            "# Task 1.1",
            "FACTS:",
            "<!-- atlas:facts abc1234 -->",
            "- проверка — `python -m scripts.atlas card m` → exit 0",
            "- факт — `git grep -n x` → `1`",
            "- ещё — `git log` → `2`",
            "<!-- /atlas:facts -->",
            "",
        ]
    )
    _put(repo, "plans/p/tasks/1.1.md", brief.encode("utf-8"))
    code, out, err = cli(repo.path, "metrics", "p#1.1")
    assert code == 0, (out, err)
    assert _cell(out, "M1 доля фактов Атласа") == "33% (1/3)"


def test_ref_before_metrics_is_usage_error(repo: GitRepo, cli: Cli) -> None:
    _put(repo, "plans/p/plan.md", b"# plan\n")
    _put(repo, "plans/p/tasks/1.1.md", b"# Task 1.1\n")
    _commit(repo, "init", "chore: init")
    code, out, err = cli(repo.path, "metrics", "p#1.1")
    assert code == 0, (out, err)  # тот же вызов без --ref валиден: код 2 ниже — только из-за --ref
    code, _, err = cli(repo.path, "--ref", "HEAD", "metrics", "p#1.1")
    assert code == 2
    assert "нужна ровно одна форма" in err


def test_bullet_without_text_is_a_violation() -> None:
    from scripts.atlas import review_form

    report = "\n".join(
        [
            "# 1.1 — ревью стадии 0, раунд 1",
            "Вердикт: CHANGES REQUESTED",
            "Итог: blocker 0, major 1, minor 0, nit 0",
            "Классы: fact 1, dryrun 0, form 0, context 0, design 0, scope 0, process 0",
            "",
            "## Замечания",
            "- [major/fact]",
            "",
            _OPEN_SECTION,
            "- Ничего сверх перечисленного.",
            "",
        ]
    )
    review, errors = review_form.parse(report)
    assert review is None
    assert any("строка 7" in e for e in errors), errors
