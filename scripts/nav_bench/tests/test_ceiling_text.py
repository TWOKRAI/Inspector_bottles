"""Тесты ``bench.py ceiling --text`` (Task 3.3): потолок набора по тексту паспортов atlas.

Ожидаемые значения — литералы (образцы текста — ``scripts/atlas/passport.py`` и ``map-form.md`` п. 3). Запуск atlas —
двойник ``runner(cmd, cwd) -> (код, stdout, stderr)``; клон и git настоящие (мини-репозиторий в ``tmp_path``), один тест
(9) гонит настоящий ``atlas`` путём.
"""

import io
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from scripts.nav_bench import bench

SYMBOL_TEXT = """\
== multiprocess_framework/modules/config_module/interfaces.py::IConfigObserver ==
multiprocess_framework/modules/config_module/interfaces.py:14; sha 1dc6c71b78d0; scanner 1-19b116add059
purpose: Протокол подписчика на изменения конфигурации.
  зовут из: —
interface: layer config_module; signature —
  members:
    __call__(key: str, old_value: Any, new_value: Any) -> None  :17
links: найдено 1 (формы: import); не видно: динамика, аннотации, упоминания
  used_by: 1
    <module> — multiprocess_framework/modules/config_module/tests/test_iconfig_contract.py:11 (import)
"""

UNIT_TEXT = """\
== unit u ==
u/; sha <sha>; scanner <scanner>
purpose: <purpose строки реестра>
interface: layer u
  all: A, B
  members:
    u/a.py — <doc члена>  (A, B)
    показано 1 из 3; все: --all members
links: найдено 3 (формы: import); не видно: динамика, аннотации, упоминания
  used_by: 2
    v — v/x.py:3 (import) ×2
    w — w/y.py:5 (import) ×1
runtime:
  threads: —
checks:
  tests: 1
    u/tests/test_a.py — u/tests/test_a.py:1 ×2
status: tier core; doc_missing нет; dynamic —
"""

FILE_TEXT = """\
== file multiprocess_framework/modules/config_module/tools/watcher.py ==
multiprocess_framework/modules/config_module/tools/watcher.py; sha abc123; scanner s1
purpose: —
interface: layer config_module
  all: —
  members:
    class ConfigFileWatcher  :196
    def load(path: str) -> Config  :40
links: найдено 0; не видно: динамика, аннотации, упоминания
"""

TWO_PASSPORTS = """\
== a/one.py::A ==
a/one.py:3; sha s; scanner x
interface: layer a
  members:
    f() -> None  :7

== unit b ==
b/; sha s; scanner x
interface: layer b
  members:
    g() -> None  :9

== missing ==
not found

== Config ==
ambiguous
a/two.py::Config
a/two.py:11
"""


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


def _entry(path, line, tol=None):
    item = {"path": path, "line": line}
    if tol is not None:
        item["tolerance"] = tol
    return item


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


def _three_questions(sha, **fields):
    return {
        "name": "mini",
        "repo_sha": sha,
        "exclude": [],
        "questions": [
            {"id": "Q1", "question": "?", "expected": [_entry("a.py", 10, 0)]},
            {"id": "Q2", "question": "?", "expected": [_entry("b.py", 20, 0)]},
            {"id": "Q3", "question": "?", "expected": [_entry("c.py", 30, 0)]},
        ],
        **fields,
    }


def _fake_runner(by_id, calls=None):
    """Двойник atlas: текст по первому id в argv (``cmd[3]``); код 0."""

    def runner(cmd, cwd):
        if calls is not None:
            calls.append((list(cmd), Path(cwd)))
        return 0, by_id.get(cmd[3], ""), ""

    return runner


# RED 1
def test_text_addresses_symbol_and_map_literals():
    assert bench.text_addresses(SYMBOL_TEXT) == {
        ("multiprocess_framework/modules/config_module/interfaces.py", 14),  # строка паспорта: путь:строка
        ("multiprocess_framework/modules/config_module/interfaces.py", 17),  # член класса `  :17` — путь паспорта
        ("multiprocess_framework/modules/config_module/tests/test_iconfig_contract.py", 11),  # связь
    }
    assert bench.text_addresses(UNIT_TEXT) == {
        ("u/a.py", None),  # член юнита: токен целиком `путь.py` -> адрес без строки
        ("v/x.py", 3),
        ("w/y.py", 5),
        ("u/tests/test_a.py", None),
        ("u/tests/test_a.py", 1),
    }
    assert bench.text_addresses(FILE_TEXT) == {
        ("multiprocess_framework/modules/config_module/tools/watcher.py", None),  # вторая строка паспорта файла
        ("multiprocess_framework/modules/config_module/tools/watcher.py", 196),
        ("multiprocess_framework/modules/config_module/tools/watcher.py", 40),
    }
    assert bench.text_addresses("") == set()


# RED 2
def test_member_line_binds_to_own_passport():
    # `== unit … ==` сбрасывает путь: `g() :9` юнита b — не адрес a/one.py; `not found` и `ambiguous` — без адресов
    assert bench.text_addresses(TWO_PASSPORTS) == {("a/one.py", 3), ("a/one.py", 7)}


# RED 3
def test_ceiling_text_is_per_question_not_pooled():
    qset = {
        "name": "mini",
        "repo_sha": "s",
        "questions": [
            {"id": "Q1", "question": "?", "expected": [_entry("x.py", 10, 0)]},
            {"id": "Q2", "question": "?", "expected": [_entry("y.py", 20, 0)]},
        ],
    }
    texts = {
        "Q1": ("== y.py::f ==\ny.py:20; sha s; scanner x\n", []),  # адрес вопроса Q2 в тексте целей Q1
        "Q2": ("== x.py::g ==\nx.py:10; sha s; scanner x\n", []),  # адрес вопроса Q1 в тексте целей Q2
    }
    report, reached, total = bench.ceiling_text(qset, texts)
    assert (reached, total) == (0, 2)
    assert "Q1 reachable=no" in report and "Q2 reachable=no" in report

    own = {"Q1": texts["Q2"], "Q2": texts["Q1"]}
    assert bench.ceiling_text(qset, own)[1:] == (2, 2)


# RED 4
def test_ceiling_text_report_literals():
    qset = {
        "name": "mini",
        "repo_sha": "s",
        "questions": [
            {"id": "B1", "question": "?", "require": "all", "expected": [_entry("x.py", 10, 2), _entry("y.py", 20)]},
            {"id": "B2", "question": "?", "require": "any", "expected": [_entry("x.py", 10, 2), _entry("y.py", 20)]},
            {"id": "B3", "question": "?", "scored": False, "expected": [_entry("z.py", 1, 0)]},
            {"id": "B4", "question": "?", "expected": [_entry("d.py", None)]},
            {"id": "B5", "question": "?", "expected": [_entry("e.py", 5)]},
            {"id": "B6", "question": "?", "expected": [_entry("f.py", 1, 0)]},
        ],
    }
    body = "== p ==\nx.py:12; sha s; scanner x\n    y.py:24 (import)\n    d.py — doc\n"  # 12 в 10±2; 24 вне 20±3
    texts = {
        "B1": (body, []),
        "B2": (body, []),
        "B3": (body, []),
        "B4": (body, []),
        "B6": ("", ["  atlas ref Foo: код 2: not found"]),  # B5 без целей: ключа нет
    }
    report, reached, total = bench.ceiling_text(qset, texts)
    assert report == [
        "B1 reachable=no",
        "  x.py:10 ±2 -> найден",
        "  y.py:20 ±3 -> нет в тексте",  # допуск по умолчанию 3
        "B2 reachable=yes",
        "  x.py:10 ±2 -> найден",
        "  y.py:20 ±3 -> нет в тексте",
        "B4 reachable=yes",
        "  d.py -> найден",  # запись без строки
        "B5 reachable=no",
        "  e.py:5 ±3 -> нет в тексте",
        "  нет целей",
        "B6 reachable=no",
        "  f.py:1 ±0 -> нет в тексте",
        "  atlas ref Foo: код 2: not found",
    ]
    assert (reached, total) == (2, 5)  # B3 (scored: false) не считается


# RED 5
def test_ceiling_text_exit_codes(tmp_path, capsys):
    repo, sha = _mini_repo(tmp_path)
    qpath = _write_json(repo / "q.json", _three_questions(sha))
    tpath = _write_json(
        repo / "t.json",
        {"set": "mini", "targets": {"Q1": [["ref", "S1"]], "Q2": [["ref", "S2"]], "Q3": [["ref", "S3"]]}},
    )
    _commit_all(repo, "freeze set and targets")  # --min требует Q и T в коммите
    runner = _fake_runner(
        {
            "S1": "== a.py::S1 ==\na.py:10; sha s; scanner x\n",
            "S2": "== b.py::S2 ==\nb.py:20; sha s; scanner x\n",
            "S3": "== c.py::S3 ==\nc.py:99; sha s; scanner x\n",  # мимо c.py:30 ±0
        }
    )

    def run(minimum=None, questions=qpath, targets=tpath):
        out = io.StringIO()
        code = _within(60, bench.ceiling_text_command, questions, targets, repo, minimum, out, runner)
        return code, out.getvalue(), capsys.readouterr().err

    code, out, _ = run()
    assert code == 0 and out.splitlines()[-1] == "ceiling-text mini: 2/3"
    assert run(minimum=2)[0] == 0  # K == --min
    code, out, _ = run(minimum=3)
    assert code == 1  # K = 2 < 3
    assert out.splitlines()[-1] == "ceiling-text mini: 2/3"  # отчёт печатается и при коде 1

    code, _, err = run(targets=repo / "нет.json")
    assert code == 2 and "ОШИБКА:" in err
    broken = repo / "broken.json"
    broken.write_text("это не json {", encoding="utf-8")
    code, _, err = run(targets=broken)
    assert code == 2 and "ОШИБКА:" in err
    code, _, err = run(targets=_write_json(tmp_path / "wrong_set.json", {"set": "other", "targets": {}}))
    assert code == 2 and "ОШИБКА:" in err
    code, _, err = run(questions=repo / "нет_набора.json")
    assert code == 2 and "ОШИБКА:" in err

    # оба флага или ни одного — ошибка разбора аргументов
    for flags in (
        ["--reference", str(tpath), "--text", str(tpath)],
        [],
    ):
        with pytest.raises(SystemExit) as stop:
            bench.main(["ceiling", "--questions", str(qpath), *flags])
        assert stop.value.code == 2
    capsys.readouterr()


@pytest.mark.parametrize(
    "bad",
    [
        {"set": "other", "targets": {}},  # set не равен имени набора
        {"set": "mini", "targets": {"Q9": [["ref", "S1"]]}},  # qid не из набора
        {"set": "mini", "targets": {"Q1": [[]]}},  # пустой argv
        {"set": "mini", "targets": {"Q1": [["ref", 7]]}},  # argv не из строк
        {"set": "mini", "targets": {"Q1": [["why", "S1"]]}},  # argv[0] не ref/map
        {"set": "mini", "targets": {"Q1": [["ref", "S1", "S2"]]}},  # id больше записей expected (одна)
        {"set": "mini", "targets": {"Q1": [["ref", "S1"], ["map", "a.py"]]}},  # id по всем argv вопроса — тоже
        {"set": "mini", "targets": {"Q1": [["ref", "S1", "--format", "json"]]}},
        {"set": "mini", "targets": {"Q1": [["ref", "S1", "--ref", "HEAD"]]}},
        {"set": "mini", "targets": {"Q1": [["ref", "S1", "--root", "/"]]}},
        {"set": "mini", "targets": {"Q1": [["ref", "S1", "--exclude", "x"]]}},
        {"set": "mini", "targets": {"Q1": [["ref", "S1", "--budget", "9999"]]}},
        {"set": "mini", "targets": {"Q1": [["ref", "S1", "--all", "used_by"]]}},
        {"set": "mini", "targets": {"Q1": [["ref", "S1", "--full"]]}},
        {"set": "mini", "targets": {"Q1": [["ref", "S1", "--budget=9999"]]}},  # форма --x=…
        {"set": "mini", "targets": {"Q1": [["ref", "S1", "--bud", "9999"]]}},  # сокращение argparse
        {"set": "mini", "targets": {"Q1": [["ref", "S1", "--ex=x"]]}},
    ],
)
def test_load_targets_rejects_invalid(tmp_path, bad):
    qset = _three_questions("abc")
    with pytest.raises(ValueError):
        bench.load_targets(_write_json(tmp_path / "t.json", bad), qset)


def test_load_targets_accepts_valid_and_drops_empty(tmp_path):
    qset = _three_questions("abc")
    good = {"set": "mini", "targets": {"Q1": [["ref", "S1"]], "Q2": [["map", "b.py"]], "Q3": []}}
    assert bench.load_targets(_write_json(tmp_path / "t.json", good), qset) == {
        "Q1": [["ref", "S1"]],
        "Q2": [["map", "b.py"]],
    }


# RED 6
def test_atlas_argv_ref_root_exclude_and_tmp_clone(tmp_path):
    repo, sha = _mini_repo(tmp_path)
    qset = _three_questions(sha, exclude=["docs/", "plans"])
    calls = []
    seen = {}

    def runner(cmd, cwd):
        cwd = Path(cwd)
        calls.append((list(cmd), cwd))
        seen["head"] = _git(cwd, "rev-parse", "HEAD")
        seen["has_code"] = (cwd / "a.py").is_file()
        seen["has_later"] = (cwd / "later.py").exists()
        seen["is_dir"] = cwd.is_dir()
        return 0, "", ""

    _within(60, bench.atlas_texts, qset, {"Q1": [["ref", "S1"]], "Q2": [["map", "b.py"]]}, repo, runner)

    assert [c[0][2:] for c in calls] == [
        [
            "ref",
            "S1",
            "--format",
            "passport",
            "--ref",
            sha,
            "--root",
            str(calls[0][1]),
            "--exclude",
            "docs/",
            "--exclude",
            "plans",
        ],
        [
            "map",
            "b.py",
            "--format",
            "passport",
            "--ref",
            sha,
            "--root",
            str(calls[0][1]),
            "--exclude",
            "docs/",
            "--exclude",
            "plans",
        ],
    ]
    assert calls[0][0][0] == sys.executable
    assert Path(calls[0][0][1]).name == "atlas" and Path(calls[0][0][1]).parent.name == "scripts"
    clone = calls[0][1]
    assert calls[1][1] == clone  # один клон на все цели
    assert clone.name.startswith("nav_bench_text_")
    assert repo.resolve() not in clone.resolve().parents and clone.resolve() != repo.resolve()  # клон вне root
    assert seen == {"head": sha, "has_code": True, "has_later": False, "is_dir": True}  # дерево ровно на repo_sha
    assert not clone.exists()  # клон удалён

    def boom(cmd, cwd):
        calls.append((list(cmd), Path(cwd)))
        raise RuntimeError("сбой запуска")

    with pytest.raises(RuntimeError):
        _within(60, bench.atlas_texts, qset, {"Q1": [["ref", "S1"]]}, repo, boom)
    assert not calls[-1][1].exists()  # и после исключения


def test_git_failure_is_error_exit_2(tmp_path, capsys):
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    qpath = _write_json(tmp_path / "q.json", _three_questions("abc"))
    tpath = _write_json(tmp_path / "t.json", {"set": "mini", "targets": {"Q1": [["ref", "S1"]]}})
    out = io.StringIO()
    code = _within(60, bench.ceiling_text_command, qpath, tpath, not_a_repo, None, out, _fake_runner({}))
    assert code == 2 and "ОШИБКА:" in capsys.readouterr().err


# RED 7
def test_atlas_error_is_report_line(tmp_path, capsys):
    repo, sha = _mini_repo(tmp_path)
    qset = _three_questions(sha)
    qset["questions"][0]["expected"] = [_entry("a.py", 10, 0), _entry("b.py", 5, 0)]
    qset["questions"][0]["require"] = "all"

    def runner(cmd, cwd):  # atlas при ошибочном id: паспорта остальных печатаются, код 2
        return (
            2,
            "== a.py::S1 ==\na.py:10; sha s; scanner x\n\n== Nope ==\nnot found\n",
            "atlas ref: id 2: not found\n",
        )

    texts = _within(60, bench.atlas_texts, qset, {"Q1": [["ref", "S1", "Nope"]]}, repo, runner)
    text, problems = texts["Q1"]
    assert problems == ["  atlas ref S1 Nope: код 2: atlas ref: id 2: not found"]
    assert bench.text_addresses(text) == {("a.py", 10)}  # stdout разобран, хотя код 2

    report, reached, total = bench.ceiling_text(qset, {"Q1": (text, problems)})
    assert report[:4] == [
        "Q1 reachable=no",
        "  a.py:10 ±0 -> найден",
        "  b.py:5 ±0 -> нет в тексте",
        "  atlas ref S1 Nope: код 2: atlas ref: id 2: not found",
    ]


# RED 8
def test_min_requires_committed_inputs(tmp_path, capsys):
    repo, sha = _mini_repo(tmp_path)
    qpath = _write_json(repo / "q.json", _three_questions(sha))
    tpath = _write_json(repo / "t.json", {"set": "mini", "targets": {"Q1": [["ref", "S1"]]}})
    runner = _fake_runner({"S1": "== a.py::S1 ==\na.py:10; sha s; scanner x\n"})

    def run(minimum, questions=qpath, targets=tpath):
        out = io.StringIO()
        code = _within(60, bench.ceiling_text_command, questions, targets, repo, minimum, out, runner)
        return code, out.getvalue(), capsys.readouterr().err

    assert run(None)[0] == 0  # без --min ничего не коммитили — и это нормально
    code, out, err = run(1)  # Q и T не в git
    assert code == 2 and "заморозь набор и цели коммитом" in err and out == ""

    _git(repo, "add", "q.json")  # Q в индексе, T не в git
    code, _, err = run(1)
    assert code == 2 and "заморозь набор и цели коммитом" in err
    _commit_all(repo, "freeze")
    code, out, err = run(1)
    assert code == 0 and out.splitlines()[-1] == "ceiling-text mini: 1/3", err  # чистые Q и T

    (repo / "q.json").write_text((repo / "q.json").read_text(encoding="utf-8") + "\n", encoding="utf-8")
    code, _, err = run(1)  # правка Q после коммита
    assert code == 2 and "заморозь набор и цели коммитом" in err
    assert run(None)[0] == 0  # без --min правка не мешает
    _commit_all(repo, "edit")

    (repo / "t.json").write_text((repo / "t.json").read_text(encoding="utf-8") + "\n", encoding="utf-8")
    code, _, err = run(1)  # правка T
    assert code == 2 and "заморозь набор и цели коммитом" in err
    _commit_all(repo, "edit t")

    (repo / ".gitignore").write_text("ign_t.json\n", encoding="utf-8")
    _commit_all(repo, "ignore")
    ignored = _write_json(repo / "ign_t.json", {"set": "mini", "targets": {"Q1": [["ref", "S1"]]}})
    code, _, err = run(1, targets=ignored)  # в .gitignore: git status чист, но файл не в коммите
    assert code == 2 and "заморозь набор и цели коммитом" in err

    outside = _write_json(tmp_path / "outside_t.json", {"set": "mini", "targets": {"Q1": [["ref", "S1"]]}})
    code, _, err = run(1, targets=outside)  # вне root
    assert code == 2 and "ОШИБКА:" in err


# RED 9
def test_real_atlas_on_mini_repo(tmp_path, capsys):
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    _git(repo, "init", "-q")
    (repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    code_text = "class Box:\n    '''Ящик.'''\n\n    def open_it(self, key: str) -> int:\n        return 1\n"
    (repo / "pkg" / "m.py").write_text(code_text, encoding="utf-8")
    sha = _commit_all(repo, "code")
    qpath = _write_json(
        repo / "q.json",
        {
            "name": "mini",
            "repo_sha": sha,
            "questions": [{"id": "Q1", "question": "?", "expected": [_entry("pkg/m.py", 4, 0)]}],  # метод open_it
        },
    )
    tpath = _write_json(repo / "t.json", {"set": "mini", "targets": {"Q1": [["ref", "pkg/m.py::Box"]]}})
    _commit_all(repo, "freeze")

    code = _within(
        300,
        bench.main,
        ["ceiling", "--questions", str(qpath), "--text", str(tpath), "--root", str(repo), "--min", "1"],
    )
    shown = capsys.readouterr()
    assert code == 0, shown.err
    assert shown.out.splitlines() == ["Q1 reachable=yes", "  pkg/m.py:4 ±0 -> найден", "ceiling-text mini: 1/1"]
    assert not (repo / "data").exists()  # кэш atlas — в клоне, не в репозитории-источнике
