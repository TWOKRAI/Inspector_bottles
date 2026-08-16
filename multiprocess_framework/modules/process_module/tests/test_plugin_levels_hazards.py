# -*- coding: utf-8 -*-
"""Опасности МЕХАНИЗМА уровней плагина — авторский набор Task 3.5 (ADR-PM-038).

Дополнение к приёмочному ``test_plugin_levels_acceptance.py`` (независимый тестер,
от критериев), а НЕ замена. Здесь то, что видно только автору механизма: порядок
объявления и отдачи, два потока вокруг одного хранилища, столкновение имени
плагина с именем фреймворка, асимметрия push/poll относительно гейта, поведение
разъёма без хранилища.

Что каждый тест сторожит, если сформулировать до прогона:

* **порядок «объявил → отдал» не обязан соблюдаться, а «отдал, но не объявил» не
  обязан молчать.** Первое — потому что ``configure`` плагина вправе отдать
  стартовое значение раньше, чем дойдёт до объявления; второе — потому что
  необъявленное имя гейту неизвестно, публиковаться не будет НИКОГДА, и тихий
  отсев неотличим от опечатки в имени;
* **опрос гейту не подчиняется, а push подчиняется** — это не оплошность, а
  ADR-PM-035: гейт про трафик, а не про то, что процесс знает о себе. Свойство
  парное: закрытый гейт даёт ноль в дереве И ненулевое в опросе;
* **имя-дубль разрешается порядком наложения, и порядок этот назван.** Уровень
  плагина ложится ПОСЛЕ агрегата воркеров и в push, и в poll — иначе опрос и
  дерево показывали бы разные числа под одним путём;
* **у хранилища два потока.** Писатель — воркер плагина, читатель — heartbeat;
  копия словаря, растущего одновременно, без лока поднимает ``RuntimeError``.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from multiprocess_framework.modules.observability_declarations import (
    KIND_METRIC,
    declared_metrics,
    forget_declarations,
)
from multiprocess_framework.modules.process_module.commands.builtin_commands import (
    BuiltinCommands,
)
from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)
from multiprocess_framework.modules.process_module.heartbeat.telemetry import (
    PLUGIN_LEVELS_ATTR,
    PluginLevels,
    build_plugin_levels,
)
from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    SubPluginContext,
)
from multiprocess_framework.modules.process_module.plugins.testing import (
    MockProcessServices,
)

#: Имя, которого нет нигде в репозитории, — положительное свойство §3.6
#: «универсальность». Механизм с зашитым списком имён провалит его по построению.
MADE_UP = "zzz.made.up.level"


@pytest.fixture(autouse=True)
def _metric_registry_guard():
    """Забыть ТОЛЬКО имена, объявленные этим тестом.

    Не ``forget_declarations(KIND_METRIC)``: сплошная очистка плоскости
    невосстановима (производители уже импортированы, объявлять некому), а
    «восстановить, объявив заново» подменяет ВЛАДЕЛЬЦА и превращает законный
    повторный импорт соседа в ``ValueError``. Точечная форма забирает ровно
    свой мусор — см. ``forget_declarations(names=...)``.
    """
    before = set(declared_metrics())
    yield
    forget_declarations(KIND_METRIC, names=set(declared_metrics()) - before)


# --------------------------------------------------------------------------- #
# Носитель: протокол-полные сервисы (ВСЯ пятёрка log_*) + дерево + heartbeat.
# --------------------------------------------------------------------------- #
class _Proxy:
    """Мини-дерево со счётом обращений.

    **Точечный ключ ВНУТРИ ``data`` раскрывается в путь** — как у настоящего
    ``TreeStore._merge_recursive``, который склеивает ``f"{path}.{key}"`` и отдаёт
    результат в ``set()`` с полным резолвом. Первая редакция этого дубля делала
    ``node.update(data)`` и клала точечное имя ОДНИМ литеральным ключом; тест
    универсальности с именем ``zzz.made.up.level`` из-за этого краснел на
    исправном механизме — дубль не умел того, что умеет стор.
    """

    def __init__(self) -> None:
        self.tree: dict[str, Any] = {}
        self.merges: list[tuple[str, dict]] = []

    def merge(self, path: str, data: dict) -> None:
        self.merges.append((path, dict(data)))
        for key, value in data.items():
            *head, last = f"{path}.{key}".split(".")
            node = self.tree
            for part in head:
                node = node.setdefault(part, {})
            if isinstance(value, dict) and isinstance(node.get(last), dict):
                node[last].update(value)
            else:
                node[last] = value

    def get(self, path: str, default: Any = None) -> Any:
        node: Any = self.tree
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


class _Services(MockProcessServices):
    """Дубль сервисов, годный И плагину, И heartbeat'у, И BuiltinCommands.

    Наследование от ``MockProcessServices``, а не своя копия: пятёрка ``log_*``
    и порты приезжают оттуда, и когда протокол вырастет, дубль вырастет с ним.
    Добавлены только приватные имена, которые читают heartbeat/команды.
    """

    def __init__(self, name: str = "proc") -> None:
        super().__init__(name=name)
        self._state_proxy = _Proxy()
        self._heartbeat: ProcessHeartbeat | None = None

    def _log_info(self, *a: Any, **k: Any) -> None:  # BuiltinCommands зовёт с подчёркиванием
        pass

    def _log_debug(self, *a: Any, **k: Any) -> None:
        pass

    def warnings(self) -> list[str]:
        return [str(entry.get("msg", "")) for entry in self.logs if entry.get("level") == "WARNING"]


def _boot(name: str = "proc") -> tuple[_Services, ProcessHeartbeat]:
    services = _Services(name=name)
    hb = ProcessHeartbeat(services)
    services._heartbeat = hb
    return services, hb


def _poll(services: _Services) -> dict:
    bc = BuiltinCommands(services)
    bc._register_introspect_commands()
    return services.command_manager.commands["introspect.telemetry"]({})


def _tree(services: _Services, leaf: str) -> Any:
    return services._state_proxy.get(f"processes.{services.name}.state.{leaf}")


def _polled_state(services: _Services) -> dict:
    """Секция ``state`` снимка уровней — ТА ЖЕ форма пути, что у тика.

    ``levels`` зеркалит поддерево ``processes.<name>`` (``workers.*`` + ``state.*``),
    поэтому уровень адресуется ``levels["state"][имя]``, ровно как ``fps``.
    Плоского ``levels[имя]`` быть не может: ``TelemetryPoller._flatten_levels``
    склеивает ключи ответа с префиксом ``processes.<name>``, и плоское имя
    уехало бы в ``processes.<name>.<имя>`` — мимо пути, которым его пишет push.
    """
    levels = _poll(services).get("levels") or {}
    return levels.get("state") or {}


# --------------------------------------------------------------------------- #
# Универсальность — положительным свойством, а не отрицательным grep'ом.
# --------------------------------------------------------------------------- #
class TestFrameworkKnowsNoNames:
    def test_a_name_absent_from_the_repository_reaches_tree_and_poll(self):
        """Выдуманное имя доезжает обеими дорогами — значит списка имён нет."""
        services, hb = _boot(name="uni")
        ctx = PluginContext(services=services, config={}, plugin_name="made_up_plugin")
        ctx.declare_metric(MADE_UP)
        ctx.publish_metric(MADE_UP, 12.0)

        hb._publish_plugin_levels_to_tree(allowed_metrics=None)
        assert _tree(services, MADE_UP) == 12.0
        assert _polled_state(services)[MADE_UP] == 12.0

    def test_the_made_up_name_enters_the_gate_catalog(self):
        """И оно же становится управляемым: гейт обходит каталог объявлений."""
        services, _hb = _boot(name="uni2")
        ctx = PluginContext(services=services, config={}, plugin_name="made_up_plugin")
        ctx.declare_metric(MADE_UP)
        assert MADE_UP in declared_metrics()


# --------------------------------------------------------------------------- #
# Порядок: объявление после первого тика; публикация до объявления.
# --------------------------------------------------------------------------- #
class TestDeclarationOrder:
    def test_declaring_after_the_first_tick_starts_flowing_on_the_next(self):
        """Каталог читается НА ТИКЕ, а не кэшируется при сборке публикатора.

        Снимок каталога, взятый один раз, оставил бы плагин, объявившийся позже
        (ленивый импорт, hot-apply рецепта), без публикации навсегда — и симптом
        искали бы в гейте, где всё верно.
        """
        services, hb = _boot(name="late")
        ctx = PluginContext(services=services, config={}, plugin_name="late_plugin")
        ctx.publish_metric("late_level", 1.0)

        hb._publish_plugin_levels_to_tree(allowed_metrics=None)
        assert _tree(services, "late_level") is None, "необъявленное имя уехало в дерево"

        ctx.declare_metric("late_level")
        hb._publish_plugin_levels_to_tree(allowed_metrics=None)
        assert _tree(services, "late_level") == 1.0

    def test_publishing_before_declaring_keeps_the_value_and_says_it_once(self):
        """Значение не теряется, а отсев не молчит — и голос ровно один на имя."""
        services, hb = _boot(name="early")
        ctx = PluginContext(services=services, config={}, plugin_name="early_plugin")
        ctx.publish_metric("early_level", 5.0)

        hb._publish_plugin_levels_to_tree(allowed_metrics=None)
        hb._publish_plugin_levels_to_tree(allowed_metrics=None)
        hb._publish_plugin_levels_to_tree(allowed_metrics=None)
        said = [msg for msg in services.warnings() if "early_level" in msg]
        assert len(said) == 1, f"ожидали ОДИН голос на имя, получили {len(said)}: {said}"

        ctx.declare_metric("early_level")
        hb._publish_plugin_levels_to_tree(allowed_metrics=None)
        assert _tree(services, "early_level") == 5.0, "значение, отданное до объявления, потеряно"


# --------------------------------------------------------------------------- #
# Повторное объявление и конфликт владельцев.
# --------------------------------------------------------------------------- #
class TestRedeclaration:
    def test_same_plugin_may_redeclare(self):
        """Плагин переимпортируют (reload, spawn) — падать на этом нельзя."""
        services, _hb = _boot(name="re")
        ctx = PluginContext(services=services, config={}, plugin_name="same_plugin")
        ctx.declare_metric("re_level")
        ctx.declare_metric("re_level")

    def test_two_plugins_of_one_process_conflict(self):
        services, _hb = _boot(name="conf")
        a = PluginContext(services=services, config={}, plugin_name="plugin_a")
        b = PluginContext(services=services, config={}, plugin_name="plugin_b")
        a.declare_metric("conf_level")
        with pytest.raises(ValueError):
            b.declare_metric("conf_level")

    def test_context_without_plugin_name_owns_by_process(self):
        """Базовый ctx без имени плагина объявляет от имени ПРОЦЕССА, не 'None'."""
        services, _hb = _boot(name="owner_proc")
        PluginContext(services=services, config={}).declare_metric("owner_level")
        second = PluginContext(services=_Services(name="owner_proc"), config={})
        second.declare_metric("owner_level")  # тот же владелец — не конфликт


# --------------------------------------------------------------------------- #
# Гейт: push подчиняется, poll — нет. Пара маркеров ON/OFF.
# --------------------------------------------------------------------------- #
class TestGateCoversPushNotPoll:
    def test_closed_gate_zeroes_push_and_open_gate_restores_it(self):
        services, hb = _boot(name="gate")
        ctx = PluginContext(services=services, config={}, plugin_name="gated_plugin")
        ctx.declare_metric("gated_level")
        ctx.publish_metric("gated_level", 9.0)

        hb.reconfigure_telemetry({"metrics": {"gated_level": {"enabled": False}}})
        hb._publish_plugin_levels_to_tree(allowed_metrics=hb._telemetry_gate.due_metrics(now=0.0))
        assert _tree(services, "gated_level") is None, "закрытый гейт не остановил push"

        hb.reconfigure_telemetry({"metrics": {"gated_level": {"enabled": True}}})
        hb._publish_plugin_levels_to_tree(allowed_metrics=hb._telemetry_gate.due_metrics(now=1.0))
        assert _tree(services, "gated_level") == 9.0, (
            "открытый гейт не дал ненулевого — без этой половины пары закрытый ноль одинаков с 'механизм не подключён'"
        )

    def test_closed_gate_still_answers_the_poll(self):
        """ADR-PM-035: гейт про трафик, опрос про знание. Закрытое окно ≠ слепота."""
        services, hb = _boot(name="gate2")
        ctx = PluginContext(services=services, config={}, plugin_name="gated_plugin2")
        ctx.declare_metric("gated_level2")
        ctx.publish_metric("gated_level2", 4.0)

        hb.reconfigure_telemetry({"metrics": {"gated_level2": {"enabled": False}}})
        hb._publish_plugin_levels_to_tree(allowed_metrics=hb._telemetry_gate.due_metrics(now=0.0))

        assert _tree(services, "gated_level2") is None
        assert _polled_state(services)["gated_level2"] == 4.0, (
            "закрытый гейт погасил и опрос — вкладка при флипе РТ-2 ослепла бы"
        )

    def test_the_gate_does_not_know_the_level_is_a_plugins(self):
        """Уровень плагина проходит ТОТ ЖЕ ``due_metrics``, что fps/latency_ms."""
        services, hb = _boot(name="gate3")
        ctx = PluginContext(services=services, config={}, plugin_name="gated_plugin3")
        ctx.declare_metric("gated_level3")
        hb.reconfigure_telemetry({"default_interval_sec": 10.0})
        allowed = hb._telemetry_gate.due_metrics(now=0.0)
        assert "gated_level3" in allowed
        # Созревание — тоже общее: второй вызов в том же окне метрику не выдаёт.
        assert "gated_level3" not in hb._telemetry_gate.due_metrics(now=0.1)


# --------------------------------------------------------------------------- #
# push == poll: одно число, один путь, одно округление.
# --------------------------------------------------------------------------- #
class TestPushEqualsPoll:
    def test_same_value_same_leaf_in_both_roads(self):
        services, hb = _boot(name="same")
        ctx = PluginContext(services=services, config={}, plugin_name="same_road")
        ctx.declare_metric("same_level")
        ctx.publish_metric("same_level", 15.34)

        hb._publish_plugin_levels_to_tree(allowed_metrics=None)
        assert _tree(services, "same_level") == pytest.approx(15.3)
        assert _polled_state(services)["same_level"] == pytest.approx(15.3), (
            "опрос и push разошлись в округлении — 'одна дорога' стало бы ложью"
        )

    def test_a_plugin_level_named_like_a_framework_metric_wins_in_both_roads(self):
        """Имя-дубль (``fps``) разрешается ОДИНАКОВО в дереве и в опросе.

        Разойдись порядок наложения — оператор видел бы в карточке одно число, а
        в опросе другое, и расхождение искали бы в камере. Дубль здесь не
        гипотетический: миграция ``CapturePlugin`` устроена именно так.
        """
        services, hb = _boot(name="dup")
        services.worker_manager.get_all_workers_status = lambda: {  # type: ignore[attr-defined]
            "w": {"status": "running", "effective_hz": 8.0, "cycle_duration_ms": 3.0}
        }
        ctx = PluginContext(services=services, config={}, plugin_name="dup_plugin")
        ctx.publish_metric("fps", 21.0)  # 'fps' объявлен фреймворком — плагин не объявляет

        hb._publish_metrics_to_tree(services.worker_manager.get_all_workers_status(), None)
        assert _tree(services, "fps") == 8.0, "предпосылка: агрегат воркеров пишет свой fps"
        hb._publish_plugin_levels_to_tree(allowed_metrics=None)
        assert _tree(services, "fps") == 21.0, "уровень плагина обязан лечь ПОСЛЕ агрегата"
        assert _polled_state(services)["fps"] == 21.0, "опрос разошёлся с деревом на имени-дубле"


# --------------------------------------------------------------------------- #
# Вложенный контекст.
# --------------------------------------------------------------------------- #
class TestSubPluginContext:
    def test_default_roads_are_named_noops(self):
        sub = SubPluginContext()
        assert sub.declare_metric("orphan") == "orphan", "заглушка обязана вернуть то же имя"
        sub.publish_metric("orphan", 1.0)

    def test_default_publish_accepts_the_exact_signature(self):
        """Именованный вызов по эталонной сигнатуре не имеет права падать.

        Урок четырёх заглушек 1.1 дословно: общая заглушка «по форме» роняла
        ``TypeError: unexpected keyword argument`` ровно там, где ставилась ради
        безопасности.
        """
        SubPluginContext().publish_metric(name="orphan", value=2.0)
        assert SubPluginContext().declare_metric(name="orphan") == "orphan"

    def test_from_parent_forwards_both_roads_and_they_work(self):
        services, hb = _boot(name="sub")
        parent = PluginContext(services=services, config={}, plugin_name="parent_plugin")
        sub = SubPluginContext.from_parent(parent, config={"nested": True})

        sub.declare_metric("sub_level")
        sub.publish_metric("sub_level", 3.5)
        hb._publish_plugin_levels_to_tree(allowed_metrics=None)
        assert _tree(services, "sub_level") == pytest.approx(3.5), (
            "дороги проброшены по имени, но не делегируют в механизм родителя"
        )

    def test_sub_level_is_owned_by_the_parent_plugin(self):
        """Вложенный объявляет ОТ ИМЕНИ родителя — своего владельца у него нет."""
        services, _hb = _boot(name="sub2")
        parent = PluginContext(services=services, config={}, plugin_name="parent_plugin2")
        SubPluginContext.from_parent(parent).declare_metric("sub_owned")
        parent.declare_metric("sub_owned")  # тот же владелец — не конфликт


# --------------------------------------------------------------------------- #
# Отключаемость и стойкость разъёма.
# --------------------------------------------------------------------------- #
class TestDisabledAndHostile:
    def test_publish_without_heartbeat_is_a_noop_not_an_error(self):
        services = MockProcessServices(name="bare")
        ctx = PluginContext(services=services, config={}, plugin_name="bare_plugin")
        ctx.declare_metric("bare_level")
        ctx.publish_metric("bare_level", 1.0)  # ни исключения, ни требований к дереву

    def test_services_refusing_the_port_give_one_named_warning(self):
        """``__slots__``-дубль не принимает атрибут — молчать об этом нельзя."""

        class _Slotted(MockProcessServices):
            """Дубль, который порт принимает на сборке и ОТКАЗЫВАЕТ потом.

            Отказывать с самого начала нельзя: базовый ``__init__`` сам ставит
            ``plugin_levels = None`` (порт обязан существовать всегда), и дубль
            не собрался бы вовсе — тест падал бы на конструкторе, ничего не
            проверив.
            """

            _sealed = False

            def __setattr__(self, key: str, value: Any) -> None:
                if key == PLUGIN_LEVELS_ATTR and self._sealed:
                    raise AttributeError(key)
                super().__setattr__(key, value)

        services = _Slotted(name="slotted")
        services._sealed = True
        ctx = PluginContext(services=services, config={}, plugin_name="slotted_plugin")
        ctx.declare_metric("slotted_level")
        ctx.publish_metric("slotted_level", 1.0)
        ctx.publish_metric("slotted_level", 2.0)
        said = [msg for msg in services.logs if msg.get("level") == "WARNING" and "slotted_level" in msg.get("msg", "")]
        assert len(said) == 1, f"ожидали ровно один голос, получили {len(said)}"

    def test_a_non_numeric_value_does_not_break_the_collector(self):
        """Прикладная опечатка в значении не имеет права уронить телеметрию тика."""
        services, hb = _boot(name="text")
        ctx = PluginContext(services=services, config={}, plugin_name="text_plugin")
        ctx.declare_metric("text_level")
        ctx.publish_metric("text_level", "не число")
        hb._publish_plugin_levels_to_tree(allowed_metrics=None)
        assert _tree(services, "text_level") == "не число"

    def test_empty_store_publishes_nothing(self):
        """Ни одного уровня — ни одного merge: не грузим дерево пустым сообщением."""
        services, hb = _boot(name="empty")
        PluginContext(services=services, config={}, plugin_name="empty_plugin").publish_metric("x", 1)
        before = len(services._state_proxy.merges)
        hb._publish_plugin_levels_to_tree(allowed_metrics=None)  # 'x' не объявлен
        assert len(services._state_proxy.merges) == before


# --------------------------------------------------------------------------- #
# Два потока вокруг одного хранилища.
# --------------------------------------------------------------------------- #
class TestConcurrency:
    def test_snapshot_survives_a_writer_growing_the_store(self):
        """Без лока ``dict(...)`` растущего словаря поднимает RuntimeError.

        Писатель здесь — отдельный поток, как в проде (воркер плагина против
        потока heartbeat), и он именно РАСТИТ словарь новыми ключами: перезапись
        существующего ключа копию не ломает, и тест на ней был бы вакуумным.
        """
        store = PluginLevels()
        stop = threading.Event()
        errors: list[BaseException] = []

        def writer() -> None:
            i = 0
            while not stop.is_set():
                store.publish(f"level_{i}", i)
                i += 1

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        try:
            for _ in range(2000):
                try:
                    store.snapshot()
                except BaseException as exc:  # noqa: BLE001 — ловим ровно то, что ищем
                    errors.append(exc)
                    break
        finally:
            stop.set()
            thread.join(timeout=5.0)
        assert not thread.is_alive(), "поток-писатель не завершился — тест повис бы"
        assert not errors, f"снимок хранилища не пережил конкурентную запись: {errors!r}"


# --------------------------------------------------------------------------- #
# Сборщик как чистая функция — без heartbeat и без дерева.
# --------------------------------------------------------------------------- #
class TestCollector:
    def test_undeclared_names_are_reported_sorted_and_not_published(self):
        payload, undeclared = build_plugin_levels({"b_unknown": 1, "a_unknown": 2}, None)
        assert payload == {}
        assert undeclared == ("a_unknown", "b_unknown")

    def test_the_collector_does_not_mutate_its_input(self):
        levels = {"x": 1}
        build_plugin_levels(levels, None)
        assert levels == {"x": 1}

    def test_booleans_are_not_rounded_into_numbers(self):
        """``round(True, 1)`` вернул бы 1 — фронт, просочившийся в уровни, обязан
        остаться распознаваемым как фронт, а не превратиться в число."""
        services, _hb = _boot(name="bool")
        ctx = PluginContext(services=services, config={}, plugin_name="bool_plugin")
        ctx.declare_metric("bool_level")
        ctx.publish_metric("bool_level", True)
        payload, _ = build_plugin_levels({"bool_level": True}, None)
        assert payload["bool_level"] is True


class TestWiringNotJustTheCollector:
    """Провод из ``_loop``, а не только сборщик.

    ДОБАВЛЕНО ВЛАДЕЛЬЦЕМ СПЕКИ (2026-08-16). Автор реализации назвал эту дыру сам:
    инъекция «убрать вызов ``_publish_plugin_levels_to_tree`` из ``_loop``» красила
    **ноль** тестов — и его набор, и приёмочный набор тестера зовут сборщик НАПРЯМУЮ.
    Механизм при этом остаётся идеальным, а система молча перестаёт публиковать:
    ровно класс «провод не проверен», который на этом проекте уже стоил находки
    «плагин не вызван молча».

    Тест судит ЭФФЕКТ на боевом пути: крутится настоящий ``_loop`` в потоке-демоне
    с дедлайном join (зависший тест хуже отсутствующего), и уровень обязан появиться
    в дереве без единого прямого вызова сборщика из теста.
    """

    def test_the_real_loop_publishes_plugin_levels(self):
        services, hb = _boot(name="wire")
        ctx = PluginContext(services=services, config={}, plugin_name="wire_plugin")
        ctx.declare_metric("wired_level")
        ctx.publish_metric("wired_level", 9.0)

        stop = threading.Event()
        pause = threading.Event()
        t = threading.Thread(target=hb._loop, args=(stop, pause), daemon=True)
        t.start()
        try:
            deadline = time.time() + 5.0
            pushed = None
            while time.time() < deadline:
                pushed = services._state_proxy.get("processes.wire.state.wired_level")
                if pushed is not None:
                    break
                time.sleep(0.05)
        finally:
            stop.set()
            t.join(timeout=5.0)
        assert not t.is_alive(), "поток _loop не завершился по stop_event за 5 с"
        assert pushed == 9.0, (
            f"боевой _loop не опубликовал уровень плагина (получили {pushed!r}) — "
            f"сборщик может быть исправен, а провод оборван"
        )
