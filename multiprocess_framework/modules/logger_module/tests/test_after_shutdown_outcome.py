# -*- coding: utf-8 -*-
"""Task 0.6 (L-4): запись ПОСЛЕ останова логгера не числится доставленной.

Сценарий — ``r6_after_shutdown.py`` (design.md §3): у закрытого менеджера реестр
каналов пуст, и до правки ``_log_warning`` отвечал ``True`` (менеджер не бросил),
хотя запись никуда не легла. Теперь закрытый ``LoggerCore.log()`` возвращает
часового ``REFUSED``, миксин читает его как «не доставлено», счёт идёт в
``channel_refused_records``, а текст уходит аварийным выходом (``emergency_log``)
с префиксом ``[logger closed]`` — не более 20 строк на менеджер.

Ожидаемые значения — литералы из ACCEPTANCE задачи, а не выводы из кода.

**Как ловится аварийная строка.** ``emergency_log`` пишет в stdlib-логгер, и в
stderr запись попадает только через ``logging.lastResort``, то есть когда у
корня НЕТ обработчиков. Под pytest у корня обработчики есть (плагин логирования),
поэтому ``capfd`` по stderr в процессе теста пуст по построению. Поэтому два
способа: (1) ОДИН тест гоняет чистый дочерний интерпретатор и читает его
настоящий stderr — это единственная проверка адреса; (2) остальные вешают свой
``logging.Handler`` на корень и читают записи — быстро и без подпроцесса.
"""

from __future__ import annotations

import copy
import logging
import os
import pickle
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from multiprocess_framework.modules.base_manager import BaseManager, ObservableMixin
from multiprocess_framework.modules.base_manager.mixins import observable_mixin as _mixin
from multiprocess_framework.modules.logger_module.core import logger_core as _logger_core_module
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

_ROOT = Path(__file__).resolve().parents[4]
_PREFIX = "[logger closed]"
_JOIN_DEADLINE_S = 5.0


class _Probe(BaseManager, ObservableMixin):
    """Потребитель миксина: ровно та дверь (``_log_warning``), что у боевых менеджеров."""

    def __init__(self, lm):
        BaseManager.__init__(self, "probe")
        ObservableMixin.__init__(self, managers={"logger": lm}, config={"logger": True})

    def initialize(self):
        self.is_initialized = True
        return True

    def _on_shutdown(self):
        return True


class _Collect(logging.Handler):
    """Собирает записи stdlib-корня; ``lines()`` отдаёт только аварийные строки закрытого логгера."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)

    def closed_records(self):
        return [r for r in list(self.records) if _PREFIX in str(r.msg)]

    def lines(self):
        # getMessage() здесь, в потоке теста: кривой формат даст исключение и красный тест.
        return [r.getMessage() for r in self.closed_records()]


@pytest.fixture
def emergency():
    """Ловец аварийных строк на корне + логгер ``logger_core`` поднят до DEBUG.

    Без подъёма уровня «0 строк для INFO» вакуумно: у логгера нет своего уровня, корень стоит на
    WARNING, и запись INFO отсекается ДО обработчика независимо от того, пишет ли код её вообще.
    """
    handler = _Collect()
    root = logging.getLogger()
    emitter = logging.getLogger(_logger_core_module.__name__)
    saved_level = emitter.level
    emitter.setLevel(logging.DEBUG)
    root.addHandler(handler)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        emitter.setLevel(saved_level)


@pytest.fixture
def lm(tmp_path):
    manager = LoggerManager(config={"log_directory": str(tmp_path)})
    try:
        yield manager
    finally:
        manager.shutdown()


def _delta(before, after, key):
    return after[key] - before[key]


# ---------------------------------------------------------------------------
# Исход: «не доставлено»
# ---------------------------------------------------------------------------


def test_before_shutdown_path_unchanged(lm):
    """Контроль: до останова прежний путь — ``None`` / ``True``, отказа нет; чистый останов тоже не отказывает."""
    m = _Probe(lm)
    m.initialize()
    s0 = lm.get_stats()
    assert lm.warning("early line", module="probe") is None
    assert m._log_warning("early line") is True
    s1 = lm.get_stats()
    assert _delta(s0, s1, "channel_refused_records") == 0
    lm.shutdown()
    s2 = lm.get_stats()
    assert _delta(s1, s2, "channel_refused_records") == 0, "штатный останов отказал собственным прощальным записям"


def test_tap_close_line_before_flag_is_delivered(lm, tmp_path):
    """Контроль: строка из ``close()`` tap'а («store flush») доходит — флаг ставится ПОЗЖЕ ``close_all_taps()``."""

    class _FlushTap:
        name = "flush_tap"

        def write(self, record):
            return {"status": "ok"}

        def close(self):
            lm.warning("store flush: 3 written, 0 lost", module="probe")

    lm.add_tap(_FlushTap(), min_level="DEBUG")
    s0 = lm.get_stats()
    lm.shutdown()
    s1 = lm.get_stats()
    assert _delta(s0, s1, "channel_refused_records") == 0
    text = "".join(p.read_text(encoding="utf-8", errors="replace") for p in tmp_path.rglob("*") if p.is_file())
    assert "store flush: 3 written, 0 lost" in text


def test_warning_after_shutdown_not_delivered(lm):
    m = _Probe(lm)
    m.initialize()
    assert m._log_warning("early line") is True
    lm.shutdown()
    assert m._log_warning("late shutdown line") is False


def test_refused_counter_grows(lm, emergency):
    """Гейт первым; потом +1 на запись; путь (а) не трогает ``unresolved_channel_records``; INFO — счёт без строки."""
    lm.shutdown()
    # DEBUG ниже порога INFO по умолчанию: гейт отклонил бы запись и до останова — это НЕ отказ.
    s0 = lm.get_stats()
    assert lm.debug("gate rejects this", module="probe") is None
    s1 = lm.get_stats()
    assert _delta(s0, s1, "channel_refused_records") == 0

    # INFO проходит гейт: отказ учтён, но аварийной строки нет (она — от WARNING).
    assert lm.info("late info line", module="probe") is _mixin.REFUSED
    s2 = lm.get_stats()
    assert _delta(s1, s2, "channel_refused_records") == 1
    assert emergency.lines() == []

    assert lm.warning("late shutdown line", module="probe") is _mixin.REFUSED
    s3 = lm.get_stats()
    assert _delta(s2, s3, "channel_refused_records") == 1
    assert _delta(s2, s3, "unresolved_channel_records") == 0


def test_error_after_shutdown_goes_to_floor(lm, emergency):
    lm.shutdown()
    s0 = lm.get_stats()
    assert lm.error("late error line", module="probe") is _mixin.REFUSED
    s1 = lm.get_stats()
    assert _delta(s0, s1, "errors_to_floor") == 1
    assert _delta(s0, s1, "channel_refused_records") == 1
    floor_text = Path(lm.error_floor.stats["path"]).read_text(encoding="utf-8")
    assert floor_text.count("late error line") == 1
    # ERROR идёт тем же аварийным путём, что и WARNING: одна строка, уровень записи сохранён.
    assert [r.levelname for r in emergency.closed_records()] == ["ERROR"]
    assert emergency.lines() == [f"{_PREFIX} probe: late error line"]


# ---------------------------------------------------------------------------
# Аварийная строка
# ---------------------------------------------------------------------------


def test_warning_after_shutdown_on_emergency_stderr(tmp_path):
    """Единственная проверка АДРЕСА: чистый интерпретатор, настоящий stderr (lastResort).

    В процессе теста этого не проверить: у корня pytest есть обработчики, и
    ``lastResort`` не включается. Не утверждаем «пишет в ``sys.__stderr__``» —
    читаем то, что реально вышло.
    """
    code = (
        "import sys\n"
        "from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager\n"
        "lm = LoggerManager(config={'log_directory': sys.argv[1]})\n"
        "lm.shutdown()\n"
        "lm.warning('late shutdown line', module='probe')\n"
    )
    env = {**os.environ, "PYTHONPATH": str(_ROOT), "PYTHONUTF8": "1"}
    proc = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        cwd=str(_ROOT),
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    closed = [line for line in proc.stderr.splitlines() if _PREFIX in line]
    assert len(closed) == 1, proc.stderr
    assert "late shutdown line" in closed[0]
    assert "probe: late shutdown line" in closed[0]


def test_closed_line_is_throttled_to_20_per_manager(tmp_path, emergency):
    """25 вызовов подряд -> 20 строк, счёт отказов +25; 4 потока x 25 -> те же 20 строк, +100 (лок счётчика строк)."""
    seq = LoggerManager(config={"log_directory": str(tmp_path / "seq")})
    seq.shutdown()
    s0 = seq.get_stats()
    for i in range(25):
        assert seq.warning(f"late shutdown line {i}", module="probe") is _mixin.REFUSED
    s1 = seq.get_stats()
    assert len(emergency.lines()) == 20
    assert _delta(s0, s1, "channel_refused_records") == 25

    emergency.records.clear()
    par = LoggerManager(config={"log_directory": str(tmp_path / "par")})
    par.shutdown()
    p0 = par.get_stats()
    go = threading.Event()

    def worker(k):
        go.wait(_JOIN_DEADLINE_S)
        for i in range(25):
            par.warning(f"late shutdown line {k}-{i}", module="probe")

    threads = [threading.Thread(target=worker, args=(k,), daemon=True) for k in range(4)]
    for t in threads:
        t.start()
    go.set()
    for t in threads:
        t.join(_JOIN_DEADLINE_S)
    assert not any(t.is_alive() for t in threads)
    p1 = par.get_stats()
    assert len(emergency.lines()) == 20
    assert _delta(p0, p1, "channel_refused_records") == 100


def test_closed_line_has_no_secret(lm, emergency):
    """Текст идёт из записи ПОСЛЕ процессоров: редактор секретов уже отработал."""
    lm.shutdown()
    lm.warning("late shutdown line password=hunter2", module="probe")
    lines = emergency.lines()
    assert len(lines) == 1
    assert "hunter2" not in lines[0]
    assert "password=***" in lines[0]


def test_closed_line_survives_percent_in_message(lm, emergency):
    """Текст — АРГУМЕНТОМ эмиссии: ``%`` в сообщении не должен тихо стереть строку."""
    lm.shutdown()
    lm.warning("disk 100% full, 50%d left %s", module="probe")
    assert emergency.lines() == [f"{_PREFIX} probe: disk 100% full, 50%d left %s"]


def test_closed_line_without_module_has_no_module_prefix(lm, emergency):
    """Источник называется в строке; пустой ``module`` — строка без префикса источника."""
    lm.shutdown()
    lm.warning("bare line", module="")
    assert emergency.lines() == [f"{_PREFIX} bare line"]


# ---------------------------------------------------------------------------
# Порядок внутри останова, tap'ы, лок дросселя (правки по ревью стадии 5)
# ---------------------------------------------------------------------------


class _RecordingTap:
    name = "late_tap"

    def __init__(self):
        self.records = []

    def write(self, record):
        self.records.append(record)
        return {"status": "ok"}

    def close(self):
        return None


class _LockSpyLogger(LoggerManager):
    """LoggerManager, у которого счётчик строк дросселя запоминает, под ``_miss_lock`` ли его читают и пишут."""

    @property
    def _closed_lines_emitted(self):
        self.__dict__.setdefault("_lock_spy", []).append(("read", self._miss_lock.locked()))
        return self.__dict__.get("_spy_value", 0)

    @_closed_lines_emitted.setter
    def _closed_lines_emitted(self, value):
        self.__dict__.setdefault("_lock_spy", []).append(("write", self._miss_lock.locked()))
        self.__dict__["_spy_value"] = value


def test_record_inside_shutdown_window_after_registry_clear_is_refused(lm, monkeypatch):
    """Флаг ставится ДО ``registry.clear()``: запись в окне между очисткой и концом останова — отказ."""
    m = _Probe(lm)
    m.initialize()
    original_clear = lm._channel_registry.clear
    inside = []

    def clear_then_write():
        channels = original_clear()
        inside.append(m._log_warning("in-window line"))
        return channels

    monkeypatch.setattr(lm._channel_registry, "clear", clear_then_write)
    s0 = lm.get_stats()
    lm.shutdown()
    s1 = lm.get_stats()
    assert inside == [False]
    assert _delta(s0, s1, "channel_refused_records") == 1


def test_tap_added_after_shutdown_gets_nothing(lm):
    """Путь (а) стоит ДО блока tap'ов: отказанная запись не уходит ещё и в tap."""
    lm.shutdown()
    tap = _RecordingTap()
    lm.add_tap(tap, min_level="DEBUG")
    s0 = lm.get_stats()
    assert lm.warning("late shutdown line", module="probe") is _mixin.REFUSED
    s1 = lm.get_stats()
    assert tap.records == []
    assert _delta(s0, s1, "channel_refused_records") == 1


def test_closed_line_counter_is_read_and_written_under_the_miss_lock(tmp_path):
    """Решение о строке (чтение) и прибавка (запись) дросселя — под ``_miss_lock``, детерминированно."""
    spy = _LockSpyLogger(config={"log_directory": str(tmp_path)})
    try:
        spy.shutdown()
        for i in range(3):
            assert spy.warning(f"late shutdown line {i}", module="probe") is _mixin.REFUSED
        events = spy.__dict__["_lock_spy"]
        kinds = [kind for kind, _locked in events]
        # Три записи → три прибавки; чтений не меньше трёх (проверка «меньше 20» плюс чтение в ``+=``).
        assert kinds.count("write") == 3
        assert kinds.count("read") >= 3
        assert all(locked for _kind, locked in events), events
    finally:
        spy.shutdown()


# ---------------------------------------------------------------------------
# Окно голоса: закрытый менеджер — состояние постоянное, слот не возвращается
# ---------------------------------------------------------------------------


def test_report_error_after_shutdown_is_throttled_by_the_window(lm):
    """3000 ``report_error`` после останова: ОДИН голос (одна строка в полу, один отказ), остальные гасит окно.

    До решения лида по окну голоса слот возвращался на каждом ``REFUSED``, и окно переставало
    дросселировать: 3000 строк в полу вместо одной.
    """
    m = _Probe(lm)
    m.initialize()
    lm.shutdown()
    s0 = lm.get_stats()
    for _ in range(3000):
        m.report_error(ValueError("late boom"), "ctx", throttle=3600.0)
    s1 = lm.get_stats()
    floor_text = Path(lm.error_floor.stats["path"]).read_text(encoding="utf-8")
    assert floor_text.count("late boom") == 1
    assert _delta(s0, s1, "channel_refused_records") == 1
    assert _delta(s0, s1, "errors_to_floor") == 1


def test_log_windowed_after_shutdown_is_throttled_by_the_window(lm):
    m = _Probe(lm)
    m.initialize()
    lm.shutdown()
    s0 = lm.get_stats()
    for _ in range(5):
        assert m.log_windowed("late_key", interval=3600.0, level="warning", message="late windowed") is False
    s1 = lm.get_stats()
    assert _delta(s0, s1, "channel_refused_records") == 1


def test_refused_sentinel_is_falsy_and_keeps_identity(lm):
    """Старое ``if lm.warning(...)`` после останова читает ложь; тождество (``is``) и копии целы."""
    refused = _mixin.REFUSED
    assert bool(refused) is False
    assert repr(refused) == "REFUSED"
    assert copy.copy(refused) is refused
    assert copy.deepcopy(refused) is refused
    assert pickle.loads(pickle.dumps(refused)) is refused
    lm.shutdown()
    result = lm.warning("late shutdown line", module="probe")
    assert result is refused
    assert not result
    assert lm.info("late info line", module="probe") is refused


# ---------------------------------------------------------------------------
# Гонка: останов во время записи
# ---------------------------------------------------------------------------


def test_race_zero_accepted_returns_refused(lm, monkeypatch):
    """Путь (б), детерминированно: останов случается между проверкой и циклом по каналам."""
    original = lm._write_record_to_channels

    def closing_first(record, names):
        lm._closed = True
        lm._channel_registry.clear()
        return original(record, names)

    monkeypatch.setattr(lm, "_write_record_to_channels", closing_first)
    s0 = lm.get_stats()
    assert lm.warning("race line", module="probe") is _mixin.REFUSED
    s1 = lm.get_stats()
    assert _delta(s0, s1, "channel_refused_records") == 1


def test_race_error_zero_accepted_floor_once(lm, monkeypatch):
    """Путь (б) для ERROR: пол уже спас запись внутри ``_write_error_record`` — второй копии нет."""
    original = lm._write_record_to_channels

    def closing_first(record, names):
        lm._closed = True
        lm._channel_registry.clear()
        return original(record, names)

    monkeypatch.setattr(lm, "_write_record_to_channels", closing_first)
    s0 = lm.get_stats()
    assert lm.error("race error line", module="probe") is _mixin.REFUSED
    s1 = lm.get_stats()
    assert _delta(s0, s1, "errors_to_floor") == 1
    assert _delta(s0, s1, "channel_refused_records") == 1
    assert Path(lm.error_floor.stats["path"]).read_text(encoding="utf-8").count("race error line") == 1


def test_warning_race_no_true_after_shutdown_returns(lm):
    """Hazard: ни одной ``True`` у записи, НАЧАТОЙ после возврата ``shutdown()``.

    Записи «в полёте» (``t_start < t_ret < t_end``) допустимы. Тест вакуумен без
    ``True`` ДО останова и без записи ПОСЛЕ — оба факта проверяются явно. Путь (б)
    он не доказывает (его доказывает ``test_race_zero_accepted_returns_refused``).
    """
    m = _Probe(lm)
    m.initialize()
    stop = threading.Event()
    saw_true = threading.Event()
    saw_after = threading.Event()
    t_ret_box: list[int] = []
    results: list[list[tuple[int, int, object]]] = [[] for _ in range(4)]

    def worker(slot):
        mine = results[slot]
        while not stop.is_set():
            t0 = time.monotonic_ns()
            value = m._log_warning("race line")
            mine.append((t0, time.monotonic_ns(), value))
            if value is True:
                saw_true.set()
            if t_ret_box and t0 >= t_ret_box[0]:
                saw_after.set()

    threads = [threading.Thread(target=worker, args=(k,), daemon=True) for k in range(4)]
    for t in threads:
        t.start()
    try:
        assert saw_true.wait(_JOIN_DEADLINE_S), "ни одной True до останова — тест вакуумен"
        lm.shutdown()
        t_ret_box.append(time.monotonic_ns())
        assert saw_after.wait(_JOIN_DEADLINE_S), "ни одной записи после останова — тест вакуумен"
    finally:
        stop.set()
        for t in threads:
            t.join(_JOIN_DEADLINE_S)
    assert not any(t.is_alive() for t in threads)
    t_ret = t_ret_box[0]
    flat = [r for per_thread in results for r in per_thread]
    late_true = [r for r in flat if r[0] >= t_ret and r[2] is True]
    assert late_true == [], f"{len(late_true)} записей, начатых после shutdown(), ответили True"
    assert any(r[2] is True and r[1] < t_ret for r in flat)
    assert any(r[0] >= t_ret and r[2] is False for r in flat)
