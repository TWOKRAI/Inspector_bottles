"""Слепые приёмочные тесты контракта `_road_cost.py` (ещё не существует).

Это RED-стадия: `multiprocess_framework/modules/tests/_road_cost.py` НЕ
СУЩЕСТВУЕТ. Источник контракта — сигнатуры и docstring'и `timed_pair` /
`count_calls`, переданные тест-стадии текстом задачи (formal `interface.py`
для этого модуля не заводился — контракт лёгкий, вложен прямо в задачу).
Реализацию (`_impl/`, диффы, файлы других тестов road-cost) НЕ читал —
работал только с контрактом и восемью критериями приёмки ниже.

Ожидаемый результат прогона: ВСЕ тесты падают на сборе с одной и той же
причиной — `ModuleNotFoundError` на строке импорта ниже, потому что модуля
физически нет. Это ТЗ для реализации, а не баг тест-файла.

Каждый тест пришпиливает ровно один критерий приёмки (нумерация — из задачи):

  1. `timed_pair` — обе величины ЗА ОДИН ВЫЗОВ, порядок (не абсолют).
  2. `timed_pair` — GC включается обратно, включая случай исключения.
  3. `count_calls` — разница python-уровня между «с вызовом хелпера» и «без»
     равна литералу N.
  4. `count_calls` — детерминизм двух подряд идущих вызовов.
  5. `count_calls` — считает вызовы на глубине трёх кадров.
  6. `count_calls` — восстанавливает ЧУЖОЙ profile-хук, и тот снова работает.
  7. `count_calls` — не оставляет СВОЙ хук при исключении в `fn`, исключение
     пробрасывается наружу.
  8. `count_calls` — те же числа под активным сторонним трассировщиком
     (заменитель реального `coverage.py` — обоснование в docstring теста).
"""

from __future__ import annotations

import gc
import sys

import pytest

from multiprocess_framework.modules.tests._road_cost import count_calls, timed_pair


# ---------------------------------------------------------------------------
# Изоляция глобального состояния интерпретатора между тестами этого файла.
#
# `timed_pair`/`count_calls` по контракту трогают три общих ресурса процесса —
# gc-переключатель, sys.setprofile, sys.settrace. Пока реализации нет, любой
# из критериев 2/6/7 может СЛОМАННО оставить их в грязном состоянии — это не
# должно каскадом ронять СОСЕДНИЕ тесты этого файла или сессионный
# `framework_metric_catalogue_guard` из conftest.py. Фикстура снимает снимок
# ДО и возвращает его же ПОСЛЕ, а gc принудительно включает на входе и выходе
# (это и есть ожидаемое здоровое состояние, если контракт вообще выполняется).
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolate_debug_hooks():
    prior_profile = sys.getprofile()
    prior_trace = sys.gettrace()
    gc.enable()
    yield
    sys.setprofile(prior_profile)
    sys.settrace(prior_trace)
    gc.enable()


# --- вспомогательные объекты для критерия 1 (busy-loop с управляемой ценой) -


def _busy(n: int) -> int:
    total = 0
    for i in range(n):
        total += i * i
    return total


def _make_workload(units: int):
    def workload() -> None:
        _busy(units)

    return workload


# --- вспомогательные объекты для критерия 3 (разница на N вызовов хелпера) --


def _helper() -> None:
    pass


def _make_caller(call_helper: bool):
    """Структурно идентичные варианты — единственная разница: сам вызов.

    Одинаковый цикл `for _ in range(5)` в обеих ветках специально, чтобы
    разница в python-level счётчике была вызвана ИМЕННО наличием вызова
    `_helper()`, а не отличием формы кода (см. память про конфаунды).
    """

    def caller() -> None:
        for _ in range(5):
            if call_helper:
                _helper()

    return caller


# --- вспомогательные объекты для критерия 5 (вызов на глубине трёх кадров) -


def _flat() -> None:
    pass


def _depth3_leaf() -> None:
    pass


def _depth2() -> None:
    _depth3_leaf()


def _depth1() -> None:
    _depth2()


# ---------------------------------------------------------------------------
# Критерий 1
# ---------------------------------------------------------------------------
def test_timed_pair_returns_per_call_seconds_in_correct_order():
    """`timed_pair` — обе секунды положительные и ЗА ОДИН ВЫЗОВ.

    fast/slow калиброваны эмпирически (busy-loop на 2000 и 40000 итераций
    даёт ~22x разницу по времени — см. отчёт тестера) так, чтобы реальное
    отношение было далеко от 1, но проверка идёт по ПОРЯДКУ и грубому
    отношению (>5x), а не по абсолютной микросекунде — абсолютный порог на
    общей машине красен без всякой регрессии.
    """
    fast = _make_workload(2000)
    slow = _make_workload(40000)

    per_call_slow, per_call_fast = timed_pair(slow, fast, repeats=100)

    assert per_call_slow > 0.0
    assert per_call_fast > 0.0
    assert per_call_slow > per_call_fast
    # ~22x по калибровке; порог 5x — большой запас на шум харнесса и машины,
    # но всё ещё отличает «за-вызов» от «плюс константа поверх вызова».
    assert per_call_slow > per_call_fast * 5


# ---------------------------------------------------------------------------
# Критерий 2
# ---------------------------------------------------------------------------
def test_timed_pair_reenables_gc_after_measured_callable_raises():
    assert gc.isenabled()

    def boom() -> None:
        raise RuntimeError("boom")

    def ok() -> None:
        pass

    with pytest.raises(RuntimeError):
        timed_pair(boom, ok, repeats=3)

    assert gc.isenabled()


# ---------------------------------------------------------------------------
# Критерий 3
# ---------------------------------------------------------------------------
def test_count_calls_python_level_difference_pins_literal_five():
    with_helper = _make_caller(call_helper=True)
    without_helper = _make_caller(call_helper=False)

    python_with, _c_with = count_calls(with_helper)
    python_without, _c_without = count_calls(without_helper)

    assert python_with - python_without == 5


# ---------------------------------------------------------------------------
# Критерий 4
# ---------------------------------------------------------------------------
def test_count_calls_is_deterministic_across_two_invocations():
    fn = _make_caller(call_helper=True)

    first = count_calls(fn)
    second = count_calls(fn)

    assert first == second


# ---------------------------------------------------------------------------
# Критерий 5
# ---------------------------------------------------------------------------
def test_count_calls_counts_three_frames_deep():
    """`_depth1` вызывает `_depth2`, тот — `_depth3_leaf`: 2 вложенных вызова
    на глубине вплоть до третьего кадра. Разница с плоским `_flat` (0
    вложенных вызовов) пришпиливает литерал 2, а не абсолютное число вызовов
    внутри `count_calls(fn)` — так тест не зависит от того, считается ли сам
    вызов `fn()` (эта неопределённость сокращается вычитанием одинаково для
    обеих сторон)."""
    python_flat, _c_flat = count_calls(_flat)
    python_deep, _c_deep = count_calls(_depth1)

    assert python_deep - python_flat == 2


# ---------------------------------------------------------------------------
# Критерий 6
# ---------------------------------------------------------------------------
def test_count_calls_restores_prior_profile_hook_and_it_still_fires():
    received: list[str] = []

    def my_hook(frame, event, arg):
        received.append(event)

    sys.setprofile(my_hook)
    try:
        count_calls(lambda: None)

        assert sys.getprofile() is my_hook

        received.clear()

        def probe() -> None:
            pass

        probe()

        assert len(received) > 0
    finally:
        sys.setprofile(None)


# ---------------------------------------------------------------------------
# Критерий 7
# ---------------------------------------------------------------------------
def test_count_calls_leaves_no_hook_when_fn_raises_and_exception_propagates():
    """Базовая линия сравнивается со СНИМКОМ до вызова, а не жёстко с `None`.

    Эмпирически проверено (в отдельном прогоне): под `pytest --cov` (реальный
    режим `make test` в проекте) `sys.gettrace()` УЖЕ занят `coverage.CTracer`
    до этого теста, а `sys.getprofile()` при этом всё равно `None` —
    coverage.py трогает только settrace-канал, не setprofile. Хардкод
    `assert sys.gettrace() is None` дал бы ложный красный под `--cov` даже при
    корректной реализации `count_calls`.
    """
    prior_profile = sys.getprofile()
    prior_trace = sys.gettrace()

    def boom() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError):
        count_calls(boom)

    assert sys.getprofile() is prior_profile
    assert sys.gettrace() is prior_trace


# ---------------------------------------------------------------------------
# Критерий 8
# ---------------------------------------------------------------------------
def test_count_calls_same_numbers_with_active_line_tracer():
    """Критерий буквально просит числа "под `pytest --cov` и без" — сравнение
    ДВУХ отдельных запусков pytest снаружи, либо вложенный `coverage.Coverage()`
    внутри одного процесса. Второе не сделал: C-трассировщик coverage.py — не
    просматриваемый Python-исходник (grep по `.venv/.../coverage/*.py` не
    нашёл ни одного `settrace`, значит переключение живёт в скомпилированном
    расширении), и я не смог подтвердить, что его `stop()` корректно вернёт
    ВНЕШНИЙ трассировщик, если этот файл сам гоняется под `make test`
    (`pytest --cov`) — риск молча срубить реальные цифры покрытия проекта
    перевешивает ценность этого теста.

    Вместо этого проверяю ту же механику безопасным способом: активный
    СТОРОННИЙ построчный трассировщик через `sys.settrace` — тем же каналом,
    каким пользуется coverage.py — не должен менять числа `count_calls`,
    который по критерию 6 обязан работать через независимый канал
    `sys.setprofile`. Это необходимое условие критерия 8, не буквальное его
    исполнение. Полную проверку "bare pytest vs pytest --cov" не проводил —
    см. раздел «что осталось открытым» в отчёте.
    """

    def workload() -> None:
        for _ in range(7):
            _helper()

    baseline = count_calls(workload)

    def _noop_trace(frame, event, arg):
        return _noop_trace

    prior_trace = sys.gettrace()
    sys.settrace(_noop_trace)
    try:
        under_tracer = count_calls(workload)
    finally:
        sys.settrace(prior_trace)

    assert under_tracer == baseline
