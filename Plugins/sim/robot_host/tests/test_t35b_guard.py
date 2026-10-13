# -*- coding: utf-8 -*-
"""Страж T3.5b: миграция тестов T2.4 хоста ``robot_host`` не потеряла проверок.

Purpose: механически доказать пять вещей про 4 мигрируемых файла (``test_v2_host.py``,
``test_v2_letter_straight.py``, ``test_v2_line_cycle.py``, ``test_v2_real_worker_manager.py``)
и обвязку ``host_harness.py``: самописного водителя протокола нет; адресов регистров и опкодов
mailbox руками нет; тесты идут через клиент v2 (разбор AST); старые имена тестов на месте;
литералы ожиданий на месте (счёт вхождений подстрок из описи ``T3.5b.guard.md``).

Срок жизни: временный. Файл удаляется при закрытии T3.7 (запись об этом — в плане
``plans/robot-protocol-v2/plan.md``, строка T3.5b).

Чего страж НЕ доказывает: поведение. Это текстовая проверка: она не видит ослабление условия
внутри ``assert`` с теми же литералами (``==`` -> ``in``, снятое сравнение при сохранённой
константе), порядок вызовов, окно «три опроса подряд», одиночность FC3. Поведение держат прогон
16 узлов T2.4 и матрица инъекций лида; свойства, которых текст не держит, названы в описи
``T3.5b.guard.md`` как «глаз» (сверка ревьюером по диффу) и «не держится ничем».

Чистый Python: без сети, без ``subprocess`` и ``git``, без импорта обвязки и плагина. Сам файл
стража в проверки не входит.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

__all__: list[str] = []

DIR = Path(__file__).resolve().parent
ROOT = DIR.parent  # Plugins/sim/robot_host
SELF = Path(__file__).resolve()

# Имя файла водителя собрано из частей: в файле стража нет подстроки с именем водителя.
_DRIVER_NAME = "v2" + "_driver"
DRIVER = DIR / f"{_DRIVER_NAME}.py"
HARNESS = DIR / "host_harness.py"
HARNESS_MODULE = "Plugins.sim.robot_host.tests.host_harness"

HOST = "test_v2_host.py"
LETTER = "test_v2_letter_straight.py"
CYCLE = "test_v2_line_cycle.py"
REAL_WM = "test_v2_real_worker_manager.py"
MIGRATED = (HOST, LETTER, CYCLE, REAL_WM)
WITH_JOB = (LETTER, CYCLE, REAL_WM)

_DRIVER_RE = re.compile("(?i)" + _DRIVER_NAME + "|v2" + "driver")
# Старшие байты REG (замер по protocol_v2.REG, 48 имён в 0x1000..0x3082): 0x10, 0x14, 0x30.
_ADDRESS_RE = re.compile(r"(?i)\b0x(10|14|30)[0-9a-f]{2}\b")
_MAILBOX_RE = re.compile(
    r"\bOP\[|OP_SPEC|\.cmd\(|\.write_\w+\(|\.transaction\(|ModbusSdkClient|CMD_|RES_(SEQ|STATUS|RVALS)"
)
_READ_RE = re.compile(r"\.read_\w+\(")

# Имена тестовых функций базы (14 функций, 16 собранных тестов в 4 файлах): терять нельзя, добавлять можно.
_TEST_NAMES: dict[str, set[str]] = {
    HOST: {
        "test_status_protocol_matches_wire",
        "test_default_protocol_is_v1",
        "test_tcp_reads_pmir_block",
        "test_no_raw_threads_under_v2_host",
        "test_fault_commands_refused_on_v2",
        "test_belt_commands_on_v2",
        "test_unknown_protocol_is_error_without_value",
        "test_restart_after_shutdown_rebinds_port",
    },
    LETTER: {"test_letter_is_straight_after_placement"},
    CYCLE: {"test_frame_to_job_to_done_cycle"},
    REAL_WM: {
        "test_v2_host_restarts_cleanly_under_real_worker_manager",
        "test_scene_job_done_t_is_plugin_monotonic_not_sim_time",
        "test_start_fails_when_ticker_worker_never_runs",
    },
}

_FAULT_PARAM_ROWS = (
    '("fault.drop", {"seconds": 7919}, "7919")',
    '("fault.delay_ms", {"ms": 7919}, "7919")',
    '("fault.vfd_code", {"code": 7919}, "7919")',
    '("fault.clear", {}, None)',
)

# Литералы ожиданий из описи T3.5b.guard.md (только строки «чем держится: страж»): (подстрока, минимум
# вхождений). Подстроки точные, из файлов базы; только литералы внутри сравнений и аргументов проверяемого
# вызова, константы модуля, на которых стоит сравнение, и параметры parametrize. Тексты сообщений
# ``assert ..., "..."`` и ``pytest.fail("...")`` сюда не входят, как и всё, что по решению лида
# исчезает при миграции (вызовы водителя, ACK, mm10, to_u16, seq-литералы цикла, тексты отказов соединения).
_LITERALS: dict[str, list[tuple[str, int]]] = {
    HOST: [
        ("_PROTO_V2_WIRE = 0x0200", 1),  # H1, H8, константа провода v2
        ("_PROTO_V2_WIRE", 4),  # определение + 3 проверки (H1, H8 x2)
        ("_PMIR_MAGIC_WIRE = 0x5632", 1),  # H3
        ("block[0] == _PMIR_MAGIC_WIRE", 1),  # H3
        ('"PMIR_MAGIC"', 1),  # H3: чтение по имени REG
        (", 3)", 1),  # H3: три слова одним чтением
        ('.get("protocol") == "v2"', 1),  # H1
        ('.get("protocol") == "v1"', 1),  # H2
        ('{"sim-robot-motion", "sim-robot-server"}', 1),  # H4
        ("_RAW_THREAD_NAMES <= v1_threads", 1),  # H4: базовая линия v1
        ("not (_RAW_THREAD_NAMES & v2_threads)", 1),  # H4: под v2 сырых потоков нет
        ("n2 >= n1 + 2", 1),  # H4
        ("time.monotonic() + 3.0", 1),  # H4: слив потоков v1 до 3.0 с
        (_FAULT_PARAM_ROWS[0], 1),  # H5
        (_FAULT_PARAM_ROWS[1], 1),  # H5
        (_FAULT_PARAM_ROWS[2], 1),  # H5
        (_FAULT_PARAM_ROWS[3], 1),  # H5
        ('resp.get("status") == "error"', 1),  # H5
        ('"не поддерживается" in message', 1),  # H5
        ('"v2" in message', 1),  # H5
        ("secret not in message", 1),  # H5: значение не эхом
        ("jog_timeout_ms=500, publish_ms=50", 1),  # H6
        ('"belt.run", {"freq_hz": 25}', 1),  # H6
        ('"belt.jog", {"direction": 1, "freq_hz": 10}', 1),  # H6
        ('.get("ok") is True', 3),  # H6: belt.run, belt.stop, belt.jog
        ('call(plugin, "belt.status").get("run") is True', 1),  # H6
        ("time.sleep(0.5)", 1),  # H6
        ("time.sleep(0.3)", 2),  # H6: после belt.stop и после belt.jog
        ("e1 > e0", 1),  # H6: энкодер растёт при belt.run
        ("!= base", 1),  # H6: jog сдвинул энкодер
        ("timeout=2.5, interval=0.15", 1),  # H6
        ("stable[0] >= 3", 1),  # H6: три одинаковых опроса подряд
        ('protocol="v3"', 1),  # H7
        ("isinstance(status, dict)", 1),  # H7
        ('status.get("state") == "error"', 1),  # H7
        ('"v3" not in repr(status)', 1),  # H7
        ("timeout: float = 3.0", 1),  # H8
        ('probe.bind(("127.0.0.1", port))', 1),  # H8
        ("assert _port_is_free(port)", 1),  # H8
    ],
    LETTER: [
        ("\nTOOL_SIGN = +1\n", 1),  # L1: определение целой строкой (упоминание в докстринге не засчитывается)
        ("[30.0, -45.0, 0.0]", 1),  # L1
        ("_TOLERANCE_DEG = 1.0", 1),  # L1
        ("(300.0, -200.0)", 1),  # L1
        ("(400.0, 100.0)", 1),  # L1
        ('"AAA", (0.0, 0.0), (100.0, 0.0)', 1),  # L1
        ('offer("A", disc_deg, True, zero_deg=0.0, sign=1.0)', 1),  # L1
        ("_PICK_MM[0]", 1),  # L1: pick в вызове задания
        ("_PLACE_MM[1]", 1),  # L1: place в вызове задания
        ("/ 10.0", 2),  # L1: P_PICK_RZ и TLM_RZ в единицах 0.1 град
        ("0x0200", 1),  # L1: провод v2
        ("(deg + 180.0) % 360.0 - 180.0", 1),  # L1
        ("TOOL_SIGN * (rz_deg - p_pick_rz_deg)", 1),  # L1
        ("abs(letter_deg) > _TOLERANCE_DEG", 1),  # L1
        ("assert not failures", 1),  # L1
    ],
    CYCLE: [
        ('{"origin_x_mm": 300.0, "origin_y_mm": -200.0}', 1),  # C1
        ("_PLACE_X_MM, _PLACE_Y_MM, _PLACE_RZ_DEG = 400.0, 100.0, 45.0", 1),  # C1
        ("_JOB_INDEX = 1", 1),  # C1
        ('scene_process="camera"', 1),  # C1
        ("0x0200", 1),  # C1: провод v2
        ('scene.produce()[0]["frame"] is not None', 1),  # C1
        ("len(objects) == 1", 1),  # C1
        ("int(passport.spawn_encoder)", 1),  # C1: ecap = энкодер объекта
        ("BeltGeometry.from_dict(_GEOMETRY_CFG)", 1),  # C1: pick из паспорта сцены
        ("lateral_px=passport.lateral_px", 1),  # C1
        ("time.monotonic() + 5.0", 1),  # C1: одно scene.job_done за 5.0 с
        ("len(sent) == 1", 1),  # C1
        ('(target, command) == ("camera", "scene.job_done")', 1),  # C1
        ('args["index"] == _JOB_INDEX', 1),  # C1
        ('== [(_JOB_INDEX, "matched")]', 1),  # C1
        ('status["active"] == 0', 1),  # C1
    ],
    REAL_WM: [
        ("_CYCLES = 3", 1),  # R1
        ("range(_CYCLES)", 1),  # R1
        ("_PROTO_V2_WIRE = 0x0200", 1),  # R1
        ("_PROTO_V2_WIRE", 3),  # R1, R2: определение + 2 проверки
        ("_HB_GROWTH_DEADLINE_S = 1.0", 1),  # R1
        ("_PORT_FREE_DEADLINE_S = 5.0", 1),  # R1
        ('["state"] == "running"', 1),  # R1
        ("timeout=3.0", 1),  # R1: соединение за 3.0 с
        ("& 0xFFFF < 0x8000", 1),  # R1: рост HB по кругу 16 бит
        ("_wait_until(lambda: _port_is_free(port), _PORT_FREE_DEADLINE_S)", 2),  # R1, R3
        ('"protocol": "v2"', 2),  # R1, R3: конфиг хоста
        ("_PICK_X_MM, _PICK_Y_MM = 300.0, -200.0", 1),  # R2
        ("_PLACE_X_MM, _PLACE_Y_MM, _PLACE_RZ_DEG = 400.0, 100.0, 45.0", 1),  # R2
        ("t_before_start = time.monotonic()", 1),  # R2
        ('scene_process="camera"', 1),  # R2
        ("_wait_until(lambda: bool(sent), 5.0)", 1),  # R2
        ("len(sent) == 1", 1),  # R2
        ('sent[0]["command"] == "scene.job_done"', 1),  # R2
        ("abs(event_t - t_after) < 5.0", 1),  # R2
        ("event_t >= t_before_start", 1),  # R2
        ('"sim_robot_ticker"', 2),  # R3: create_worker и start_worker подмены
        ('"_V2_TICKER_TIMEOUT_S", 0.3', 1),  # R3
        ('["state"] == "error"', 1),  # R3
    ],
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _scope() -> list[Path]:
    """4 мигрируемых файла + обвязка и файл водителя, если они есть."""
    files = [DIR / name for name in MIGRATED]
    files += [path for path in (HARNESS, DRIVER) if path.exists()]
    return files


def _scan(files: list[Path], pattern: re.Pattern[str]) -> list[str]:
    """Нарушения ``файл:строка: текст`` — все строки файлов, где ``pattern`` находит совпадение."""
    found: list[str] = []
    for path in files:
        for number, line in enumerate(_read(path).splitlines(), start=1):
            if pattern.search(line):
                found.append(f"{path.name}:{number}: {line.strip()}")
    return found


def _fail(title: str, violations: list[str]) -> None:
    assert not violations, f"{title}:\n" + "\n".join(violations)


def _calls(tree: ast.AST) -> list[ast.Call]:
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)]


def _has_call_name(tree: ast.AST, name: str) -> bool:
    return any(isinstance(c.func, ast.Name) and c.func.id == name for c in _calls(tree))


def _has_call_attr(tree: ast.AST, attr: str, first_arg: str | None = None) -> bool:
    for call in _calls(tree):
        if not (isinstance(call.func, ast.Attribute) and call.func.attr == attr):
            continue
        if first_arg is None:
            return True
        if call.args and isinstance(call.args[0], ast.Constant) and call.args[0].value == first_arg:
            return True
    return False


def test_no_old_driver_left() -> None:
    """Файла самописного водителя нет; имени водителя нет ни в одном ``*.py``/``*.md`` пакета хоста."""
    violations: list[str] = []
    if DRIVER.exists():
        violations.append(f"{DRIVER.name}:1: файл водителя существует")
    for suffix in ("*.py", "*.md"):
        for path in sorted(ROOT.rglob(suffix)):
            if "__pycache__" in path.parts or path.resolve() == SELF:
                continue
            for number, line in enumerate(_read(path).splitlines(), start=1):
                if _DRIVER_RE.search(line):
                    violations.append(f"{path.relative_to(ROOT).as_posix()}:{number}: {line.strip()}")
    _fail("самописный водитель остался", violations)


def test_no_handwritten_addresses() -> None:
    """В тестах и обвязке нет адресов регистров руками (``0x10xx``, ``0x14xx``, ``0x30xx``): только имена ``REG``."""
    _fail("адреса регистров руками", _scan(_scope(), _ADDRESS_RE))


def test_no_handwritten_mailbox() -> None:
    """В тестах и обвязке нет опкодов, адресов mailbox и сырых записей; любое ``.read_*(`` идёт по ``REG[``."""
    violations = _scan(_scope(), _MAILBOX_RE)
    for path in _scope():
        for number, line in enumerate(_read(path).splitlines(), start=1):
            if _READ_RE.search(line) and "REG[" not in line:
                violations.append(f"{path.name}:{number}: чтение не по REG[...]: {line.strip()}")
    _fail("протокол mailbox руками", violations)


def test_migrated_files_use_client() -> None:
    """Обвязка есть; 4 файла берут ее и ``open_client``; файлы с заданием вызывают ``cvt_job`` и ``wait_done_hb``;
    тест буквы читает ``P_PICK_RZ`` командой ``param_get``. Разбор AST, не подстроки."""
    violations: list[str] = []
    if not HARNESS.exists():
        violations.append(f"{HARNESS.name}:1: файла обвязки нет")
    for name in MIGRATED:
        tree = ast.parse(_read(DIR / name), filename=name)
        imports_harness = any(isinstance(n, ast.ImportFrom) and n.module == HARNESS_MODULE for n in ast.walk(tree))
        if not imports_harness:
            violations.append(f"{name}:1: нет `from {HARNESS_MODULE} import ...`")
        if not _has_call_name(tree, "open_client"):
            violations.append(f"{name}:1: нет вызова open_client(...)")
        if name in WITH_JOB:
            if not _has_call_attr(tree, "cvt_job"):
                violations.append(f"{name}:1: нет вызова <клиент>.cvt_job(...)")
            if not _has_call_name(tree, "wait_done_hb"):
                violations.append(f"{name}:1: нет вызова wait_done_hb(...)")
        if name == LETTER and not _has_call_attr(tree, "param_get", "P_PICK_RZ"):
            violations.append(f'{name}:1: нет вызова <клиент>.param_get("P_PICK_RZ")')
    _fail("миграция идет не через клиент", violations)


def test_old_test_names_kept() -> None:
    """Все старые тестовые функции на месте (новые можно добавлять), в ``test_v2_host.py`` — 4 строки параметров."""
    violations: list[str] = []
    for name, expected in _TEST_NAMES.items():
        text = _read(DIR / name)
        have = set(re.findall(r"^def (test_\w+)\(", text, flags=re.M))
        for missing in sorted(expected - have):
            violations.append(f"{name}:1: нет тестовой функции {missing}")
    host_text = _read(DIR / HOST)
    for row in _FAULT_PARAM_ROWS:
        if row not in host_text:
            violations.append(f"{HOST}:1: нет строки параметров {row}")
    _fail("старые тесты потеряны", violations)


def test_expectation_literals_kept() -> None:
    """Литералы ожиданий из описи на месте: каждая подстрока встречается не меньше, чем в файле базы."""
    violations: list[str] = []
    for name, rows in _LITERALS.items():
        text = _read(DIR / name)
        for needle, minimum in rows:
            have = text.count(needle)
            if have < minimum:
                violations.append(f"{name}:1: {needle!r} встречается {have} раз, нужно не меньше {minimum}")
    _fail("литералы ожиданий потеряны", violations)
