"""Тесты строгого потолка ``bench.py ceiling --text`` (Task 3.4): K' рядом с прежним K.

Запись ``expected`` с непустым ``symbol`` строго найдена, только если в тексте ЕЁ вопроса есть блок (строка
``== ... ==`` и следующие до следующего заголовка) с id ``путь::symbol`` и адрес ЭТОГО блока попал в окно записи.
Записи без ``symbol`` читаются по окну, как раньше. Ожидаемые значения — литералы; запуск atlas — двойник
``runner(cmd, cwd)``, кроме последнего теста: он гонит настоящий ``atlas`` на мини-репозитории.

Результат ``bench.ceiling_text_both(qset, texts)`` — ``(отчёт, K, K_строгое | None, N)``.
"""

import io
import json
import re
import subprocess
import threading
from pathlib import Path

import pytest

from scripts.nav_bench import bench


def _within(seconds, func, *args, **kwargs):
    """Вызов в демон-потоке с дедлайном: зависший git или atlas не вешает прогон тестов."""
    box = {}

    def target():
        try:
            box["value"] = func(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 — исключение возвращается в поток теста
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(seconds)
    assert not thread.is_alive(), f"{getattr(func, '__name__', func)} не вернулся за {seconds} с"
    if "error" in box:
        raise box["error"]
    return box["value"]


def _git(repo, *args):
    done = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return done.stdout.strip()


def _commit_all(repo, message):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _mini_repo(tmp_path):
    """Репозиторий с кодом на первом коммите (``repo_sha``) и файлом, которого на нём ещё нет."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    sha = _commit_all(repo, "code")
    (repo / "later.py").write_text("y = 2\n", encoding="utf-8")
    _commit_all(repo, "later")
    return repo, sha


def _code_repo(tmp_path):
    """Репозиторий-«дерево с кодом atlas»: `scripts/atlas/__main__.py` в коммите. Возвращает (путь, HEAD)."""
    code = tmp_path / "code_tree"
    (code / "scripts" / "atlas").mkdir(parents=True)
    _git(code, "init", "-q")
    (code / "scripts" / "atlas" / "__main__.py").write_text("VERSION = 1\n", encoding="utf-8")
    return code, _commit_all(code, "atlas code")


def _fake_runner(by_id, calls=None):
    """Двойник atlas: текст по первому id в argv (``cmd[3]``); код 0."""

    def runner(cmd, cwd):
        if calls is not None:
            calls.append((list(cmd), Path(cwd)))
        return 0, by_id.get(cmd[3], ""), ""

    return runner


def E(path, symbol, line, tolerance=None):  # noqa: N802 — короткая запись эталона из литералов брифа
    item = {"path": path, "symbol": symbol, "line": line}
    if tolerance is not None:
        item["tolerance"] = tolerance
    return item


def _qset(*questions, sha="s"):
    return {"name": "mini", "repo_sha": sha, "questions": list(questions)}


def _question(qid, expected, **fields):
    return {"id": qid, "question": "?", **fields, "expected": expected}


# R1 -------------------------------------------------------------------------------------------------------------

R1_QSET = _qset(_question("Q1", [E("m.py", "f", 105), E("m.py", "K", 102)], require="all"))
R1_TEXT_NEIGHBOUR = "== m.py::f ==\nm.py:105; sha s; scanner x\n\n== m.py::K ==\nnot found\n"
R1_TEXT_OWN = "== m.py::f ==\nm.py:105; sha s; scanner x\n\n== m.py::K ==\nm.py:102; sha s; scanner x\n"


# RED 1
def test_strict_neighbour_window_is_not_own_passport():
    """F11 в миниатюре: адрес соседнего паспорта (105) лежит в окне записи K (102 ±3), но блок `m.py::K` не нашёл её."""
    neighbour_report = [
        "Q1 reachable=yes (строго no)",
        "  m.py:105 ±3 -> найден",
        "  m.py:102 ±3 -> найден вне блока записи",
    ]
    got = bench.ceiling_text_both(R1_QSET, {"Q1": (R1_TEXT_NEIGHBOUR, [])})
    assert got == (neighbour_report, 1, 0, 1)
    assert bench.ceiling_text(R1_QSET, {"Q1": (R1_TEXT_NEIGHBOUR, [])}) == (neighbour_report, 1, 1)  # тот же отчёт

    own_report = ["Q1 reachable=yes", "  m.py:105 ±3 -> найден", "  m.py:102 ±3 -> найден"]
    got = bench.ceiling_text_both(R1_QSET, {"Q1": (R1_TEXT_OWN, [])})
    assert got == (own_report, 1, 1, 1)
    assert bench.ceiling_text(R1_QSET, {"Q1": (R1_TEXT_OWN, [])}) == (own_report, 1, 1)


# R2 -------------------------------------------------------------------------------------------------------------

R2_OUTSIDE = (["Q1 reachable=yes (строго no)", "  x.py:17 ±3 -> найден вне блока записи"], 1, 0, 1)
R2_OWN = (["Q1 reachable=yes", "  x.py:17 ±3 -> найден"], 1, 1, 1)
R2_ABSENT = (["Q1 reachable=no", "  x.py:17 ±3 -> нет в тексте"], 0, 0, 1)


# RED 2
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(  # a: адрес члена в блоке класса, не метода
            "== x.py::C ==\nx.py:10; sha s; scanner x\n  members:\n    m() -> None  :17\n",
            R2_OUTSIDE,
            id="a-member-in-class-block",
        ),
        pytest.param(  # b: другой путь у блока с тем же именем
            "== y.py::C.m ==\ny.py:5; sha s; scanner x\n    caller — x.py:17 (call)\n",
            R2_OUTSIDE,
            id="b-other-path-same-name",
        ),
        pytest.param(  # c: блок соседнего символа с похожим id (C.m2, не C.m)
            "== x.py::C.m2 ==\nx.py:17; sha s; scanner x\n", R2_OUTSIDE, id="c-similar-id-m2"
        ),
        pytest.param(  # d: заголовок юнита — не блок записи
            "== unit x ==\nx/; sha s; scanner x\n    w — x.py:17 (import)\n", R2_OUTSIDE, id="d-unit-block"
        ),
        pytest.param(  # e: заголовок файла — не блок записи
            "== file x.py ==\nx.py; sha s; scanner x\n  members:\n    def m() -> None  :17\n",
            R2_OUTSIDE,
            id="e-file-block",
        ),
        pytest.param(  # f: свой блок есть, но его адрес (40) мимо окна; 16 в блоке C соседа
            "== x.py::C.m ==\nx.py:40; sha s; scanner x\n\n== x.py::C ==\nx.py:16; sha s; scanner x\n",
            R2_OUTSIDE,
            id="f-own-block-address-outside-window",
        ),
        pytest.param("== x.py::C.m ==\nx.py:17; sha s; scanner x\n", R2_OWN, id="g-own-block-header-address"),
        pytest.param(  # h: адрес связи (used_by) внутри собственного блока засчитан
            "== x.py::C.m ==\nx.py:40; sha s; scanner x\n    h — x.py:17 (call)\n",
            R2_OWN,
            id="h-own-block-link-address",
        ),
        pytest.param("== C.m ==\nambiguous\nx.py::C.m\nx.py:17\n", R2_ABSENT, id="i-ambiguous-no-addresses"),
    ],
)
def test_strict_needs_own_block_path_and_symbol(text, expected):
    qset = _qset(_question("Q1", [E("x.py", "C.m", 17)]))
    assert bench.ceiling_text_both(qset, {"Q1": (text, [])}) == expected


# R3 -------------------------------------------------------------------------------------------------------------

_NO_KEY = "<ключа нет>"


# RED 3
@pytest.mark.parametrize("v", [_NO_KEY, None, "", 5], ids=["no-key", "none", "empty-string", "int-5"])
def test_strict_without_symbol_keeps_window_reading(v):
    """Запись без (пустого, нестрокового) `symbol` читается по окну: K' == K, а при единственной такой записи K' нет."""
    first = {"path": "a.py", "line": 10, "tolerance": 0}
    if v is not _NO_KEY:
        first["symbol"] = v
    text = "== a.py::S ==\na.py:10; sha s; scanner x\n"

    both = _qset(_question("Q1", [first, E("a.py", "S", 10, 0)], require="all"))
    assert bench.ceiling_text_both(both, {"Q1": (text, [])}) == (
        ["Q1 reachable=yes", "  a.py:10 ±0 -> найден", "  a.py:10 ±0 -> найден"],
        1,
        1,
        1,
    )

    alone = _qset(_question("Q1", [first], require="all"))
    assert bench.ceiling_text_both(alone, {"Q1": (text, [])}) == (
        ["Q1 reachable=yes", "  a.py:10 ±0 -> найден"],
        1,
        None,
        1,
    )


# R4 -------------------------------------------------------------------------------------------------------------


# RED 4
def test_strict_is_per_question_and_follows_require():
    qset = _qset(
        _question("Q1", [E("a.py", "A", None), E("a.py", "Z", 30)], require="any"),
        _question("Q2", [E("a.py", "Z", 30)], scored=False),
        _question("Q3", [E("a.py", "B", 7)]),
    )
    texts = {
        "Q1": ("== a.py::A ==\na.py:5; sha s; scanner x\n\n== a.py::B ==\na.py:7; sha s; scanner x\n", []),
        "Q2": ("== a.py::A ==\na.py:29; sha s; scanner x\n", []),
        "Q3": ("== a.py::A ==\na.py:5; sha s; scanner x\n", []),
    }
    assert bench.ceiling_text_both(qset, texts) == (
        [
            "Q1 reachable=yes",
            "  a.py -> найден",
            "  a.py:30 ±3 -> нет в тексте",
            "Q3 reachable=yes (строго no)",
            "  a.py:7 ±3 -> найден вне блока записи",
        ],
        2,
        1,
        2,
    )


# R5 -------------------------------------------------------------------------------------------------------------


# RED 5
def test_command_prints_both_numbers_min_by_window(tmp_path, capsys):
    repo, sha = _mini_repo(tmp_path)
    qset = {
        "name": "mini",
        "repo_sha": sha,
        "exclude": [],
        "questions": [
            _question("Q1", [E("m.py", "f", 105), E("m.py", "K", 102)], require="all"),
            _question("Q2", [E("b.py", "g", 20)]),
        ],
    }
    qpath = _write_json(repo / "q.json", qset)
    tpath = _write_json(
        repo / "t.json",
        {"set": "mini", "targets": {"Q1": [["ref", "m.py::f", "m.py::K"]], "Q2": [["ref", "b.py::g"]]}},
    )
    _commit_all(repo, "freeze set and targets")  # --min требует Q и T в коммите
    code_tree, head = _code_repo(tmp_path)
    runner = _fake_runner(
        {"m.py::f": R1_TEXT_NEIGHBOUR, "b.py::g": "== b.py::g ==\nb.py:20; sha s; scanner x\n"},
    )

    def run(minimum=None):
        out = io.StringIO()
        code = _within(60, bench.ceiling_text_command, qpath, tpath, repo, minimum, out, runner, code_tree)
        return code, out.getvalue().splitlines(), capsys.readouterr().err

    code, lines, err = run()
    assert code == 0, err
    assert lines == [
        f"atlas-код: {head}",
        "Q1 reachable=yes (строго no)",
        "  m.py:105 ±3 -> найден",
        "  m.py:102 ±3 -> найден вне блока записи",
        "Q2 reachable=yes",
        "  b.py:20 ±3 -> найден",
        "ceiling-text mini: 2/2 (строго 1/2)",
    ]

    code, _, err = run(minimum=2)  # --min сравнивается с K по окну, не со строгим
    assert code == 0, err

    code, lines, _ = run(minimum=3)  # K = 2 < 3
    assert code == 1
    assert lines[-1] == "ceiling-text mini: 2/2 (строго 1/2)"  # отчёт печатается и при коде 1


# R6 -------------------------------------------------------------------------------------------------------------


# RED 6
def test_real_atlas_strict_on_mini_repo(tmp_path, capsys):
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    _git(repo, "init", "-q")
    (repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    code_text = "'''Модуль.'''\n\n\ndef f() -> int:\n    return 1\n\ndef g() -> int:\n    return 2\n"  # f :4, g :7
    (repo / "pkg" / "m.py").write_text(code_text, encoding="utf-8")
    sha = _commit_all(repo, "code")
    qpath = _write_json(
        repo / "q.json",
        {
            "name": "mini",
            "repo_sha": sha,
            "questions": [_question("Q1", [E("pkg/m.py", "f", 4), E("pkg/m.py", "g", 7)], require="all")],
        },
    )
    tpath = _write_json(repo / "t.json", {"set": "mini", "targets": {"Q1": [["ref", "f"]]}})  # голый id
    _commit_all(repo, "freeze")

    code = _within(
        300,
        bench.main,
        ["ceiling", "--questions", str(qpath), "--text", str(tpath), "--root", str(repo)],
    )
    shown = capsys.readouterr()
    assert code == 0, shown.err
    version, *rows = shown.out.splitlines()
    assert re.fullmatch(r"atlas-код: [0-9a-f]{40}( \+правки)?", version), version
    assert rows == [
        "Q1 reachable=yes (строго no)",
        "  pkg/m.py:4 ±3 -> найден",
        "  pkg/m.py:7 ±3 -> найден вне блока записи",
        "ceiling-text mini: 1/1 (строго 0/1)",
    ]
    assert not (repo / "data").exists()  # кэш atlas — в клоне, не в репозитории-источнике
