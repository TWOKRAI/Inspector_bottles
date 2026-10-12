"""Слепые приёмочные тесты `atlas metrics` и читателя отчёта ревью `review_form` (Task 1.9f, RED до кода).

Purpose: десять тестов по REDS брифа plans/2026-10-04_atlas/tasks/1.9f.tester.md. Контракт читателя —
    `scripts.atlas.review_form.parse(text) -> (review | None, list[str])`; контракт CLI —
    `main(["metrics", <spec>..., [--base <spec>]...])`: таблица `| метрика | <колонки> |` из пяти метрик
    (M1 доля фактов Атласа, M2 blocker+major р.1 по классам и сумма fact+dryrun+form, M3 раундов до APPROVED,
    M4 коммитов после DONE), блок «нарушения формы (N):» и последняя строка `U1/U2: …`. Формат отчёта —
    ADR-ATL-004 §5 (`scripts/atlas/DECISIONS.md`) и шаблон `.claude/plugins/dev/templates/review-report.md`.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Правила файла. Ожидаемые значения — литералы из брифа или пересчитанные вручную по живым отчётам, из кода под
проверкой не берутся (хелпер `_report` строит ВХОД из чисел, а не ответ). Файлы временных репозиториев пишутся
байтами (без CRLF-подмены Windows). Любой вызов main() и git идёт через дедлайн (`run_with_deadline`).
Подкоманда `metrics` до кода не зарегистрирована: фикстура `cli` превращает argparse-`invalid choice` в явный
`pytest.fail`, чтобы красный не прятался за кодом 2, который в части тестов и есть ожидаемый ответ.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest

from scripts.atlas.tests.conftest import GitRepo, run_with_deadline

__all__: list[str] = []

_ROOT = Path(__file__).resolve().parents[3]
_TEMPLATE = _ROOT / ".claude" / "plugins" / "dev" / "templates" / "review-report.md"
_K0 = _ROOT / "plans" / "2026-10-07_k0-framework-quality" / "reports"
_ATLAS = _ROOT / "plans" / "2026-10-04_atlas" / "reports"

_SEVERITIES = ("blocker", "major", "minor", "nit")
_CLASSES = ("fact", "dryrun", "form", "context", "design", "scope", "process")
_LABELS = (
    "M1 доля фактов Атласа",
    "M2 blocker+major р.1 по классам",
    "M2 из них fact+dryrun+form",
    "M3 раундов до APPROVED",
    "M4 коммитов после DONE",
)
_LAST_LINE = "U1/U2: не считаются — журнала нет (Task 1.10b)"
_REQUIRED_SECTION = "## Что я оставил открытым / ненадёжным"

Cli = Callable[..., tuple[int, str, str]]


# --- общие помощники ---------------------------------------------------------------------------------------------


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Cli:
    """cli(cwd, *argv) -> (код, stdout, stderr): main(argv) в потоке с дедлайном, cwd подменён."""

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
        if "invalid choice" in captured.err:
            pytest.fail(f"подкоманда `metrics` не зарегистрирована: {captured.err.strip()[:300]}")
        return code, captured.out, captured.err

    return run


def _put(repo: GitRepo, rel: str, text: str) -> None:
    """Записать файл байтами UTF-8 (окончания строк — как в `text`)."""
    path = repo.path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _make_plan(
    repo: GitRepo, slug: str, ids: tuple[str, ...] = (), *, prefix: str = "", plan_text: str = "# План\n"
) -> str:
    """plans/<prefix><slug>/plan.md и tasks/<id>.md для каждого id; вернуть каталог плана от корня."""
    base = f"plans/{prefix}{slug}"
    _put(repo, f"{base}/plan.md", plan_text)
    for task_id in ids:
        _put(repo, f"{base}/tasks/{task_id}.md", f"# Task {task_id} — проба\n\nTASK: {task_id}\n")
    return base


def _report(
    findings: list[tuple[str, str]],
    verdict: str = "CHANGES REQUESTED",
    *,
    task: str = "1.1",
    rnd: int = 1,
) -> str:
    """Валидный отчёт §5 из пунктов (степень, класс): Итог и Классы считаются по входу, не по коду под проверкой."""
    sev = [sum(1 for s, _ in findings if s == name) for name in _SEVERITIES]
    cls = [sum(1 for _, c in findings if c == name) for name in _CLASSES]
    lines = [
        f"# {task} — ревью стадии 0, раунд {rnd}",
        f"Вердикт: {verdict}",
        "Итог: " + ", ".join(f"{n} {v}" for n, v in zip(_SEVERITIES, sev)),
        "Классы: " + ", ".join(f"{n} {v}" for n, v in zip(_CLASSES, cls)),
        "",
        "## Замечания",
    ]
    for severity, klass in findings:
        lines.append(f"- [{severity}/{klass}] замечание {severity} {klass}: вход → наблюдение.")
    lines += ["", _REQUIRED_SECTION, "- Ничего сверх перечисленного.", ""]
    return "\n".join(lines)


def _broken_report() -> str:
    """Отчёт с ровно одним нарушением грамматики: вердикт с лишним словом (строка 2)."""
    return _report([("nit", "form")]).replace("Вердикт: CHANGES REQUESTED", "Вердикт: CHANGES REQUESTED сейчас", 1)


def _table(out: str) -> tuple[list[str], dict[str, list[str]]]:
    """Разобрать таблицу stdout: (ячейки заголовка, {подпись метрики: ячейки}); строк таблицы ровно 7."""
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in out.splitlines() if ln.startswith("|")]
    assert len(rows) == 7, f"в таблице {len(rows)} строк вместо 7 (заголовок, разделитель, пять метрик): {out!r}"
    assert all(re.fullmatch(r":?-+:?", c) for c in rows[1]), f"вторая строка не разделитель: {rows[1]}"
    assert [r[0] for r in rows[2:]] == list(_LABELS), f"подписи метрик: {[r[0] for r in rows[2:]]}"
    return rows[0], {r[0]: r[1:] for r in rows[2:]}


def _example_lines() -> list[str]:
    """Первый блок в четырёх обратных кавычках с меткой `markdown` шаблона (пример отчёта §5)."""
    lines = _TEMPLATE.read_text(encoding="utf-8").splitlines()
    start = lines.index("````markdown")
    end = lines.index("````", start + 1)
    return lines[start + 1 : end]


def _join(lines: list[str]) -> str:
    return "\n".join(lines) + "\n"


def _fields(review: object) -> tuple[object, object, object, object]:
    return (
        review.verdict,  # type: ignore[attr-defined]
        tuple(review.severities),  # type: ignore[attr-defined]
        tuple(review.classes),  # type: ignore[attr-defined]
        tuple(tuple(p) for p in review.findings),  # type: ignore[attr-defined]
    )


# --- review_form: читатель отчёта -------------------------------------------------------------------------------


def test_review_form_real_reports_and_template() -> None:
    from scripts.atlas import review_form

    # (файл, вердикт, Итог, Классы, число пунктов) — литералы из брифа, сверены чтением шапок живых отчётов
    live = [
        (_ATLAS / "1.9c.review-r1.md", "CHANGES REQUESTED", (0, 7, 9, 1), (0, 5, 5, 1, 5, 1, 0), 17),
        (_ATLAS / "1.9c.review-r2.md", "CHANGES REQUESTED", (0, 1, 2, 1), (0, 3, 1, 0, 0, 0, 0), 4),
        (_ATLAS / "1.9c.review-code-r1.md", "CHANGES REQUESTED", (2, 1, 3, 3), (0, 3, 1, 0, 5, 0, 0), 9),
        (_ATLAS / "1.9c.review-code-r2.md", "CHANGES REQUESTED", (1, 0, 0, 2), (0, 0, 0, 0, 2, 1, 0), 3),
        (_K0 / "1.2.review-r1.md", "CHANGES REQUESTED", (0, 6, 9, 10), (7, 5, 4, 5, 2, 0, 2), 25),
        (_K0 / "1.1.review-r1.md", "CHANGES REQUESTED", (1, 3, 6, 2), (4, 5, 3, 0, 0, 0, 0), 12),
        (_K0 / "1.1.review-r2.md", "APPROVED", (0, 0, 4, 1), (2, 1, 1, 1, 0, 0, 0), 5),
    ]
    problems: list[str] = []
    for path, verdict, severities, classes, count in live:
        review, errors = review_form.parse(path.read_text(encoding="utf-8"))
        if review is None or errors:
            problems.append(f"{path.name}: ожидалось (review, []), получено ошибок {errors}")
            continue
        got = (review.verdict, tuple(review.severities), tuple(review.classes), len(review.findings))
        if got != (verdict, severities, classes, count):
            problems.append(f"{path.name}: {got} != {(verdict, severities, classes, count)}")
    assert not problems, "\n".join(problems)

    def first(path: Path) -> tuple[str, str]:
        review, _ = review_form.parse(path.read_text(encoding="utf-8"))
        return tuple(review.findings[0])  # type: ignore[union-attr, return-value]

    assert first(_ATLAS / "1.9c.review-r1.md") == ("major", "dryrun")
    assert first(_K0 / "1.2.review-r1.md") == ("major", "design")

    # порядок пунктов — порядок строк файла (малые отчёты, порядок выписан по файлам)
    small = {
        _ATLAS / "1.9c.review-r2.md": [("major", "dryrun"), ("minor", "dryrun"), ("minor", "dryrun"), ("nit", "form")],
        _ATLAS / "1.9c.review-code-r2.md": [("blocker", "design"), ("nit", "design"), ("nit", "scope")],
        _K0 / "1.1.review-r2.md": [
            ("minor", "fact"),
            ("minor", "dryrun"),
            ("minor", "context"),
            ("minor", "form"),
            ("nit", "fact"),
        ],
    }
    for path, order in small.items():
        review, _ = review_form.parse(path.read_text(encoding="utf-8"))
        assert review is not None and [tuple(p) for p in review.findings] == order, path.name

    # пример шаблона: те же поля, кортежи, порядок пунктов
    review, errors = review_form.parse(_join(_example_lines()))
    assert errors == []
    assert review is not None
    assert review.verdict == "CHANGES REQUESTED"
    assert isinstance(review.severities, tuple) and review.severities == (0, 2, 1, 1)
    assert isinstance(review.classes, tuple) and review.classes == (1, 1, 0, 1, 1, 0, 0)
    assert isinstance(review.findings, tuple)
    assert [tuple(p) for p in review.findings] == [
        ("major", "dryrun"),
        ("major", "design"),
        ("minor", "context"),
        ("nit", "fact"),
    ]

    # экспресс-ревью teamlead — не по §5 (`VERDICT:`, `## Находки`, пункты `- [blocker]` без класса)
    express, express_errors = review_form.parse(
        (_ATLAS / "1.9c.review-express-teamlead.md").read_text(encoding="utf-8")
    )
    assert express is None
    assert isinstance(express_errors, list) and len(express_errors) >= 1


def test_review_form_violations() -> None:
    from scripts.atlas import review_form

    base = _example_lines()
    assert review_form.parse(_join(base))[1] == [], "исходный пример шаблона должен быть без нарушений"
    last_bullet = max(i for i, ln in enumerate(base) if ln.startswith("- [nit/fact]"))
    after = last_bullet + 1  # индекс (с 0) вставки сразу после последнего пункта; номер строки вставки = after + 1
    open_idx = base.index(_REQUIRED_SECTION)
    assert base[-1].startswith("- "), "последняя строка примера — пункт раздела «Что я оставил…»"

    def put(index: int, new: str) -> list[str]:
        return base[:index] + [new] + base[index:]

    def swap(index: int, new: str) -> list[str]:
        return base[:index] + [new] + base[index + 1 :]

    # (метка, строки, номер строки, который должен назвать текст нарушения, либо None — номер не требуется)
    cases: list[tuple[str, list[str], int | None]] = [
        ("вердикт с лишним словом", swap(1, "Вердикт: CHANGES REQUESTED сейчас"), 2),
        ("Итог: blocker 1 при 0 пунктов blocker", swap(2, "Итог: blocker 1, major 2, minor 1, nit 1"), None),
        ("восьмой класс в строке 4", swap(3, base[3] + ", other 0"), 4),
        (
            "Классы: fact 2 при одном пункте fact",
            swap(3, "Классы: fact 2, dryrun 1, form 0, context 1, design 1, scope 0, process 0"),
            None,
        ),
        ("пункт с отступом", put(after, "  - [major/fact] x"), after + 1),
        ("пункт без класса", put(after, "- [major] без класса"), after + 1),
        ("класс вне словаря", put(after, "- [major/other] x"), after + 1),
        ("заголовок «Замечания р.1»", swap(base.index("## Замечания"), "## Замечания р.1"), None),
        ("пустой раздел «Что я оставил…»", base[:-1], None),
        ("нет раздела «Что я оставил…»", base[: open_idx - 1], None),
        ("три строки", base[:3], None),
        ("заголовок «Ревью» с заглавной", swap(0, "# 1.2 — Ревью стадии 0, раунд 1"), None),
    ]
    problems: list[str] = []
    for label, lines, want_line in cases:
        review, errors = review_form.parse(_join(lines))
        if review is not None or not errors:
            problems.append(
                f"{label}: ожидалось (None, [нарушения]), получено review={review is not None}, errors={errors}"
            )
            continue
        if want_line is not None and not any(re.search(rf"строка {want_line}(?!\d)", e) for e in errors):
            problems.append(f"{label}: ни одна строка нарушения не называет «строка {want_line}»: {errors}")
    assert not problems, "\n".join(problems)

    # парный положительный случай: добавлен пункт, Итог и Классы обновлены — нарушений нет
    lines = put(after, "- [nit/form] x")
    lines[2] = "Итог: blocker 0, major 2, minor 1, nit 2"
    lines[3] = "Классы: fact 1, dryrun 1, form 1, context 1, design 1, scope 0, process 0"
    review, errors = review_form.parse(_join(lines))
    assert errors == []
    assert review is not None
    assert tuple(review.severities) == (0, 2, 1, 2)
    assert tuple(review.classes) == (1, 1, 1, 1, 1, 0, 0)
    assert len(review.findings) == 5
    assert tuple(review.findings[-1]) == ("nit", "form")


def test_review_form_crlf_same_as_lf() -> None:
    from scripts.atlas import review_form

    lf_text = _join(_example_lines())
    assert "\r" not in lf_text
    crlf_text = lf_text.replace("\n", "\r\n")
    assert crlf_text.count("\r\n") == lf_text.count("\n")
    lf_review, lf_errors = review_form.parse(lf_text)
    crlf_review, crlf_errors = review_form.parse(crlf_text)
    assert lf_errors == [] and crlf_errors == []
    assert lf_review is not None and crlf_review is not None
    assert _fields(crlf_review) == _fields(lf_review)
    assert _fields(crlf_review)[1] == (0, 2, 1, 1)


# --- metrics: живые файлы ---------------------------------------------------------------------------------------


def test_metrics_live_k0_literals(cli: Cli) -> None:
    code, out, _ = cli(_ROOT, "metrics", "k0-framework-quality#1.2")
    assert code == 0, out
    header, rows = _table(out)
    assert header == ["метрика", "k0-framework-quality#1.2"]
    assert rows["M2 blocker+major р.1 по классам"] == ["major dryrun 2, form 1, context 1, design 2"]
    assert rows["M2 из них fact+dryrun+form"] == ["3"]
    assert rows["M3 раундов до APPROVED"] == ["нет (раундов 1)"]
    assert rows["M1 доля фактов Атласа"] == ["—"]
    assert out.splitlines()[-1] == _LAST_LINE

    code, out, _ = cli(_ROOT, "metrics", "k0-framework-quality#1.1")
    assert code == 0, out
    header, rows = _table(out)
    assert header == ["метрика", "k0-framework-quality#1.1"]
    assert rows["M2 blocker+major р.1 по классам"] == ["blocker dryrun 1; major fact 1, dryrun 2"]
    assert rows["M2 из них fact+dryrun+form"] == ["4"]
    assert rows["M3 раундов до APPROVED"] == ["2"]

    # две колонки одним вызовом: голый slug — все задачи плана с tasks/<id>.md (1.1, 1.2; 1.3.result.md — не задача)
    code, out, _ = cli(_ROOT, "metrics", "k0-framework-quality")
    assert code == 0, out
    header, rows = _table(out)
    assert header == ["метрика", "k0-framework-quality#1.1", "k0-framework-quality#1.2"]
    assert rows["M2 blocker+major р.1 по классам"] == [
        "blocker dryrun 1; major fact 1, dryrun 2",
        "major dryrun 2, form 1, context 1, design 2",
    ]
    assert rows["M2 из них fact+dryrun+form"] == ["4", "3"]
    assert rows["M3 раундов до APPROVED"] == ["2", "нет (раундов 1)"]
    assert out.splitlines()[-1] == _LAST_LINE

    # atlas#1.9c: r1 и r2 — CHANGES REQUESTED; review-code-* и express-teamlead не читаются; число M4 живое — не сверяем
    code, out, _ = cli(_ROOT, "metrics", "atlas#1.9c")
    _, rows = _table(out)
    assert rows["M2 blocker+major р.1 по классам"] == ["major dryrun 3, context 1, design 3"]
    assert rows["M2 из них fact+dryrun+form"] == ["3"]
    assert rows["M3 раундов до APPROVED"] == ["нет (раундов 2)"]
    assert out.splitlines()[-1] == _LAST_LINE


# --- metrics: M1 ------------------------------------------------------------------------------------------------

_ATLAS_FACT = "- проверка — `python -m scripts.atlas card m` → exit 0"
_OTHER_FACT = "- факт — `git grep -n x` → `1`"
_TRAP_FACT = "- вызов `python -m scripts.atlas card` описан — `git grep -n card` → `3`"
_UV_FACT = "- через uv — `uv run python -m scripts.atlas card m` → exit 0"


def _brief(lines: list[str], *, close: bool = True, after: str = "") -> str:
    block = ["<!-- atlas:facts abc1234 -->", *lines]
    if close:
        block.append("<!-- /atlas:facts -->")
    return "# Task X — проба\n\nTASK: X\nFACTS:\n" + "\n".join(block) + "\n" + after


def test_metrics_m1_share(repo: GitRepo, cli: Cli) -> None:
    _make_plan(repo, "probe")
    base = "plans/probe/tasks"
    briefs: dict[str, tuple[str, str]] = {
        "1.1": (_brief([_ATLAS_FACT, _ATLAS_FACT.replace("card m", "ref x"), _TRAP_FACT]), "67% (2/3)"),
        "1.2": (_brief([_ATLAS_FACT, _UV_FACT, *([_OTHER_FACT] * 6)]), "13% (1/8)"),
        "1.3": (_brief([_OTHER_FACT, _OTHER_FACT]), "0% (0/2)"),
        "1.4": ("# Task 1.4 — без блока\n\nTASK: 1.4\nFACTS:\n" + _ATLAS_FACT + "\n", "—"),
        "1.5": (_brief([_ATLAS_FACT, _ATLAS_FACT], close=False), "—"),
        "1.6": (
            _brief(
                [
                    "- строка без команды вообще",
                    "  - вложенная — `python -m scripts.atlas ref x` → `1`",
                    "- ещё — `git log` → `2`",
                    "- ok — `python -m scripts.atlas card y` → `3`",
                ]
            ),
            "50% (2/4)",
        ),
        "1.7": (_brief([_ATLAS_FACT] * 5 + [_OTHER_FACT] * 3), "63% (5/8)"),
        "1.8": (
            _brief(
                [
                    "Пояснение к блоку: python -m scripts.atlas card z",
                    "",
                    "- a — `python -m scripts.atlas card a` → `1`",
                    "- b — `git status` → `2`",
                ]
            ),
            "50% (1/2)",
        ),
        "1.9": (
            _brief(
                [_OTHER_FACT, _OTHER_FACT],
                after="ACCEPTANCE:\n- команда — `python -m scripts.atlas check` → exit 0\n",
            ),
            "0% (0/2)",
        ),
        # блок только в брифе роли, в главном брифе блока нет
        "2.1": ("# Task 2.1 — главный бриф без блока\n\nTASK: 2.1\n", "—"),
    }
    for task_id, (text, _) in briefs.items():
        _put(repo, f"{base}/{task_id}.md", text)
    _put(repo, f"{base}/2.1.tester.md", "# 2.1 — бриф tester\n\n" + _brief([_ATLAS_FACT, _ATLAS_FACT]))

    ids = list(briefs)
    code, out, _ = cli(repo.path, "metrics", *[f"probe#{i}" for i in ids])
    assert code == 0, out
    header, rows = _table(out)
    assert header == ["метрика", *[f"probe#{i}" for i in ids]]
    got = dict(zip(ids, rows["M1 доля фактов Атласа"]))
    want = {i: expected for i, (_, expected) in briefs.items()}
    assert got == want


# --- metrics: M2 ------------------------------------------------------------------------------------------------


def test_metrics_m2_classes_and_sums(repo: GitRepo, cli: Cli) -> None:
    ids = ("1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7")
    base = _make_plan(repo, "probe", ids)
    reports = f"{base}/reports"
    # id -> (отчёт r1 или None, M2, M2 из них)
    cases: dict[str, tuple[list[tuple[str, str]] | None, str, str]] = {
        "1.1": (
            [
                ("blocker", "design"),
                ("major", "dryrun"),
                ("major", "dryrun"),
                ("major", "form"),
                ("minor", "fact"),
                ("nit", "context"),
            ],
            "blocker design 1; major dryrun 2, form 1",
            "3",
        ),
        "1.2": (
            [("major", "process"), ("major", "fact"), ("major", "fact"), ("minor", "dryrun")],
            "major fact 2, process 1",
            "2",
        ),
        "1.3": ([("minor", "fact"), ("nit", "form")], "0", "0"),
        "1.4": (None, "—", "—"),
        "1.5": ([("major", "form")], "major form 1", "1"),
        "1.6": (
            [
                ("blocker", "scope"),
                ("blocker", "context"),
                ("major", "process"),
                ("major", "design"),
                ("major", "context"),
                ("major", "fact"),
            ],
            "blocker context 1, scope 1; major fact 1, context 1, design 1, process 1",
            "1",
        ),
        "1.7": ([("blocker", "fact")], "blocker fact 1", "1"),
    }
    for task_id, (findings, _, _) in cases.items():
        if findings is not None:
            _put(repo, f"{reports}/{task_id}.review-r1.md", _report(findings, task=task_id))
    # r2 с другими классами не влияет на M2 (у 1.5 — только на M3); у 1.4 r1 нет, есть r2 -> «—»
    _put(repo, f"{reports}/1.5.review-r2.md", _report([("major", "fact")] * 3, task="1.5", rnd=2))
    _put(repo, f"{reports}/1.4.review-r2.md", _report([("blocker", "fact")], task="1.4", rnd=2))

    code, out, _ = cli(repo.path, "metrics", *[f"probe#{i}" for i in ids])
    assert code == 0, out
    _, rows = _table(out)
    assert dict(zip(ids, rows["M2 blocker+major р.1 по классам"])) == {i: c[1] for i, c in cases.items()}
    assert dict(zip(ids, rows["M2 из них fact+dryrun+form"])) == {i: c[2] for i, c in cases.items()}


# --- metrics: M3 ------------------------------------------------------------------------------------------------


def test_metrics_m3_rounds(repo: GitRepo, cli: Cli) -> None:
    ids = ("2.1", "2.2", "2.3", "2.4", "2.5", "1.1", "2.6", "2.7", "2.8")
    base = _make_plan(repo, "probe", ids)
    reports = f"{base}/reports"
    nit = [("nit", "form")]

    def rep(name: str, verdict: str, task: str, rnd: int, text: str | None = None) -> None:
        _put(repo, f"{reports}/{name}", text if text is not None else _report(nit, verdict, task=task, rnd=rnd))

    rep("2.1.review-r1.md", "CHANGES REQUESTED", "2.1", 1)
    rep("2.1.review-r2.md", "APPROVED", "2.1", 2)
    rep("2.2.review-r1.md", "APPROVED", "2.2", 1)
    rep("2.3.review-r1.md", "CHANGES REQUESTED", "2.3", 1)
    rep("2.3.review-r2.md", "CHANGES REQUESTED", "2.3", 2)
    # 2.4 — отчётов нет
    rep("2.5.review-r1.md", "CHANGES REQUESTED", "2.5", 1)
    rep("2.5.review-r2.md", "CHANGES REQUESTED", "2.5", 2)
    rep("2.5.review-r9.md", "APPROVED", "2.5", 9)
    rep("2.5.review-r10.md", "APPROVED", "2.5", 10)
    # префикс id: 1.10 не читается как 1.1
    rep("1.1.review-r1.md", "CHANGES REQUESTED", "1.1", 1)
    rep("1.10.review-r1.md", "APPROVED", "1.10", 1)
    # review-code-r<N> не читается
    rep("2.6.review-r1.md", "CHANGES REQUESTED", "2.6", 1)
    rep("2.6.review-code-r1.md", "APPROVED", "2.6", 1)
    # один отчёт с нарушением -> «?»
    rep("2.7.review-r1.md", "CHANGES REQUESTED", "2.7", 1, _broken_report())
    # нарушение в отчёте r2 перекрывает APPROVED в r1
    rep("2.8.review-r1.md", "APPROVED", "2.8", 1)
    rep("2.8.review-r2.md", "CHANGES REQUESTED", "2.8", 2, _broken_report())

    want = {
        "2.1": "2",
        "2.2": "1",
        "2.3": "нет (раундов 2)",
        "2.4": "—",
        "2.5": "9",
        "1.1": "нет (раундов 1)",
        "2.6": "нет (раундов 1)",
        "2.7": "?",
        "2.8": "?",
    }
    code, out, _ = cli(repo.path, "metrics", *[f"probe#{i}" for i in ids])
    _, rows = _table(out)
    assert dict(zip(ids, rows["M3 раундов до APPROVED"])) == want
    assert code == 1, "в таблице есть «?» — код должен быть 1"


# --- metrics: M4 ------------------------------------------------------------------------------------------------


def _m4_history(repo: GitRepo) -> tuple[str, str]:
    """Настоящие коммиты; вернуть (полный хеш DONE-коммита задачи 1.1, полный хеш коммита с трейлером probe#1.10)."""

    def commit(name: str, message: str) -> str:
        _put(repo, f"files/{name}.txt", name + "\n")
        return repo.commit(message)

    commit("init", "chore: init")
    commit("before", "feat: до DONE\n\nTask: probe#1.1")
    done = commit("done", "feat: сам DONE-коммит\n\nTask: probe#1.1")
    commit("docs", "docs(plans): запись в плане\n\nTask: probe#1.1")
    commit("fix", "fix(core): правка\n\nTask: probe#1.1")
    commit("brk", "feat!: ломающая правка\n\nTask: probe#1.1")
    other = commit("other", "fix: чужая задача\n\nTask: probe#1.10")
    commit("plain", "fix: без трейлера")
    repo.git("checkout", "-q", "-b", "side")
    commit("side", "fix: работа в ветке")
    repo.git("checkout", "-q", "main")
    commit("main2", "chore: main ушёл вперёд")
    repo.git("merge", "--no-ff", "-q", "side", "-m", "merge: ветка side\n\nTask: probe#1.1")
    return done, other


def test_metrics_m4_after_done(repo: GitRepo, cli: Cli) -> None:
    done, other = _m4_history(repo)
    assert len(done) == 40 and len(other) == 40 and done != other
    plan_dir = "plans/2026-10-11_probe"
    for task_id in ("1.1", "1.10", "1.2"):
        _put(repo, f"{plan_dir}/tasks/{task_id}.md", f"# Task {task_id} — проба\n\nTASK: {task_id}\n")

    def plan(*lines: str) -> None:
        _put(repo, f"{plan_dir}/plan.md", "# План\n\n" + "\n".join(lines) + "\n")

    good = f"3 (не docs 2) после {done[:7]}"
    # (метка, строки плана, ожидаемая ячейка M4 колонки probe#1.1, код выхода)
    cases: list[tuple[str, list[str], str, int]] = [
        ("хеш в обратных кавычках", [f"- Task 1.1: описание [DONE 2026-10-11 — `{done}`, PR #5]"], good, 0),
        ("хеш в кавычках сокращён до 9 знаков", [f"- Task 1.1: описание [DONE 2026-10-11 — `{done[:9]}`]"], good, 0),
        ("голый хеш из 40 знаков", [f"- Task 1.1: описание [DONE 2026-10-11 — слияние {done}]"], good, 0),
        (
            "PR #1234567 и дата не хеши — берётся хеш",
            [f"- Task 1.1: описание [DONE 2026-10-11 — PR #1234567 2026-10-11, слияние {done}]"],
            good,
            0,
        ),
        (
            "хеш-подобное вне группы DONE игнорируется",
            [f"- Task 1.1: описание `deadbeef1` с хвостом [DONE 2026-10-11 — `{done}`]"],
            good,
            0,
        ),
        ("PENDING", ["- Task 1.1: описание [PENDING]"], "—", 0),
        ("хеш в группе PENDING", [f"- Task 1.1: описание [PENDING — `{done}`]"], "—", 0),
        ("DONE без хеша", ["- Task 1.1: описание [DONE 2026-10-11 — закрыто без слияния]"], "— (DONE без хеша)", 0),
        ("нет строки задачи", [f"- Task 1.2: другая задача [DONE 2026-10-11 — `{done}`]"], "—", 0),
        ("есть только строка 1.10", [f"- Task 1.10: другая задача [DONE 2026-10-11 — `{done}`]"], "—", 0),
        ("хеш, не являющийся коммитом", ["- Task 1.1: описание [DONE 2026-10-11 — `deadbeef1`]"], "?", 1),
    ]
    problems: list[str] = []
    for label, lines, want, want_code in cases:
        plan(*lines)
        code, out, _ = cli(repo.path, "metrics", "probe#1.1")
        _, rows = _table(out)
        if rows["M4 коммитов после DONE"] != [want] or code != want_code:
            problems.append(
                f"{label}: ячейка {rows['M4 коммитов после DONE']} код {code}, ожидалось [{want!r}] код {want_code}"
            )
        if want == "?" and not any(ln.startswith("  ") and "хеш DONE deadbeef1" in ln for ln in out.splitlines()):
            problems.append(f"{label}: нет строки нарушения с текстом «хеш DONE deadbeef1»: {out!r}")
    assert not problems, "\n".join(problems)

    # `- Task 1.10:` не путается с `1.1` в обе стороны; у 1.10 DONE — коммит probe#1.10, после него трейлеров нет
    plan(
        f"- Task 1.10: другая [DONE 2026-10-11 — `{other}`]",
        f"- Task 1.1: описание [DONE 2026-10-11 — `{done}`]",
    )
    code, out, _ = cli(repo.path, "metrics", "probe#1.1", "probe#1.10")
    header, rows = _table(out)
    assert header == ["метрика", "probe#1.1", "probe#1.10"]
    assert rows["M4 коммитов после DONE"] == [good, f"0 (не docs 0) после {other[:7]}"]
    assert code == 0


# --- metrics: поиск плана, колонки, метки -----------------------------------------------------------------------


def test_metrics_plan_lookup_and_columns(repo: GitRepo, cli: Cli) -> None:
    # план без даты, голый slug: колонки в натуральном порядке, служебные файлы — не задачи
    base = _make_plan(repo, "T2.3", ("1.10", "1.2"))
    for extra in (
        "1.2.tester.md",
        "1.2.result.md",
        "1.2.injections.md",
        "1.2.injections.json",
        "1.10.injections.md",
        "notes.md",
    ):
        _put(repo, f"{base}/tasks/{extra}", "служебный файл\n")
    code, out, _ = cli(repo.path, "metrics", "T2.3")
    assert code == 0, out
    assert "\r" not in out
    header, _ = _table(out)
    assert header == ["метрика", "T2.3#1.2", "T2.3#1.10"]
    assert "база" not in out and "сейчас" not in out, "без --base меток нет"
    assert out.splitlines()[-1] == _LAST_LINE

    # план с датой
    _make_plan(repo, "dated", ("1.1",), prefix="2026-10-11_")
    for spec in ("dated#1.1", "dated"):
        code, out, _ = cli(repo.path, "metrics", spec)
        assert code == 0, out
        assert _table(out)[0] == ["метрика", "dated#1.1"]

    # метки: --base идут первыми в порядке указания, остальные — «сейчас»; --base после spec и до spec
    for name in ("a", "b", "c"):
        _make_plan(repo, name, ("1.1",))
    code, out, _ = cli(repo.path, "metrics", "c#1.1", "--base", "a#1.1", "--base", "b#1.1")
    assert code == 0, out
    assert _table(out)[0] == ["метрика", "база a#1.1", "база b#1.1", "сейчас c#1.1"]
    code, out, _ = cli(repo.path, "metrics", "c#1.1", "--base", "b#1.1", "--base", "a#1.1")
    assert _table(out)[0] == ["метрика", "база b#1.1", "база a#1.1", "сейчас c#1.1"]
    code, out, _ = cli(repo.path, "metrics", "--base", "a#1.1", "c#1.1")
    assert code == 0, out
    assert _table(out)[0] == ["метрика", "база a#1.1", "сейчас c#1.1"], (
        "значение --base одно, следующий spec — «сейчас»"
    )
    code, out, _ = cli(repo.path, "metrics", "--base", "a#1.1")
    assert code == 0, out
    assert _table(out)[0] == ["метрика", "база a#1.1"]
    assert out.splitlines()[-1] == _LAST_LINE

    # ошибки вызова — код 2 (после положительных проверок выше: «подкоманды нет» дало бы тот же код)
    _make_plan(repo, "dup", ("1.1",))
    _make_plan(repo, "dup", ("1.1",), prefix="2026-10-11_")
    errors = [
        ("два плана с одним slug", ("dup#1.1",)),
        ("нет плана", ("nonesuch#1.1",)),
        ("неизвестная задача", ("T2.3#9.9",)),
        ("нет spec", ()),
        ("--ref не принимается", ("T2.3#1.2", "--ref", "x")),
    ]
    problems: list[str] = []
    for label, args in errors:
        code, out, err = cli(repo.path, "metrics", *args)
        if code != 2:
            problems.append(f"{label}: код {code}, ожидалось 2 (stdout {out[:80]!r}, stderr {err[:120]!r})")
    assert not problems, "\n".join(problems)


# --- metrics: нарушения и код выхода ----------------------------------------------------------------------------


def test_metrics_violations_exit_code(repo: GitRepo, cli: Cli) -> None:
    # нарушение в r1: «?» в M2, обеих строках и M3, одна строка в блоке (один отчёт читают M2 и M3), код 1
    base = _make_plan(repo, "viol", ("1.1",))
    _put(repo, f"{base}/reports/1.1.review-r1.md", _broken_report())
    code, out, _ = cli(repo.path, "metrics", "viol#1.1")
    assert code == 1, out
    _, rows = _table(out)
    assert rows["M2 blocker+major р.1 по классам"] == ["?"]
    assert rows["M2 из них fact+dryrun+form"] == ["?"]
    assert rows["M3 раундов до APPROVED"] == ["?"]
    lines = out.splitlines()
    assert lines[-1] == _LAST_LINE
    head = lines.index("нарушения формы (1):")
    assert lines[head - 1] == "", "перед блоком — пустая строка"
    assert head < len(lines) - 1
    block = [ln for ln in lines[head + 1 : -1] if ln.strip()]
    assert len(block) == 1, f"одно и то же нарушение печатается один раз: {block}"
    assert block[0].startswith("  plans/viol/reports/1.1.review-r1.md: "), block[0]
    assert re.search(r"строка 2(?!\d)", block[0]), block[0]

    # без нарушений — код 0 и блока нет
    ok_base = _make_plan(repo, "fine", ("1.1",))
    _put(repo, f"{ok_base}/reports/1.1.review-r1.md", _report([("nit", "form")], "APPROVED"))
    code, out, _ = cli(repo.path, "metrics", "fine#1.1")
    assert code == 0, out
    assert "нарушения формы" not in out
    assert out.splitlines()[-1] == _LAST_LINE

    # плохой хеш DONE — код 1 (на коммите истории; репозиторию нужен хотя бы один коммит)
    _put(repo, "seed.txt", "seed\n")
    repo.commit("chore: seed")
    bad_base = _make_plan(
        repo,
        "badhash",
        ("1.1",),
        plan_text="# План\n\n- Task 1.1: описание [DONE 2026-10-11 — `deadbeef1`]\n",
    )
    assert bad_base == "plans/badhash"
    code, out, _ = cli(repo.path, "metrics", "badhash#1.1")
    assert code == 1, out
    assert "хеш DONE deadbeef1" in out

    # нет плана — код 2
    code, _, _ = cli(repo.path, "metrics", "nonesuch#1.1")
    assert code == 2
