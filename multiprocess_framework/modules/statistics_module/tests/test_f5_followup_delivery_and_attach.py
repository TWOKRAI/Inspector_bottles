"""Ф5-добор по ревью: доставка чисел считается по ИСХОДУ, attach — по ФАКТУ подписки.

Два блокера, оба воспроизведены владельцем/ревьюером ДО правки, обе пары
вход→выход перенесены сюда литералами:

* **Б1** — ``ObservationManager`` считал ВЫЗОВЫ ``_deliver_number``, а не
  доставки: ``_emit_to_taps`` выходил на ``if not self._tap_sinks: return``
  раньше всякого учёта и об исходе не рассказывал. Пять записей при нуле
  приёмников и пять записей при живом приёмнике давали ОДИН и тот же
  ``delivered=5``, то есть счётчик, заведённый отличать живую плоскость чисел
  от мёртвой, к этому различию был слеп;
* **З3** — ``StatsManager.attach_observation_port`` докладывал ``True`` по
  форме вызова: по тождеству объекта порта (``add_tap`` не звался вовсе), по
  ``callable(add_tap)`` (вызываемый no-op проходил) и присваивал
  ``_observation_port`` ДО подписки (исключение из ``add_tap`` оставляло
  менеджера полуподключённым).

**Каждое число здесь — литерал, и у каждого «ноль» есть парный якорь,
дающий ненулевое** (``tap.writes``, ``get_metric(...)["count"]``,
``observation_bypasses``): ноль сам по себе проходит и тогда, когда механизм
не запустился вовсе — в этом файле такое случалось у соседей трижды.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from ..core.stats_manager import StatsManager
from ..observation.observation_manager import ObservationManager, observation_port

# --------------------------------------------------------------------------- #
# Приёмники-двойники
# --------------------------------------------------------------------------- #


class _CountingTap:
    """Живой приёмник: считает принятое. Якорь к ``numbers_delivered``."""

    name = "counting_tap"

    def __init__(self) -> None:
        self.writes = 0
        self.records: List[Dict[str, Any]] = []

    def write(self, record: Dict[str, Any]) -> None:
        self.writes += 1
        self.records.append(record)

    def close(self) -> None:  # pragma: no cover — best-effort хук remove_tap
        pass


class _RaisingTap:
    """Приёмник, чей ``write()`` всегда бросает."""

    name = "raising_tap"

    def __init__(self) -> None:
        self.calls = 0

    def write(self, record: Dict[str, Any]) -> None:
        self.calls += 1
        raise ValueError("приёмник не принял запись")

    def close(self) -> None:  # pragma: no cover
        pass


def _make_port(name: str) -> ObservationManager:
    port = ObservationManager(manager_name=name)
    assert port.initialize(), f"{name}: initialize() вернул False — стенд сломан ДО нагрузки"
    return port


def _make_stats(name: str) -> StatsManager:
    """Реальный ``StatsManager`` без файлового канала и без фонового сброса окна."""
    mgr = StatsManager(
        manager_name=name,
        config={
            "enable_logging": False,
            "aggregation_interval": 300.0,
            "flush_interval": 300.0,
            "channels": {"file_stats": {"enabled": False}},
        },
    )
    assert mgr.initialize(), f"{name}: initialize() вернул False — стенд сломан ДО нагрузки"
    return mgr


# =========================================================================== #
# Б1 — счётчик доставки отличает живую плоскость чисел от мёртвой
# =========================================================================== #


class TestB1DeliveryCounterSeesTheOutcome:
    def test_the_owners_pair_five_numbers_with_and_without_a_tap(self) -> None:
        """Пара вход→выход, из-за которой блокер и заведён.

        ДО правки обе половины давали ``delivered=5`` — счётчик отвечал на
        вопрос «сколько раз звали». ПОСЛЕ: мёртвая половина — пять потерь,
        живая — пять доставок, и её приёмник это подтверждает своим числом.
        """
        dead = _make_port("b1_dead_plane")
        try:
            for _ in range(5):
                dead.record_metric("plugin.frames", 1)
            stats = dead.get_stats()
            assert stats["numbers_delivered"] == 0, (
                f"приёмников нет — доставок не было ни одной, получено {stats['numbers_delivered']}"
            )
            assert stats["numbers_dropped_no_sink"] == 5, (
                f"пять чисел не дошли ни до кого, получено {stats['numbers_dropped_no_sink']}"
            )
        finally:
            dead.shutdown()

        live = _make_port("b1_live_plane")
        tap = _CountingTap()
        live.add_tap(tap, min_level="DEBUG", name="live")
        try:
            for _ in range(5):
                live.record_metric("plugin.frames", 1)
            stats = live.get_stats()
            # Якорь: приёмник действительно получил пять — без него «5» ниже
            # было бы совместимо с нулём доставок.
            assert tap.writes == 5, f"живой приёмник обязан получить пять записей, получено {tap.writes}"
            assert stats["numbers_delivered"] == 5, f"получено {stats['numbers_delivered']}"
            assert stats["numbers_dropped_no_sink"] == 0, f"получено {stats['numbers_dropped_no_sink']}"
        finally:
            live.shutdown()

    def test_the_reviewers_pair_removing_the_tap_stops_delivered_from_growing(self) -> None:
        """Пара ревьюера: attach → 1 доехало → remove_tap → 4 записи.

        ДО правки ``delivered`` вырастал на 4, реестр не менялся, все шесть
        счётчиков говорили «всё хорошо» — четыре числа исчезали молча.
        """
        port = _make_port("b1_after_remove")
        tap = _CountingTap()
        port.add_tap(tap, min_level="DEBUG", name="doomed")
        try:
            port.record_metric("plugin.frames", 1)
            assert tap.writes == 1, f"первая запись обязана доехать, получено {tap.writes}"
            assert port.get_stats()["numbers_delivered"] == 1

            assert port.remove_tap("doomed") is True, "tap обязан был существовать — стенд сломан"

            for _ in range(4):
                port.record_metric("plugin.frames", 1)

            stats = port.get_stats()
            assert tap.writes == 1, f"после снятия приёмник не должен получить НИЧЕГО, получено {tap.writes}"
            assert stats["numbers_delivered"] == 1, (
                f"после снятия tap'а доставок больше не было, получено {stats['numbers_delivered']}"
            )
            assert stats["numbers_dropped_no_sink"] == 4, (
                f"четыре числа обязаны быть названы потерей, получено {stats['numbers_dropped_no_sink']}"
            )
        finally:
            port.shutdown()

    def test_a_raising_sink_is_a_loss_not_a_delivery(self) -> None:
        """Приёмник бросил — число не доехало ни до кого, и это ДВА разных счётчика."""
        port = _make_port("b1_raising")
        tap = _RaisingTap()
        port.add_tap(tap, min_level="DEBUG", name="raising")
        try:
            port.record_metric("plugin.frames", 1)  # контракт «tail не роняет эмитента»
            stats = port.get_stats()
            assert tap.calls == 1, f"якорь: приёмника обязаны были ПОЗВАТЬ, вызовов {tap.calls}"
            assert stats["numbers_delivered"] == 0, f"получено {stats['numbers_delivered']}"
            assert stats["numbers_dropped_no_sink"] == 1, f"получено {stats['numbers_dropped_no_sink']}"
            assert stats["numbers_dropped_by_sink_error"] == 1, f"получено {stats['numbers_dropped_by_sink_error']}"
        finally:
            port.shutdown()

    def test_a_tap_cut_off_by_its_threshold_is_a_loss_too(self) -> None:
        """Единственный tap с порогом ERROR: у чисел уровня нет — запись до него не идёт.

        Проверяется ПАРОЙ: ``tap.writes == 0`` и ``numbers_dropped_no_sink == 1``.
        Если бы порог числа не резал, первый литерал стал бы единицей и тест
        покраснел бы, а не согласился молча.
        """
        port = _make_port("b1_threshold")
        tap = _CountingTap()
        port.add_tap(tap, min_level="ERROR", name="high_threshold")
        try:
            port.record_metric("plugin.frames", 1)
            stats = port.get_stats()
            assert tap.writes == 0, f"порог ERROR обязан отсечь запись без уровня, получено {tap.writes}"
            assert stats["numbers_delivered"] == 0, f"получено {stats['numbers_delivered']}"
            assert stats["numbers_dropped_no_sink"] == 1, f"получено {stats['numbers_dropped_no_sink']}"
        finally:
            port.shutdown()

    def test_a_reentrant_input_goes_to_neither_of_the_two_counters(self) -> None:
        """Реентрантный вход считается как раньше — своим счётчиком, и только им.

        Одна потеря — один счётчик: записать подавление ещё и в
        ``numbers_dropped_no_sink`` значило бы посчитать её дважды.
        """
        port = _make_port("b1_reentrant")

        class _ReentrantTap:
            name = "reentrant_tap"

            def __init__(self) -> None:
                self.writes = 0

            def write(self, record: Dict[str, Any]) -> None:
                self.writes += 1
                port.record_metric("reentrant.echo", 1)

            def close(self) -> None:  # pragma: no cover
                pass

        tap = _ReentrantTap()
        port.add_tap(tap, min_level="DEBUG", name="reentrant")
        try:
            for _ in range(5):
                port.record_metric("plugin.frames", 1)

            stats = port.get_stats()
            assert tap.writes == 5, f"якорь: внешние пять обязаны дойти до tap'а, получено {tap.writes}"
            assert stats["numbers_delivered"] == 5, f"получено {stats['numbers_delivered']}"
            assert stats["numbers_suppressed_reentrant"] == 5, f"получено {stats['numbers_suppressed_reentrant']}"
            assert stats["numbers_dropped_no_sink"] == 0, (
                "подавленный echo уже посчитан своим счётчиком — в потери «ни до кого» "
                f"он идти не должен, получено {stats['numbers_dropped_no_sink']}"
            )
        finally:
            port.shutdown()

    def test_the_pair_is_the_discriminator_not_delivered_alone(self) -> None:
        """Смешанный ход: часть доехала, часть — нет. Пара различает, одно число — нет.

        ``delivered > 0`` истинно в ОБОИХ состояниях (и в здоровом, и в
        наполовину потерянном) — ровно поэтому докстринг ``get_stats``
        переписан на пару.
        """
        port = _make_port("b1_mixed")
        tap = _CountingTap()
        port.add_tap(tap, min_level="DEBUG", name="mixed")
        try:
            port.record_metric("a", 1)
            port.record_metric("b", 1)
            port.remove_tap("mixed")
            port.record_metric("c", 1)

            stats = port.get_stats()
            assert tap.writes == 2, f"якорь: две записи обязаны доехать, получено {tap.writes}"
            assert stats["numbers_delivered"] == 2
            assert stats["numbers_dropped_no_sink"] == 1
            healthy = stats["numbers_delivered"] > 0 and stats["numbers_dropped_no_sink"] == 0
            assert healthy is False, "пара обязана назвать это состояние нездоровым"
            assert stats["numbers_delivered"] > 0, (
                "…при том что ОДИН только `delivered > 0` называет его здоровым — "
                "это и есть причина, по которой различитель стал парой"
            )
        finally:
            port.shutdown()

    def test_get_stats_key_is_exposed_and_starts_at_zero(self) -> None:
        """Ключ существует у свежего порта — потребитель не обязан гадать про KeyError."""
        port = _make_port("b1_key_present")
        try:
            stats = port.get_stats()
            assert "numbers_dropped_no_sink" in stats, f"ключ обязан быть в get_stats(), есть {sorted(stats)!r}"
            assert stats["numbers_dropped_no_sink"] == 0
        finally:
            port.shutdown()


class TestB1EmitToTapsReturnsTheCount:
    """Шов, на котором держится всё остальное: раздача отдаёт ЧИСЛО принявших."""

    def test_emit_returns_zero_without_taps_and_the_count_with_them(self) -> None:
        port = _make_port("b1_emit_contract")
        try:
            assert port._emit_to_taps({"metric": "x", "value": 1}) == 0, "приёмников нет — ноль"

            first, second = _CountingTap(), _CountingTap()
            port.add_tap(first, min_level="DEBUG", name="first")
            port.add_tap(second, min_level="DEBUG", name="second")
            assert port._emit_to_taps({"metric": "x", "value": 1}) == 2, "двое приняли — двойка"
            assert (first.writes, second.writes) == (1, 1), (
                f"якорь: оба приёмника обязаны получить запись, получено {(first.writes, second.writes)}"
            )

            port.add_tap(_RaisingTap(), min_level="DEBUG", name="raising")
            assert port._emit_to_taps({"metric": "x", "value": 1}) == 2, (
                "бросивший приёмник в счёт принявших не идёт, двое исправных — идут"
            )
        finally:
            port.shutdown()

    def test_emit_does_not_block_the_caller_under_a_raising_sink(self) -> None:
        """Раздача обязана ВЕРНУТЬСЯ, а не повиснуть: тест, способный блокироваться, — в потоке."""
        port = _make_port("b1_emit_no_hang")
        port.add_tap(_RaisingTap(), min_level="DEBUG", name="raising")
        result: List[Optional[int]] = [None]

        def _run() -> None:
            result[0] = port._emit_to_taps({"metric": "x", "value": 1})

        worker = threading.Thread(target=_run, daemon=True)
        worker.start()
        worker.join(timeout=5.0)
        try:
            assert not worker.is_alive(), "раздача не вернулась за 5 с — зависание вместо отказа"
            assert result[0] == 0, f"единственный приёмник бросил — принявших ноль, получено {result[0]!r}"
        finally:
            port.shutdown()


# =========================================================================== #
# З3 — attach докладывает успех только при СОСТОЯВШЕЙСЯ подписке
# =========================================================================== #


class _NoOpAddTapPort:
    """Порт с вызываемым, но НИЧЕГО не делающим ``add_tap`` (дыра 2).

    Ровно та форма, что проходила проверку ``callable(add_tap)``: attach
    возвращал ``True``, ``get_all_metrics()`` оставался ``{}``, а
    ``observation_bypasses`` — ``{}``, то есть оба индикатора «всё хорошо».
    """

    def __init__(self) -> None:
        self.add_calls = 0

    def add_tap(self, channel: Any, *, min_level: Any = "ERROR", name: Optional[str] = None) -> None:
        self.add_calls += 1
        return None

    def remove_tap(self, name: str) -> bool:
        return False

    def record_metric(self, *args: Any, **kwargs: Any) -> None:
        pass


class _RaisingAddTapPort(_NoOpAddTapPort):
    """Порт, чей ``add_tap`` бросает (дыра 3)."""

    def add_tap(self, channel: Any, *, min_level: Any = "ERROR", name: Optional[str] = None) -> None:
        self.add_calls += 1
        raise RuntimeError("подписка не удалась")


def _number_reaches_the_manager(mgr: StatsManager, metric: str) -> bool:
    """НАБЛЮДАЕМЫЙ критерий: число, записанное после attach, доехало обратно.

    Не шпион на имя ``add_tap`` — он сторожил бы имя, а не свойство. Здесь
    спрашивается результат: агрегат метрики виден менеджеру.
    """
    mgr.record_metric(metric, 1)
    mgr.flush()
    return mgr.get_metric(metric) is not None


class TestZ3AttachReportsTheFactOfSubscription:
    def test_reattach_after_the_tap_was_removed_still_delivers(self) -> None:
        """Пара ревьюера: attach → remove_tap → attach ТЕМ ЖЕ объектом.

        ДО правки вторая ``attach`` возвращала ``True``, не позвав ``add_tap``
        вовсе (ветка тождества), и числа переставали возвращаться менеджеру
        навсегда. Судим по наблюдаемому: ``True`` обязан означать доставку.
        """
        port = _make_port("z3_reattach_port")
        mgr = _make_stats("z3_reattach")
        try:
            assert mgr.attach_observation_port(port) is True
            tap_name = mgr._observation_tap_name
            assert port.has_tap(tap_name) is True, "стенд сломан ДО нагрузки: подписки нет"

            assert port.remove_tap(tap_name) is True
            assert port.has_tap(tap_name) is False, "стенд: tap обязан быть снят"

            verdict = mgr.attach_observation_port(port)
            delivered = _number_reaches_the_manager(mgr, "z3.reattached")

            assert verdict is delivered, (
                f"attach вернул {verdict!r}, а число {'доехало' if delivered else 'НЕ доехало'} — "
                "успех обязан означать доставку, а не тождество объекта"
            )
            assert verdict is True, "порт живой и подписываемый — attach обязан состояться"
            assert port.has_tap(tap_name) is True, "после успешного attach подписка обязана быть живой"
        finally:
            mgr.shutdown()
            port.shutdown()

    def test_a_callable_no_op_add_tap_is_refused(self) -> None:
        """Дыра 2: ``add_tap`` вызвался и не подписал никого — это отказ."""
        port = _NoOpAddTapPort()
        mgr = _make_stats("z3_noop")
        try:
            assert mgr.attach_observation_port(port) is False, (
                "порт, не подписавший никого, не вернёт число обратно — attach обязан отказать"
            )
            assert port.add_calls == 1, f"якорь: ``add_tap`` обязан был быть ПОЗВАН, вызовов {port.add_calls}"
            # Менеджер остался на прежней прямой дороге — и это видно с ДВУХ сторон.
            assert _number_reaches_the_manager(mgr, "z3.noop") is True, "отказ attach не должен ронять запись"
            assert mgr.observation_bypasses == {"record_metric": 1}, (
                f"обход обязан быть посчитан и назван по методу, получено {mgr.observation_bypasses!r}"
            )
        finally:
            mgr.shutdown()

    def test_a_throwing_add_tap_leaves_a_fresh_manager_on_the_direct_road(self) -> None:
        """Дыра 3, половина первая: подписка бросила — состояние не мутировано."""
        port = _RaisingAddTapPort()
        mgr = _make_stats("z3_raising_fresh")
        try:
            assert mgr.attach_observation_port(port) is False
            assert port.add_calls == 1, f"якорь: ``add_tap`` был позван, вызовов {port.add_calls}"
            assert _number_reaches_the_manager(mgr, "z3.raising") is True
            assert mgr.observation_bypasses == {"record_metric": 1}, f"получено {mgr.observation_bypasses!r}"
        finally:
            mgr.shutdown()

    def test_a_throwing_add_tap_does_not_break_an_already_working_port(self) -> None:
        """Дыра 3, половина вторая: неудачное переключение не рвёт РАБОЧУЮ подписку.

        Порядок «снять со старого → подписать нового» на отказе нового оставлял
        менеджера при старом порте с уже снятым tap'ом: числа уходили в порт и
        не возвращались никуда, при нулевых ``observation_bypasses``.
        """
        good = _make_port("z3_good_port")
        bad = _RaisingAddTapPort()
        mgr = _make_stats("z3_switch_fails")
        try:
            assert mgr.attach_observation_port(good) is True
            tap_name = mgr._observation_tap_name
            assert _number_reaches_the_manager(mgr, "z3.before") is True, "стенд сломан ДО нагрузки"

            assert mgr.attach_observation_port(bad) is False, "порт с бросающим add_tap обязан получить отказ"

            assert good.has_tap(tap_name) is True, (
                "неудачное переключение не имеет права снимать подписку с РАБОЧЕГО порта"
            )
            assert _number_reaches_the_manager(mgr, "z3.after") is True, (
                "после отказавшего переключения числа обязаны идти прежней дорогой"
            )
            assert mgr.observation_bypasses == {}, (
                f"дорога через порт цела — обходов быть не должно, получено {mgr.observation_bypasses!r}"
            )
        finally:
            mgr.shutdown()
            good.shutdown()

    def test_switching_to_another_live_port_moves_the_subscription(self) -> None:
        """Пара-контроль к предыдущему: УДАЧНОЕ переключение старую подписку снимает."""
        first = _make_port("z3_first_port")
        second = _make_port("z3_second_port")
        mgr = _make_stats("z3_switch_ok")
        try:
            assert mgr.attach_observation_port(first) is True
            tap_name = mgr._observation_tap_name
            assert mgr.attach_observation_port(second) is True

            assert first.has_tap(tap_name) is False, "старый порт не должен держать мёртвую подписку"
            assert second.has_tap(tap_name) is True, "новый порт обязан быть подписан"
            assert _number_reaches_the_manager(mgr, "z3.moved") is True
        finally:
            mgr.shutdown()
            first.shutdown()
            second.shutdown()

    def test_detaching_with_none_still_returns_false_and_removes_the_tap(self) -> None:
        """Законное явное отключение не изменилось: ``False`` + снятая подписка."""
        port = _make_port("z3_detach_port")
        mgr = _make_stats("z3_detach")
        try:
            assert mgr.attach_observation_port(port) is True
            tap_name = mgr._observation_tap_name
            assert mgr.attach_observation_port(None) is False, "явное отключение — не успех подписки"
            assert port.has_tap(tap_name) is False, "подписка обязана быть снята"
            assert _number_reaches_the_manager(mgr, "z3.detached") is True, "прямая дорога обязана работать"
            assert mgr.observation_bypasses == {"record_metric": 1}, f"получено {mgr.observation_bypasses!r}"
        finally:
            mgr.shutdown()
            port.shutdown()

    def test_reattach_returns_true_only_when_the_port_can_be_asked(self) -> None:
        """Порт, который на ``has_tap`` бросает, подписку не подтверждает.

        Пара к предыдущим: «спросить нечем» (дубля без ``has_tap``) и «спросили,
        и он сломался» — разные вещи; второе доверия к подписке не прибавляет.
        """

        class _BrokenHasTapPort(_NoOpAddTapPort):
            def add_tap(self, channel: Any, *, min_level: Any = "ERROR", name: Optional[str] = None) -> str:
                self.add_calls += 1
                return str(name)

            def has_tap(self, name: str) -> bool:
                raise RuntimeError("порт не может ответить о себе")

        port = _BrokenHasTapPort()
        mgr = _make_stats("z3_broken_has_tap")
        try:
            assert mgr.attach_observation_port(port) is False, (
                "порт, отказавший на читающем вопросе о подписке, обязан получить отказ"
            )
            assert port.add_calls == 1, f"якорь: ``add_tap`` был позван, вызовов {port.add_calls}"
            assert mgr.observation_bypasses == {}, "до первой записи обходов быть не должно"
            assert _number_reaches_the_manager(mgr, "z3.broken") is True
            assert mgr.observation_bypasses == {"record_metric": 1}, f"получено {mgr.observation_bypasses!r}"
        finally:
            mgr.shutdown()

    def test_repeated_attach_of_a_live_port_does_not_pile_up_taps(self) -> None:
        """Идемпотентность не потеряна: повтор не заводит второй подписки."""
        port = _make_port("z3_idempotent_port")
        mgr = _make_stats("z3_idempotent")
        try:
            assert mgr.attach_observation_port(port) is True
            assert mgr.attach_observation_port(port) is True
            assert len(port._tap_sinks) == 1, (
                f"повторный attach обязан остаться одной подпиской, получено {len(port._tap_sinks)}"
            )
            assert _number_reaches_the_manager(mgr, "z3.idem") is True
            metric = mgr.get_metric("z3.idem")
            assert metric is not None and metric["count"] == 1.0, (
                f"число обязано быть учтено РОВНО один раз, получено {metric!r}"
            )
        finally:
            mgr.shutdown()
            port.shutdown()


# =========================================================================== #
# Побочная находка сквозного теста З6: резолвер порта ронял ЧИТАТЕЛЯ уровней
# =========================================================================== #


class _ServicesWithBrokenGetManager:
    """``get_manager`` вызываем и БРОСАЕТ — репродукция ``ProcessManagerProcess``."""

    def __init__(self) -> None:
        self.calls = 0

    def get_manager(self, name: str) -> Any:
        self.calls += 1
        raise AttributeError("'ProcessManagerProcess' object has no attribute '_registry'")


class TestObservationPortResolverDoesNotRaise:
    """Контракт функции — «``None`` = названный no-op, уровень не роняет линию».

    Найдено сквозным тестом блокера З6 (``process_module``): ступень 1 резолвера
    звала ``get_manager`` без защиты, и на таком держателе падала ВСЯ команда
    ``introspect.observability`` — диагностика умирала там, где её зовут
    разбирать инцидент. Правка S2 закрыла тем же доводом путь счётчиков, путь
    уровней остался открытым.
    """

    def test_a_throwing_get_manager_yields_none_instead_of_an_exception(self) -> None:
        svc = _ServicesWithBrokenGetManager()
        assert observation_port(svc) is None
        assert svc.calls == 1, f"якорь: ступень 1 обязана была ПОПЫТАТЬСЯ, вызовов {svc.calls}"

    def test_the_slot_is_still_returned_when_it_resolves(self) -> None:
        """Пара-контроль: глушение не должно превратить резолвер в вечный ``None``."""
        port = _make_port("resolver_live_slot")

        class _ServicesWithSlot:
            def get_manager(self, name: str) -> Any:
                return port

        try:
            assert observation_port(_ServicesWithSlot()) is port
        finally:
            port.shutdown()
