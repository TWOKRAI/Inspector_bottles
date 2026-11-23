"""Слепые приёмочные тесты Task 4.5b (scan.py, links.py, passport.py): места потоков, оговорки пустых разделов,
вызовы метода по имени. Написаны до кода, по поведению из брифа; DESIGN автора не читался.

Purpose: А — `ThreadSite` пишется для КАЖДОГО конструктора потока (без `.start()` в той же функции тоже; цепочка
    `Thread(...).start()` — ровно одна запись); Б — оговорки в тексте паспорта символа у пустых
    `threads`/`commands`/`io` (JSON и `map` не меняются); В — ключ `links.call_sites_by_name` у паспорта метода
    (`{count, items}`; `items` = `null` при N > 10), у класса и функции `null`, у `map` ключа нет; Г — прочие ключи
    схемы прежние.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Фикстуры — мини-репозитории git (`repo` из conftest) и строки кода для `scan_text`; номера строк берутся маркером
`# @имя` в конце строки фикстуры либо выписаны литералом. Ожидаемые значения — литералы. Вызовы идут в daemon-потоке с
дедлайном. Тесты «регрессия, зелёные на текущем дереве» помечены в докстринге словом РЕГРЕССИЯ.
"""

from __future__ import annotations

from typing import Any

from scripts.atlas.tests.conftest import GitRepo, run_with_deadline

__all__: list[str] = []

DEADLINE_S = 120.0

OLD_LINKS_KEYS = {"used_by", "uses", "subclasses", "call_sites", "call_sites_unresolved", "bases", "structural"}
SECTION_KEYS = {
    "purpose": {"text", "called_from", "called_from_more", "declared_at"},
    "interface": {"layer", "all", "signature", "members"},
    "runtime": {"processes", "threads", "commands", "io"},
    "checks": {"findings", "tests"},
    "status": {"tier", "doc_missing", "dynamic", "stale", "frozen"},
}
ITEM_KEYS = {"where", "how", "scope", "enclosing", "same_file", "rank"}

THREADS_NOTE = "threads: — (ищет: Thread, Timer, Observer)"
COMMANDS_EMPTY_NOTE = "commands: — (ищет только def command_specs(); register_command(...) не читает)"
COMMANDS_NULL_OLD = "форма command_specs() не объявлена"
COMMANDS_CLAUSE = "(ищет только def command_specs(); register_command(...) не читает)"


# ---------------------------------------------------------------- помощники


def _line(src: str, marker: str) -> int:
    """Номер строки фикстуры с маркером `# @marker` (ровно одной)."""
    hits = [i for i, text in enumerate(src.splitlines(), 1) if text.rstrip().endswith(f"# @{marker}")]
    assert len(hits) == 1, f"маркер {marker!r}: строк {len(hits)}"
    return hits[0]


def _sites(src: str) -> list[tuple[str, int, str, bool | None]]:
    from scripts.atlas.scan import scan_text

    facts = run_with_deadline(lambda: scan_text(src), DEADLINE_S)
    return sorted((s.pattern, s.line, s.enclosing, s.daemon) for s in facts.thread_sites)


def _commit(repo: GitRepo, files: dict[str, str]) -> str:
    repo.git("config", "core.autocrlf", "false")
    for rel, text in files.items():
        repo.write(rel, text)
    return repo.commit("fixture")


def _build(repo: GitRepo, ident: str) -> dict:
    from scripts.atlas.passport import build_passport

    return run_with_deadline(lambda: build_passport(repo.path, "HEAD", ident), DEADLINE_S)


def _build_map(repo: GitRepo, target: str) -> dict:
    from scripts.atlas.passport import build_map

    return run_with_deadline(lambda: build_map(repo.path, "HEAD", target), DEADLINE_S)


def _stripped(passport: dict) -> list[str]:
    from scripts.atlas.passport import render_text

    text = run_with_deadline(lambda: render_text(passport, full=True), DEADLINE_S)
    return [line.strip() for line in text.splitlines()]


def _by_name(p: dict) -> Any:
    assert "call_sites_by_name" in p["links"], f"нет ключа call_sites_by_name; ключи links: {sorted(p['links'])}"
    return p["links"]["call_sites_by_name"]


# ---------------------------------------------------------------- А. места потоков

_A1 = """\
import threading


class Svc:
    def __init__(self):
        self._t = threading.Thread(target=self._run)  # @ctor

    def start(self):
        self._t.start()

    def _run(self):
        pass
"""


def test_a1_ctor_in_init_start_in_other_method_gives_site() -> None:
    """А1: конструктор в `__init__`, `.start()` в другом методе -> одна запись у конструктора (строка конструктора)."""
    assert _sites(_A1) == [("Thread", _line(_A1, "ctor"), "Svc.__init__", None)]


_A2 = """\
import threading


def make(f):
    t = threading.Thread(target=f)  # @ctor
    return t
"""


def test_a2_ctor_without_any_start_gives_site() -> None:
    """А2: `t = threading.Thread(target=f)` без `.start()` нигде -> запись есть."""
    assert _sites(_A2) == [("Thread", _line(_A2, "ctor"), "make", None)]


_A2B = """\
from threading import Timer
from watchdog.observers import Observer


def timer(f):
    t = Timer(1.5, f)  # @timer
    return t


def watch():
    obs = Observer()  # @obs
    return obs
"""


def test_a2_timer_and_observer_without_start_give_sites() -> None:
    """А2 (шаблоны `Timer`, `Observer` — те же, что у `Thread`): конструкторы без `.start()` дают записи."""
    assert _sites(_A2B) == sorted(
        [
            ("Timer", _line(_A2B, "timer"), "timer", None),
            ("Observer", _line(_A2B, "obs"), "watch", None),
        ]
    )


_A2C = """\
import threading


def multi(f):
    t = threading.Thread(  # @ctor
        target=f,
        daemon=True,
    )
    return t
"""


def test_a2_daemon_literal_and_ctor_line_kept_without_start() -> None:
    """Форма записи прежняя: `daemon` — литерал конструктора, `line` — первая строка многострочного конструктора."""
    assert _sites(_A2C) == [("Thread", _line(_A2C, "ctor"), "multi", True)]


_A3 = """\
import threading


def other_target():
    pass


class Svc:
    def go(self):
        self._t = threading.Thread(target=other_target)  # @ctor

    def _run(self):
        pass
"""


def test_a3_ctor_with_target_not_a_method_of_class_gives_site() -> None:
    """А3: `target=other_target` (не метод класса) и ни одного `.start()` -> запись есть."""
    assert _sites(_A3) == [("Thread", _line(_A3, "ctor"), "Svc.go", None)]


_A4 = """\
import threading


def chained(f):
    threading.Thread(target=f).start()  # @chain
"""


def test_a4_chained_ctor_start_gives_exactly_one_site() -> None:
    """А4: цепочка `threading.Thread(target=f).start()` -> РОВНО одна запись (дубль по функции и строке не пишется)."""
    assert _sites(_A4) == [("Thread", _line(_A4, "chain"), "chained", None)]


_A4B = """\
import threading


def started(f):
    t = threading.Thread(target=f, daemon=True)  # @ctor
    t.start()
"""


def test_a4_assigned_ctor_with_start_in_same_function_gives_exactly_one_site() -> None:
    """А4 (смежный случай): `t = Thread(...)` и `t.start()` в одной функции -> одна запись, не две."""
    assert _sites(_A4B) == [("Thread", _line(_A4B, "ctor"), "started", True)]


_A5 = """\
import threading


def build(f):
    return threading.Thread(target=f)  # @build


def run(f):
    t = threading.Thread(target=f)  # @run
    return t
"""


def test_a5_functions_named_build_and_run_with_ctor_give_sites() -> None:
    """А5: функции `build` и `run`, внутри которых создаётся поток, дают записи (раньше такие имена не давали)."""
    assert _sites(_A5) == sorted(
        [
            ("Thread", _line(_A5, "build"), "build", None),
            ("Thread", _line(_A5, "run"), "run", None),
        ]
    )


_A_PASSPORT = {
    "pkg/__init__.py": "",
    "pkg/svc.py": _A1.replace("# @ctor", ""),
}


def test_a1_site_reaches_passport_threads_json(repo: GitRepo) -> None:
    """А1 через паспорт: у класса `Svc` в `runtime.threads` одна запись прежней формы, `where` — строка конструктора."""
    _commit(repo, _A_PASSPORT)
    assert _build(repo, "pkg/svc.py::Svc")["runtime"]["threads"] == [
        {"pattern": "Thread", "daemon": None, "where": "pkg/svc.py:6"}
    ]


# ---------------------------------------------------------------- Б. оговорки пустых разделов в тексте

_EMPTY_FILES = {
    "pkg/__init__.py": "",
    "pkg/svc.py": ("class Plain:\n    pass\n\n\nclass Declared:\n    def command_specs(self):\n        return []\n"),
}


def test_b_empty_threads_line_has_note(repo: GitRepo) -> None:
    """Б: пустой `threads` -> `threads: — (ищет: Thread, Timer, Observer)` (после отступа) вместо голого прочерка."""
    _commit(repo, _EMPTY_FILES)
    lines = _stripped(_build(repo, "pkg/svc.py::Plain"))
    assert THREADS_NOTE in lines
    assert "threads: —" not in lines


def test_b_empty_commands_list_line_has_note(repo: GitRepo) -> None:
    """Б: `commands` = `[]` (объявлена, литералов нет) -> оговорка про `def command_specs()`, `register_command`."""
    _commit(repo, _EMPTY_FILES)
    p = _build(repo, "pkg/svc.py::Declared")
    assert p["runtime"]["commands"] == []  # предпосылка: именно `[]`, не null
    lines = _stripped(p)
    assert COMMANDS_EMPTY_NOTE in lines
    assert "commands: —" not in lines


def test_b_null_commands_keeps_old_text_and_adds_clause(repo: GitRepo) -> None:
    """Б: `commands` = null -> прежний текст «форма command_specs() не объявлена» остаётся, после него — та же оговорка
    в скобках."""
    _commit(repo, _EMPTY_FILES)
    p = _build(repo, "pkg/svc.py::Plain")
    assert p["runtime"]["commands"] is None  # предпосылка
    rows = [s for s in _stripped(p) if s.startswith("commands:")]
    assert len(rows) == 1
    row = rows[0]
    assert COMMANDS_NULL_OLD in row
    assert row.endswith(COMMANDS_CLAUSE)
    assert row.index(COMMANDS_NULL_OLD) < row.index(COMMANDS_CLAUSE)


def test_b_empty_io_line_names_scanner_patterns(repo: GitRepo) -> None:
    """Б: пустой `io` -> строка начинается `io: — (ищет: `, заканчивается `)`, в перечне есть `Observer.schedule`."""
    _commit(repo, _EMPTY_FILES)
    rows = [s for s in _stripped(_build(repo, "pkg/svc.py::Plain")) if s.startswith("io:")]
    assert len(rows) == 1
    row = rows[0]
    assert row.startswith("io: — (ищет: ")
    assert row.endswith(")")
    assert "Observer.schedule" in row


def test_b_io_note_names_replace_family_too(repo: GitRepo) -> None:
    """Б (трактовка «шаблоны ввода-вывода сканера» = то, что `IoFact` реально ловит): в перечне названы и
    `os.replace`, `os.rename`, `shutil.move`. ТРАКТОВКА брифа, не буква: точное написание имён в брифе не дано."""
    _commit(repo, _EMPTY_FILES)
    row = next(s for s in _stripped(_build(repo, "pkg/svc.py::Plain")) if s.startswith("io:"))
    for pattern in ("os.replace", "os.rename", "shutil.move"):
        assert pattern in row, row


_FULL_FILES = {
    "pkg/__init__.py": "",
    "pkg/run.py": (
        "import os\n"
        "import threading\n\n\n"
        "class Busy:\n"
        "    def command_specs(self):\n"
        '        return (("go", None),)\n\n'
        "    def start(self):\n"
        "        t = threading.Thread(target=print)\n"
        "        t.start()\n\n"
        "    def save(self, a, b):\n"
        "        os.replace(a, b)\n"
    ),
}


def test_b_nonempty_sections_have_no_note(repo: GitRepo) -> None:
    """Б: непустые `threads`/`commands`/`io` печатаются записями, оговорки «ищет» нигде нет."""
    _commit(repo, _FULL_FILES)
    p = _build(repo, "pkg/run.py::Busy")
    assert p["runtime"]["threads"] != [] and p["runtime"]["commands"] != [] and p["runtime"]["io"] != []  # предпосылка
    lines = _stripped(p)
    assert not [s for s in lines if "ищет" in s], [s for s in lines if "ищет" in s]
    assert "threads:" in lines and "commands:" in lines and "io:" in lines


def test_b_json_runtime_unchanged_for_empty_sections(repo: GitRepo) -> None:
    """РЕГРЕССИЯ: JSON паспорта не меняется — пустые разделы `[]`/`null`, без текста оговорки."""
    _commit(repo, _EMPTY_FILES)
    assert _build(repo, "pkg/svc.py::Plain")["runtime"] == {
        "processes": None,
        "threads": [],
        "commands": None,
        "io": [],
    }
    assert _build(repo, "pkg/svc.py::Declared")["runtime"]["commands"] == []


_MAP_REG = (
    "version: 1\nmodules:\n"
    "  - id: u\n"
    '    paths: ["u/"]\n'
    "    layer: framework\n"
    "    tier: core\n"
    "    docs: []\n"
    "    parent: null\n"
    '    purpose: "Юнит u."\n'
)
_MAP_FILES = {
    "modules.yaml": _MAP_REG,
    "u/__init__.py": "",
    "u/a.py": "def run_a():\n    return 1\n",
}


def test_b_map_text_keeps_bare_dashes_for_unit_and_file(repo: GitRepo) -> None:
    """РЕГРЕССИЯ: у `map` (юнит и файл) текст прежний — `threads: —`, `commands: —`, `io: —`, оговорок «ищет» нет."""
    _commit(repo, _MAP_FILES)
    for target in ("u", "u/a.py"):
        lines = _stripped(_build_map(repo, target))
        for kept in ("threads: —", "commands: —", "io: —"):
            assert kept in lines, (target, kept)
        assert not [s for s in lines if "ищет" in s], target


# ---------------------------------------------------------------- В. вызовы метода по имени

_STEP = (
    "class Step:\n"
    "    def run_x(self):\n"
    "        return 1\n\n"
    "    def other(self):\n"
    "        self.run_x()\n\n\n"
    "def helper():\n"
    "    return 2\n"
)

_THREE: dict[str, str] = {
    "pkg/__init__.py": "",
    "pkg/step.py": _STEP,
    "pkg/a.py": "def caller_a(step):\n    step.run_x()  # @a\n",
    "pkg/b.py": "def caller_b(step):\n    step.run_x()  # @b\n",
    "pkg/c.py": "def caller_c(step):\n    step.run_x()  # @c\n",
}
STEP_METHOD = "pkg/step.py::Step.run_x"


def test_v_method_passport_has_call_sites_by_name_key(repo: GitRepo) -> None:
    """В: в `links` паспорта МЕТОДА есть ключ `call_sites_by_name` формы `{"count": N, "items": [...]}`."""
    _commit(repo, _THREE)
    got = _by_name(_build(repo, STEP_METHOD))
    assert isinstance(got, dict)
    assert set(got) == {"count", "items"}


def test_v_three_prod_files_three_items_with_addresses(repo: GitRepo) -> None:
    """В: три вызова `step.run_x()` из трёх разных prod-файлов -> count 3 и 3 записи с адресами этих вызовов."""
    _commit(repo, _THREE)
    got = _by_name(_build(repo, STEP_METHOD))
    assert got["count"] == 3
    assert sorted(e["where"] for e in got["items"]) == ["pkg/a.py:2", "pkg/b.py:2", "pkg/c.py:2"]
    assert {e["where"]: e["enclosing"] for e in got["items"]} == {
        "pkg/a.py:2": "caller_a",
        "pkg/b.py:2": "caller_b",
        "pkg/c.py:2": "caller_c",
    }


def test_v_items_how_is_by_name_and_form_matches_call_sites(repo: GitRepo) -> None:
    """В: запись `items` — той же формы, что у `call_sites` (ключи `where, how, scope, enclosing, same_file, rank`), но
    `how` == "by-name"; вызовы из других файлов и prod."""
    _commit(repo, _THREE)
    items = _by_name(_build(repo, STEP_METHOD))["items"]
    assert items, "items пуст"
    for e in items:
        assert set(e) == ITEM_KEYS, e
        assert e["how"] == "by-name"
        assert e["scope"] == "prod"
        assert e["same_file"] is False


def test_v_self_call_not_counted_and_call_sites_stay_exact(repo: GitRepo) -> None:
    """В: `self.run_x()` внутри класса в by-name не идёт; `call_sites` по-прежнему только точные адреса (один:
    `pkg/step.py:6`), `call_sites_unresolved` не меняется (3 — три неотнесённых `step.run_x()` из трёх файлов)."""
    _commit(repo, _THREE)
    p = _build(repo, STEP_METHOD)
    assert [(e["where"], e["how"]) for e in p["links"]["call_sites"]] == [("pkg/step.py:6", "name-call")]
    assert p["links"]["call_sites_unresolved"] == 3
    by_name = _by_name(p)
    assert "pkg/step.py:6" not in [e["where"] for e in by_name["items"]]
    assert by_name["count"] == 3


_EXCLUDED = {
    "pkg/__init__.py": "",
    "pkg/step.py": _STEP,
    "pkg/real.py": "def caller(step):\n    step.run_x()  # @real\n",
    "pkg/bare.py": ("def run_x():\n    return 0\n\n\ndef g():\n    run_x()\n\n\ndef h(run_x):\n    run_x()\n"),
    "tests/__init__.py": "",
    "tests/test_step.py": "def test_a(step):\n    step.run_x()\n    step.run_x()\n",
}


def test_v_bare_shadowed_and_test_scope_calls_not_counted(repo: GitRepo) -> None:
    """В: голые вызовы `run_x()` (в том числе затенённый параметром) и вызовы из тестового файла (scope tests) в
    by-name не идут: остаётся один prod-вызов `step.run_x()` из `pkg/real.py`."""
    _commit(repo, _EXCLUDED)
    got = _by_name(_build(repo, STEP_METHOD))
    assert got["count"] == 1
    assert [e["where"] for e in got["items"]] == ["pkg/real.py:2"]
    assert all(not e["where"].startswith("tests/") for e in got["items"])


def test_v_no_outside_callers_gives_zero_and_empty_items(repo: GitRepo) -> None:
    """В (по формуле «N <= 10 -> N записей»): внешних вызовов нет -> `{"count": 0, "items": []}`."""
    _commit(repo, {"pkg/__init__.py": "", "pkg/step.py": _STEP})
    assert _by_name(_build(repo, STEP_METHOD)) == {"count": 0, "items": []}


def _many(calls: int) -> dict[str, str]:
    body = "def many(step):\n" + "".join("    step.run_x()\n" for _ in range(calls))
    return {"pkg/__init__.py": "", "pkg/step.py": _STEP, "pkg/many.py": body}


def test_v_boundary_exactly_ten_calls_gives_ten_items(repo: GitRepo) -> None:
    """В: ровно 10 вызовов -> count 10, `items` — 10 записей (строки 2..11 файла `pkg/many.py`)."""
    _commit(repo, _many(10))
    got = _by_name(_build(repo, STEP_METHOD))
    assert got["count"] == 10
    assert sorted(e["where"] for e in got["items"]) == sorted(f"pkg/many.py:{n}" for n in range(2, 12))


def test_v_boundary_eleven_calls_gives_null_items(repo: GitRepo) -> None:
    """В: ровно 11 вызовов -> count 11, `items` = null."""
    _commit(repo, _many(11))
    got = _by_name(_build(repo, STEP_METHOD))
    assert got["count"] == 11
    assert got["items"] is None


_CLASS_FUNC = {
    "pkg/__init__.py": "",
    "pkg/step.py": _STEP,
    "pkg/use.py": "def caller(obj, step):\n    obj.helper()\n    step.run_x()\n",
}


def test_v_class_passport_has_null_by_name(repo: GitRepo) -> None:
    """В: у паспорта КЛАССА ключ `call_sites_by_name` присутствует со значением null."""
    _commit(repo, _CLASS_FUNC)
    assert _by_name(_build(repo, "pkg/step.py::Step")) is None


def test_v_function_passport_has_null_by_name_even_with_same_named_calls(repo: GitRepo) -> None:
    """В: у паспорта ФУНКЦИИ ключ присутствует со значением null (хотя `obj.helper()` в коде есть)."""
    _commit(repo, _CLASS_FUNC)
    assert _by_name(_build(repo, "pkg/step.py::helper")) is None


def test_v_map_has_no_by_name_key_for_unit_and_file(repo: GitRepo) -> None:
    """РЕГРЕССИЯ: у `map` (юнит и файл) в `links` ключа `call_sites_by_name` нет."""
    _commit(repo, _MAP_FILES)
    for target in ("u", "u/a.py"):
        assert "call_sites_by_name" not in _build_map(repo, target)["links"], target


def test_v_text_up_to_ten_lists_header_and_addresses(repo: GitRepo) -> None:
    """В: при N <= 10 текст метода — строка `по имени метода, тип не проверен (3):` и адреса вызовов."""
    _commit(repo, _THREE)
    lines = _stripped(_build(repo, STEP_METHOD))
    assert "по имени метода, тип не проверен (3):" in lines
    joined = "\n".join(lines[lines.index("по имени метода, тип не проверен (3):") :])
    for where in ("pkg/a.py:2", "pkg/b.py:2", "pkg/c.py:2"):
        assert where in joined, where


def test_v_text_boundary_ten_still_lists(repo: GitRepo) -> None:
    """В: ровно 10 -> строка с `(10):` и адреса (хотя бы первый и последний), без фразы «имя частое»."""
    _commit(repo, _many(10))
    lines = _stripped(_build(repo, STEP_METHOD))
    assert "по имени метода, тип не проверен (10):" in lines
    joined = "\n".join(lines)
    assert "pkg/many.py:2" in joined and "pkg/many.py:11" in joined
    assert "имя частое" not in joined


def test_v_text_over_ten_prints_count_without_addresses(repo: GitRepo) -> None:
    """В: при N > 10 — одна строка `по имени метода (prod, без self): 11 вызовов .run_x(...) - имя частое, адреса не
    печатаются` и никаких адресов вызовов; строки «тип не проверен» нет."""
    _commit(repo, _many(11))
    lines = _stripped(_build(repo, STEP_METHOD))
    assert "по имени метода (prod, без self): 11 вызовов .run_x(...) - имя частое, адреса не печатаются" in lines
    joined = "\n".join(lines)
    assert "pkg/many.py:" not in joined
    assert "тип не проверен" not in joined


# ---------------------------------------------------------------- Г. остальная схема не меняется


def test_g_links_keys_are_old_plus_by_name_for_all_kinds(repo: GitRepo) -> None:
    """Г: ключи `links` у метода, класса, функции = прежние семь + `call_sites_by_name`; ничего лишнего."""
    _commit(repo, _CLASS_FUNC)
    for ident in (STEP_METHOD, "pkg/step.py::Step", "pkg/step.py::helper"):
        assert set(_build(repo, ident)["links"]) == OLD_LINKS_KEYS | {"call_sites_by_name"}, ident


def test_g_other_sections_keys_unchanged(repo: GitRepo) -> None:
    """РЕГРЕССИЯ: ключи остальных пяти разделов прежние (у метода, класса, функции)."""
    _commit(repo, _CLASS_FUNC)
    for ident in (STEP_METHOD, "pkg/step.py::Step", "pkg/step.py::helper"):
        p = _build(repo, ident)
        for section, keys in SECTION_KEYS.items():
            assert set(p[section]) == keys, (ident, section)
