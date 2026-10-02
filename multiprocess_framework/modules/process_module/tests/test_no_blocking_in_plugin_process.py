# -*- coding: utf-8 -*-
"""Task 5.2 — страж: в ``process()`` плагина нет ожидания (``time.sleep``).

Источник — раздел «Task 5.2» плана ``plans/transport-single-policy/phase-5.md``, пункт «Страж»:
AST по ``<корень>/**/plugin.py``, функции ``process`` / ``_process_*``: вызов ``time.sleep`` /
``sleep(`` -> красный с именем файла и строкой. Корень — параметр: тест передаёт ``tmp_path`` с
синтетическим плагином (в ``Plugins/`` не пишет), боевой прогон — по ``Plugins/``.

**Как страж вызывается (решение тестера, пин):**

    find_blocking_calls(root: Path) -> list[BlockingCall]     # сырой поиск, ничего не бросает
    assert_no_blocking_calls(root: Path) -> None              # AssertionError с «<файл>:<строка>»

``BlockingCall`` — ``NamedTuple(path, lineno, function, call)``; ``path`` — относительно ``root``,
с прямыми слэшами. Сам страж живёт в ЭТОМ файле (как соседние AST-стражи): исполнителю остаётся
привести ``Plugins/`` в чистоту — тест боевого прогона красный, пока в ``robot_control/plugin.py``
стоят два ``time.sleep`` (на HEAD 5.2: ``:198`` в ``process`` и ``:240`` в ``_process_marker``).

Что считается ожиданием (решение тестера, пин):

* ``time.sleep(...)`` и любой вызов вида ``<имя>.sleep(...)`` (покрывает ``import time as t``);
* голый ``sleep(...)`` (``from time import sleep``);
* корни поиска — функции с именем ``process`` или ``_process_*``; ``configure``, ``start``,
  воркер-петли и прочие методы ожидать вправе, ЕСЛИ их не зовёт горячий путь;
* **транзитивность по ``self``** (ревью 5.2, инъекция лида M6b: ``time.sleep`` в помощнике
  ``_actuate``, вызванном из ``process()``, — страж по одним именам был зелёным). От корня страж
  идёт по вызовам ``self.<метод>()`` методов ТОГО ЖЕ класса, транзитивно (множество посещённых),
  и называет цепочку: ``process -> _actuate``. Одно место докладывается один раз — по самой
  короткой цепочке.

**Чего страж НЕ видит** (честно, без «гарантирует»): функции уровня модуля и чужих модулей,
методы базового класса и миксинов, вызовы через ``getattr``/переменную/колбэк, ``Event.wait`` и
``queue.get(timeout=…)``. Он ловит ``sleep`` в коде самого класса плагина, не больше.

Самотесты стража помечены «контроль»: они зелёные сегодня по построению (страж — часть этого
файла) и держат сам детектор от вырождения в «ничего не находит». Красный сегодня — один:
``test_plugins_tree_has_no_sleep_in_process`` (боевой прогон).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

import pytest

# <корень репозитория>/multiprocess_framework/modules/process_module/tests/<этот файл>
REPO_ROOT = Path(__file__).resolve().parents[4]
PLUGINS_ROOT = REPO_ROOT / "Plugins"


class BlockingCall(NamedTuple):
    """Одно найденное ожидание внутри ``process``-функции плагина."""

    path: str  # относительно root, прямые слэши
    lineno: int
    function: str
    call: str


def _is_process_function(name: str) -> bool:
    return name == "process" or name.startswith("_process_")


def _call_name(node: ast.Call) -> str | None:
    """``time.sleep`` / ``t.sleep`` / ``sleep`` -> читаемое имя; иначе ``None``."""
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "sleep":
        base = func.value.id if isinstance(func.value, ast.Name) else "?"
        return f"{base}.sleep"
    if isinstance(func, ast.Name) and func.id == "sleep":
        return "sleep"
    return None


def _self_calls(fn: ast.AST, methods: dict) -> list[str]:
    """Имена методов того же класса, вызванных из ``fn`` как ``self.<имя>(...)``, в порядке исходника."""
    names: list[str] = []
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
            and node.func.attr in methods
        ):
            names.append(node.func.attr)
    return names


def _sleeps(fn: ast.AST) -> list[tuple[int, str]]:
    return [(n.lineno, name) for n in ast.walk(fn) if isinstance(n, ast.Call) and (name := _call_name(n)) is not None]


def find_blocking_calls(root: Path) -> list[BlockingCall]:
    """Найти ожидания на горячем пути ``process`` / ``_process_*`` всех ``<root>/**/plugin.py``.

    ``function`` — цепочка от корня: ``"process"`` для прямого вызова,
    ``"process -> _actuate"`` для вызова в методе того же класса.
    """
    found: list[BlockingCall] = []
    for plugin_file in sorted(Path(root).rglob("plugin.py")):
        tree = ast.parse(plugin_file.read_text(encoding="utf-8"), filename=str(plugin_file))
        rel = plugin_file.relative_to(root).as_posix()
        # (строка, вызов) -> самая короткая цепочка; одно место — одна строка отчёта.
        best: dict[tuple[int, str], list[str]] = {}

        def note(chain: list[str], fn: ast.AST) -> None:
            for lineno, call in _sleeps(fn):
                key = (lineno, call)
                if key not in best or len(chain) < len(best[key]):
                    best[key] = chain

        in_class: set[int] = set()
        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            methods = {m.name: m for m in cls.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
            in_class.update(id(m) for m in methods.values())
            for root_name in (n for n in methods if _is_process_function(n)):
                # BFS: цепочки в порядке длины, посещённые не повторяются (рекурсия не зацикливает).
                visited = {root_name}
                queue = [[root_name]]
                while queue:
                    chain = queue.pop(0)
                    note(chain, methods[chain[-1]])
                    for callee in _self_calls(methods[chain[-1]], methods):
                        if callee not in visited:
                            visited.add(callee)
                            queue.append([*chain, callee])
        # Функции с именем процесса вне класса (уровень модуля) — только прямой вызов.
        for fn in ast.walk(tree):
            if (
                isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                and _is_process_function(fn.name)
                and id(fn) not in in_class
            ):
                note([fn.name], fn)
        found.extend(BlockingCall(rel, lineno, " -> ".join(chain), call) for (lineno, call), chain in best.items())
    return sorted(found)


def assert_no_blocking_calls(root: Path) -> None:
    """Красный с «<файл>:<строка> <функция> -> <вызов>» на каждое найденное ожидание."""
    found = find_blocking_calls(root)
    assert not found, "ожидание в process() плагина:\n" + "\n".join(
        f"  {c.path}:{c.lineno} {c.function}() -> {c.call}(...)" for c in found
    )


# --- Самотесты стража на синтетических плагинах (контроль) -----------------------------------------


def _write_plugin(root: Path, package: str, source: str) -> Path:
    pkg = root / package
    pkg.mkdir(parents=True, exist_ok=True)
    path = pkg / "plugin.py"
    path.write_text(source, encoding="utf-8")
    return path


def test_guard_is_red_on_a_synthetic_plugin_with_time_sleep_in_process_and_names_the_file(tmp_path: Path) -> None:
    """контроль: синтетический плагин с ``time.sleep`` в ``process()`` -> красный с именем файла."""
    _write_plugin(
        tmp_path,
        "slow_plugin",
        "import time\n\nclass P:\n    def process(self, items):\n        time.sleep(0.1)\n        return items\n",
    )

    with pytest.raises(AssertionError) as exc:
        assert_no_blocking_calls(tmp_path)

    message = str(exc.value)
    assert "slow_plugin/plugin.py" in message
    assert ":5" in message  # строка вызова


def test_guard_reports_exactly_file_line_function_for_sleep_in_process(tmp_path: Path) -> None:
    """контроль."""
    _write_plugin(
        tmp_path,
        "slow_plugin",
        "import time\n\nclass P:\n    def process(self, items):\n        time.sleep(0.1)\n        return items\n",
    )

    assert find_blocking_calls(tmp_path) == [BlockingCall("slow_plugin/plugin.py", 5, "process", "time.sleep")]


def test_guard_catches_sleep_in_underscore_process_helpers(tmp_path: Path) -> None:
    """контроль: ``_process_marker`` — тоже горячий путь (в robot_control второе из двух мест)."""
    _write_plugin(
        tmp_path,
        "marker_plugin",
        "import time\n\nclass P:\n    def process(self, items):\n        return items\n"
        "    def _process_marker(self, item):\n        time.sleep(0.05)\n        return item\n",
    )

    assert [(c.function, c.lineno) for c in find_blocking_calls(tmp_path)] == [("_process_marker", 7)]


def test_guard_catches_bare_sleep_and_aliased_time_module(tmp_path: Path) -> None:
    """контроль: ``from time import sleep`` и ``import time as t``."""
    _write_plugin(
        tmp_path,
        "bare",
        "from time import sleep\n\nclass P:\n    def process(self, items):\n        sleep(0.1)\n        return items\n",
    )
    _write_plugin(
        tmp_path,
        "aliased",
        "import time as t\n\nclass P:\n    def process(self, items):\n        t.sleep(0.1)\n        return items\n",
    )

    found = {(c.path, c.call) for c in find_blocking_calls(tmp_path)}

    assert found == {("bare/plugin.py", "sleep"), ("aliased/plugin.py", "t.sleep")}


def test_guard_follows_self_method_calls_from_process_and_names_the_chain(tmp_path: Path) -> None:
    """Ревью 5.2 (инъекция M6b): ``process()`` -> ``self._actuate()`` -> ``time.sleep`` -> красный."""
    _write_plugin(
        tmp_path,
        "hidden_sleep",
        "import time\n\n"
        "class P:\n"
        "    def process(self, items):\n"
        "        self._actuate()\n"
        "        return items\n"
        "    def _actuate(self):\n"
        "        self._wait()\n"
        "    def _wait(self):\n"
        "        time.sleep(0.1)\n",
    )

    assert find_blocking_calls(tmp_path) == [
        BlockingCall("hidden_sleep/plugin.py", 10, "process -> _actuate -> _wait", "time.sleep")
    ]
    with pytest.raises(AssertionError) as exc:
        assert_no_blocking_calls(tmp_path)
    assert "hidden_sleep/plugin.py:10" in str(exc.value)


def test_guard_reports_a_place_once_by_the_shortest_chain_and_survives_recursion(tmp_path: Path) -> None:
    """``process`` зовёт ``_process_marker`` с ``sleep``: одна строка отчёта (корень ``_process_marker``).

    Взаимная рекурсия ``_a`` <-> ``_b`` не зацикливает обход.
    """
    _write_plugin(
        tmp_path,
        "dup",
        "import time\n\n"
        "class P:\n"
        "    def process(self, items):\n"
        "        self._process_marker(items)\n"
        "        self._a()\n"
        "    def _process_marker(self, item):\n"
        "        time.sleep(0.05)\n"
        "    def _a(self):\n"
        "        self._b()\n"
        "    def _b(self):\n"
        "        self._a()\n",
    )

    assert find_blocking_calls(tmp_path) == [BlockingCall("dup/plugin.py", 8, "_process_marker", "time.sleep")]


def test_guard_does_not_follow_calls_on_other_objects_or_sleep_in_unreached_methods(tmp_path: Path) -> None:
    """``other._wait()`` — не ``self``; ``_loop`` никто с горячего пути не зовёт -> зелёный."""
    _write_plugin(
        tmp_path,
        "clean2",
        "import time\n\n"
        "class P:\n"
        "    def process(self, items):\n"
        "        other = P()\n"
        "        other._loop()\n"
        "        return items\n"
        "    def _loop(self):\n"
        "        time.sleep(0.05)\n",
    )

    assert find_blocking_calls(tmp_path) == []


def test_guard_is_green_on_a_clean_plugin_and_ignores_sleep_outside_process(tmp_path: Path) -> None:
    """контроль: ``sleep`` в ``configure`` / воркер-петле не запрещён; страж не краснеет без причины."""
    _write_plugin(
        tmp_path,
        "clean",
        "import time\n\n"
        "class P:\n"
        "    def configure(self, ctx):\n"
        "        time.sleep(0.01)\n"
        "    def _loop(self, stop, pause):\n"
        "        time.sleep(0.05)\n"
        "    def process(self, items):\n"
        "        return items\n",
    )

    assert find_blocking_calls(tmp_path) == []
    assert_no_blocking_calls(tmp_path)  # не бросает


def test_guard_scans_only_files_named_plugin_py(tmp_path: Path) -> None:
    """контроль: корень сканируется по ``**/plugin.py``; чужие имена файлов страж не трогает."""
    pkg = tmp_path / "other"
    pkg.mkdir()
    (pkg / "helper.py").write_text(
        "import time\n\nclass P:\n    def process(self, items):\n        time.sleep(1)\n", encoding="utf-8"
    )

    assert find_blocking_calls(tmp_path) == []


def test_guard_collects_every_violation_across_files_not_just_the_first(tmp_path: Path) -> None:
    """контроль: красный перечисляет ВСЕ места — исполнителю не нужно чинить по одному на прогон."""
    src = "import time\n\nclass P:\n    def process(self, items):\n        time.sleep(0.1)\n        return items\n"
    _write_plugin(tmp_path, "a", src)
    _write_plugin(tmp_path / "nested", "b", src)

    with pytest.raises(AssertionError) as exc:
        assert_no_blocking_calls(tmp_path)

    assert "a/plugin.py" in str(exc.value)
    assert "nested/b/plugin.py" in str(exc.value)


# --- Боевой прогон -------------------------------------------------------------------------------


def test_plugins_root_exists_so_the_battle_scan_is_not_vacuous() -> None:
    """контроль: корень боевого прогона на месте и содержит плагины (иначе «зелёный» ничего не проверял бы)."""
    assert PLUGINS_ROOT.is_dir(), f"{PLUGINS_ROOT} не найден"
    assert len(list(PLUGINS_ROOT.rglob("plugin.py"))) >= 10


def test_plugins_tree_has_no_sleep_in_process() -> None:
    """Боевой прогон по ``Plugins/``. КРАСНЫЙ до правки: ``robot_control/plugin.py`` — два ``time.sleep``."""
    assert_no_blocking_calls(PLUGINS_ROOT)
