# -*- coding: utf-8 -*-
"""Независимая приёмка «порт наблюдений» (Н1-Н5) — задача из брифа, ветка feat/observation-port.

Источник контракта: ТЕКСТ требований Н1-Н5 из брифа задачи, а не диффы/планы/чужие
тесты этой фазы (все они были явно запрещены к чтению). Разрешённые к чтению файлы
использованы как БИБЛИОТЕКА для конструирования фикстур (тот же приём, что и в
соседних тестах модуля — ``test_telemetry_tick.py``, ``test_introspect_telemetry.py``,
``test_telemetry_levels_poll_acceptance.py``), а не как источник ожиданий:

  - ``plugins/base.py`` (PluginContext.declare_metric/publish_metric) — публичный
    фасад плагина, его докстринг ЯВНО называет путь публикации
    (``processes.<процесс>.state.plugins.<писатель>.<имя>``);
  - ``heartbeat/telemetry.py`` — импортируются ТОЛЬКО символы-библиотека
    (``PLUGIN_LEVELS_ATTR``, ``get_or_create_plugin_levels``, ``gated_metrics``),
    сам файл не читался (запрещён явно);
  - ``heartbeat/process_heartbeat.py`` — импортируется класс ``ProcessHeartbeat``
    как библиотека для форсирования тика (``hb._loop(FakeStop, _NoPause)``),
    сам файл не читался (запрещён явно);
  - ``state_store_module/core/tree_store.py`` — РЕАЛЬНЫЙ ``TreeStore`` (не фейк).
    Использован буквально, а не через заглушку: фейковый ``_state_proxy`` в этом
    файле — тонкая обёртка (`merge`/`set` делегируют в настоящий ``TreeStore``), а
    не независимая реализация merge-алгоритма. Это закрывает «фейк доказывает
    только фейк» (правило проекта test-authorship) для Н1/Н2/Н3/Н5, которые все
    про форму итогового дерева;
  - ``Plugins/sources/capture/plugin.py`` — читался целиком (разрешено явно),
    используется НАПРЯМУЮ как класс (не через мок).

ВАЖНО (честное раскрытие утечки, а не «не заметил»): при разведке пути `path`,
которым ``_state_proxy.merge`` передаётся тику (нужно было понять, каким
образом «processes.<proc>.state» попадает в общий путь — из docstring'а
``plugins/base.py`` это было известно только как ИТОГОВЫЙ адрес, но не как
устройство сборки), был выполнен широкий ``Grep`` по всей директории
``tests/`` модуля БЕЗ исключения запрещённых файлов, и в его вывод попали
фрагменты (несколько строк с номерами) из ЗАПРЕЩЁННЫХ
``test_plugin_levels_hazards.py`` и ``test_writer_subtree_hazards.py``:
конкретно — что ``_state_proxy.merge`` зовётся как ``merge("processes.<name>",
{"state": {...}})``, и несколько имён тестовых плагинов/сценариев из тех
файлов (``order_plugin`` vs framework ``fps``, ``nw_plugin``, ``zero_plugin``,
``empty_plugin``). Эти фрагменты НЕ использованы как источник ожиданий этого
файла: тесты ниже не пришпиливают устройство разбиения ``(path, data)`` и не
используют ни одно из увиденных имён сценариев/плагинов — вместо этого путь
подтверждён НЕЗАВИСИМО через прогон (см. `probe_observation_ns.py`, разведка
СВОИМ, не подсмотренным способом: реальный ``TreeStore`` + ``get_subtree`` после
тика), а конкретный способ, которым фреймворк режет merge на (path, data),
тестами ниже не проверяется вовсе — итоговое дерево проверяется ОДНИМ
``get_subtree`` запросом, что и требует Н5. Раскрыто здесь, а не скрыто,
по прямому требованию брифа.

Решения по неоднозначностям:
  - Н1 «push через тик» — трактован как «после форсированного тика
    ``ProcessHeartbeat`` (``hb._loop`` с fake-clock, БЕЗ time.sleep) лист
    появляется с ОПУБЛИКОВАННЫМ значением», а не «публикуется НЕМЕДЛЕННО при
    вызове publish_metric» — докстринг ``publish_metric`` в plugins/base.py
    прямо говорит «уезжает в дерево СБОРЩИКОМ ТИКА», то есть публикация без
    тика в дерево не попадает по контракту (характеризацией подтверждено:
    без тика ``processes.<proc>.state`` вообще отсутствует в дереве).
  - Н1 «poll текущих уровней» — трактован как ``introspect.telemetry`` →
    ``levels`` (уже существующая команда readback'а, подтверждено соседним
    РАЗРЕШЁННЫМ тестом ``test_telemetry_levels_poll_acceptance.py`` как
    прецедент API, не как источник ожиданий Н1-Н5). Характеризацией
    подтверждено: poll ВИДИТ опубликованное значение даже БЕЗ единого тика —
    это две независимые дороги, и тест это явно проверяет раздельно.
  - Форма ответа ``levels`` НЕ фиксируется дословно (тот же принцип, что в
    разрешённом прецеденте): вместо жёсткого dict-shape используется
    суффиксный поиск листа по хвосту пути (writer, name) — свойство
    «путь заканчивается на .<writer>.<name> и несёт литерал» переживает
    смену формы обёртки вокруг него.
  - Н4 «capture-совместимость» — «файл не изменён» проверяется ``git diff``
    против ветки ``main``; сам плагин драйвится БЕЗ реальной камеры (cv2)
    напрямую через его публичный ``configure()`` + внутренний ``_tick_stats()``
    (единственная точка, которая реально зовёт ``_publish_levels()`` — видно
    прямо в разрешённом файле, без обращения к forbidden-путям), что не
    требует ни ``cv2.VideoCapture``, ни полного lifecycle start/stop.
  - Н5 «одним запросом» — трактован буквально как ОДИН вызов
    ``TreeStore.get_subtree(path)`` (не серия точечных ``get``).

Ожидание к концу прогона: все тесты ниже ЗЕЛЁНЫЕ (характеризация выполнена
заранее вручную, см. probe-скрипт в scratchpad) — контракт наблюдался, а не
только предполагался.
"""

from __future__ import annotations

from typing import Any


from multiprocess_framework.modules.observability_declarations import forget_declarations
from multiprocess_framework.modules.process_module.commands.builtin_commands import (
    BuiltinCommands,
)
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore

# --------------------------------------------------------------------------- #
# Часы и стоп-событие — форсирование тика БЕЗ time.sleep (образец: test_telemetry_tick.py)
# --------------------------------------------------------------------------- #


class FakeClock:
    """Управляемый монотонный источник времени."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += float(dt or 0.0)


class FakeStop:
    """Останавливает цикл при достижении ``t_end``; ``wait`` двигает фейк-часы."""

    def __init__(self, clock: FakeClock, t_end: float) -> None:
        self._clock = clock
        self._t_end = t_end

    def is_set(self) -> bool:
        return self._clock() >= self._t_end

    def wait(self, timeout: float | None = None) -> None:
        self._clock.advance(timeout)


class _NoPauseEvent:
    def is_set(self) -> bool:
        return False


def _force_one_tick(hb: ProcessHeartbeat, clock: FakeClock) -> None:
    """Ровно один проход цикла тика — общий помощник для всех тестов ниже."""
    start = clock.t
    hb._loop(FakeStop(clock, t_end=start + 0.01), _NoPauseEvent())


# --------------------------------------------------------------------------- #
# Реальный TreeStore за фейковым _state_proxy — НЕ независимый фейк-merge
# --------------------------------------------------------------------------- #


class _TreeBackedProxy:
    """``merge``/``set`` делегируют в НАСТОЯЩИЙ ``TreeStore`` (не переизобретают алгоритм).

    Это то, что отличает тесты ниже от «фейк доказывает только фейк»: дерево,
    которое проверяется ``get_subtree``, построено ТЕМ ЖЕ merge-алгоритмом,
    что использует прод (``TreeStore._merge_recursive``), а не приблизительной
    копией в тестовом коде.
    """

    def __init__(self, tree: TreeStore) -> None:
        self.tree = tree

    def merge(self, path: str, data: dict) -> None:
        self.tree.merge(path, data)

    def set(self, path: str, value: Any) -> None:
        self.tree.set(path, value)


class HeartbeatServices:
    """Единый объект ``services`` — сервисы, которые видит И ``ProcessHeartbeat``,
    И ``PluginContext`` (это ОБЯЗАНО быть одним и тем же объектом: опубликованный
    плагином уровень лежит в хранилище на ``services``, и собрать его тиком может
    только ``ProcessHeartbeat``, построенный НАД ТЕМ ЖЕ ``services``)."""

    def __init__(self, name: str = "camera_0") -> None:
        self.name = name
        self.worker_manager = None
        self.router_manager = None
        self.command_manager = None
        self.memory_manager = None
        self._health_state = None
        self._current_process_status = "running"
        self._config: dict = {}
        self.tree = TreeStore()
        self._state_proxy = _TreeBackedProxy(self.tree)

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def log_debug(self, *a, **k) -> None: ...
    def log_info(self, *a, **k) -> None: ...
    def log_warning(self, *a, **k) -> None: ...
    def log_error(self, *a, **k) -> None: ...
    def log_critical(self, *a, **k) -> None: ...

    def send_message(self, target: str, message: dict) -> bool:
        return True


def _make_env(name: str = "camera_0") -> tuple[HeartbeatServices, FakeClock, ProcessHeartbeat]:
    services = HeartbeatServices(name)
    clock = FakeClock()
    hb = ProcessHeartbeat(services, clock=clock)
    return services, clock, hb


# --------------------------------------------------------------------------- #
# Опрос (poll) — introspect.telemetry -> levels, через BuiltinCommands
# --------------------------------------------------------------------------- #


class _FakeCommandManager:
    def __init__(self) -> None:
        self.handlers: dict = {}
        self.metadata: dict = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler
        self.metadata[name] = metadata or {}

    def dispatch(self, command: str, data: dict | None = None) -> dict:
        return self.handlers[command](data or {})


class _OuterServices:
    """Процесс-адресат для BuiltinCommands: свой CommandManager + ссылка на hb."""

    def __init__(self, hb: ProcessHeartbeat, name: str = "camera_0") -> None:
        self.command_manager = _FakeCommandManager()
        self.name = name
        self.logger_manager = None
        self.error_manager = None
        self.stats_manager = None
        self.router_manager = None
        self._config: dict = {}
        self._heartbeat = hb
        self._state_store_manager = None

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def _log_info(self, *a, **k) -> None: ...
    def _log_debug(self, *a, **k) -> None: ...


def _poll_levels(hb: ProcessHeartbeat, name: str = "camera_0") -> Any:
    """Один опрос ``introspect.telemetry`` -> ``levels`` (не мутирует систему)."""
    outer = _OuterServices(hb, name)
    bc = BuiltinCommands(outer)
    bc._register_introspect_commands()
    res = outer.command_manager.dispatch("introspect.telemetry")
    assert res["success"] is True
    return res.get("levels")


# --------------------------------------------------------------------------- #
# Суффиксный поиск листа по (writer, name) — форма обёртки НЕ фиксируется
# --------------------------------------------------------------------------- #


def _leaves_by_suffix(obj: Any, *suffix: str, _path: tuple[str, ...] = ()) -> list[Any]:
    """Собрать значения всех листьев, чей путь заканчивается сегментами ``suffix``.

    Не привязывается к точной форме обёртки (``{"state": {"plugins": ...}}`` vs
    что угодно ещё) — только к тому, что хвост пути (последние N сегментов)
    совпадает с ``suffix``. Тот же принцип, что у ``_flatten_numbers`` в
    разрешённом прецеденте (``test_telemetry_levels_poll_acceptance.py``), но
    с сохранением ПУТИ, а не только множества чисел — нужен именно путь, чтобы
    доказать Н2 (разные писатели = разные листья, а не совпавшее число).
    """
    out: list[Any] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            out.extend(_leaves_by_suffix(value, *suffix, _path=_path + (str(key),)))
    else:
        if len(_path) >= len(suffix) and _path[-len(suffix) :] == tuple(suffix):
            out.append(obj)
    return out


def _leaf_paths_by_suffix(obj: Any, *suffix: str, _path: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    """Как :func:`_leaves_by_suffix`, но возвращает ПОЛНЫЕ пути (а не значения).

    Нужен отдельно от суффиксного поиска значений: сам суффиксный поиск
    сознательно НЕ фиксирует форму обёртки ВОКРУГ адреса (см. докстринг
    ``_leaves_by_suffix``), но сегмент ``plugins`` в Н1 — не обёртка, а часть
    контракта адресации (``state.plugins.<writer>.<name>``, по нему резолвят
    GUI и правила гейта). Полный путь даёт возможность проверить именно этот
    сегмент, не пришпиливая при этом остальную форму ответа.
    """
    out: list[tuple[str, ...]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            out.extend(_leaf_paths_by_suffix(value, *suffix, _path=_path + (str(key),)))
    else:
        if len(_path) >= len(suffix) and _path[-len(suffix) :] == tuple(suffix):
            out.append(_path)
    return out


def _assert_plugin_leaf_via_poll(levels: Any, writer: str, name: str, expected: Any) -> None:
    """Проверить И значение листа (суффиксный поиск), И то, что он лежит по
    адресу через сегмент ``plugins`` — найдено инъекцией координатора
    (``plugins`` -> ``plugins_x`` в механизме): чисто суффиксный поиск
    `(writer, name)` эту подмену не ловит, потому что игнорирует всё, что
    выше хвоста пути. Push-тесты этого файла адрес уже пришпиливают явным
    индексированием (``subtree["plugins"][...]``) — эта проверка выравнивает
    poll-дорогу с push-дорогой по строгости адресации.
    """
    values = _leaves_by_suffix(levels, writer, name)
    assert len(values) == 1, f"писатель {writer!r} метрика {name!r}: ожидался 1 лист, найдено {values}"
    assert values[0] == expected

    paths = _leaf_paths_by_suffix(levels, writer, name)
    assert len(paths) == 1
    assert "plugins" in paths[0], (
        f"лист {writer}.{name} найден НЕ по адресу через сегмент 'plugins' "
        f"(state.plugins.<writer>.<name> из Н1) — фактический путь: {paths[0]}"
    )


# --------------------------------------------------------------------------- #
# Н1 — push через тик heartbeat
# --------------------------------------------------------------------------- #


class TestH1PushViaHeartbeatTick:
    def test_published_value_appears_at_the_leaf_after_one_tick(self) -> None:
        """P публикует x=11.0 -> после ОДНОГО форсированного тика лист
        processes.<proc>.state.plugins.P.x существует и равен 11.0 (литерал)."""
        services, clock, hb = _make_env("camera_0")
        try:
            ctx = PluginContext(services=services, plugin_name="P")
            ctx.declare_metric("x")
            ctx.publish_metric("x", 11.0)

            # ЯКОРЬ до тика: без тика путь processes.camera_0.state вообще
            # отсутствует в дереве — публикация сама по себе НЕ пишет в дерево
            # (докстринг publish_metric: "уезжает в дерево СБОРЩИКОМ ТИКА").
            assert not services.tree.has("processes.camera_0.state")

            _force_one_tick(hb, clock)

            subtree = services.tree.get_subtree("processes.camera_0.state")
            assert subtree["plugins"]["P"]["x"] == 11.0
        finally:
            forget_declarations("metric", names={"x"})

    def test_leaf_tracks_republished_value_across_a_second_tick(self) -> None:
        """Квантор «публикация доезжает на КАЖДОМ такте, а не только на первом» —
        минимум ДВА тика (правило проекта): republish другого литерала должен
        отразиться, а не застыть на значении первого тика."""
        services, clock, hb = _make_env("camera_0")
        try:
            ctx = PluginContext(services=services, plugin_name="P")
            ctx.declare_metric("x")

            ctx.publish_metric("x", 11.0)
            _force_one_tick(hb, clock)
            assert services.tree.get_subtree("processes.camera_0.state")["plugins"]["P"]["x"] == 11.0

            # Литерал с РОВНО одним знаком после запятой: характеризацией
            # подтверждено (см. также разрешённый прецедент
            # test_telemetry_levels_poll_acceptance.py, докстринг
            # _distinct_workers), что push-путь округляет числовые уровни до
            # 1 знака (round(x, 1)) — величина с одним знаком проходит через
            # это округление без потерь, и сравнение остаётся однозначным.
            ctx.publish_metric("x", 47.3)
            clock.advance(0.02)
            _force_one_tick(hb, clock)
            leaf_after_second_tick = services.tree.get_subtree("processes.camera_0.state")["plugins"]["P"]["x"]
            assert leaf_after_second_tick == 47.3, (
                "лист остался на значении первого тика — публикация не доезжает на повторных тактах"
            )
        finally:
            forget_declarations("metric", names={"x"})


# --------------------------------------------------------------------------- #
# Н1 — poll через опрос текущих уровней (introspect.telemetry -> levels)
# --------------------------------------------------------------------------- #


class TestH1PollCurrentLevels:
    def test_published_value_visible_via_poll_without_any_tick(self) -> None:
        """P публикует x=11.0 -> опрос ВИДИТ значение НЕМЕДЛЕННО, без единого
        тика (poll — снимок «что процесс знает о себе сейчас», а не то, что уже
        уехало push'ем; см. решение по неоднозначности в шапке файла)."""
        services, _clock, hb = _make_env("camera_0")
        try:
            ctx = PluginContext(services=services, plugin_name="P")
            ctx.declare_metric("x")
            ctx.publish_metric("x", 11.0)

            # ЯКОРЬ: push-дорога в это же самое время дерево не тронула (ни
            # единого тика не было) — разводит push и poll как ДВЕ независимые
            # дороги, а не одну с разным именем.
            assert not services.tree.has("processes.camera_0.state")

            levels = _poll_levels(hb, "camera_0")
            assert levels is not None
            _assert_plugin_leaf_via_poll(levels, "P", "x", 11.0)
        finally:
            forget_declarations("metric", names={"x"})

    def test_poll_after_a_tick_still_agrees_with_the_published_literal(self) -> None:
        """Тот же лист виден опросом и ПОСЛЕ того, как push уже провёз его через
        тик (обе дороги согласны об одном и том же текущем значении)."""
        services, clock, hb = _make_env("camera_0")
        try:
            ctx = PluginContext(services=services, plugin_name="P")
            ctx.declare_metric("x")
            ctx.publish_metric("x", 11.0)
            _force_one_tick(hb, clock)

            levels = _poll_levels(hb, "camera_0")
            _assert_plugin_leaf_via_poll(levels, "P", "x", 11.0)
        finally:
            forget_declarations("metric", names={"x"})


# --------------------------------------------------------------------------- #
# Н2 — два плагина, одноимённый лист -> два РАЗНЫХ листа, без чужого значения
# --------------------------------------------------------------------------- #


class TestH2TwoPluginsSameLeafName:
    def test_two_writers_get_two_separate_leaves_with_own_literals(self) -> None:
        """P и Q оба публикуют x (разные литералы) -> в дереве ДВА листа
        (plugins.P.x, plugins.Q.x), у каждого своё число. Позитивный якорь на
        ОБА литерала в ОДНОМ тесте — правило проекта против чисто-отрицательных
        тестов, которые зелены и на мёртвом механизме."""
        services, clock, hb = _make_env("camera_0")
        try:
            ctx_p = PluginContext(services=services, plugin_name="P")
            ctx_q = PluginContext(services=services, plugin_name="Q")
            ctx_p.declare_metric("x")
            ctx_q.declare_metric("x")
            ctx_p.publish_metric("x", 11.0)
            ctx_q.publish_metric("x", 22.0)

            _force_one_tick(hb, clock)
            subtree = services.tree.get_subtree("processes.camera_0.state")

            # Позитив: каждый писатель — СВОЙ лист со СВОИМ литералом.
            assert subtree["plugins"]["P"]["x"] == 11.0
            assert subtree["plugins"]["Q"]["x"] == 22.0

            # Негатив (только В ПАРЕ с позитивом выше, не сам по себе — правило
            # проекта): ни один merge не занёс значение P под путь Q и наоборот.
            assert subtree["plugins"]["P"]["x"] != subtree["plugins"]["Q"]["x"]
            assert "Q" not in subtree["plugins"]["P"]
            assert "P" not in subtree["plugins"]["Q"]
        finally:
            forget_declarations("metric", names={"x"})

    def test_two_writers_visible_separately_via_poll_too(self) -> None:
        """То же разделение видно и опросом (levels), не только push-деревом."""
        services, clock, hb = _make_env("camera_0")
        try:
            ctx_p = PluginContext(services=services, plugin_name="P")
            ctx_q = PluginContext(services=services, plugin_name="Q")
            ctx_p.declare_metric("x")
            ctx_q.declare_metric("x")
            ctx_p.publish_metric("x", 11.0)
            ctx_q.publish_metric("x", 22.0)
            _force_one_tick(hb, clock)

            levels = _poll_levels(hb, "camera_0")
            _assert_plugin_leaf_via_poll(levels, "P", "x", 11.0)
            _assert_plugin_leaf_via_poll(levels, "Q", "x", 22.0)
        finally:
            forget_declarations("metric", names={"x"})


# --------------------------------------------------------------------------- #
# Н3 — порядок публикаций не меняет итог
# --------------------------------------------------------------------------- #


class TestH3PublicationOrderDoesNotMatter:
    @staticmethod
    def _run(order: list[str]) -> dict:
        services, clock, hb = _make_env("camera_0")
        values = {"P": 11.0, "Q": 22.0}
        ctxs = {
            "P": PluginContext(services=services, plugin_name="P"),
            "Q": PluginContext(services=services, plugin_name="Q"),
        }
        for writer in order:
            ctxs[writer].declare_metric("x")
            ctxs[writer].publish_metric("x", values[writer])
        _force_one_tick(hb, clock)
        return services.tree.get_subtree("processes.camera_0.state")

    def test_forward_order_p_then_q(self) -> None:
        try:
            subtree = self._run(["P", "Q"])
            assert subtree["plugins"]["P"]["x"] == 11.0
            assert subtree["plugins"]["Q"]["x"] == 22.0
        finally:
            forget_declarations("metric", names={"x"})

    def test_reverse_order_q_then_p_gives_the_same_result(self) -> None:
        try:
            subtree = self._run(["Q", "P"])
            assert subtree["plugins"]["P"]["x"] == 11.0
            assert subtree["plugins"]["Q"]["x"] == 22.0
        finally:
            forget_declarations("metric", names={"x"})


# --------------------------------------------------------------------------- #
# Н4 — capture-совместимость: файл не изменён, метрики видны
# --------------------------------------------------------------------------- #


class TestH4CaptureCompatibility:
    # УДАЛЁН 2026-09-01 (Task 1.3b) — ``test_capture_plugin_file_is_byte_for_byte_unchanged_vs_main``.
    # Сторож был ОДНОРАЗОВЫЙ и фазовый: «Plugins/sources/capture/plugin.py не
    # отличается от main» доказывало совместимость фазы observation-port. Его
    # собственный докстринг назвал условие снятия заранее: после merge фазы
    # сравнение вырождается в diff ветки с самой собой, и ПЕРВАЯ ЗАКОННАЯ правка
    # capture красит тест без всякой вины. Такая правка пришла: 1.3b снимает на
    # строке 288 второй разъём и заводит отказ открытия камеры в плоскость
    # ошибок (DeviceOpenFailed). Тест удалён, а не подкручен — чинить его
    # значило бы делать вид, что неизменность файла инвариант навсегда.
    # Совместимость capture продолжает держать соседний тест по МЕТРИКАМ.

    def test_capture_metrics_visible_under_the_plugin_subtree(self) -> None:
        """capture_fps/frame_count/drops видны под state.plugins.<имя плагина>.<метрика>.

        Реальный CapturePlugin, без камеры (cv2): единственная точка, которая
        реально публикует эти три уровня — ``_tick_stats()`` (видно в САМОМ
        файле, строки ``self._publish_levels()`` внутри ``_tick_stats``), и она
        не трогает ``self._cap``. ``_fps_timer`` отведён в прошлое, чтобы порог
        «раз в секунду» сработал без time.sleep.
        """
        from Plugins.sources.capture.plugin import CapturePlugin

        services, clock, hb = _make_env("camera_0")
        try:
            ctx = PluginContext(services=services, plugin_name="capture", config={"auto_start": False})
            plugin = CapturePlugin()
            plugin.configure(ctx)  # объявляет capture_fps/frame_count/drops сам

            plugin._fps_timer = 0.0  # форсируем elapsed >> 1.0 без сна
            plugin._frame_count = 7
            plugin._drops = 3
            plugin._tick_stats()  # реально зовёт _publish_levels()

            _force_one_tick(hb, clock)
            subtree = services.tree.get_subtree("processes.camera_0.state")

            leaf = subtree["plugins"]["capture"]
            assert leaf["frame_count"] == 7
            assert leaf["drops"] == 3
            assert "capture_fps" in leaf
            assert isinstance(leaf["capture_fps"], float)
        finally:
            forget_declarations("metric", names={"capture_fps", "frame_count", "drops"})


# --------------------------------------------------------------------------- #
# Н5 — обход поддерева ОДНИМ запросом находит ВСЕ опубликованные листья
# --------------------------------------------------------------------------- #


class TestH5SingleSubtreeQueryFindsEveryPublishedLeaf:
    def test_one_get_subtree_call_finds_a_writer_added_inline_in_the_test(self) -> None:
        """Два «заранее известных» писателя + ОДИН СВЕЖИЙ, заведённый прямо
        здесь, без единой правки framework-кода/конфига (просто ещё один
        PluginContext с новым plugin_name) -> ОДИН вызов get_subtree находит
        ВСЕ ТРИ. Механизм ничего не знает заранее об именах писателей — это и
        доказывает «нулевая правка кода на нового писателя»."""
        services, clock, hb = _make_env("camera_0")
        try:
            ctx_p = PluginContext(services=services, plugin_name="P")
            ctx_q = PluginContext(services=services, plugin_name="Q")
            ctx_p.declare_metric("x")
            ctx_q.declare_metric("y")
            ctx_p.publish_metric("x", 11.0)
            ctx_q.publish_metric("y", 22.0)

            # Писатель, заведённый ПРЯМО ЗДЕСЬ, а не заранее известный фреймворку.
            ctx_fresh = PluginContext(services=services, plugin_name="freshly_added_writer")
            ctx_fresh.declare_metric("z")
            ctx_fresh.publish_metric("z", 33.0)

            _force_one_tick(hb, clock)

            # ОДИН запрос поддерева — не серия точечных get().
            subtree = services.tree.get_subtree("processes.camera_0.state")

            assert subtree["plugins"]["P"]["x"] == 11.0
            assert subtree["plugins"]["Q"]["y"] == 22.0
            assert subtree["plugins"]["freshly_added_writer"]["z"] == 33.0
        finally:
            forget_declarations("metric", names={"x", "y", "z"})

    def test_a_writer_that_never_published_does_not_appear(self) -> None:
        """Контроль: обход не выдумывает лист для писателя, который объявил
        имя, но НИЧЕГО не публиковал — «находит все ОПУБЛИКОВАННЫЕ», не «все
        объявленные»."""
        services, clock, hb = _make_env("camera_0")
        try:
            ctx_p = PluginContext(services=services, plugin_name="P")
            ctx_silent = PluginContext(services=services, plugin_name="silent_writer")
            ctx_p.declare_metric("x")
            ctx_silent.declare_metric("never_published")
            ctx_p.publish_metric("x", 11.0)
            # ctx_silent.publish_metric(...) НЕ зовём.

            _force_one_tick(hb, clock)
            subtree = services.tree.get_subtree("processes.camera_0.state")

            assert subtree["plugins"]["P"]["x"] == 11.0
            assert "silent_writer" not in subtree.get("plugins", {})
        finally:
            forget_declarations("metric", names={"x", "never_published"})
