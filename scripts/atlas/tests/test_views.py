"""Приёмочные тесты видов `card`, `pack`, `log` (Task 1.6, RED до кода).

Purpose: вывод видов на временных репозиториях с заданными датами (рецепты Ф1-Ф5 брифа), ленивая сборка,
    формы CLI и тексты ошибок, импорт шаблона id задачи из валидатора коммитов.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Ожидаемые значения — литералы из раздела «Эталонные выводы» брифа; SHA — только `repo.commit(...)` / `repo.head`.
Весь stdout сравнивается списком строк (`splitlines()`), stderr — строкой с `\\n` в конце. Каталог `data/`
временных репозиториев исключён через .git/info/exclude. Все вызовы git и main() идут через дедлайн conftest.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas.tests.conftest import FixedAdapter, GitRepo, RepoFactory

__all__: list[str] = []

_REFS = ("--ref", "main", "--main-ref", "main")


def _new_repo(factory: RepoFactory, name: str) -> GitRepo:
    repo = factory.create(name)
    exclude = repo.path / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("data/\n", encoding="utf-8")
    return repo


def _plan(*rows: str) -> str:
    return "# Alpha\n\n## Порядок выполнения\n\n" + "".join(f"- Task {row}\n" for row in rows)


def _modules(rows: list[tuple[str, list[str], str | None, list[str]]]) -> str:
    """rows: (id, paths, tier или None, docs); layer у всех модулей — см. _LAYERS (по умолчанию scripts)."""
    text = "version: 1\nmodules:\n"
    for module_id, paths, tier, docs in rows:
        layer = _LAYERS.get(module_id, "scripts")
        text += (
            f"  - id: {module_id}\n    paths: {json.dumps(paths)}\n    layer: {layer}\n"
            f"    tier: {tier or 'null'}\n    docs: {json.dumps(docs)}\n    parent: null\n"
        )
    return text


_LAYERS = {"m": "framework"}


def _env(mp: pytest.MonkeyPatch, stamp: str) -> None:
    full = stamp if "T" in stamp else f"{stamp}T10:00:00+0000"
    mp.setenv("GIT_AUTHOR_DATE", full)
    mp.setenv("GIT_COMMITTER_DATE", full)


def _commit(repo: GitRepo, mp: pytest.MonkeyPatch, stamp: str, subject: str, *trailers: str) -> str:
    _env(mp, stamp)
    message = subject + ("\n\n" + "\n".join(trailers) if trailers else "")
    return repo.commit(message)


def _merge(repo: GitRepo, mp: pytest.MonkeyPatch, stamp: str, branch: str, message: str) -> str:
    _env(mp, stamp)
    repo.git("checkout", "-q", "main")
    repo.git("merge", "-q", "--no-ff", "-m", message, branch)
    return repo.head


def _s7(sha: str) -> str:
    return sha[:7]


def _lines(res: Any) -> list[str]:
    assert res.code == 0, res.err
    assert res.err == ""
    return res.out.splitlines()


# ---------------------------------------------------------------- Ф1


def _f1_repo(factory: RepoFactory, mp: pytest.MonkeyPatch, name: str = "f1") -> tuple[GitRepo, dict[str, str]]:
    repo = _new_repo(factory, name)
    shas: dict[str, str] = {}
    repo.write("modules.yaml", _modules([("m", ["m/"], "core", ["m/README.md"]), ("n", ["n/"], None, [])]))
    repo.write("m/README.md", "# m\n\nПервая строка назначения модуля m.\nВторая строка.\n")
    repo.write(
        "m/interfaces.py",
        '__all__ = ["Beta", "Alpha"]\n\n\nclass Alpha:\n    pass\n\n\nclass Beta:\n    pass\n',
    )
    repo.write("m/tests/test_m.py", "from m.interfaces import Alpha\n\n\ndef test_a():\n    Alpha()\n")
    repo.write(
        "plans/2026-10-01_alpha/plan.md",
        _plan(
            "1.1: first [DONE 2026-10-01]",
            "1.2: second [PENDING]",
            "1.3: third [IN PROGRESS]",
            "1.4: fourth [BLOCKED]",
            "1.5: fifth [DEFERRED]",
            "1.6: sixth [SUPERSEDED]",
            "1.10: tenth [PENDING]",
        ),
    )
    repo.write("plans/2026-10-02_beta/plan.md", _plan("1.1: b-first [PENDING]"))
    repo.write("plans/2026-10-03_gamma/plan.md", _plan("1.1: g [DONE 2026-10-01]"))
    shas["init"] = _commit(repo, mp, "2026-10-01", "init")
    rows = [
        ("c2", "m/a.py", "2026-10-02", "m: a", ("Refs: plans/2026-10-01_alpha/plan.md", "Task: alpha#1.1")),
        ("c3", "m/b.py", "2026-10-03", "m: b", ("Task: beta#1.1",)),
        ("c4", "m/c.py", "2026-10-04", "m: c", ("Refs: plans/2026-10-02_beta/plan.md",)),
        ("c5", "n/z.py", "2026-10-05", "n: z", ("Refs: plans/2026-10-03_gamma/plan.md",)),
        ("c6", "m/d.py", "2026-10-06", "m: d", ("Refs: plans/2026-10-03_gamma/plan.md",)),
        ("c7", "m/e.py", "2026-10-07", "m: e", ()),
        ("c8", "m/f.py", "2026-10-08", "m: f — " + "очень длинная тема " * 8, ()),
    ]
    for key, path, day, subject, trailers in rows:
        repo.write(path, "x = 1\n")
        shas[key] = _commit(repo, mp, day, subject.rstrip(), *trailers)
    return repo, shas


def _f1_expected(shas: dict[str, str]) -> list[str]:
    return [
        "Модуль m — framework, ярус core",
        "Назначение: Первая строка назначения модуля m.",
        "API (2): Alpha, Beta",
        "Открытые задачи (2 планов, 5 задач):",
        "  beta — 1: 1.1",
        "  alpha — 4: 1.2, 1.3, 1.4, 1.10",
        "Коммиты (7 всего, последние 5):",
        f"  {_s7(shas['c8'])} 2026-10-08 m: f — очень длинная тема очень длинная тема очень длинная тема"
        " очень длинная тема очень …",
        f"  {_s7(shas['c7'])} 2026-10-07 m: e",
        f"  {_s7(shas['c6'])} 2026-10-06 m: d",
        f"  {_s7(shas['c4'])} 2026-10-04 m: c",
        f"  {_s7(shas['c3'])} 2026-10-03 m: b",
        "Находки (1):",
        "  info INTERFACE_WITHOUT_TEST interface:m:Beta -",
    ]


def test_card_shape_links_and_order(repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, shas = _f1_repo(repo_factory, monkeypatch)
    first = _lines(atlas(repo, "card", "m", *_REFS))
    assert first == _f1_expected(shas)
    assert _lines(atlas(repo, "card", "m", *_REFS)) == first


# ---------------------------------------------------------------- Ф2

_EMPTY_CARD = [
    "Модуль {id} — scripts, ярус —",
    "Назначение: нет README в docs: modules.yaml",
    "API (0): —",
    "Открытые задачи: нет",
    "Коммиты (0 всего, последние 0):",
    "Находки (0):",
]


def _f2_repo(factory: RepoFactory, mp: pytest.MonkeyPatch, name: str) -> tuple[GitRepo, dict[str, str]]:
    repo = _new_repo(factory, name)
    shas: dict[str, str] = {}
    repo.write(
        "modules.yaml",
        _modules(
            [
                ("a_b", ["a_b/"], None, []),
                ("axb", ["axb/"], None, []),
                ("big", ["big/"], None, ["big/README.md"]),
                ("ghost", ["ghost/"], None, ["ghost/README.md"]),
                ("idle", ["idle/"], None, []),
            ]
        ),
    )
    repo.write("a_b/interfaces.py", '__all__ = ["P"]\n\n\nclass P:\n    pass\n')
    repo.write("axb/interfaces.py", '__all__ = ["Q"]\n\n\nclass Q:\n    pass\n')
    names = [f"N{i:02d}" for i in range(1, 23)]
    repo.write(
        "big/interfaces.py",
        "__all__ = " + json.dumps(names) + "\n\n\n" + "\n\n".join(f"class {n}:\n    pass" for n in names) + "\n",
    )
    readme = [
        "# big", "", "[![ci](x)](y)", "", "> цитата", "", "---", "", "- пункт списка", "", "| a | b |", "",
        "```", "code", "```", "", "Настоящее назначение " + "я" * 200,
    ]  # fmt: skip
    repo.write("big/README.md", "\n".join(readme) + "\n")
    for i in range(1, 7):
        rows = [f"1.{k}: t{k} [PENDING]" for k in range(1, 8)] if i == 1 else ["1.1: t [PENDING]"]
        repo.write(f"plans/2026-10-0{i}_p{i}/plan.md", _plan(*rows))
    shas["init"] = _commit(repo, mp, "2026-10-01", "init")
    for i in range(1, 7):
        repo.write(f"big/f{i}.py", "x\n")
        shas[f"f{i}"] = _commit(repo, mp, f"2026-10-0{i + 1}", f"big f{i}", f"Refs: plans/2026-10-0{i}_p{i}/plan.md")
    return repo, shas


def test_card_edges_caps_and_unknown_kinds(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch, set_adapters: Any
) -> None:
    repo, shas = _f2_repo(repo_factory, monkeypatch, "f2")
    assert _lines(atlas(repo, "card", "a_b", *_REFS)) == [
        "Модуль a_b — scripts, ярус —",
        "Назначение: нет README в docs: modules.yaml",
        "API (1): P",
        "Открытые задачи: нет",
        "Коммиты (1 всего, последние 1):",
        f"  {_s7(shas['init'])} 2026-10-01 init",
        "Находки (1):",
        "  info INTERFACE_WITHOUT_TEST interface:a_b:P -",
    ]
    assert "API (1): Q" in _lines(atlas(repo, "card", "axb", *_REFS))
    assert _lines(atlas(repo, "card", "big", *_REFS)) == [
        "Модуль big — scripts, ярус —",
        "Назначение: Настоящее назначение " + "я" * 138 + "…",
        "API (22): " + ", ".join(f"N{i:02d}" for i in range(1, 21)) + ", … ещё 2",
        "Открытые задачи (6 планов, 12 задач):",
        "  p1 — 7: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, … ещё 1",
        "  p2 — 1: 1.1",
        "  p3 — 1: 1.1",
        "  p4 — 1: 1.1",
        "  p5 — 1: 1.1",
        "  … ещё 1 планов",
        "Коммиты (7 всего, последние 5):",
        f"  {_s7(shas['f6'])} 2026-10-07 big f6",
        f"  {_s7(shas['f5'])} 2026-10-06 big f5",
        f"  {_s7(shas['f4'])} 2026-10-05 big f4",
        f"  {_s7(shas['f3'])} 2026-10-04 big f3",
        f"  {_s7(shas['f2'])} 2026-10-03 big f2",
        "Находки (22):",
        *[f"  info INTERFACE_WITHOUT_TEST interface:big:N{i:02d} -" for i in range(1, 11)],
        "  … ещё 12",
    ]
    for name in ("ghost", "idle"):
        assert _lines(atlas(repo, "card", name, *_REFS)) == [line.format(id=name) for line in _EMPTY_CARD]

    from scripts.atlas.build import ADAPTERS
    from scripts.atlas.schema import AdapterOutput, Edge, Finding, Node

    def fixed() -> Any:
        findings = [
            Finding(code, severity, "module:idle", detail, f"{code} on module:idle", "fixed")
            for code, severity, detail in (
                ("FUTURE_CODE", "info", ""),
                ("A_CODE", "blocking", ""),
                ("Z_CODE", "blocking", "d2"),
                ("M_CODE", "warning", ""),
            )
        ]
        return AdapterOutput(
            nodes=[Node(kind="widget", id="w")],
            edges=[Edge("future", "module:idle", "widget:w", "x")],
            findings=findings,
        )

    set_adapters(*ADAPTERS, FixedAdapter(fixed))
    repo2, _ = _f2_repo(repo_factory, monkeypatch, "f2_fixed")
    assert _lines(atlas(repo2, "card", "idle", *_REFS)) == [
        *[line.format(id="idle") for line in _EMPTY_CARD[:5]],
        "Находки (4):",
        "  blocking A_CODE module:idle -",
        "  blocking Z_CODE module:idle d2",
        "  warning M_CODE module:idle -",
        "  info FUTURE_CODE module:idle -",
    ]


# ---------------------------------------------------------------- Ф3


def _f3_repo(factory: RepoFactory, mp: pytest.MonkeyPatch) -> GitRepo:
    repo = _new_repo(factory, "f3")
    repo.write("modules.yaml", _modules([("m", ["m/"], None, []), ("n", ["n/"], None, [])]))
    repo.write(
        "plans/2026-10-01_alpha/plan.md",
        _plan("1.1: a [PENDING]", "1.2: b [PENDING]", "1.3: c [PENDING]", "1.4: d [PENDING]", "1.10: e [PENDING]"),
    )
    repo.write("plans/2026-10-02_beta/plan.md", _plan("1.1: b [PENDING]"))
    repo.write("plans/2026-10-03_other/plan.md", _plan("1.1: o [PENDING]"))
    _commit(repo, mp, "2026-09-30", "init")
    repo.git("checkout", "-q", "-b", "feat")
    for path in ("m/a.py", "n/b.py", "plans/2026-10-01_alpha/tasks/1.1.md"):
        repo.write(path, "x = '2026-10-01'\n")
    _commit(repo, mp, "2026-10-01", "t1", "Task: alpha#1.1")
    for path in ("m/a.py", "m/c.py"):
        repo.write(path, "x = '2026-10-02'\n")
    _commit(repo, mp, "2026-10-02", "t2", "Task: alpha#1.2")
    _merge(repo, mp, "2026-10-02T12:00:00+0000", "feat", "Merge feat")
    repo.write("m/shared.py", "x = '2026-10-03'\n")
    _commit(repo, mp, "2026-10-03", "t3", "Task: alpha#1.2", "Task: alpha#1.3")
    repo.write("n/zzz.py", "x = '2026-10-03'\n")
    _commit(repo, mp, "2026-10-03", "t4", "Task: other#1.1")
    repo.git("rm", "-q", "m/c.py")
    _commit(repo, mp, "2026-10-04", "t5", "Task: alpha#1.2")
    repo.write("m/a.py", "x = '2026-10-05'\n")
    _commit(repo, mp, "2026-10-05", "t6", "Task: alpha#1.10")
    repo.write("plans/2026-10-02_beta/tasks/1.1.md", "x = '2026-10-06'\n")
    _commit(repo, mp, "2026-10-06", "t7", "Task: beta#1.1")
    return repo


def _alpha_head(task: str) -> str:
    return f"Задача alpha#{task} — статус pending, план plans/2026-10-01_alpha/plan.md"


def test_pack_modules_candidates_and_git_source(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _f3_repo(repo_factory, monkeypatch)
    tail = "Хвосты прошлых задач плана (0 задач):"
    m_files = ["Файлы-кандидаты в FILES (2):", "  m/a.py — 1.1, 1.2, 1.10", "  m/shared.py — 1.2, 1.3"]
    assert _lines(atlas(repo, "pack", "alpha#1.2", *_REFS)) == [
        _alpha_head("1.2"), "Модули: m (коммиты задачи)", *m_files, tail,
    ]  # fmt: skip
    assert _lines(atlas(repo, "pack", "alpha#1.4", *_REFS)) == [
        _alpha_head("1.4"), "Модули: m (последняя задача плана с модулями — 1.10)", *m_files, tail,
    ]  # fmt: skip
    assert _lines(atlas(repo, "pack", "alpha#1.4", "--module", "n", *_REFS)) == [
        _alpha_head("1.4"), "Модули: n (--module)", "Файлы-кандидаты в FILES (1):", "  n/b.py — 1.1", tail,
    ]  # fmt: skip
    assert _lines(atlas(repo, "pack", "beta#1.1", *_REFS)) == [
        "Задача beta#1.1 — статус pending, план plans/2026-10-02_beta/plan.md",
        "Модули: — (у плана нет коммитов с модулями)",
        "Файлы-кандидаты в FILES (0):",
        tail,
    ]


# ---------------------------------------------------------------- Ф4


def _f4_repo(factory: RepoFactory, mp: pytest.MonkeyPatch) -> GitRepo:
    repo = _new_repo(factory, "f4")
    repo.write("modules.yaml", _modules([("m", ["m/"], None, []), ("n", ["n/"], None, [])]))
    done = "[DONE 2026-10-01]"
    repo.write(
        "plans/2026-10-01_alpha/plan.md",
        _plan(
            f"1.1: one {done}", f"1.2: two {done}", f"1.3: three {done}", f"1.4: four {done}",
            "1.5: five [PENDING]", f"1.6: six {done}", f"1.7: seven {done}", "1.9: nine [PENDING]",
        ),
    )  # fmt: skip
    repo.write("plans/2026-10-02_flat.md", _plan("1.1: f [PENDING]"))
    tasks = "plans/2026-10-01_alpha/tasks/"
    repo.write(
        tasks + "1.1.result.md",
        "# Итог 1.1\n\n## Сделано\n- сделано\n\n## Осталось\n- хвост один\n- хвост два\n\n"
        "## Не проверено\n- не проверил X\n\n## Инъекции\n\n"
        "| инъекция | предсказано красных | наблюдалось | тест |\n|---|---|---|---|\n"
        "| равная | 2 | 2 | t |\n| разная | 1 | 2 | t |\n| нечисло | 3+? | 4 | t |\n"
        "| дыра | 0 | 0 | t |\n| обратная | 3 | 0 | t |\n\n"
        "## Замер\n\n| метрика | было | стало |\n|---|---|---|\n| строки | 5 | 6 |\n\n## Кому передано\n\nлиду\n",
    )
    repo.write(
        tasks + "1.2.result.md",
        "**Сделано.** всё.\n\n**Не проверено.** абзац без списка, одной строкой.\n\n**Осталось.** остаток в абзаце.\n",
    )
    repo.write(tasks + "1.3.result.md", "## Что сделано\n\nтекст\n")
    repo.write(tasks + "1.4.result.md", "## Осталось\n- нет\n\n## Не проверено\n- Windows\n")
    repo.write(
        tasks + "1.5.md",
        "# 1.5\n\n## Открыто для лида (решает лид)\n\n| № | вопрос | замер | умолчание |\n|---|---|---|---|\n"
        "| О1 | первый вопрос? | m1 | d1 |\n| О2 | второй вопрос? | m2 | d2 |\n\n## Дальше\n\nтекст\n",
    )
    repo.write(
        tasks + "1.6.md",
        "# 1.6\n\n## Открыто для лида\n\n| № | вопрос | замер | умолчание |\n|---|---|---|---|\n"
        "| О1 | вопрос шестой | m | d |\n",
    )
    repo.write(tasks + "1.7.result.md", "## Осталось\n- хвост чужого модуля\n\n## Не проверено\n- чужое\n")
    repo.write(tasks + "1.5a.result.md", "## Осталось\n- хвост подзадачи\n\n## Не проверено\n- ничего нового\n")
    repo.write(tasks + "1.9.result.md", "## Осталось\n- свой хвост\n\n## Не проверено\n- своё\n")
    repo.write(tasks + "1.10.result.md", "## Осталось\n- хвост десятой\n\n## Не проверено\n- нет\n")
    repo.write(tasks + "notes.result.md", "## Осталось\n- чужой файл\n\n## Не проверено\n- чужой\n")
    repo.write(tasks + "readme.md", "любая строка\n")
    repo.write(tasks + "1.1.notes.md", "любая строка\n")
    _commit(repo, mp, "2026-09-30", "init")
    for task, path, day in (
        ("1.1", "m/a.py", "01"),
        ("1.2", "m/b.py", "02"),
        ("1.7", "n/x.py", "03"),
        ("1.9", "m/t.py", "04"),
    ):
        repo.write(path, f"x = '2026-10-{day}'\n")
        _commit(repo, mp, f"2026-10-{day}", f"task {task}", f"Task: alpha#{task}")
    return repo


def test_pack_tails_forms_filters_and_order(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _f4_repo(repo_factory, monkeypatch)
    assert _lines(atlas(repo, "pack", "alpha#1.9", *_REFS)) == [
        _alpha_head("1.9"),
        "Модули: m (коммиты задачи)",
        "Файлы-кандидаты в FILES (3):",
        "  m/a.py — 1.1",
        "  m/b.py — 1.2",
        "  m/t.py — 1.9",
        "Хвосты прошлых задач плана (7 задач):",
        "  alpha#1.1 (done):",
        "    Осталось:",
        "      - хвост один",
        "      - хвост два",
        "    Не проверено:",
        "      - не проверил X",
        "    Инъекции, где предсказано ≠ наблюдалось (2):",
        "      разная — предсказано 1, наблюдалось 2",
        "      обратная — предсказано 3, наблюдалось 0",
        "  alpha#1.2 (done):",
        "    Осталось:",
        "      остаток в абзаце.",
        "    Не проверено:",
        "      абзац без списка, одной строкой.",
        "  alpha#1.3 (done):",
        "    итог без разделов формы 0.7: plans/2026-10-01_alpha/tasks/1.3.result.md",
        "  alpha#1.4 (done):",
        "    Не проверено:",
        "      - Windows",
        "  alpha#1.5 (pending):",
        "    Открыто для лида (2):",
        "      О1: первый вопрос?",
        "      О2: второй вопрос?",
        "  alpha#1.5a (—):",
        "    Осталось:",
        "      - хвост подзадачи",
        "    Не проверено:",
        "      - ничего нового",
        "  alpha#1.10 (—):",
        "    Осталось:",
        "      - хвост десятой",
    ]
    assert _lines(atlas(repo, "pack", "flat#1.1", *_REFS)) == [
        "Задача flat#1.1 — статус pending, план plans/2026-10-02_flat.md",
        "Модули: — (у плана нет коммитов с модулями)",
        "Файлы-кандидаты в FILES (0):",
        "Хвосты прошлых задач плана: у плана нет каталога tasks/",
    ]


# ---------------------------------------------------------------- Ф5


def _f5_repo(factory: RepoFactory, mp: pytest.MonkeyPatch) -> tuple[GitRepo, dict[str, str]]:
    repo = _new_repo(factory, "f5")
    shas: dict[str, str] = {}
    repo.write(
        "modules.yaml",
        _modules(
            [
                ("outer", ["o/"], None, []),
                ("inner", ["o/in/"], None, []),
                ("one", ["one.txt"], None, []),
                ("n", ["n/"], None, []),
            ]
        ),
    )
    _commit(repo, mp, "2026-10-01", "init")

    def one(key: str, path: str, stamp: str, subject: str, *trailers: str) -> None:
        repo.write(path, "x = 1\n")
        shas[key] = _commit(repo, mp, stamp, subject, *trailers)

    one("c1", "o/a.py", "2026-10-02", "c1: o/a", "Task: alpha#1.1")
    repo.git("checkout", "-q", "-b", "feat1")
    one("f1a", "o/b.py", "2026-10-02T11:00:00+0000", "f1a: o/b", "Task: alpha#1.2")
    one("f1b", "o/in/x.py", "2026-10-02T12:00:00+0000", "f1b: o/in/x", "Task: alpha#1.3")
    shas["M1"] = _merge(repo, mp, "2026-10-03", "feat1", "Merge feat1")
    one("c2", "n/q.py", "2026-10-04", "c2: n/q")
    repo.git("checkout", "-q", "-b", "feat2")
    one("f2a", "o/c.py", "2026-10-04T11:00:00+0000", "f2a: o/c")
    shas["M2"] = _merge(repo, mp, "2026-10-05", "feat2", "Merge feat2")
    one("c3", "o/d.py", "2026-10-06", "c3: o/d", "Task: alpha#1.4", "Task: alpha#1.5")
    one("c4", "one.txt", "2026-10-07", "c4: one.txt", "Task: alpha#1.6")
    one("c5", "o/in/y.py", "2026-10-08", "c5: o/in/y")
    return repo, shas


def test_log_grouping_nested_modules_and_limit(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, s = _f5_repo(repo_factory, monkeypatch)
    main = ("--main-ref", "main")
    assert _lines(atlas(repo, "log", "outer", *main)) == [
        "Лог модуля outer — first-parent main, записей 4",
        "Task alpha#1.4 (1):",
        f"  {_s7(s['c3'])} 2026-10-06 c3: o/d",
        "Task alpha#1.5 (1):",
        f"  {_s7(s['c3'])} 2026-10-06 c3: o/d",
        "Task alpha#1.2 (1):",
        f"  {_s7(s['M1'])} 2026-10-03 Merge feat1",
        "Task alpha#1.1 (1):",
        f"  {_s7(s['c1'])} 2026-10-02 c1: o/a",
        "(без Task) (1):",
        f"  {_s7(s['M2'])} 2026-10-05 Merge feat2",
    ]
    assert _lines(atlas(repo, "log", "inner", *main)) == [
        "Лог модуля inner — first-parent main, записей 2",
        "Task alpha#1.3 (1):",
        f"  {_s7(s['M1'])} 2026-10-03 Merge feat1",
        "(без Task) (1):",
        f"  {_s7(s['c5'])} 2026-10-08 c5: o/in/y",
    ]
    assert _lines(atlas(repo, "log", "one", *main)) == [
        "Лог модуля one — first-parent main, записей 1",
        "Task alpha#1.6 (1):",
        f"  {_s7(s['c4'])} 2026-10-07 c4: one.txt",
    ]
    assert _lines(atlas(repo, "log", "outer", *main, "-n", "2")) == [
        "Лог модуля outer — first-parent main, записей 2",
        "Task alpha#1.4 (1):",
        f"  {_s7(s['c3'])} 2026-10-06 c3: o/d",
        "Task alpha#1.5 (1):",
        f"  {_s7(s['c3'])} 2026-10-06 c3: o/d",
        "(без Task) (1):",
        f"  {_s7(s['M2'])} 2026-10-05 Merge feat2",
    ]
    assert _builds_count(repo) == 0, "log не строит реестр"


def _builds_count(repo: GitRepo) -> int:
    db = repo.path / "data" / "atlas.sqlite"
    if not db.exists():
        return 0
    con = sqlite3.connect(db)
    try:
        return int(con.execute("SELECT COUNT(*) FROM builds").fetchone()[0])
    except sqlite3.OperationalError:  # таблицы нет — сборок нет
        return 0
    finally:
        con.close()


# ---------------------------------------------------------------- формы, ошибки, ленивая сборка


def test_cli_forms_errors_lazy_build_and_task_pattern(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = _f1_repo(repo_factory, monkeypatch)
    db = repo.path / "data" / "atlas.sqlite"
    assert _builds_count(repo) == 0
    assert atlas(repo, "card", "m", *_REFS).code == 0
    assert _builds_count(repo) == 1
    before = db.read_bytes()
    assert atlas(repo, "card", "m", *_REFS).code == 0
    assert db.read_bytes() == before, "второй card не должен менять базу"

    expected_err = {
        ("card", "nosuch"): "atlas: module not found\n",
        ("log", "nosuch", "--main-ref", "main"): "atlas: module not found\n",
        ("pack", "alpha#1.1", "--module", "nosuch"): "atlas: module not found\n",
        ("pack", "nosuch#1.1"): "atlas: task not found\n",
        ("pack", "alpha#9.9"): "atlas: task not found\n",
        ("pack", "alpha"): "atlas: task must be <slug>#<id>\n",
        ("pack", "alpha#"): "atlas: task must be <slug>#<id>\n",
        ("pack", "#1.1"): "atlas: task must be <slug>#<id>\n",
        ("pack", "alpha#zz"): "atlas: task must be <slug>#<id>\n",
        ("log", "m", "-n", "0", "--main-ref", "main"): "atlas: -n must be a positive integer\n",
    }
    got: dict[tuple[str, ...], tuple[Any, str, str]] = {}
    for argv in expected_err:
        extra = () if argv[0] == "log" else _REFS
        res = atlas(repo, *argv, *extra)
        got[argv] = (res.code, res.out, res.err)
    assert got == {argv: (2, "", err) for argv, err in expected_err.items()}

    assert atlas(repo, "--json", "card", "m", *_REFS).code == 2
    assert atlas(repo, "log", "m", "--ref", "main", "--main-ref", "main").code == 2
    assert atlas(repo, "card").code == 2

    from scripts.atlas import views
    from scripts.validate_commit import validate_commit

    assert views.TASK_ID_PATTERN is validate_commit.TASK_ID_PATTERN
    assert "{0,3}[0-9]{1,3}" not in Path(views.__file__).read_text(encoding="utf-8")


# ---------------------------------------------------------------- ревью р.1: тай-брейки, hash seed, дубли --module

_ROOT = Path(__file__).resolve().parents[3]


def _pack_in_subprocess(repo: GitRepo, seed: str, *argv: str) -> list[str]:
    import os
    import subprocess
    import sys

    from scripts.atlas.tests.conftest import run_with_deadline

    env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(_ROOT), "PYTHONUTF8": "1"}
    proc = run_with_deadline(
        lambda: subprocess.run(
            [sys.executable, "-m", "scripts.atlas", *argv],
            cwd=repo.path,
            env=env,
            capture_output=True,
            check=False,
        )
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    return proc.stdout.decode("utf-8").splitlines()


def test_pack_order_is_total_under_hash_seeds(repo_factory: RepoFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _new_repo(repo_factory, "seeds")
    repo.write("modules.yaml", _modules([("m", ["m/"], None, [])]))
    repo.write("plans/2026-10-01_alpha/plan.md", _plan("1.1: first [PENDING]"))
    ids = ("1.2", "1.02", "01.2")
    for ident in ids:
        repo.write(f"plans/2026-10-01_alpha/tasks/{ident}.result.md", f"## Осталось\n- хвост {ident}\n")
    _commit(repo, monkeypatch, "2026-09-30", "init")
    for day, ident in (("2026-10-01", "01.2"), ("2026-10-02", "1.02"), ("2026-10-03", "1.2")):
        repo.write("m/a.py", f"x = '{day}'\n")
        _commit(repo, monkeypatch, day, f"t {ident}", f"Task: alpha#{ident}")
    expected = [
        "Задача alpha#1.1 — статус pending, план plans/2026-10-01_alpha/plan.md",
        "Модули: m (последняя задача плана с модулями — 1.2)",
        "Файлы-кандидаты в FILES (1):",
        "  m/a.py — 01.2, 1.02, 1.2",
        "Хвосты прошлых задач плана (3 задач):",
        "  alpha#01.2 (—):",
        "    Осталось:",
        "      - хвост 01.2",
        "  alpha#1.02 (—):",
        "    Осталось:",
        "      - хвост 1.02",
        "  alpha#1.2 (—):",
        "    Осталось:",
        "      - хвост 1.2",
    ]
    outputs = {
        seed: _pack_in_subprocess(repo, seed, "pack", "alpha#1.1", *_REFS) for seed in ("0", "1", "2", "3")
    }
    assert outputs == {seed: expected for seed in outputs}


def test_card_commit_tie_breaks_by_sha_ascending(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _new_repo(repo_factory, "tie_card")
    repo.write("modules.yaml", _modules([("m", ["m/"], None, [])]))
    _commit(repo, monkeypatch, "2026-10-01", "init")
    created: dict[str, str] = {}
    for k in range(1, 6):
        repo.write(f"m/f{k}.py", "x = 1\n")
        created[_commit(repo, monkeypatch, "2026-10-02", f"m: tie {k}")] = f"m: tie {k}"
    assert list(created) != sorted(created), "порядок создания совпал с порядком SHA: тест не различает тай-брейк"
    lines = _lines(atlas(repo, "card", "m", *_REFS))
    start = lines.index("Коммиты (5 всего, последние 5):")
    assert lines[start + 1 : start + 6] == [f"  {_s7(sha)} 2026-10-02 {created[sha]}" for sha in sorted(created)]


def test_log_group_tie_uses_natural_order(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _new_repo(repo_factory, "tie_log")
    repo.write("modules.yaml", _modules([("o", ["o/"], None, [])]))
    _commit(repo, monkeypatch, "2026-10-01", "init")
    shas = {}
    for ident in ("1.10", "1.9"):
        repo.write(f"o/t{ident}.py", "x = 1\n")
        shas[ident] = _commit(repo, monkeypatch, "2026-10-02", f"o: t{ident}", f"Task: alpha#{ident}")
    assert _lines(atlas(repo, "log", "o", "--main-ref", "main")) == [
        "Лог модуля o — first-parent main, записей 2",
        "Task alpha#1.9 (1):",
        f"  {_s7(shas['1.9'])} 2026-10-02 o: t1.9",
        "Task alpha#1.10 (1):",
        f"  {_s7(shas['1.10'])} 2026-10-02 o: t1.10",
    ]


def test_pack_latest_task_tie_uses_larger_natural_id(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _new_repo(repo_factory, "tie_pack")
    repo.write("modules.yaml", _modules([("m", ["m/"], None, []), ("n", ["n/"], None, [])]))
    repo.write(
        "plans/2026-10-01_alpha/plan.md",
        _plan("1.5: five [PENDING]", "1.9: nine [PENDING]", "1.10: ten [PENDING]"),
    )
    _commit(repo, monkeypatch, "2026-09-30", "init")
    repo.write("n/y.py", "x = 1\n")
    _commit(repo, monkeypatch, "2026-10-02", "t10", "Task: alpha#1.10")
    repo.write("m/x.py", "x = 1\n")
    _commit(repo, monkeypatch, "2026-10-02", "t9", "Task: alpha#1.9")
    assert _lines(atlas(repo, "pack", "alpha#1.5", *_REFS)) == [
        "Задача alpha#1.5 — статус pending, план plans/2026-10-01_alpha/plan.md",
        "Модули: n (последняя задача плана с модулями — 1.10)",
        "Файлы-кандидаты в FILES (1):",
        "  n/y.py — 1.10",
        "Хвосты прошлых задач плана (0 задач):",
    ]


def test_pack_duplicate_module_flags_collapse(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _f3_repo(repo_factory, monkeypatch)
    assert _lines(atlas(repo, "pack", "alpha#1.4", "--module", "n", "--module", "n", *_REFS)) == [
        _alpha_head("1.4"),
        "Модули: n (--module)",
        "Файлы-кандидаты в FILES (1):",
        "  n/b.py — 1.1",
        "Хвосты прошлых задач плана (0 задач):",
    ]
