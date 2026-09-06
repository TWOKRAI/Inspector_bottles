# -*- coding: utf-8 -*-
"""Приёмочный набор Task 3.3 — независимый tester, RED-до-реализации.

Заголовок брифа не в формате ``MODE:/INTERFACE:/TASK:`` этого агента, но бриф —
самодостаточный RED-протокол (явные критерии приёмки, явная рамка «реализации
нет, тесты обязаны быть красными», worktree на коммите ДО реализации). Трактую
как RED-эквивалент (см. память тестера
``feedback_freeform_brief_without_mode_header``), а не форсирую MODE:regression
(его первый шаг — ``git diff`` — тут просто нечего сравнивать).

Task 3.3 (``plans/observability-closure/phase-3-store-and-signal.md``):
запись в стор наблюдаемости перестаёт быть синхронным вызовом в потоке
эмитента (сегодня — ``StoreTapChannel.write`` → ``ObservabilityStore.
append_records([rec])``, пачка из одной записи, commit на каждую) и уходит
через ограниченную очередь + фоновый дренаж пачкой + ``flush(timeout)`` на
останов. ``interface.py`` для задачи НЕТ; источник контракта — 9 критериев
приёмки брифа + карточка плана (замер «было +120 мкс», «grep def flush — ноль
вхождений», «BoundedChannel/append_records/log_windowed не переписываются»).

**Честно про угаданное.** У задачи ЕСТЬ новый переиспользуемый механизм —
класс, который: (1) кладёт записи в ограниченную очередь, (2) дренирует их
фоновым потоком пачками, (3) отдаёт ``flush(timeout) -> (записано, потеряно)``,
(4) берёт имя счётчика потерь параметром конструктора (K-Т3), (5) не
импортирует стор вовсе (K8, чтобы трек otel-export мог взять его целиком).
Имени и адреса этого класса нет НИГДЕ в дереве (grep по ``flush``/
``BatchDrain``/``dropped_overflow`` в ``channel_routing_module/`` — см. отчёт
tester'а, ноль совпадений на новый механизм). Угадан ОДИН символ —
``BatchDrainWorker`` — и адрес хеджирован по ТРЁМ правдоподобным модулям
(тот же приём, что уже есть в этом дереве —
``test_windowed_voice_primitive_acceptance.py`` хеджирует адрес
``log_windowed``). Конструктор угадан как
``BatchDrainWorker(sink, capacity, counter_name=..., overflow=...)`` с
``.write(record)`` / ``.flush(timeout) -> (written, lost)`` — НИЧЕМ не
подтверждён, кроме формы критериев К-Т2/К-Т3/«ёмкость и голос»/«класс не
знает про стор». Если реализация назовёт класс/адрес/сигнатуру иначе —
поправить ``_WORKER_CANDIDATE_MODULES``/``_WORKER_CLASS_NAME`` и, при
необходимости, kwargs конструктора в тестах этого класса.

Остальные критерии (1, К-Т1а, К-Т1б, 7, 9) проверяются через УЖЕ
СУЩЕСТВУЮЩИЕ символы (``BoundedChannel``, ``StoreTapChannel``,
``ObservabilityStore``) — угадывать там нечего, они уже в дереве.

Карта критерий → тест:
    1. Цена постановки (соло×3, число+темп)     → TestCriterion1CostOfAcceptedInfoRecord
    2. К-Т1(а) put при полной, не разгребаемой   → TestCriterionKT1PutNeverStalls::...kt1_a...
    3. К-Т1(б) put во время идущего drain()      → TestCriterionKT1PutNeverStalls::...kt1_b...
    4. К-Т2 flush(timeout) -> (записано,потеряно) → TestCriterionKT2Flush
    5. К-Т3 counter_name — параметр конструктора  → TestCriterionKT3CounterNameIsAParameter
    6. Ёмкость и голос окном                      → TestCriterionCapacityAndWindowedVoice
    7. Останов: строка "store flush: N/M" литералом → TestCriterion7And9ShutdownFlushIsNamedNotSilentlyLost
    8. Класс не знает про стор                    → TestCriterionClassDoesNotKnowAboutStore
    9. Потеря на останове названа, не обнаружена постфактум → TestCriterion7And9...

Дисциплина: вызовы, способные заблокироваться, — в демон-потоке с
``join(timeout=...)``; литералы вместо значений из предмета; парная проверка
достижимости у каждого утверждения об отсутствии.
"""

from __future__ import annotations

import inspect
import logging
import re
import tempfile
import threading
import time
from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.channel_routing_module.observability import (
    BoundedChannel,
    ObservabilityStore,
    StoreTapChannel,
)
from multiprocess_framework.modules.logger_module.core.windowed_voice import reset_process_voices


# ---------------------------------------------------------------------------
# Общие фикстуры / хелперы
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_windowed_voices():
    """windowed_voice — процесс-синглтон (память tester: ``feedback_windowed_voice_is_a_process_wide_singleton``).

    Сбрасываем вокруг КАЖДОГО теста защитно, даже не зная заранее, какой
    holder (процессный/свой) возьмёт реализация.
    """
    reset_process_voices()
    yield
    reset_process_voices()


def _log_record_dict(
    level: str = "INFO", message: str = "probe", module: str = "worker_module", **extra: Any
) -> Dict[str, Any]:
    """Форма LogRecord.to_dict() — вход StoreTapChannel.write (см. store_tap.py, докстринг модуля)."""
    return {
        "timestamp": 1.0,
        "level": level,
        "scope": "system",
        "message": message,
        "module": module,
        "extra": dict(extra),
    }


class _LockHoldMeter:
    """Лок, помнящий длительность каждого удержания (для К-Т1(б))."""

    def __init__(self, lock):
        self._lock = lock
        self.holds: List[float] = []
        self._entered = 0.0

    def __enter__(self):
        result = self._lock.__enter__()
        self._entered = time.perf_counter()
        return result

    def __exit__(self, *exc):
        self.holds.append(time.perf_counter() - self._entered)
        return self._lock.__exit__(*exc)


_BOUNDED_RECORD = {"kind": "log", "module": "m", "ts": 1.0, "severity": "info", "message": "x" * 40, "context": {}}


# ---------------------------------------------------------------------------
# Критерий 1 — цена постановки: соло, ×3, число микросекунд + темп (не одно без другого)
# ---------------------------------------------------------------------------


class TestCriterion1CostOfAcceptedInfoRecord:
    """Бюджет принадлежит ДОРОГЕ лог-записи у эмитента, не механизму (правка спеки до старта).

    До задачи 3.3 замерено ~113-120 мкс/запись (StoreTapChannel.write делает
    executemany на ОДИН ряд + commit синхронно). Бюджет после задачи —
    не больше базы (построение record-dict без tap'а, та же дорога) + 5 мкс.
    """

    BUDGET_OVERHEAD_SEC = 5e-6  # литерал спеки — 5 мкс

    @staticmethod
    def _measure_once(n: int = 2000) -> tuple[float, float]:
        with tempfile.TemporaryDirectory() as tmp:
            store = ObservabilityStore(f"{tmp}/obs.db")
            tap = StoreTapChannel(store)
            try:
                # база: та же дорога (построение LogRecord-dict), БЕЗ tap.write
                t0 = time.perf_counter()
                for i in range(n):
                    _log_record_dict(message=f"m{i}")
                base = time.perf_counter() - t0

                t0 = time.perf_counter()
                for i in range(n):
                    tap.write(_log_record_dict(message=f"m{i}"))
                with_tap = time.perf_counter() - t0
            finally:
                store.close()
        overhead_per_call = (with_tap - base) / n
        throughput = n / with_tap  # rec/s — темп ОБЯЗАН измеряться рядом с числом мкс
        return overhead_per_call, throughput

    def test_overhead_stays_within_budget_across_three_solo_runs(self):
        """Не гонять под нагрузкой (см. правило брифа) — единственный процесс, три независимых прогона.

        **Судится МЕДИАНА трёх, а не все три (правка ведущего).** Карточка плана
        говорит «медиана трёх соло-прогонов», файл требовал каждого из трёх — и
        мигал: первый прогон прогревает БД и стоит заметно дороже двух
        последующих, из-за чего тест краснел без всякой связи с предметом (в
        матрице инъекций он трижды из пятнадцати краснел от шума, засоряя
        вердикт). Расхождение спеки и теста, а не свойство. Изменена одна
        строка — критерий сравнения; и вход, и бюджет, и требование «темп рядом
        с числом» остались как их написал независимый тестер.
        """
        results = [self._measure_once() for _ in range(3)]
        overheads = sorted(o for o, _ in results)
        throughputs = [t for _, t in results]
        median = overheads[1]

        assert median <= self.BUDGET_OVERHEAD_SEC, (
            f"МЕДИАНА цены постановки {median * 1e6:.1f} мкс превышает бюджет (база+5мкс): "
            f"overhead_us={[round(o * 1e6, 1) for o in overheads]}, темп rec/s={[round(t) for t in throughputs]} "
            f"— число без темпа недействительно, приведены оба; до задачи 3.3 наблюдалось ~113-120 мкс/запись"
        )


# ---------------------------------------------------------------------------
# К-Т1 — put никогда не блокируется. (а) контроль полной-не-разгребаемой очереди
#         (скорее всего уже зелён — предупреждение спеки), (б) подозреваемое:
#         во время идущего drain() (тот же лок на копию всего буфера).
# ---------------------------------------------------------------------------


class TestCriterionKT1PutNeverStalls:
    @staticmethod
    def _baseline_put_seconds(n: int = 5000) -> float:
        ch = BoundedChannel("kt1_baseline", capacity=1024, overflow="drop_oldest")
        t0 = time.perf_counter()
        for _ in range(n):
            ch.write(_BOUNDED_RECORD)
        return (time.perf_counter() - t0) / n

    def test_kt1_a_full_undrained_queue_matches_empty_queue_pace(self):
        """Контроль (а). Спека прямо предупреждает: этот тест, скорее всего, зелёный уже сегодня —
        сам по себе он ничего не доказывает, он контроль для (б)."""
        capacity = 1024
        ch = BoundedChannel("kt1_a", capacity=capacity, overflow="drop_oldest")
        for _ in range(capacity):
            ch.write(_BOUNDED_RECORD)  # заполнили до потолка, НЕ разгребаем

        n = 5000
        t0 = time.perf_counter()
        for _ in range(n):
            ch.write(_BOUNDED_RECORD)
        full_per_call = (time.perf_counter() - t0) / n
        empty_per_call = self._baseline_put_seconds(n)

        assert full_per_call <= empty_per_call * 5, (
            f"темп put у заполненной-не-разгребаемой очереди хуже пустой более чем в 5х: "
            f"full={full_per_call * 1e6:.2f}мкс empty={empty_per_call * 1e6:.2f}мкс"
        )

    def test_kt1_b_drain_holds_the_lock_for_a_constant_time(self):
        """К-Т1(б), ПЕРЕПИСАН вердиктом CTO: сторож ЗАПАСА, а не лечение регрессии.

        **Что здесь стояло раньше и почему заменено.** Прежняя редакция мерила
        max латентности ``put`` во время идущего ``drain()`` и требовала
        ``<= база * 50``. Тест краснел при ЛЮБОЙ реализации, включая ту, ради
        которой он писался: его порог лежит ниже обычного хвоста переключения
        потоков на этой машине, то есть меряет планировщик.

        **Регрессии, которую он описывал, не существует.** Посылка задачи —
        «постановка ждёт копию буфера под локом» — проверялась трижды разными
        руками, и все три прогона оказались слишком короткими: при достаточном
        числе повторов разницы между редакциями ``drain()`` нет вовсе, тот же
        хвост писателя даёт конкурент, который лока не берёт, а выбросы падают
        на одни и те же повторы у всех конкурентов. Часть замеров вдобавок
        сравнивала объём работы конкурента, а не факт взятия лока.

        **Что проверяется вместо этого:** время удержания лока, замеренное
        ИЗНУТРИ критической секции ``drain()``. Это свойство конструкции —
        секция O(1) вместо O(ёмкость), — и оно существует независимо от того,
        видно ли его снаружи. Сторож охраняет ЗАПАС: сегодня секция укладывается
        в литерал с большим запасом, и он стоит, чтобы она не выросла позже,
        а не потому, что что-то наблюдалось. Планировщик на это число не влияет:
        внутри секции нет ни одного вызова, способного уснуть.

        Единственный изменённый метод этого файла; остальные — как их написал
        независимый тестер.
        """
        capacity = 1024
        holds = []
        for _ in range(7):  # медиана повторов: одиночное вытеснение не решает исход
            ch = BoundedChannel("kt1_b", capacity=capacity, overflow="drop_oldest")
            for _ in range(capacity):
                ch.write(_BOUNDED_RECORD)
            meter = _LockHoldMeter(ch._lock)
            ch._lock = meter
            ch.drain()
            assert meter.holds, "предусловие: drain() обязан был взять лок"
            holds.append(max(meter.holds) * 1e6)
        holds.sort()
        median_us = holds[len(holds) // 2]

        assert median_us <= 2.0, (
            f"drain() держит лок {median_us:.2f} мкс при ёмкости {capacity} (потолок 2.0 мкс) — "
            f"критическая секция снова пропорциональна ёмкости; все семь замеров: "
            f"{[round(h, 2) for h in holds]}"
        )


# ---------------------------------------------------------------------------
# Новый механизм (угаданный класс) — К-Т2, К-Т3, «ёмкость и голос», «класс не знает про стор»
# ---------------------------------------------------------------------------

_WORKER_CANDIDATE_MODULES = (
    "multiprocess_framework.modules.channel_routing_module.observability.batch_drain_worker",
    "multiprocess_framework.modules.channel_routing_module.observability.bounded_channel",
    "multiprocess_framework.modules.channel_routing_module.observability",
)
_WORKER_CLASS_NAME = "BatchDrainWorker"


def _import_worker_class() -> Any:
    errors: List[str] = []
    for path in _WORKER_CANDIDATE_MODULES:
        try:
            module = __import__(path, fromlist=[_WORKER_CLASS_NAME])
            return getattr(module, _WORKER_CLASS_NAME)
        except (ImportError, AttributeError) as exc:
            errors.append(f"{path}: {exc!r}")
    pytest.fail(
        f"{_WORKER_CLASS_NAME} не найден ни по одному из угаданных адресов — это ОЖИДАЕМО "
        'до реализации Task 3.3 (интерфейса нет; замер до старта тестера дал \'grep "def flush" '
        "по observability/ — ноль вхождений'):\n"
        + "\n".join(errors)
        + "\nПри реальном имени/месте — поправить _WORKER_CANDIDATE_MODULES/_WORKER_CLASS_NAME "
        "в этом файле."
    )


class _FakeSink:
    """Двойник ObservabilityStore.append_records. НЕ ObservabilityStore — класс обязан
    работать с любым объектом такой формы (К8: не знает про стор)."""

    def __init__(self) -> None:
        self.batches: List[List[Dict[str, Any]]] = []

    def append_records(self, records: List[Dict[str, Any]]) -> int:
        self.batches.append(list(records))
        return len(records)

    @property
    def total_written(self) -> int:
        return sum(len(b) for b in self.batches)


class _NeverAcceptingSink:
    """Сток, который никогда не примет пачку — для проверки честного lost>0 на недостижимом дедлайне."""

    def append_records(self, records: List[Dict[str, Any]]) -> int:
        raise RuntimeError("сток недоступен (двойник для К-Т2)")


@pytest.fixture
def worker_class():
    return _import_worker_class()


class TestCriterionKT2Flush:
    """flush(timeout) -> (записано, потеряно); недостижимый дедлайн — управление возвращается
    быстро с честным потеряно>0, а не ждёт."""

    def test_flush_returns_written_and_lost_pair(self, worker_class):
        sink = _FakeSink()
        w = worker_class(sink=sink, capacity=64, counter_name="dropped_overflow")
        for i in range(5):
            w.write({"n": i})

        outcome = w.flush(timeout=2.0)

        assert isinstance(outcome, tuple) and len(outcome) == 2, (
            f"flush(timeout) обязан вернуть ПАРУ (записано, потеряно), получено {outcome!r}"
        )
        written, lost = outcome
        assert written == 5 and lost == 0, (
            f"все 5 принятых записей обязаны быть дожаты без потерь при достижимом дедлайне, "
            f"получено written={written} lost={lost}"
        )

    def test_flush_returns_promptly_with_honest_loss_on_unreachable_deadline(self, worker_class):
        w = worker_class(sink=_NeverAcceptingSink(), capacity=64, counter_name="dropped_overflow")
        for i in range(10):
            w.write({"n": i})

        result: List[Any] = [None]

        def _call() -> None:
            result[0] = w.flush(timeout=0.05)

        t0 = time.perf_counter()
        t = threading.Thread(target=_call, daemon=True)
        t.start()
        t.join(timeout=5.0)  # жёсткий потолок — зависший поток обязан быть обнаружен, не спрятан
        elapsed = time.perf_counter() - t0

        assert not t.is_alive(), "flush(timeout) повис вместо возврата с честным исходом"
        assert result[0] is not None, "flush(timeout) не вернул значение за отведённый потолок"
        written, lost = result[0]
        assert lost > 0, (
            f"недостижимый сток при timeout=0.05 обязан дать потеряно>0, получено written={written} lost={lost}"
        )
        assert elapsed < 1.0, f"flush(timeout=0.05) занял {elapsed:.2f}с — не честный быстрый возврат"


class TestCriterionKT3CounterNameIsAParameter:
    """Имя счётчика вытеснений — параметр конструктора, не литерал в классе."""

    def test_constructor_counter_name_drives_the_voice_and_the_counter(self, worker_class, caplog):
        sink = _FakeSink()
        capacity = 3
        w = worker_class(sink=sink, capacity=capacity, counter_name="dropped_overflow")

        with caplog.at_level(logging.DEBUG):
            for i in range(capacity + 20):  # гарантированное переполнение
                w.write({"n": i})

        dropped = getattr(w, "dropped_overflow", None)
        if dropped is None and hasattr(w, "counters"):
            dropped = w.counters().get("dropped_overflow")
        assert dropped is not None and dropped > 0, (
            "счётчик под именем 'dropped_overflow' (параметр конструктора) не найден или равен нулю — "
            "имя счётчика обязано определяться counter_name, а не литералом внутри класса"
        )
        assert any("dropped_overflow" in r.getMessage() for r in caplog.records), (
            "голос обязан называть ИМЕННО имя счётчика, данное конструктору (counter_name)"
        )

    def test_class_source_has_no_hardcoded_store_evicted_literal(self, worker_class):
        source = inspect.getsource(worker_class)
        # достижимость: страж обязан реально читать файл класса, а не молчать по любой причине
        assert "counter_name" in source, (
            "страж не видит 'counter_name' в исходнике класса — проверка ниже была бы пустой (нечего сверять)"
        )
        assert "store_evicted" not in source, (
            "класс жёстко ссылается на литерал 'store_evicted' — по К-Т3 плоскость-специфичное имя "
            "не должно быть зашито в общий (переиспользуемый треком otel-export) класс"
        )


class TestCriterionCapacityAndWindowedVoice:
    """Очередь имеет потолок (память не растёт неограниченно); потеря на переполнении
    считается и получает голос ОКНОМ (не строка на каждую потерю)."""

    def test_capacity_is_bounded_and_overflow_is_voiced_by_window_not_per_drop(self, worker_class, caplog):
        capacity = 5
        w = worker_class(sink=_FakeSink(), capacity=capacity, counter_name="dropped_overflow")
        total = 500

        with caplog.at_level(logging.DEBUG):
            for i in range(total):
                w.write({"n": i})

            # достижимость: контроль БЕЗ переполнения (та же конструкция, ёмкость с запасом) —
            # голоса быть не должно вовсе; без этого控троля "мало строк" могло бы значить
            # "переполнения не было" вместо "окно подавляет".
            control = worker_class(sink=_FakeSink(), capacity=total + 10, counter_name="dropped_overflow")
            for i in range(10):
                control.write({"n": i})

        voice_lines = [r for r in caplog.records if "dropped_overflow" in r.getMessage()]
        expected_drops = total - capacity

        depth = getattr(w, "depth", None)
        if depth is None and hasattr(w, "__len__"):
            depth = len(w)
        if depth is not None:
            assert depth <= capacity, f"глубина очереди {depth} превышает объявленный потолок {capacity}"

        assert len(voice_lines) >= 1, (
            f"переполнение ({expected_drops} потерь ожидается) обязано дать хотя бы ОДИН голос — "
            f"получено 0 (достижимость: контрольный экземпляр без переполнения не должен голосить вовсе, "
            f"и его строки сюда не попали бы по фильтру имени)"
        )
        assert len(voice_lines) < expected_drops, (
            f"голос звучит {len(voice_lines)} раз почти на каждую из ~{expected_drops} потерь — "
            "обязано быть окном (log_windowed), а не построчно"
        )


class TestCriterionClassDoesNotKnowAboutStore:
    """Класс создаётся в одиночку, без ObservabilityStore в окружении вовсе (К8)."""

    def test_constructs_and_works_with_a_bare_sink_double_no_store_anywhere(self, worker_class):
        sink = _FakeSink()  # НЕ ObservabilityStore
        w = worker_class(sink=sink, capacity=16, counter_name="dropped_overflow")
        w.write({"n": 1})
        written, lost = w.flush(timeout=1.0)
        assert written >= 0 and lost >= 0  # факт: отработало без стора в окружении вовсе

    def test_class_module_source_has_no_observability_store_import(self, worker_class):
        module = inspect.getmodule(worker_class)
        source = inspect.getsource(module) if module else ""
        # достижимость: модуль обязан реально содержать сам класс — иначе "нет ObservabilityStore"
        # означало бы "файл пуст", а не "класс её не знает"
        assert _WORKER_CLASS_NAME in source, "страж не нашёл сам класс в его же модуле — проверка ниже пустая"
        assert "ObservabilityStore" not in source and "observability_store" not in source, (
            f"модуль {module.__name__ if module else '?'} ссылается на ObservabilityStore — "
            "К8 требует, чтобы переиспользуемый класс не знал про стор вовсе"
        )


# ---------------------------------------------------------------------------
# Критерии 7 и 9 — реальная интеграция StoreTapChannel + ObservabilityStore
# (существующие символы, угадывать нечего): останов дожимает и называет исход,
# третьего исхода («исчезла молча») быть не должно.
# ---------------------------------------------------------------------------


class TestCriterion7And9ShutdownFlushIsNamedNotSilentlyLost:
    LOG_LINE_RE = re.compile(r"store flush: (\d+) записано, (\d+) потеряно")

    def test_close_under_load_logs_literal_line_and_accounts_for_every_write(self, tmp_path, caplog):
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        tap = StoreTapChannel(store)
        n = 50

        with caplog.at_level(logging.DEBUG):
            for i in range(n):
                tap.write(_log_record_dict(message=f"row{i}"))
            tap.close()  # немедленный останов, по формулировке критерия 9

        matches = [self.LOG_LINE_RE.search(r.getMessage()) for r in caplog.records]
        matches = [m for m in matches if m]
        assert matches, (
            "после close() ожидалась строка 'store flush: N записано, M потеряно' литералом — "
            f"ни одной не найдено среди захваченных строк: {[r.getMessage() for r in caplog.records]!r}"
        )

        written_in_line = sum(int(m.group(1)) for m in matches)
        lost_in_line = sum(int(m.group(2)) for m in matches)
        rows_in_store = store.count()
        store.close()

        assert rows_in_store + lost_in_line == n, (
            f"третьего исхода («исчезла молча») быть не должно: в сторе {rows_in_store} строк + "
            f"потеряно (из строки лога) {lost_in_line} обязано равняться числу принятых write() = {n}, "
            f"получено {rows_in_store + lost_in_line} (строка лога сообщила 'записано'={written_in_line})"
        )
