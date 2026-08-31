# -*- coding: utf-8 -*-
"""Авторские hazard'ы снятия по писателю (Ф2, Task 2.2).

Приёмку «поддерево ушедшего писателя исчезает» пишет независимый тестер от
критериев (``test_f2_acceptance_writer_retraction.py``) — здесь СВОЙ класс
находок: внутренние опасности МЕХАНИЗМА, видимые только тому, кто знает, как он
собран. Их три, и каждая названа тем, что может сломаться именно в этой
конструкции:

1. **Порядок внутри тика.** Снятие стоит ПЕРВЫМ шагом
   ``_publish_telemetry_to_tree`` — до сборки уровней и до раннего выхода
   «нечего слать». Переставь его в конец — и процесс, чей последний писатель
   только что ушёл, не снял бы ничего никогда (публиковать нечего → ранний
   выход). Переставь после сборки — и публикация возвращённого писателя,
   пришедшая в это окно, потеряла бы лист до следующего тика.

2. **Бухгалтерия запаса.** Тратится ТОЛЬКО на успехе вызова, а «успех» на
   fire-and-forget дороге означает лишь «вызов вернулся». Значит: (а) молча
   потерянное сообщение обязано быть утверждено ещё раз, (б) исключение не
   имеет права стоить запаса, (в) запас обязан кончаться — иначе снятие
   становится вечным фоновым трафиком.

3. **Гонка publish/retract одного писателя.** ``retract`` идёт потоком
   остановки плагина, ``publish`` — потоком воркера, снятие в дереве —
   потоком heartbeat. Между снимком ведомости и вызовом ``delete`` стоит
   реальный IPC-вызов, и публикация возвращённого писателя успевает прийти
   ровно туда.

Дубли дерева — ``TreeStore``-подобные (merge разворачивает точку в путь, delete
снимает РОВНО сегмент), взяты у соседнего файла, а не переписаны: дубль, который
умеет меньше стора, красит исправный механизм (уже случалось — см. докстринг
``_Proxy`` в ``test_plugin_levels_hazards.py``).

Всё блокирующее — в daemon-потоке с ``join(timeout)``: тест, который висит
вместо того, чтобы упасть, хуже отсутствующего.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

import pytest

from multiprocess_framework.modules.process_module.heartbeat.telemetry import (
    DEPARTED_DELETE_BUDGET,
    PLUGIN_LEVELS_ATTR,
    PluginLevels,
)
from multiprocess_framework.modules.process_module.plugins.base import PluginContext

from .test_plugin_levels_hazards import _boot, _level, _Proxy, _Services, _tick_levels

#: Литерал запаса, а НЕ импортированная константа механизма. Проверять число
#: тем же числом, которым его вычислили, — это согласие кода с самим собой:
#: смена ``DEPARTED_DELETE_BUDGET`` на 1 или на 99 не покрасила бы ни одного
#: теста ниже. Расхождение с механизмом сторожится отдельной парой (см.
#: ``TestTheBudgetLiteralMatchesTheMechanism``).
_K = 3


def _path(services: _Services, writer: str) -> str:
    return f"processes.{services.name}.state.plugins.{writer}"


def _subtree(services: _Services, writer: str) -> Any:
    return services._state_proxy.get(_path(services, writer))


def _writer(services: _Services, name: str) -> PluginContext:
    """Контекст плагина-писателя. Объявления нет намеренно: с Ф1 публиковать
    можно и без него, а объявление засоряло бы общий каталог метрик."""
    return PluginContext(services=services, config={}, plugin_name=name)


def _port(services: _Services) -> PluginLevels:
    port = getattr(services, PLUGIN_LEVELS_ATTR, None)
    assert isinstance(port, PluginLevels), "порт уровней не создан — писатель не публиковал"
    return port


class _LosingProxy(_Proxy):
    """Дерево, чей ``delete`` МОЛЧА теряет первые ``lose`` сообщений.

    Форма потери — дословно та, ради которой существует запас: вызов вернулся
    как обычно (``StateProxy.delete`` fire-and-forget, отправитель ответа не
    видит), а до стора сообщение не доехало. Отличается от исключения тем, что
    отправитель НЕ УЗНАЁТ о потере — иначе тест проверял бы отказ, а не потерю.
    """

    def __init__(self, lose: int) -> None:
        super().__init__()
        self._lose = lose

    def delete(self, path: str) -> bool:
        self.deletes.append(path)
        if self._lose > 0:
            self._lose -= 1
            return False  # «доставлено» с точки зрения отправителя, дерево не тронуто
        return super().delete(path)


class _RaisingProxy(_Proxy):
    """Дерево, чей ``delete`` БРОСАЕТ первые ``fail`` раз.

    Не гипотеза: прокси без этой дороги отвечает ``AttributeError``, а отказ
    транспорта, поднятый наружу, — обычное дело на остановке процесса.
    """

    def __init__(self, fail: int) -> None:
        super().__init__()
        self._fail = fail
        self.attempts = 0

    def delete(self, path: str) -> bool:
        self.attempts += 1
        if self._fail > 0:
            self._fail -= 1
            raise RuntimeError("транспорт снятия недоступен")
        return super().delete(path)


class _PublishingOnDeleteProxy(_Proxy):
    """Дерево, чей ``delete`` даёт возвращённому писателю опубликоваться РОВНО
    между снимком ведомости и снятием узла.

    Детерминированная замена потоку: то же окно, но без ожиданий и без флейка.
    """

    def __init__(self, hook: Callable[[], None]) -> None:
        super().__init__()
        self._hook = hook

    def delete(self, path: str) -> bool:
        self._hook()
        return super().delete(path)


# =========================================================================== #
# 1. Порядок внутри тика
# =========================================================================== #
class TestTheRetractionDoesNotDependOnHavingSomethingToPublish:
    def test_the_last_writer_leaving_still_gets_its_subtree_removed(self):
        """Ушёл ПОСЛЕДНИЙ писатель — публиковать нечего, снимать нужно.

        Ровно этот случай проваливает снятие, поставленное в конец тика: секция
        ``state`` пуста, ``if not data: return`` срабатывает, и хвост метода
        недостижим. Якорь существования — лист с литералом до стопа; второй
        якорь — ``merges`` НЕ растёт на тике снятия (то есть слать было
        действительно нечего, и тест судит именно этот случай, а не соседний).
        """
        services, hb = _boot(name="last")
        writer = _writer(services, "only_writer")
        writer.publish_metric("fps", 12.5)
        _tick_levels(hb)
        assert _level(services, "only_writer", "fps") == 12.5, "предпосылка: лист есть с литералом"

        writer._retract_metrics()
        merges_before = len(services._state_proxy.merges)
        _tick_levels(hb)

        assert len(services._state_proxy.merges) == merges_before, (
            "тик прислал merge — значит публиковать было что, и тест судит не тот случай"
        )
        assert _subtree(services, "only_writer") is None, (
            f"поддерево последнего писателя пережило тик — снятие стоит ПОСЛЕ раннего выхода "
            f"«нечего слать». Дерево: {services._state_proxy.tree}"
        )

    def test_the_delete_is_addressed_by_the_writer_not_by_the_leaf(self):
        """Адрес снятия — узел ПИСАТЕЛЯ, литералом, а не путь до листа.

        Сторожит форму пути целиком: промахнись механизм сегментом (``state`` без
        ``plugins``, лист вместо узла, имя процесса не то) — литерал разойдётся.
        """
        services, hb = _boot(name="addr")
        writer = _writer(services, "addressed")
        writer.publish_metric("fps", 1.0)
        _tick_levels(hb)
        writer._retract_metrics()
        _tick_levels(hb)

        assert services._state_proxy.deletes == ["processes.addr.state.plugins.addressed"], (
            f"снятие адресовало не узел писателя: {services._state_proxy.deletes}"
        )


# =========================================================================== #
# 2. Бухгалтерия запаса
# =========================================================================== #
class TestTheBudgetSurvivesALostDelete:
    def test_a_silently_lost_delete_is_reasserted_on_the_next_tick(self):
        """Потеря первого снятия не хоронит его — кванторно, по тикам.

        Первый ``delete`` теряется молча (отправитель об этом не узнаёт), второй
        доезжает. Проверяются ОБА тика: после первого поддерево ОБЯЗАНО быть на
        месте (иначе потеря не воспроизведена и тест доказывает не то), после
        второго — исчезнуть.
        """
        services, hb = _boot(name="lost")
        services._state_proxy = _LosingProxy(lose=1)
        writer = _writer(services, "unlucky")
        writer.publish_metric("fps", 33.3)
        _tick_levels(hb)
        assert _level(services, "unlucky", "fps") == 33.3, "предпосылка: лист есть с литералом"

        writer._retract_metrics()

        _tick_levels(hb)
        assert _subtree(services, "unlucky") is not None, (
            "первое снятие не потерялось — инъекция потери не воспроизведена, и второй тик ничего не доказывает"
        )

        _tick_levels(hb)
        assert _subtree(services, "unlucky") is None, (
            f"второе утверждение снятия не пришло — запас не переживает одну потерю. "
            f"Обращений к delete: {services._state_proxy.deletes}"
        )

    def test_the_budget_is_finite_and_the_traffic_stops(self):
        """Запас КОНЕЧЕН: ровно три утверждения на одну остановку, не по одному
        сообщению каждый тик до конца жизни процесса.

        Литерал 3, а не ``DEPARTED_DELETE_BUDGET``: тест обязан покраснеть и
        когда механизм сменит число, и когда он перестанет считать вовсе.
        Тиков заведомо больше запаса (кванторно, ≥2).
        """
        services, hb = _boot(name="finite")
        writer = _writer(services, "counted")
        writer.publish_metric("fps", 7.0)
        _tick_levels(hb)
        writer._retract_metrics()

        for _ in range(10):
            _tick_levels(hb)

        assert len(services._state_proxy.deletes) == _K, (
            f"утверждений снятия {len(services._state_proxy.deletes)}, ожидали ровно {_K}: "
            f"{services._state_proxy.deletes}"
        )
        assert _port(services).departed_writers() == (), (
            "исчерпанный писатель остался в ведомости — конечный запас стал бессрочной записью"
        )

    def test_an_exception_does_not_spend_the_budget(self):
        """Исключение — не расход запаса: сообщение из процесса не вышло.

        Отказов ПЯТЬ, то есть больше запаса. Спишись запас на них — писатель
        ушёл бы из ведомости после третьего, и поддерево не сняли бы никогда,
        сколько ни чини транспорт. Якорь в том же тесте: пока транспорт падает,
        сосед-писатель продолжает ехать в дерево своим литералом (тик жив, а не
        проглочен отказом).
        """
        services, hb = _boot(name="raise")
        services._state_proxy = _RaisingProxy(fail=5)
        dying = _writer(services, "dying")
        neighbour = _writer(services, "neighbour")
        dying.publish_metric("fps", 11.1)
        neighbour.publish_metric("fps", 22.2)
        _tick_levels(hb)
        assert _level(services, "dying", "fps") == 11.1, "предпосылка"

        dying._retract_metrics()

        for tick in range(1, 6):  # все пять отказных тиков проверяются поимённо
            neighbour.publish_metric("fps", 22.2)
            _tick_levels(hb)
            assert _subtree(services, "dying") is not None, (
                f"тик {tick}: поддерево снято, хотя транспорт снятия падал — дубль не воспроизвёл отказ"
            )
            assert _level(services, "neighbour", "fps") == 22.2, (
                f"тик {tick}: ЯКОРЬ — отказ снятия погасил публикацию соседа, то есть уронил весь тик"
            )

        _tick_levels(hb)  # транспорт починился
        assert _subtree(services, "dying") is None, (
            f"снятие не состоялось после починки транспорта — запас сгорел на отказах. "
            f"Попыток: {services._state_proxy.attempts}"
        )

    def test_a_writer_that_never_published_costs_no_traffic(self):
        """Остановка плагина без единого уровня не шлёт ни одного снятия.

        В дереве у него ничего нет (сборщик проецирует ровно хранилище), поэтому
        три сообщения были бы платой ни за что. ЯКОРЬ в том же тесте: писатель с
        листом трафик порождает.
        """
        services, hb = _boot(name="silentw")
        loud = _writer(services, "loud")
        loud.publish_metric("fps", 5.0)
        _tick_levels(hb)

        silent = _writer(services, "silent")
        assert silent._retract_metrics() == 0, "предпосылка: снимать у молчуна было нечего"
        _tick_levels(hb)
        assert services._state_proxy.deletes == [], (
            f"остановка молчуна породила снятия: {services._state_proxy.deletes}"
        )

        loud._retract_metrics()
        _tick_levels(hb)
        assert services._state_proxy.deletes == ["processes.silentw.state.plugins.loud"], (
            f"ЯКОРЬ: писатель С листом снятия не породил — тест выше зелен по причине «не работает вовсе»: "
            f"{services._state_proxy.deletes}"
        )


class TestTheBudgetLiteralMatchesTheMechanism:
    """Пара к литералу ``_K``: тесты выше не читают константу механизма, поэтому
    её расхождение с ними ловится ЗДЕСЬ, одним явным сравнением, а не молчанием."""

    def test_the_mechanism_still_uses_the_literal_the_tests_assume(self):
        assert DEPARTED_DELETE_BUDGET == _K, (
            f"запас механизма стал {DEPARTED_DELETE_BUDGET}, а тесты этого файла считают {_K} — "
            f"сверьте кванторные утверждения выше, они судят число сообщений"
        )


# =========================================================================== #
# 3. Гонка publish/retract одного писателя
# =========================================================================== #
class TestAReturningWriterBeatsItsOwnDeletion:
    def test_a_publish_landing_inside_the_delete_is_repaired_by_the_same_tick(self):
        """Публикация возвращённого писателя пришла в окно «снимок → delete».

        Ведомость на момент снимка ещё содержит писателя, поэтому снятие уходит;
        публикация при этом уже случилась. Тик обязан вернуть лист ТЕМ ЖЕ
        merge — потому что сборка идёт ПОСЛЕ снятия. Собери он раньше — лист
        пропал бы до следующего тика, и на стенде это выглядело бы мерцанием
        показаний живого плагина.

        Кванторно: проверяется и следующий тик — отложенное снятие не имеет
        права догнать писателя позже.
        """
        services, hb = _boot(name="window")
        writer = _writer(services, "returning")
        writer.publish_metric("fps", 60.0)
        _tick_levels(hb)
        writer._retract_metrics()

        landed: list[bool] = []

        def republish() -> None:
            if landed:  # ровно один раз — второе окно уже не гонка
                return
            landed.append(True)
            writer.publish_metric("fps", 55.5)

        services._state_proxy = _PublishingOnDeleteProxy(republish)
        # Дерево дубля начинается пустым — вернём предпосылку тем же путём, каким
        # её кладёт механизм: одним тиком до гонки писатель не публиковал бы, но
        # узел в дереве обязан существовать, иначе снимать нечего.
        services._state_proxy.merge(f"processes.{services.name}", {"state": {"plugins": {"returning": {"fps": 60.0}}}})
        assert _level(services, "returning", "fps") == 60.0, "предпосылка: узел в дереве есть"

        _tick_levels(hb)

        assert landed, "инъекция не сработала: публикация не пришла в окно снятия"
        assert _level(services, "returning", "fps") == 55.5, (
            f"вернувшийся писатель потерял лист на своём же тике — сборка идёт ПЕРЕД снятием. "
            f"Дерево: {services._state_proxy.tree}"
        )
        assert _port(services).departed_writers() == (), (
            "писатель остался в ведомости после публикации — publish не снимает свой ключ"
        )

        _tick_levels(hb)
        assert _level(services, "returning", "fps") == 55.5, (
            "следующий тик всё-таки снял живого писателя — отложенное снятие догнало его позже"
        )

    def test_a_returned_writer_generates_no_deletions_at_all(self):
        """Возвращение писателя гасит отложенное снятие ЭФФЕКТОМ, а не только в
        ведомости: по его пути не уходит ни одного ``delete``.

        Проверять это листом в дереве бесполезно — порядок «сначала снять, потом
        собрать» вернул бы лист тем же тиком, и отравленная ведомость выглядела
        бы исправной. Видно её по трафику: лишнее снятие уезжает вниз реальной
        MISSING-дельтой, и потребители (сток, read-model) успевают на ней
        вычистить строки живого писателя. Кванторно — три тика подряд.

        ЯКОРЬ в том же тесте: сосед, который ушёл и НЕ вернулся, снятия
        порождает.
        """
        services, hb = _boot(name="returned")
        back = _writer(services, "comes_back")
        gone = _writer(services, "stays_gone")
        back.publish_metric("fps", 1.5)
        gone.publish_metric("fps", 2.5)
        _tick_levels(hb)
        assert _level(services, "comes_back", "fps") == 1.5, "предпосылка"

        back._retract_metrics()
        gone._retract_metrics()
        back.publish_metric("fps", 9.5)  # вернулся ДО первого же тика

        for _ in range(3):
            _tick_levels(hb)

        assert services._state_proxy.deletes.count(_path(services, "comes_back")) == 0, (
            f"по вернувшемуся писателю ушло снятие — publish не снял свой ключ с ведомости: "
            f"{services._state_proxy.deletes}"
        )
        gone_deletes = services._state_proxy.deletes.count(_path(services, "stays_gone"))
        assert gone_deletes == _K, (
            f"ЯКОРЬ: по НЕ вернувшемуся писателю снятий {gone_deletes}, ожидали {_K} — "
            f"тест выше зелен по причине «снятий не бывает вовсе»"
        )
        assert _level(services, "comes_back", "fps") == 9.5, "вернувшийся писатель не виден в дереве"

    def test_publish_and_retract_from_another_thread_never_break_the_tick(self):
        """Тот же писатель бьётся публикацией и снятием из ЧУЖОГО потока, пока
        тикает heartbeat.

        Три потока вокруг одной ведомости — как в проде (воркер плагина,
        остановка плагина, heartbeat). Судится две вещи: ни одна из сторон не
        поднимает исключение (в том числе ``RuntimeError: dictionary changed
        size during iteration`` на обходе ведомости), и после того как поток
        встал, система приходит в определённое состояние — последняя публикация
        видна в дереве.

        Поток — daemon с ``join(timeout)``; тест, который висит вместо падения,
        хуже отсутствующего.
        """
        services, hb = _boot(name="churn")
        writer = _writer(services, "racer")
        writer.publish_metric("fps", 1.0)
        _tick_levels(hb)

        stop = threading.Event()
        errors: list[BaseException] = []

        def churn() -> None:
            try:
                while not stop.is_set():
                    writer.publish_metric("fps", 1.0)
                    writer._retract_metrics()
            except BaseException as exc:  # noqa: BLE001 — ловим ровно то, что ищем
                errors.append(exc)

        thread = threading.Thread(target=churn, daemon=True)
        thread.start()
        try:
            for _ in range(300):
                _tick_levels(hb)
        finally:
            stop.set()
            thread.join(timeout=5.0)

        assert not thread.is_alive(), "поток-мучитель не завершился — тест повис бы"
        assert not errors, f"публикация/снятие не пережили конкурентный тик: {errors!r}"

        # Поток встал — состояние приводится к определённости и проверяется литералом.
        writer.publish_metric("fps", 88.8)
        _tick_levels(hb)
        assert _level(services, "racer", "fps") == 88.8, (
            f"после гонки живой писатель не виден в дереве. Дерево: {services._state_proxy.tree}"
        )


# =========================================================================== #
# 4. Два ушедших подряд — у каждого свой запас
# =========================================================================== #
class TestTwoDepartedWritersInARow:
    def test_each_departure_carries_its_own_budget_and_the_living_one_is_untouched(self):
        """Второй ушедший не тратит запас первого и не задевает живого.

        Ведомость по ключу писателя — сторожится по тикам: на тике ухода первого
        второй и третий живы своими литералами; на тике ухода второго третий
        по-прежнему жив, а первый остаётся снятым.
        """
        services, hb = _boot(name="pair")
        first = _writer(services, "first_gone")
        second = _writer(services, "second_gone")
        alive = _writer(services, "still_here")
        for ctx, value in ((first, 10.1), (second, 20.2), (alive, 30.3)):
            ctx.publish_metric("fps", value)
        _tick_levels(hb)
        assert _level(services, "first_gone", "fps") == 10.1, "предпосылка"
        assert _level(services, "second_gone", "fps") == 20.2, "предпосылка"
        assert _level(services, "still_here", "fps") == 30.3, "предпосылка"

        first._retract_metrics()
        _tick_levels(hb)
        assert _subtree(services, "first_gone") is None, "первый ушедший не снят"
        assert _level(services, "second_gone", "fps") == 20.2, "уход первого задел второго до его остановки"
        assert _level(services, "still_here", "fps") == 30.3, "уход первого задел живого писателя"

        second._retract_metrics()
        _tick_levels(hb)
        assert _subtree(services, "second_gone") is None, "второй ушедший не снят"
        assert _subtree(services, "first_gone") is None, "первый вернулся в дерево"
        assert _level(services, "still_here", "fps") == 30.3, "уход второго задел живого писателя"

        # У каждого свой счёт: по три утверждения на писателя, ни одного лишнего.
        for _ in range(5):
            _tick_levels(hb)
        by_writer = {
            "first_gone": services._state_proxy.deletes.count("processes.pair.state.plugins.first_gone"),
            "second_gone": services._state_proxy.deletes.count("processes.pair.state.plugins.second_gone"),
            "still_here": services._state_proxy.deletes.count("processes.pair.state.plugins.still_here"),
        }
        assert by_writer == {"first_gone": _K, "second_gone": _K, "still_here": 0}, by_writer


# =========================================================================== #
# 5. Отключаемость: процесс без порта уровней
# =========================================================================== #
class TestAProcessWithoutThePortTicksAsBefore:
    def test_a_tick_without_any_writer_neither_raises_nor_deletes(self):
        """Порт создаётся лениво первой публикацией. Процесс, где её не было,
        обязан тикать как раньше — снятие не имеет права требовать порт."""
        services, hb = _boot(name="bare")
        assert getattr(services, PLUGIN_LEVELS_ATTR, None) is None, "предпосылка: порта нет"

        _tick_levels(hb)  # не бросает

        assert services._state_proxy.deletes == [], services._state_proxy.deletes
        assert services._state_proxy.tree == {}, services._state_proxy.tree


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
