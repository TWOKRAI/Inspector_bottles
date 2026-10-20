"""Сторож T5.3f f3: тесты не трогают поля состояния драйвера робота v2; швы — литеральный белый список.

Purpose:
    После T5.3f состояние драйвера живёт в ``RobotState`` (``drv.state``). Сторож по AST держит три границы.
    (а) Тесты драйвера робота v2 (``Services/device_hub/tests``, ``Plugins/hub/device_hub/tests``): имена бывших
    полей состояния (``_syncing``, ``_jog``, ``_prog_alive``, ...) и любой приватный атрибут через ``.state`` —
    ноль обращений; прочие приватные имена драйвера (швы) — ровно литералы ``_SEAMS``. ``getattr`` / ``setattr`` /
    ``hasattr`` / ``delattr`` со строковым литералом считаются, ``self.`` и ``cls.`` — нет (свои классы теста).
    (б) Код вне пакета ``robot_driver_v2`` и вне тестов (``Services``, ``Plugins``, ``multiprocess_prototype``):
    импорт ``RobotState`` / ``RobotStateView`` / ``JogView`` / ``_JogRun`` и вызов переходов — ноль. Уникальные
    имена переходов ловятся при ЛЮБОМ получателе (псевдоним ``st = drv.state; st.begin_sync()`` виден); общие имена
    (``view``, ``enqueue_job``, ``stop_unconfirmed``, ...) — только через ``<…>.state.<имя>(``.
    Снятие швов — задача SPI хаба, не этого сторожа.

Public API:
    Только тесты ``test_*``.

Stability: lite
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_PKG = _ROOT / "Services" / "device_hub" / "drivers" / "robot_driver_v2"
_TEST_DIRS = (_ROOT / "Services" / "device_hub" / "tests", _ROOT / "Plugins" / "hub" / "device_hub" / "tests")
_OUTSIDE_DIRS = ("Services", "Plugins", "multiprocess_prototype")
_MARKERS = ("RobotDriverV2", "robot_driver_v2")
# Файлы драйвера v2 без маркеров в тексте (берут драйвер через помощники другого теста)
_EXTRA_V2_TESTS = ("test_t53f_m6_guard.py",)

# Бывшие поля состояния драйвера (до T5.3f) и поля RobotState: через объект драйвера — 0 обращений
_STATE_FIELDS = frozenset(
    {
        "_busy",
        "_prog_alive",
        "_program_active",
        "_prog_handle",
        "_job_active",
        "_jog",
        "_jog_starting",
        "_jog_stopping",
        "_last_hold",
        "_syncing",
        "_stopping",
        "_shutdown",
        "_stop_level",
        "_latch_level",
        "_latch_failed",
        "_latch_value",
        "_latch_attempts",
        "_echo_checked",
        "_stop_unconfirmed",
        "_stop_unconfirmed_text",
        "_own_stops",
        "_job_queue",
        "_return_queue",
        "_returns_done",
        "_returns_failed",
        "_flags_lock",
    }
)

# Швы тестов: приватное имя драйвера -> число обращений (AST, файлы драйвера v2). Снятие — задача SPI хаба.
_SEAMS = {
    "_client": 35,
    "_param_lock": 20,
    "_epoch": 16,
    "_resync_maybe": 7,
    "_jog_tx_lock": 5,
    "_last_reconnect": 5,
    "_ready": 3,
    "_transport": 3,
    "_activity_alive": 3,
    "_values": 2,
    "_last_resync": 2,
    "_process_stop": 1,
    "_store": 1,
    "_dispatch": 1,
}

# Переходы RobotState с общими именами: вне пакета ловятся только через ``<…>.state.<имя>(``
_COMMON_NAMES = frozenset({"view", "enqueue_job", "enqueue_return", "stop_unconfirmed", "stop_unconfirmed_text"})
_STATE_CLASSES = frozenset({"RobotState", "RobotStateView", "JogView", "_JogRun"})
_ATTR_FUNCS = frozenset({"getattr", "setattr", "hasattr", "delattr"})


def _transitions() -> frozenset[str]:
    """Публичные методы ``RobotState`` (переходы и ``view``) — из AST ``state.py``, без импорта пакета."""
    tree = ast.parse((_PKG / "state.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "RobotState")
    return frozenset(
        n.name
        for n in cls.body
        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_") and not _is_property(n)
    )


def _is_property(node: ast.FunctionDef) -> bool:
    return any(isinstance(d, ast.Name) and d.id == "property" for d in node.decorator_list)


def _driver_private_names() -> frozenset[str]:
    """Приватные имена драйвера: ``self._x`` и ``def _x`` во всех модулях пакета, кроме ``state.py``."""
    names: set[str] = set()
    for path in _PKG.glob("*.py"):
        if path.name == "state.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
                names.add(node.attr)
            elif isinstance(node, ast.FunctionDef):
                names.add(node.name)
    return frozenset(n for n in names if n.startswith("_") and not n.startswith("__"))


def _is_private(name: str) -> bool:
    return name.startswith("_") and not name.startswith("__")


def _v2_test_files() -> list[Path]:
    out: list[Path] = []
    for directory in _TEST_DIRS:
        for path in sorted(directory.glob("*.py")):
            if path.name == Path(__file__).name:
                continue
            text = path.read_text(encoding="utf-8")
            if path.name in _EXTRA_V2_TESTS or any(m in text for m in _MARKERS):
                out.append(path)
    return out


def _private_accesses(path: Path) -> list[tuple[str, int, bool]]:
    """``(имя, строка, через .state)`` каждого приватного обращения не через ``self`` / ``cls``."""
    found: list[tuple[str, int, bool]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Attribute) and _is_private(node.attr):
            base = node.value
            if isinstance(base, ast.Name) and base.id in ("self", "cls"):
                continue
            via_state = isinstance(base, ast.Attribute) and base.attr == "state"
            found.append((node.attr, node.lineno, via_state))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _ATTR_FUNCS
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
            and _is_private(node.args[1].value)
        ):
            arg0 = node.args[0]
            via_state = isinstance(arg0, ast.Attribute) and arg0.attr == "state"
            found.append((node.args[1].value, node.lineno, via_state))
    return found


def test_tests_do_not_touch_driver_state_fields() -> None:
    """(а) Поля состояния и приватные атрибуты ``.state`` в тестах драйвера v2 — 0 обращений."""
    files = _v2_test_files()
    assert files, "файлы драйвера v2 не найдены: сторож слеп"
    offenders = [
        f"{path.name}:{line} {name}"
        for path in files
        for name, line, via_state in _private_accesses(path)
        if name in _STATE_FIELDS or via_state
    ]
    assert offenders == [], offenders


def test_seam_whitelist_is_literal() -> None:
    """(а) Прочие приватные имена драйвера в тестах — ровно литералы ``_SEAMS`` (и никаких новых имён)."""
    driver_names = _driver_private_names() - _STATE_FIELDS
    seen: dict[str, int] = {}
    for path in _v2_test_files():
        for name, _line, via_state in _private_accesses(path):
            if name in driver_names and not via_state:
                seen[name] = seen.get(name, 0) + 1
    assert seen == _SEAMS


def _outside_files() -> list[Path]:
    out: list[Path] = []
    for top in _OUTSIDE_DIRS:
        for path in (_ROOT / top).rglob("*.py"):
            rel = path.relative_to(_ROOT)
            if "tests" in rel.parts or path.name.startswith("test_") or "__pycache__" in rel.parts:
                continue
            if _PKG in path.parents:
                continue
            out.append(path)
    return out


def _violations_outside(paths: list[Path], root: Path) -> list[str]:
    transitions = _transitions()
    unique = transitions - _COMMON_NAMES
    names = transitions | _STATE_CLASSES
    bad: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not any(n in text for n in names):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        rel = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(a.name in _STATE_CLASSES for a in node.names):
                bad.append(f"{rel}:{node.lineno} import {[a.name for a in node.names]}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                attr, owner = node.func.attr, node.func.value
                on_state = isinstance(owner, ast.Attribute) and owner.attr == "state"
                if attr in unique or (attr in transitions and on_state):
                    bad.append(f"{rel}:{node.lineno} .{attr}(")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in _ATTR_FUNCS
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in unique
            ):
                bad.append(f"{rel}:{node.lineno} {node.func.id}(..., {node.args[1].value!r})")
    return bad


def test_no_state_transitions_outside_package() -> None:
    """(б) Вне пакета и тестов нет импорта ``RobotState`` / ``_JogRun`` и вызовов переходов."""
    files = _outside_files()
    assert len(files) > 100, "обход кода вне пакета не нашёл файлов: сторож слеп"
    assert _violations_outside(files, _ROOT) == []


def test_guard_sees_aliased_transition_call(tmp_path: Path) -> None:
    """Сам сторож (б) видит ``st = drv.state; st.begin_sync()`` и импорт ``RobotState`` в чужом модуле."""
    alias = tmp_path / "alias.py"
    alias.write_text("def f(drv):\n    st = drv.state\n    return st.begin_sync()\n", encoding="utf-8")
    imp = tmp_path / "imp.py"
    imp.write_text("from Services.device_hub.drivers.robot_driver_v2 import RobotState\n", encoding="utf-8")
    common = tmp_path / "common.py"
    common.write_text("def f(drv):\n    return drv.state.enqueue_job(1)\n", encoding="utf-8")
    plain = tmp_path / "plain.py"
    plain.write_text("def f(drv):\n    return drv.enqueue_job(1)\n", encoding="utf-8")
    assert len(_violations_outside([alias], tmp_path)) == 1
    assert len(_violations_outside([imp], tmp_path)) == 1
    assert len(_violations_outside([common], tmp_path)) == 1
    assert _violations_outside([plain], tmp_path) == []
