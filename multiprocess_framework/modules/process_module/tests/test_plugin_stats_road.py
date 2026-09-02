# -*- coding: utf-8 -*-
"""Этап 6, задача 1.1: плагин отдаёт бизнес-метрику тем же жестом, что лог.

Что здесь судится и почему именно так:

* **Оракул — протокол и настоящий менеджер**, не рукописный список. Дорога метрик
  ложится в проект, где имя ``record_metric`` УЖЕ живёт с двумя противоположными
  смыслами: у ``StatsManager``/``ObservableMixin`` это counter, у
  ``ObservabilityHub._emit_stat`` — gauge. Третье написание сигнатур сделало бы
  расхождение вопросом времени, поэтому совпадение сверяется ``inspect.signature``.
  ``isinstance`` у ``runtime_checkable``-протокола проверяет ТОЛЬКО имена и
  перестановку аргументов пропустил бы молча.
* **Единица — секунды.** Миллисекунды на этой дороге не падают тестом: агрегат
  соберётся, а границы бакетов задачи 2.2 сложат все кадровые тайминги в первый
  бакет — p95 станет константой при зелёном прогоне. Поэтому единица судится
  числом, где секунды и мс расходятся (0.016 ≠ 16), и читается из НАСТОЯЩЕГО
  ``StatsManager``.
* **Ненастроенная плоскость обязана быть слышимой.** У метрики нет возврата
  (сигнатура дословна менеджеру), поэтому счётчик и однократный голос — её
  единственный канал наблюдаемости. У документов рядом есть ``False``; здесь его
  нет, и «тихо вернули» было бы полной слепотой.
"""

from __future__ import annotations

import inspect
import sys

import pytest

from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    stats_plane_report,
)
from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    SubPluginContext,
)
from multiprocess_framework.modules.process_module.plugins.interfaces import (
    IPluginStatsManager,
    IProcessServices,
)
from multiprocess_framework.modules.process_module.plugins.testing import (
    MockProcessServices,
    MockStatsManager,
)
from multiprocess_framework.modules.statistics_module.core.stats_manager import StatsManager
from multiprocess_framework.modules.tests._road_cost import count_calls, timed_pair

#: Порт, который читает фасад. Имя одно и то же в протоколе, в процессе и в дубле —
#: рукописные копии одного имени расходятся молча, поэтому копия здесь одна.
STATS_PORT = "stats_manager"


def _four_roads() -> set[str]:
    """Четвёрка stats — из узкого протокола, а не перечислением в тесте."""
    return {name for name, _ in inspect.getmembers(IPluginStatsManager) if not name.startswith("_")}


def _shape(fn: object) -> list[tuple[str, object, object]]:
    """Форма сигнатуры без ``self`` и без аннотаций: имя, род параметра, дефолт.

    Аннотации намеренно выброшены: ``Optional[Dict]`` менеджера и ``dict | None``
    протокола — одно и то же обязательство, записанное разным синтаксисом, и
    сравнение по тексту аннотации краснело бы на переписывании типов, ничего не
    говоря о совместимости вызова. Имя, позиция и дефолт — ровно то, чем вызов
    ломается на самом деле.
    """
    params = list(inspect.signature(fn).parameters.values())  # type: ignore[arg-type]
    return [(p.name, p.kind, p.default) for p in params if p.name != "self"]


# ==============================================================================
# Оракул не должен быть вакуумным
# ==============================================================================


class TestTheOracleItself:
    def test_the_protocol_declares_the_stats_port(self) -> None:
        """Порт объявлен в ``IProcessServices`` — иначе дорога снова была бы несудима.

        Ровно тот дефект, что чинили у документов (Н-9): фасад читает менеджер с
        сервисов, а протокол о нём не знает — дубль, собранный по протоколу,
        менеджера не имеет, и путь метрики нельзя ни пройти, ни отказать.
        """
        members = {name for name, _ in inspect.getmembers(IProcessServices) if not name.startswith("_")}
        assert STATS_PORT in members

    def test_the_narrow_protocol_declares_exactly_the_four(self) -> None:
        """Четыре дороги — не три и не пять. Сломанный разбор протокола краснеет здесь."""
        assert _four_roads() == {"record_metric", "gauge", "record_timing", "histogram"}

    def test_the_protocol_carries_no_metric_type_argument(self) -> None:
        """Рода метрики строкой в аргументах нет ни у одной дороги.

        Род выбирается ИМЕНЕМ метода, как у ``StatsManager``. Появись пятый
        аргумент ``metric_type`` — тот же выбор существовал бы в двух написаниях,
        и они разошлись бы, как уже разошлось значение имени ``record_metric``.
        """
        for road in sorted(_four_roads()):
            names = [name for name, _kind, _default in _shape(getattr(IPluginStatsManager, road))]
            assert "metric_type" not in names, f"{road} завёл строковый род метрики"

    @pytest.mark.parametrize("road", sorted(_four_roads()))
    def test_the_protocol_matches_the_real_manager(self, road: str) -> None:
        """Сигнатура протокола совпадает с настоящим ``StatsManager`` — дословно.

        Не «похожа»: имена, позиции и дефолты. ``isinstance`` этого не проверяет,
        а ``record_metric(name, value=1)`` против ``record_metric(value, name)``
        сломался бы у первого же вызывающего.
        """
        assert _shape(getattr(IPluginStatsManager, road)) == _shape(getattr(StatsManager, road))

    @pytest.mark.parametrize("road", sorted(_four_roads()))
    def test_the_facade_matches_the_protocol(self, road: str) -> None:
        """И фасад плагина — та же форма. Третьего написания в проекте нет."""
        assert _shape(getattr(PluginContext, road)) == _shape(getattr(IPluginStatsManager, road))

    def test_the_real_manager_satisfies_the_narrow_protocol(self) -> None:
        """Настоящий менеджер годен как ``IPluginStatsManager`` — по построению, не по вере."""
        assert isinstance(StatsManager(manager_name="oracle_probe"), IPluginStatsManager)


# ==============================================================================
# Дорога метрики: проходится, штампуется, отказывает вслух
# ==============================================================================


class TestTheStatsRoadIsJudged:
    def test_all_four_roads_reach_the_manager_with_their_own_kind(self) -> None:
        """Каждая дорога доезжает и приносит СВОЙ род — счётчик не превращается в gauge."""
        manager = MockStatsManager()
        ctx = PluginContext(services=MockProcessServices(stats_manager=manager), config={})

        ctx.record_metric("frames", 3)
        ctx.gauge("temperature", 42.5)
        ctx.record_timing("cycle", 0.016)
        ctx.histogram("roi_area", 128.0)

        assert [(kind, name, value) for kind, name, value, _tags in manager.records] == [
            ("counter", "frames", 3),
            ("gauge", "temperature", 42.5),
            ("timing", "cycle", 0.016),
            ("histogram", "roi_area", 128.0),
        ]

    def test_the_default_of_record_metric_is_one(self) -> None:
        """``ctx.record_metric("name")`` считает единицу — как у менеджера."""
        manager = MockStatsManager()
        ctx = PluginContext(services=MockProcessServices(stats_manager=manager), config={})

        ctx.record_metric("frames")

        assert manager.records[0][2] == 1

    def test_the_metric_carries_the_name_of_its_plugin(self) -> None:
        """Метрика штампуется источником — иначе две серии сливаются в одну.

        Класс дефекта прожитый: процессный счётчик без ключа эмитента показывает
        сумму двух плагинов как одно правдоподобное число, и разойтись они могут
        сколь угодно далеко, оставаясь незаметными.
        """
        manager = MockStatsManager()
        ctx = PluginContext(services=MockProcessServices(stats_manager=manager), config={}, plugin_name="color_mask")

        ctx.record_metric("frames")

        assert manager.records[0][3] == {"plugin": "color_mask"}

    def test_an_explicit_tag_wins_over_the_stamp(self) -> None:
        """Лесенка как у логов: явное на call-site бьёт автоштамп."""
        manager = MockStatsManager()
        ctx = PluginContext(services=MockProcessServices(stats_manager=manager), config={}, plugin_name="color_mask")

        ctx.record_metric("frames", 1, {"plugin": "по-своему", "roi": "верх"})

        assert manager.records[0][3] == {"plugin": "по-своему", "roi": "верх"}

    def test_without_a_plugin_name_no_stamp_is_invented(self) -> None:
        """Базовый контекст процесса штампа не ставит — выдумывать источник нечем."""
        manager = MockStatsManager()
        ctx = PluginContext(services=MockProcessServices(stats_manager=manager), config={})

        ctx.record_metric("frames")

        assert manager.records[0][3] is None

    def test_no_plane_is_a_named_state_not_a_silent_one(self) -> None:
        """Плоскости нет — законно, но не безмолвно: счётчик растёт, голос звучит ОДИН раз.

        Возврата у метрики нет, поэтому счётчик — единственное, чем «писали
        некуда» отличается от «записали».
        """
        services = MockProcessServices()  # stats_manager=None — как процесс без менеджера
        ctx = PluginContext(services=services, config={}, plugin_name="checker")

        ctx.record_metric("frames")
        ctx.gauge("temperature", 1.0)
        ctx.record_timing("cycle", 0.016)

        report = stats_plane_report(services)["stats"]
        assert report["declared"] is False
        assert report["without_plane"] == 3, "считаться обязана каждая метрика, а не первая"

        warnings = [entry for entry in services.logs if entry["level"] == "WARNING" and "[stats]" in entry["msg"]]
        assert len(warnings) == 1, f"голос обязан прозвучать ровно один раз: {warnings}"
        assert "frames" in warnings[0]["msg"], "голос без имени метрики не показывает, кого чинить"
        assert "checker" in warnings[0]["msg"], "голос без источника не показывает, где чинить"

    def test_a_manager_failure_does_not_take_the_line_down(self) -> None:
        """Сбой учёта стоит метрики, а не линии — и назван ПРИЧИНОЙ.

        Ищется текст самого сбоя, а не слово «stats»: сообщение про
        ненастроенную плоскость тоже содержит ``[stats]``, и проверка по нему
        зеленела бы на чужой ветке — ровно так однажды и вышло у документов.
        """
        services = MockProcessServices(stats_manager=MockStatsManager(raises=RuntimeError("окно схлопнулось")))
        ctx = PluginContext(services=services, config={}, plugin_name="checker")

        ctx.record_metric("frames")  # не поднимает

        said = [entry for entry in services.logs if "окно схлопнулось" in entry["msg"]]
        assert said, f"причина сбоя не названа ни одной записью: {services.logs}"
        assert said[0]["level"] == "ERROR", f"сбой учёта сказан уровнем {said[0]['level']}"

    def test_a_failure_is_not_counted_as_a_missing_plane(self) -> None:
        """Два диагноза не сливаются: «менеджера нет» лечится конфигом, «упал» — кодом."""
        services = MockProcessServices(stats_manager=MockStatsManager(raises=RuntimeError("окно схлопнулось")))
        ctx = PluginContext(services=services, config={})

        ctx.record_metric("frames")

        report = stats_plane_report(services)["stats"]
        assert report["declared"] is True, "менеджер объявлен — сбой не должен читаться как его отсутствие"
        assert report["without_plane"] == 0


# ==============================================================================
# Настоящая связка: процесс + StatsManager, не дубль
# ==============================================================================


class TestTheRealWiring:
    @pytest.fixture
    def process(self):
        """Настоящий ``ProcessModule`` с настоящими менеджерами.

        Дубль доказывает договорённости дубля. Гасится обязательно: менеджеры
        поднимают потоки, а поток, держащий владельца, делает стенд бессмертным —
        этот класс утечки уже стоил проекту аварийного завершения гейта.
        """
        from multiprocess_framework.modules.process_module.core.process_module import ProcessModule

        module = ProcessModule(name="stats_road_probe", config={})
        module.initialize()
        try:
            yield module
        finally:
            module.shutdown()

    def test_a_metric_from_the_facade_reaches_the_real_aggregate(self, process) -> None:
        """Метрика плагина видна в агрегате настоящего ``StatsManager`` — со штампом."""
        ctx = PluginContext(services=process, config={}, plugin_name="color_mask")

        ctx.record_metric("frames_processed", 3)

        aggregate = process.stats_manager.get_metric("frames_processed")
        assert aggregate is not None, "метрика не доехала до настоящего менеджера"
        assert aggregate["type"] == "counter"
        assert aggregate["count"] == 3
        assert aggregate["tags"] == {"plugin": "color_mask"}

    def test_the_timing_unit_is_seconds_on_the_real_manager(self, process) -> None:
        """Период кадра 60 fps приезжает как 0.0167 с, а не как 16 мс.

        Число выбрано так, что секунды и миллисекунды расходятся в тысячу раз:
        совпади единицы — агрегат всё равно собрался бы, и ошибка вскрылась бы
        только границами бакетов задачи 2.2, где p95 стал бы константой.
        """
        ctx = PluginContext(services=process, config={}, plugin_name="capture")

        ctx.record_timing("frame_period", 1.0 / 60.0)

        aggregate = process.stats_manager.get_metric("frame_period")
        assert aggregate["type"] == "timing"
        assert aggregate["max"] == pytest.approx(0.016666, abs=1e-5)
        assert aggregate["max"] < 1.0, "значение похоже на миллисекунды — единица разошлась с менеджером"

    def test_the_real_process_satisfies_the_protocol_with_the_port_declared(self, process) -> None:
        """Настоящий процесс годен по ``IProcessServices`` вместе с новым портом."""
        assert hasattr(process, STATS_PORT)
        assert isinstance(process, IProcessServices)

    def test_a_process_without_managers_still_satisfies_the_protocol(self) -> None:
        """И процесс ДО initialize() — тоже: порт есть, значение ``None``.

        Довод тот же, что у стока документов: объявление в протоколе не имеет
        права сделать штатную конфигурацию не удовлетворяющей контракту, иначе
        dev-проверка ``isinstance`` падала бы там, где всё правильно.
        """
        from multiprocess_framework.modules.process_module.core.process_module import ProcessModule

        bare = ProcessModule(name="stats_port_probe")
        assert getattr(bare, STATS_PORT) is None
        assert isinstance(bare, IProcessServices)


# ==============================================================================
# Суб-контекст: четвёрка целиком, а не одна дорога из четырёх
# ==============================================================================


class TestTheSubContextCarriesTheStatsRoad:
    @pytest.mark.parametrize("road", sorted(_four_roads()))
    def test_every_road_exists_and_is_callable(self, road: str) -> None:
        """Каждая из четырёх есть у суб-контекста и вызывается без родителя.

        Урок Н-6 дословно: дефект, починенный на одной развилке из двух,
        воскресает на соседней. Вложенный плагин, звавший ``ctx.histogram``,
        получил бы ``AttributeError`` ровно так же, как когда-то ``log_warning``.
        """
        sub = SubPluginContext()
        fn = getattr(sub, road, None)
        assert callable(fn), f"суб-контекст не несёт {road} — вложенный плагин упадёт AttributeError"
        assert fn("проверка вызова", 1) is None

    @pytest.mark.parametrize("road", sorted(_four_roads()))
    def test_the_parentless_default_keeps_the_signature(self, road: str) -> None:
        """Заглушка без родителя несёт ТУ ЖЕ сигнатуру, что протокол и менеджер.

        Найдено независимым тестером, и найдено только им. Первая редакция
        ставила ОДНУ заглушку на все четыре дороги
        (``_noop_stat(name, value=1, tags=None)``) с доводом «сигнатуры
        совпадают по форме»; довод был неверен — у менеджера параметр таймингов
        зовётся ``duration``, а у gauge/histogram значение обязательно. Тест
        автора рядом звал заглушку ПОЗИЦИОННО и оставался зелёным, то есть
        подтверждал согласие автора с собственной моделью:

            SubPluginContext().record_timing("frame", duration=0.016)
            TypeError: _noop_stat() got an unexpected keyword argument 'duration'

        Заглушка, поставленная РАДИ безопасного вызова без родителя, роняла
        линию на именованном вызове по эталонной сигнатуре.
        """
        assert _shape(getattr(SubPluginContext(), road)) == _shape(getattr(IPluginStatsManager, road))

    @pytest.mark.parametrize("road", sorted(_four_roads()))
    def test_the_parentless_default_accepts_the_reference_keyword_call(self, road: str) -> None:
        """Пара к предыдущему: вызов ИМЕНОВАННЫМИ аргументами не падает.

        Сигнатура и вызов — разные половины: совпадение форм проверено выше
        оракулом, а здесь тем, чем пользуется вызывающий. Позиционный вызов
        соседнего теста этот класс пропустил.
        """
        second = "duration" if road == "record_timing" else "value"
        getattr(SubPluginContext(), road)(name="кадр", **{second: 0.016})

    @pytest.mark.parametrize("road", sorted(_four_roads()))
    def test_from_parent_forwards_every_stats_road(self, road: str) -> None:
        """``from_parent`` пробрасывает ВСЮ четвёрку — не часть.

        Поле у суб-контекста и проброс родителем — разные половины: с полями, но
        без проброса, метрика вложенного плагина уходила бы в no-op. Это тише
        падения и потому хуже: падение ищут, бесшумную потерю — нет.
        """
        manager = MockStatsManager()
        parent = PluginContext(services=MockProcessServices(stats_manager=manager), config={}, plugin_name="parent")
        sub = SubPluginContext.from_parent(parent, config={"nested": True})

        getattr(sub, road)("из вложенного", 1)

        assert [name for _kind, name, _value, _tags in manager.records] == ["из вложенного"], (
            f"{road} не доехал до менеджера родителя"
        )
        assert manager.records[0][3] == {"plugin": "parent"}, "запись потеряла источник родителя"


# ==============================================================================
# Цена горячего пути — числом, а не словом «незначительно»
# ==============================================================================


def _report(capsys: "pytest.CaptureFixture", line: str) -> None:
    """Печать замера мимо capture, безопасная для консоли в cp1251.

    Форма взята у ``logger_module/tests/test_gate_cost_bench.py`` дословно и по
    той же причине: русский текст в дефолтной консоли Windows роняет тест
    ``UnicodeEncodeError``, и «зелёный прогон» оказывается верным только под
    utf-8. Кодировка снимается ВНУТРИ ``disabled()`` — снаружи у capture-объекта
    она всегда ``UTF-8``, и защита была бы тождеством.
    """
    with capsys.disabled():
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(encoding, errors="replace").decode(encoding, errors="replace"))


class TestTheCostOfTheHotPath:
    """Что фасад добавляет к вызову менеджера — дельтой, на ОДИНАКОВОЙ работе."""

    def test_the_facade_adds_little_over_a_direct_call(self, capsys: pytest.CaptureFixture) -> None:
        """Цена фасада — разница с прямым вызовом, делающим РОВНО ТО ЖЕ.

        Сравнивать ``ctx.record_metric("m")`` с ``manager.record_metric("m")``
        было бы нечестно: у первого есть тег источника, у второго нет, и разница
        приписала бы фасаду стоимость работы менеджера с тегами. Поэтому у
        прямого вызова тот же тег.

        Ориентир для чтения числа: отфильтрованная эмиссия лога (та, что не
        доедет до файла) стоит 0.26–0.35 мкс — гейт ``logger_module/tests/
        test_gate_cost_bench.py``. Метрика, в отличие от неё, доезжает ВСЕГДА:
        сравнение с этой базой отвечает не «дорого ли», а «во сколько раз
        дороже самого дешёвого, что есть на горячем пути».
        """
        # Стенд БОЕВОЙ, а не двойник (находка ревью Ф5, S3). Прежняя редакция
        # строила ``MockProcessServices(stats_manager=manager)``, то есть меряла
        # дорогу ``ctx → _MockObservationPort → StatsManager`` — в замер не
        # входили ни ``_route_number``, ни ``_deliver_number``/``_emit_to_taps``,
        # ни ``_PortTap``, ни ``_on_port_record``, то есть вся цепочка Ф5,
        # ради которой бюджет и переписывался. Ревьюер перемерил тем же
        # харнессом: двойник 3.311 мкс против 4.172 мкс на настоящем порте.
        # Тот же класс, что фаза сама нашла в дыре P9 — фейковый харнесс
        # доказывает харнесс, — и здесь он остался незамеченным.
        from ...statistics_module.observation.observation_manager import ObservationManager

        manager = StatsManager(manager_name="cost_probe")
        port = ObservationManager(manager_name="cost_probe_port")
        assert port.initialize(), "стенд сломан ДО замера: порт не поднялся"
        assert manager.attach_observation_port(port), "стенд сломан ДО замера: порт не подключился"

        class _ServicesWithRealPort(MockProcessServices):
            """Слот ``observation`` отдаёт НАСТОЯЩИЙ порт, а не форвардящий двойник.

            Подменять надо именно ``get_manager``: резолвер
            (``observation_manager.observation_port``) ходит первой ступенью
            туда, и держать ссылку на порт в атрибуте бесполезно — первая
            редакция этой правки так и сделала, замер не изменился ни на
            микросекунду, и правка была мнимой.
            """

            def get_manager(self, slot):
                if slot == "observation":
                    return port
                return super().get_manager(slot)

        ctx = PluginContext(
            services=_ServicesWithRealPort(stats_manager=manager), config={}, plugin_name="bench_plugin"
        )
        same_tag = {"plugin": "bench_plugin"}

        through_facade, direct = timed_pair(
            lambda: ctx.record_metric("hot"),
            lambda: manager.record_metric("hot", 1, same_tag),
            repeats=20_000,
        )
        overhead = through_facade - direct
        ratio = through_facade / direct

        _report(capsys, "\nЦена stats-фасада (задача 1.1):")
        _report(capsys, f"  через ctx.record_metric:   {through_facade * 1e6:.3f} мкс")
        _report(capsys, f"  напрямую с тем же тегом:   {direct * 1e6:.3f} мкс")
        _report(capsys, f"  цена фасада (дельта):      {overhead * 1e6:.3f} мкс  (справочно — НЕ гейтуется)")
        _report(capsys, f"  отношение facade/direct:   {ratio:.3f}x  (гейтуется)")
        _report(capsys, "  для сравнения, база гейта: 0.26-0.35 мкс (отклонённая запись лога)")

        # Бюджет ПЕРЕПИСАН 2026-08-26 (Ф5, решение владельца) — 2.0 → 5.0 мкс.
        #
        # Что было: фасад звал ``self.services.stats_manager`` напрямую, дельта
        # ~0.38 мкс на штатной машине (A/B на пред-имплементационном коммите
        # `b9bd8345` дал 0.16-0.18 мкс, 3/3 зелёных), потолок 2.0 мкс.
        #
        # Что стало: Ф5 сделала порт единственным писателем чисел, и фасад
        # теперь идёт ctx → порт → CRM-tap → StatsManager. Замер БОЕВЫМ стендом
        # (порт подключён у обеих сторон), три прогона: 2.674 / 2.839 / 2.850 мкс.
        #
        # **Что этот тест меряет НА САМОМ ДЕЛЕ — и чего не меряет.** Правка по
        # ревью Ф5 (S3) подключила порт и к ``manager``, то есть порт входит в
        # ОБЕ стороны разности и сокращается. Значит здесь измеряется цена
        # ФАСАДА (резолв слота + лишний хоп), а НЕ цена прохода через порт.
        # Собственная цена порта — около 0.93 мкс на вызов, она снята отдельным
        # замером и этим сторожем НЕ охраняется. Прежняя редакция комментария
        # объясняла бюджет «структурной ценой прохода через порт» — это было
        # неверно дважды: и потому, что мерился двойник, и потому, что разность
        # цену порта сокращает.
        #
        # Почему цена ПРИНЯТА, а не срезана: срезать её значит уплощать слой
        # записи, то есть отдавать назад ровно ту единственность писателя,
        # ради которой Ф5 делалась. Слот-вызывающие фреймворка (57 сайтов)
        # сидят на редких событиях, а не на операциях (``state_proxy`` —
        # resync/re-adopt, не каждая запись состояния).
        #
        # ПРАВКА 2026-09-02 (Р-12, добор Task 2.10): снята формулировка «три
        # вызова на кадр у плагина захвата, при 60 fps это 0.17 мс в секунду» —
        # проверено чтением и оказалось неверно. Единственный БОЕВОЙ вызывающий
        # (``Plugins/sources/capture/plugin.py:246``, метод ``_emit_stats``) не
        # сидит на кадре: он зовётся из ``_tick_stats``, а та встаёт рано и
        # выходит по ``elapsed < 1.0: return`` — эмиссия ОКОННАЯ, раз в
        # секунду, а не на кадр. Горячего пути через фасад НА КАДР в проекте
        # нет; заменить старое число новым непроверенным замером («вес в
        # секунду» при оконной эмиссии) здесь не стали — это отдельное
        # измерение, а не предмет этого теста.
        #
        # Почему потолок обязан по-прежнему ловить ПОЯВЛЕНИЕ новой работы на
        # этом пути — копию словаря на вызов, лишний лок, разбор имени. Такое
        # стоит единиц мкс на фоне 2.67-2.85 мкс, измеренных Ф5.
        #
        # ФОРМА ГЕЙТА ПЕРЕПИСАНА 2026-09-01 (замыкатель класса Н-7, добор ревью
        # Ф2) — абсолютная дельта заменена на ОТНОШЕНИЕ facade/direct. Порог НЕ
        # подгонялся: менялась ФОРМА критерия, потому что разность двух шумных
        # величин шумит СИЛЬНЕЕ каждой из них по отдельности — та же болезнь,
        # что у бенчмарков вообще.
        #
        # Наблюдение, из-за которого форма сменилась. Три соло-замера ревью
        # (координатор, Ф2): дельта 5.13 / 13.38 / 13.04 мкс — разброс 2.5x, и
        # ДВА из трёх уже превысили бы старый потолок 5.0 без единой реальной
        # регрессии. Отношение facade/direct на тех же трёх прогонах: 2.36 /
        # 2.28 / 2.37 — разброс ~4%, не 2.5x. Мои независимые 4 соло-замера НА
        # ЭТОЙ машине (2026-09-01, тем же тестом) отношение дословно НЕ
        # воспроизвели: 1.78 / 1.78 / 1.70 / 1.78 — ниже, чем у координатора, но
        # с той же тесной кучностью (разброс ~5%, не ~2х у абсолюта). Расхождение
        # между двумя наборами (1.70-1.79 против 2.28-2.37) не разбиралось —
        # вероятно, разная загрузка машины/окружения между сессиями; называю
        # честно, а не тихо ужимаю под один порог без явного запаса.
        #
        # ПОТОЛОК ПЕРЕСМОТРЕН 2026-09-02 (Р-12, решение владельца): 4.2 → 3.0.
        # Число 4.2 держалось на замере координатора (2.28-2.37) — а тот, по
        # разбору владельца (``plans/observability-closure/plan.md`` §4, Р-12),
        # СНЯТ НЕ НА ЭТОМ СТЕНДЕ: нагрузочная гипотеза не подтвердилась (три
        # параллельных экземпляра дают 1.75-1.79, под ``--cov`` отношение падает
        # до 1.35-1.40), а форма теста ДО правки S3 (двойник вместо боевого
        # порта) воспроизводимо давала 2.15-2.23 сама по себе. Устарела ПОСЫЛКА
        # потолка, не только число. Главное следствие решения — тайминг-гейт
        # ЛЮБОЙ ширины слеп к классу регрессии, ради которого он заявлен (+0.2
        # мкс на базе 6.3 сдвигает отношение с 1.80 до 1.86 — недостаточно,
        # чтобы отличить регрессию от дрожи машины), поэтому 3.0 остаётся
        # ШИРОКИМ сторожем катастроф, а мелочь (копия словаря, лишний лок,
        # разбор имени) стережёт СЧЁТНЫЙ сторож ниже — числом python-вызовов,
        # которое от машины и нагрузки не зависит вовсе.
        assert ratio < 3.0, (
            f"фасад подорожал ОТНОСИТЕЛЬНО прямого вызова: {ratio:.3f}x "
            f"(через фасад {through_facade * 1e6:.3f} мкс, напрямую {direct * 1e6:.3f} мкс, "
            f"дельта {overhead * 1e6:.3f} мкс)"
        )

    def test_the_facade_call_count_pins_two_invariants(self) -> None:
        """Счётный сторож (Р-12, добор Task 2.10) — другим объективом, чем тайминг.

        Тайминг-гейт выше слеп к мелкой регрессии на шумной машине (см.
        комментарий у него: +0.2 мкс на базе 6.3 сдвигает отношение всего с
        1.80 до 1.86). Число вызовов от машины и нагрузки не зависит — считаются
        СОБЫТИЯ ВЫЗОВА (:func:`count_calls`), а не часы, — и стережёт ту же
        мелочь ДВУМЯ литералами, каждый про СВОЙ инвариант:

        * ``direct == (26, 29)`` — на дороге ЕДИНСТВЕННОГО ПИСАТЕЛЯ
          (``StatsManager.record_metric`` → ``ObservationPort._route_number`` →
          гейт → ``ObservationManager._deliver_number`` → ``_emit_to_taps`` →
          тот же менеджер обратно через tap) не появилось новой работы;
        * ``facade - direct == (4, 6)`` — работа фасада
          (``PluginContext.record_metric``) сверх прямого вызова. Состав:
          **+5** кадров (``record_metric`` фасада, ``_stats_call``,
          ``_observation_port``, резолвер ``observation_port``, ``get_manager``)
          и **−1** (``StatsManager.record_metric`` — фасад входит в дорогу
          ступенью ниже, в ``ObservationPort.record_metric``), итого 4.

        **Почему литералы ПАРАМИ, а не одним py-числом.** Замер классов событий:
        ``d.copy()`` → c+1, py+0; ``with lock:`` → c+1, py+0; ``acquire()`` /
        ``release()`` → c+2; ``copy.copy(d)`` → py+1, c+2. То есть счётчик
        только по python-вызовам СЛЕП к двум из трёх регрессий, ради которых
        сторож заведён (копия словаря и лишний лок в их естественной форме) —
        их видит только C-половина пары. Честное слепое пятно, которое не
        закрывает ни одна половина: ``dict(d)`` и ``{**d}`` дают 0/0 — их не
        поймает ни счётный сторож, ни тайминг-гейт.

        **Почему число стабильно только с версии этого коммита.** До поднятия
        импорта (см. ``PluginContext._observation_port``) на дороге фасада
        стояло выражение ``import`` НА КАЖДЫЙ ВЫЗОВ, а под импорт-хуком
        ``shibokensupport`` оно стоит четыре профилируемых Python-вызова даже
        когда модуль уже в ``sys.modules``. Литерал из-за этого гулял: 9 под
        узким прогоном pytest и 5 под полным — состояние ``builtins.__import__``
        меняет соседний тест (``test_observability_ttl.py::TestMechanismHazards::
        test_concurrent_writes_and_sweeps_lose_nothing``: гонка импортов из
        нескольких потоков переводит ``__feature_import__`` в
        ``__lazy_import__``). После поднятия импорта разница равна **(4, 6)** во
        всех четырёх состояниях хука — голом, ``__feature_import__``,
        ``__lazy_import__`` и под ``coverage`` — то есть стала свойством КОДА,
        а не прогона.

        **Числа сняты на CPython 3.12** (версия пришпилена в ``pyproject``).
        C-счёт чувствительнее к версии интерпретатора, чем python-счёт;
        при смене версии литералы обязаны быть пересняты, а не подогнаны.

        Прогрев ОТДЕЛЬНЫМИ именами метрик перед счётом обязателен: первый вызов
        новой метрики ЗАВОДИТ агрегат (другое число вызовов), а сторож обязан
        считать УСТОЯВШУЮСЯ дорогу, а не создание записи.
        """
        from ...statistics_module.observation.observation_manager import ObservationManager

        manager = StatsManager(manager_name="cost_probe_count")
        port = ObservationManager(manager_name="cost_probe_count_port")
        assert port.initialize(), "стенд сломан ДО счёта: порт не поднялся"
        assert manager.attach_observation_port(port), "стенд сломан ДО счёта: порт не подключился"

        class _ServicesWithRealPort(MockProcessServices):
            def get_manager(self, slot):
                if slot == "observation":
                    return port
                return super().get_manager(slot)

        ctx = PluginContext(
            services=_ServicesWithRealPort(stats_manager=manager), config={}, plugin_name="bench_plugin"
        )
        same_tag = {"plugin": "bench_plugin"}
        direct_call = lambda: manager.record_metric("warm_direct", 1, same_tag)  # noqa: E731
        facade_call = lambda: ctx.record_metric("warm_facade")  # noqa: E731

        # Прогрев — см. докстринг: первый вызов заводит агрегат, это не то,
        # что стережёт этот тест.
        direct_call()
        facade_call()

        direct = count_calls(direct_call)
        facade = count_calls(facade_call)
        overhead = (facade[0] - direct[0], facade[1] - direct[1])

        assert direct == (26, 29), (
            f"дорога единственного писателя завела новую работу: {direct} вместо (26, 29) (python-вызовов, C-вызовов)"
        )
        assert overhead == (4, 6), (
            f"работа фасада сверх прямого вызова изменилась: {overhead} вместо (4, 6) "
            f"(прямая дорога — {direct}, фасад — {facade})"
        )

        manager.shutdown()
        port.shutdown()
