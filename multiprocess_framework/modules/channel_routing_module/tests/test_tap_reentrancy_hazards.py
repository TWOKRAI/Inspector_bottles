# -*- coding: utf-8 -*-
"""D1 — реентерабельность раздачи в tap'ы и AB/BA реестра каналов (АВТОРСКИЕ тесты).

Опасности, видимые автору механизма:

  1. **Лавина.** Tap, эмитящий запись в своём ``write()``, — не экзотика: так
     ведёт себя любой sink, который сам логирует. До правки это давало рекурсию
     до предела интерпретатора (воспроизведено: 498 записей, глубина 498), а
     `RecursionError` глотался `except Exception` внутри цикла раздачи — наружу
     отказ выходил как «часть записей куда-то делась».
  2. **Молчаливое подавление.** Ограничить глубину мало: подавленная запись —
     это потеря, и без ИМЕНОВАННОГО счётчика она неотличима от исправной тишины.
  3. **Поточность защиты.** Флаг «раздача идёт» обязан быть свойством СТЕКА, а
     не менеджера: общий флаг глушил бы законную раздачу в соседнем потоке.
  4. **Возврат флага при любом исходе**, включая не-`Exception`: иначе поток
     навсегда остаётся «внутри раздачи», и tail для него замолкает целиком.
  5. **AB/BA.** ``ChannelRegistry.register()`` писал предупреждение ПОД своим
     локом, то есть брал «лок реестра → лок логгера»; обратный порядок
     («лок логгера → лок реестра») существует на пути раздачи в tap. Цикла не
     было только потому, что так сложилась проводка.
  6. **Немой реестр.** Без переданных разъёмов реестр молчал полностью, и
     «менеджеров нет» выглядело как «всё в порядке».
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List

from ..core.channel_registry import ChannelRegistry
from ..core.channel_routing_manager import LOSS_COUNTER_KEYS, ChannelRoutingManager
from ..interfaces import IChannel

#: Дедлайн ожиданий. Регрессия обязана падать, а не висеть (правило D2.3).
_DEADLINE_SEC = 30.0


class _Manager(ChannelRoutingManager):
    """Наследник без собственной проводки — судим базу."""

    def __init__(self, name: str = "d1") -> None:
        super().__init__(manager_name=name)


class _RecordingChannel(IChannel):
    def __init__(self, name: str = "rec") -> None:
        self._name = name
        self.written: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        self.written.append(data)
        return {"status": "success"}

    def close(self) -> None:
        pass


class _ReentrantTap(_RecordingChannel):
    """Tap, который на каждую принятую запись эмитит ещё одну — как логирующий sink."""

    def __init__(self, mgr: _Manager, name: str = "reentrant") -> None:
        super().__init__(name)
        self._mgr = mgr

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        super().write(data)
        self._mgr._emit_to_taps({"msg": "эхо tap'а"}, "ERROR")
        return {"status": "success"}


def test_reentrant_tap_does_not_avalanche() -> None:
    """Лавина ограничена ПЕРВЫМ уровнем, а не пределом рекурсии."""
    mgr = _Manager()
    tap = _ReentrantTap(mgr)
    mgr.add_tap(tap, min_level="DEBUG", name="reentrant")

    mgr._emit_to_taps({"msg": "первая запись"}, "ERROR")

    # Ровно одна доставка: вложенная раздача подавлена. Литерал, а не
    # производная от кода — иначе тест согласился бы с любым числом.
    assert len(tap.written) == 1, f"раздача ушла вглубь: {len(tap.written)} записей"


def test_suppressed_reentrant_records_are_counted_by_name() -> None:
    """Подавление названо счётчиком: молчаливое подавление = невидимая потеря."""
    mgr = _Manager()
    mgr.add_tap(_ReentrantTap(mgr), min_level="DEBUG", name="reentrant")

    assert mgr.get_stats()["tap_reentrant_suppressed"] == 0
    mgr._emit_to_taps({"msg": "первая"}, "ERROR")
    assert mgr.get_stats()["tap_reentrant_suppressed"] == 1

    mgr._emit_to_taps({"msg": "вторая"}, "ERROR")
    assert mgr.get_stats()["tap_reentrant_suppressed"] == 2, "счётчик обязан расти, а не быть флагом"


def test_counter_is_part_of_the_loss_registry() -> None:
    """Счётчик — в реестре потерь, иначе он не доедет до readback'а потребителей."""
    assert "tap_reentrant_suppressed" in LOSS_COUNTER_KEYS


def test_guard_is_per_thread_not_per_manager() -> None:
    """Раздача в одном потоке не глушит раздачу в другом.

    Общий на менеджер флаг прошёл бы тесты 1–2 и при этом ломал бы главное:
    пока один поток внутри раздачи, соседний терял бы свои записи молча.
    """
    mgr = _Manager()
    inside = threading.Event()
    release = threading.Event()
    other_thread_written: List[int] = []

    class _BlockingTap(_RecordingChannel):
        """Держит ПЕРВЫЙ вызов внутри раздачи; остальные пропускает сразу.

        Если бы держались все, соседний поток блокировался бы на самом tap'е —
        и тест мерил бы блокировку канала, а не поточность защиты.
        """

        def __init__(self, name: str) -> None:
            super().__init__(name)
            self._first = True

        def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
            super().write(data)
            if self._first:
                self._first = False
                inside.set()
                release.wait(timeout=_DEADLINE_SEC)  # держим поток ВНУТРИ раздачи
            return {"status": "success"}

    tap = _BlockingTap("blocking")
    mgr.add_tap(tap, min_level="DEBUG", name="blocking")

    holder = threading.Thread(target=lambda: mgr._emit_to_taps({"msg": "держим"}, "ERROR"), daemon=True)
    holder.start()
    assert inside.wait(timeout=_DEADLINE_SEC), "поток-держатель не вошёл в раздачу"

    def _other() -> None:
        before = len(tap.written)
        mgr._emit_to_taps({"msg": "из соседнего потока"}, "ERROR")
        other_thread_written.append(len(tap.written) - before)

    other = threading.Thread(target=_other, daemon=True)
    other.start()
    other.join(timeout=_DEADLINE_SEC)
    release.set()
    holder.join(timeout=_DEADLINE_SEC)

    assert not other.is_alive() and not holder.is_alive(), "потоки не завершились в дедлайн"
    assert other_thread_written == [1], (
        f"соседний поток потерял запись из-за чужой раздачи: {other_thread_written}; "
        f"подавлений={mgr.get_stats()['tap_reentrant_suppressed']}"
    )


def test_depth_flag_is_released_even_on_base_exception() -> None:
    """Не-``Exception`` из tap'а не должен запирать поток «внутри раздачи» навсегда.

    `except Exception` в цикле такое не ловит — флаг снимает только `finally`.
    Без него следующая запись этого потока считалась бы реентрантной, и tail
    замолчал бы для него целиком, а счётчик потерь при этом рос бы.
    """
    mgr = _Manager()

    class _NotAnException(BaseException):
        """Своя, а не KeyboardInterrupt: последнюю pytest считает сигналом снять прогон."""

    class _Nasty(_RecordingChannel):
        def __init__(self, name: str) -> None:
            super().__init__(name)
            self.raise_it = True

        def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
            super().write(data)
            if self.raise_it:
                raise _NotAnException("tap уронил не-Exception")
            return {"status": "success"}

    tap = _Nasty("nasty")
    mgr.add_tap(tap, min_level="DEBUG", name="nasty")

    try:
        mgr._emit_to_taps({"msg": "первая"}, "ERROR")
    except _NotAnException:
        pass

    tap.raise_it = False
    mgr._emit_to_taps({"msg": "вторая"}, "ERROR")

    assert len(tap.written) >= 2, (
        "вторая запись не дошла: флаг глубины остался поднятым после не-Exception; "
        f"подавлений={mgr.get_stats()['tap_reentrant_suppressed']}"
    )


# =============================================================================
# AB/BA реестра каналов
# =============================================================================


def test_registry_does_not_hold_its_lock_while_logging() -> None:
    """AB/BA: рандеву стоит НА САМОЙ операции — на вызове разъёма из register().

    Порядок «лок реестра → лок логгера» существовал в `register()`; обратный
    («лок логгера → лок реестра») живёт на пути раздачи в tap, где логгер под
    своим локом читает состав каналов. Барьер на входе в метод такую коллизию
    НЕ воспроизводит: короткий проход укладывается в один квант интерпретатора,
    и потоки расходятся во времени. Поэтому рандеву висит внутри самого
    разъёма — там, где до правки лок реестра был бы уже взят.

    Регрессия проявится дедлоком, поэтому оба потока — с дедлайном.
    """
    logger_lock = threading.Lock()
    at_log_call = threading.Event()
    b_holds_logger_lock = threading.Event()
    errors: List[BaseException] = []

    registry = ChannelRegistry(log_warning=lambda msg: _warn(msg))

    def _warn(_msg: str) -> None:
        # Мы внутри разъёма: до правки здесь уже удерживался лок реестра.
        at_log_call.set()
        assert b_holds_logger_lock.wait(timeout=_DEADLINE_SEC), "B не взял лок логгера"
        with logger_lock:  # порядок A: (реестр?) → логгер
            pass

    registry.register(_RecordingChannel("ch"))  # первый — без предупреждения

    def _thread_a() -> None:
        try:
            registry.register(_RecordingChannel("ch"))  # повтор имени → предупреждение
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def _thread_b() -> None:
        try:
            with logger_lock:  # порядок B: логгер → реестр
                b_holds_logger_lock.set()
                assert at_log_call.wait(timeout=_DEADLINE_SEC), "A не дошёл до разъёма"
                registry.all()  # нужен лок реестра
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    a = threading.Thread(target=_thread_a, daemon=True)
    b = threading.Thread(target=_thread_b, daemon=True)
    a.start()
    b.start()
    a.join(timeout=_DEADLINE_SEC)
    b.join(timeout=_DEADLINE_SEC)

    assert not a.is_alive() and not b.is_alive(), "дедлок AB/BA: реестр держит свой лок, пока зовёт разъём логирования"
    assert errors == [], f"потоки упали: {errors!r}"


def test_registry_without_connectors_is_loud_not_silent(caplog: Any) -> None:
    """Реестр без разъёмов пишет через аварийный выход, а не молчит.

    Молчание здесь опаснее шума: «менеджеров нет» выглядело снаружи ровно так
    же, как «всё в порядке».
    """
    registry = ChannelRegistry()  # ни одного разъёма
    registry.register(_RecordingChannel("dup"))

    with caplog.at_level(logging.WARNING):
        registry.register(_RecordingChannel("dup"))  # повтор → предупреждение

    assert any("replaced" in rec.message or "replaced" in rec.getMessage() for rec in caplog.records), (
        f"реестр промолчал о замене канала: {[r.getMessage() for r in caplog.records]}"
    )
