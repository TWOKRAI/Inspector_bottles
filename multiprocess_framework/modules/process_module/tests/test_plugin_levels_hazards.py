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
* **имя-дубль не разрешается — он отбрасывается.** Р3.5-11 сняла политику
  наложения («порядок несущий», «плагин побеждает») целиком: лист берётся, только
  если объявленный владелец имени совпадает с публикатором. Сторожится в ОБЕИХ
  дорогах — чужое имя не появляется ни в дереве, ни в опросе, и об этом слышно;
* **весь тик — ОДИН merge, и объединение имеет три ловушки** (Р3.5-12): пустой
  снимок воркеров не имеет права проглотить уровни и ``shm``; политика публикатора
  «все счётчики ``shm`` нулевые — не грузим дерево» обязана уцелеть внутри общей
  сборки; «данных нет вовсе» обязано давать НОЛЬ вызовов merge, а не пустой;
* **владелец считается в трёх местах — объявлении, публикации и снятии.** Разойдись
  они хоть в одном звене, уровень либо не поедет (владелец ≠ публикатор), либо не
  снимется на остановке. Сторожится ЭФФЕКТОМ на боевой тройке, а не чтением кода;
* **свежесть держится жизненным циклом.** ``retract`` зовёт фреймворк на остановке
  плагина, ПОСЛЕ пользовательского ``shutdown`` — плагин вправе отдать последнее
  значение в нём самом (``CapturePlugin`` обнуляет частоту на остановке захвата), и
  снятие до него оставило бы это значение висеть навсегда;
* **у хранилища три потока.** Писатель — воркер плагина, читатель — heartbeat,
  третий снимает уровни на остановке; копия словаря, растущего одновременно, без
  лока поднимает ``RuntimeError``.
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
    ProcessModulePlugin,
    SubPluginContext,
)
from multiprocess_framework.modules.process_module.plugins.testing import (
    MockProcessServices,
)

#: Имя, которого нет нигде в репозитории, — положительное свойство §3.6
#: «универсальность». Механизм с зашитым списком имён провалит его по построению.
#:
#: БЕЗ ТОЧЕК, и это не косметика. Точечное имя уровня — отдельный, уже записанный
#: резидуал: ``TreeStore._merge_recursive`` разворачивает точку в ПУТЬ, но только
#: когда узел ``state`` уже существует как dict; на первом merge тот же ключ ложится
#: литералом. До Р3.5-12 уровни ехали своим merge прямо в ``processes.<p>.state``, и
#: первая ветка не встречалась; после объединения встречается обе. Судить тут форму
#: пути значило бы судить резидуал вместо универсальности — тестер пришёл к тому же
#: выводу независимо (``zzz_made_up_level`` в его П3).
MADE_UP = "zzz_made_up_level"


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
        self._merge_recursive(path, data)

    def _merge_recursive(self, path: str, data: dict) -> None:
        """Дословно ``TreeStore._merge_recursive``: в dict рекурсия, если целевой
        узел ТОЖЕ dict; иначе — ``set`` по склеенному пути с полным резолвом точек."""
        for key, value in data.items():
            child = f"{path}.{key}" if path else key
            if isinstance(value, dict) and isinstance(self.get(child), dict):
                self._merge_recursive(child, value)
            else:
                *head, last = child.split(".")
                node = self.tree
                for part in head:
                    node = node.setdefault(part, {})
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


def _tick_levels(hb: ProcessHeartbeat, allowed_metrics=None) -> None:
    """Прогнать сборку тика БЕЗ воркеров — то есть судить ровно уровни.

    Р3.5-12 схлопнула три публикатора тика в один
    (``_publish_telemetry_to_tree``), и пустой снимок воркеров здесь не оговорка,
    а ловушка №1 объединения: ранний выход по ``not workers`` жил в прежнем
    воркерном публикаторе, и в общей сборке он проглотил бы и уровни, и ``shm``.
    Каждый вызов ниже — заодно проверка, что не проглатывает.
    """
    hb._publish_telemetry_to_tree({}, allowed_metrics)


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

        _tick_levels(hb)
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

        _tick_levels(hb)
        assert _tree(services, "late_level") is None, "необъявленное имя уехало в дерево"

        ctx.declare_metric("late_level")
        _tick_levels(hb)
        assert _tree(services, "late_level") == 1.0

    def test_publishing_before_declaring_keeps_the_value_and_says_it_once(self):
        """Значение не теряется, а отсев не молчит — и голос ровно один на имя."""
        services, hb = _boot(name="early")
        ctx = PluginContext(services=services, config={}, plugin_name="early_plugin")
        ctx.publish_metric("early_level", 5.0)

        _tick_levels(hb)
        _tick_levels(hb)
        _tick_levels(hb)
        said = [msg for msg in services.warnings() if "early_level" in msg]
        assert len(said) == 1, f"ожидали ОДИН голос на имя, получили {len(said)}: {said}"

        ctx.declare_metric("early_level")
        _tick_levels(hb)
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
        _tick_levels(hb, hb._telemetry_gate.due_metrics(now=0.0))
        assert _tree(services, "gated_level") is None, "закрытый гейт не остановил push"

        hb.reconfigure_telemetry({"metrics": {"gated_level": {"enabled": True}}})
        _tick_levels(hb, hb._telemetry_gate.due_metrics(now=1.0))
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
        _tick_levels(hb, hb._telemetry_gate.due_metrics(now=0.0))

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

        _tick_levels(hb)
        assert _tree(services, "same_level") == pytest.approx(15.3)
        assert _polled_state(services)["same_level"] == pytest.approx(15.3), (
            "опрос и push разошлись в округлении — 'одна дорога' стало бы ложью"
        )

    def test_a_plugin_level_named_like_a_framework_metric_is_rejected_in_both_roads(self):
        """Имя-дубль (``fps``) ОТБРАСЫВАЕТСЯ, и одинаково в дереве и в опросе.

        Здесь стоял ровно обратный тест — «уровень плагина обязан лечь ПОСЛЕ
        агрегата и победить». Он пинил политику наложения ADR-PM-038, снятую
        Р3.5-11 целиком, и был зелен, пока политика была объявлена; на живом
        стенде она при этом НЕ РАБОТАЛА — продовое правило троттла
        ``processes.**.state.fps: 0.05`` вырезало вторую запись всегда, потому что
        оба merge тика приходили в одно окно 15.6-мс сетки Windows.

        Свойство, которое тест сторожил, уцелело и усилилось: **дерево и опрос
        отвечают на имя-дубль ОДИНАКОВО**. Изменился ответ — не «побеждает
        плагин», а «плагин отброшен, показание владельца цело». Судится значением,
        а не отсутствием вызова.
        """
        services, hb = _boot(name="dup")
        services.worker_manager.get_all_workers_status = lambda: {  # type: ignore[attr-defined]
            "w": {"status": "running", "effective_hz": 8.0, "cycle_duration_ms": 3.0}
        }
        ctx = PluginContext(services=services, config={}, plugin_name="dup_plugin")
        ctx.publish_metric("fps", 21.0)  # 'fps' объявлен фреймворком — чужое имя

        hb._publish_telemetry_to_tree(services.worker_manager.get_all_workers_status(), None)
        assert _tree(services, "fps") == 8.0, "агрегат воркеров подменён публикацией в чужое имя"
        assert _polled_state(services)["fps"] == 8.0, "опрос разошёлся с деревом на имени-дубле"
        assert any("fps" in msg for msg in services.warnings()), (
            f"отсев чужого имени промолчал — тихий отсев неотличим от опечатки: {services.warnings()}"
        )

    def test_the_rejection_voice_names_all_three_participants(self):
        """В голосе — имя, публикатор и владелец: три разных диагноза, три действия."""
        services, hb = _boot(name="voice")
        PluginContext(services=services, config={}, plugin_name="loud_plugin").publish_metric("fps", 1.0)

        _tick_levels(hb)

        said = [msg for msg in services.warnings() if "fps" in msg]
        assert len(said) == 1, said
        assert "loud_plugin" in said[0], said
        assert "telemetry" in said[0], f"владелец имени не назван — не отличить чужое имя от опечатки: {said[0]}"


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
        _tick_levels(hb)
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
        _tick_levels(hb)
        assert _tree(services, "text_level") == "не число"

    def test_empty_store_publishes_nothing(self):
        """Ни одного уровня — ни одного merge: не грузим дерево пустым сообщением."""
        services, hb = _boot(name="empty")
        PluginContext(services=services, config={}, plugin_name="empty_plugin").publish_metric("x", 1)
        before = len(services._state_proxy.merges)
        _tick_levels(hb)  # 'x' не объявлен
        assert len(services._state_proxy.merges) == before


# --------------------------------------------------------------------------- #
# Два потока вокруг одного хранилища.
# --------------------------------------------------------------------------- #
#: Сколько имён писатель успевает добавить до сброса. Предохранитель, а не
#: параметр механизма: без него тест падал не тем, что ищет, — ``MemoryError``.
#: Воспроизведено 2026-08-16 на этом же тесте после Р3.5-11: запись стала парой
#: ``(значение, публикатор)``, чтение — двумя проходами, писатель за 80 с успевал
#: съесть память раньше, чем читатель заканчивал свои 2000 копий. Сброс через
#: ``retract`` держит РОСТ (новые ключи — то, что и поднимает RuntimeError)
#: бесконечным при ограниченном размере.
_GROWTH_WINDOW = 20_000


class TestConcurrency:
    def test_a_copy_survives_a_writer_growing_the_store(self):
        """Без лока ``dict(...)`` растущего словаря поднимает RuntimeError.

        Писатель здесь — отдельный поток, как в проде (воркер плагина против
        потока heartbeat), и он именно РАСТИТ словарь новыми ключами: перезапись
        существующего ключа копию не ломает, и тест на ней был бы вакуумным.

        Проверяются ОБА чтения. ``publications`` — вход сборщика тика и опроса,
        то есть тот, чей отказ погасил бы телеметрию; ``snapshot`` — производная
        проекция, у которой между взятием копии и её обходом лока уже нет, и
        именно поэтому она обязана обходить КОПИЮ, а не живой словарь.
        ``retract`` крутится тем же потоком — третий писатель, появившийся с
        Р3.5-14, ходит в то же хранилище.
        """
        store = PluginLevels()
        stop = threading.Event()
        errors: list[BaseException] = []

        def writer() -> None:
            i = 0
            while not stop.is_set():
                store.publish(f"level_{i}", i, "writer_plugin")
                i += 1
                if i >= _GROWTH_WINDOW:
                    store.retract("writer_plugin")
                    i = 0

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        try:
            for n in range(2000):
                try:
                    store.publications() if n % 2 else store.snapshot()
                except BaseException as exc:  # noqa: BLE001 — ловим ровно то, что ищем
                    errors.append(exc)
                    break
        finally:
            stop.set()
            thread.join(timeout=5.0)
        assert not thread.is_alive(), "поток-писатель не завершился — тест повис бы"
        assert not errors, f"чтение хранилища не пережило конкурентную запись: {errors!r}"


# --------------------------------------------------------------------------- #
# Сборщик как чистая функция — без heartbeat и без дерева.
# --------------------------------------------------------------------------- #
class TestCollector:
    def test_unowned_names_are_reported_sorted_and_not_published(self):
        payload, rejected = build_plugin_levels({"b_unknown": (1, "pub_b"), "a_unknown": (2, "pub_a")}, None)
        assert payload == {}
        # Тройка целиком: имя, публикатор и владелец (None = не объявлено никем).
        assert rejected == (("a_unknown", "pub_a", None), ("b_unknown", "pub_b", None))

    def test_a_foreign_owner_is_reported_with_the_owners_name(self):
        """Чужое имя и необъявленное — РАЗНЫЕ диагнозы, различимы третьим элементом."""
        _payload, rejected = build_plugin_levels({"fps": (99.0, "самозванец")}, None)
        assert len(rejected) == 1
        name, publisher, owner = rejected[0]
        assert (name, publisher) == ("fps", "самозванец")
        assert owner is not None and owner.startswith("multiprocess_framework."), owner

    def test_the_collector_does_not_mutate_its_input(self):
        levels = {"x": (1, "p")}
        build_plugin_levels(levels, None)
        assert levels == {"x": (1, "p")}

    def test_booleans_are_not_rounded_into_numbers(self):
        """``round(True, 1)`` вернул бы 1 — фронт, просочившийся в уровни, обязан
        остаться распознаваемым как фронт, а не превратиться в число."""
        services, _hb = _boot(name="bool")
        ctx = PluginContext(services=services, config={}, plugin_name="bool_plugin")
        ctx.declare_metric("bool_level")
        ctx.publish_metric("bool_level", True)
        payload, _ = build_plugin_levels({"bool_level": (True, "bool_plugin")}, None)
        assert payload["bool_level"] is True


class TestWiringNotJustTheCollector:
    """Провод из ``_loop``, а не только сборщик.

    ДОБАВЛЕНО ВЛАДЕЛЬЦЕМ СПЕКИ (2026-08-16). Автор реализации назвал эту дыру сам:
    инъекция «убрать вызов публикатора уровней из ``_loop``» красила **ноль**
    тестов — и его набор, и приёмочный набор тестера зовут сборщик НАПРЯМУЮ.
    Механизм при этом остаётся идеальным, а система молча перестаёт публиковать:
    ровно класс «провод не проверен», который на этом проекте уже стоил находки
    «плагин не вызван молча».

    Адрес инъекции после Р3.5-12 — вызов ``_publish_telemetry_to_tree`` в ``_loop``
    (три прежних публикатора схлопнуты в один). Формулировка выше намеренно
    осталась про ЭФФЕКТ, а не про имя метода: имя менять можно, провод — нет.

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


# --------------------------------------------------------------------------- #
# Р3.5-12 — три ловушки объединения трёх merge в один.
#
# Каждая — не гипотеза, а место, где прежний код имел ранний выход или политику,
# и где объединение могло их молча потерять. Судится ЧИСЛОМ вызовов merge и
# составом единственного payload'а, а не формой внутренних функций.
# --------------------------------------------------------------------------- #
class _ShmRouter:
    """Router с одним ненулевым счётчиком — чтобы группа ``shm`` реально ехала."""

    def get_shm_stats(self) -> dict:
        return {"frame_torn_reads": 3}


class _ZeroRouter:
    """Router со всеми нулями — политика публикатора обязана его промолчать."""

    def get_shm_stats(self) -> dict:
        return {}


def _boot_hb(services: _Services) -> ProcessHeartbeat:
    hb = ProcessHeartbeat(services)
    services._heartbeat = hb
    return hb


class TestOneMergePerTick:
    def _services_with_worker(self, name: str) -> _Services:
        services = _Services(name=name)
        services.worker_manager.get_all_workers_status = lambda: {  # type: ignore[attr-defined]
            "w": {"status": "running", "effective_hz": 8.0, "cycle_duration_ms": 3.0}
        }
        return services

    def test_workers_shm_and_levels_ride_one_merge(self):
        """Три источника → один merge и один путь ``processes.<name>``."""
        services = self._services_with_worker("one")
        services.router_manager = _ShmRouter()
        hb = _boot_hb(services)
        ctx = PluginContext(services=services, config={}, plugin_name="one_plugin")
        ctx.declare_metric("one_level")
        ctx.publish_metric("one_level", 4.0)

        hb._publish_telemetry_to_tree(services.worker_manager.get_all_workers_status(), None)

        assert len(services._state_proxy.merges) == 1, services._state_proxy.merges
        path, data = services._state_proxy.merges[0]
        assert path == "processes.one"
        assert data["workers"]["w"]["status"] == "running"
        assert data["state"]["fps"] == 8.0
        assert data["state"]["one_level"] == 4.0
        assert data["state"]["shm"]["torn_reads"] == 3

    def test_no_workers_does_not_swallow_levels_and_shm(self):
        """ЛОВУШКА 1: прежний ранний выход по ``not workers`` жил в воркерном
        публикаторе и глотал только воркерные листья — ``shm`` и уровни ехали
        своими merge. В общей сборке тот же выход проглотил бы всё."""
        services = _Services(name="nw")
        services.worker_manager.get_all_workers_status = lambda: {}  # type: ignore[attr-defined]
        services.router_manager = _ShmRouter()
        hb = _boot_hb(services)
        ctx = PluginContext(services=services, config={}, plugin_name="nw_plugin")
        ctx.declare_metric("nw_level")
        ctx.publish_metric("nw_level", 6.0)

        hb._publish_telemetry_to_tree({}, None)

        assert len(services._state_proxy.merges) == 1, services._state_proxy.merges
        _path, data = services._state_proxy.merges[0]
        assert "workers" not in data
        assert data["state"]["nw_level"] == 6.0
        assert data["state"]["shm"]["torn_reads"] == 3

    def test_all_zero_shm_still_does_not_load_the_tree(self):
        """ЛОВУШКА 2: «все счётчики нулевые → не грузим дерево» — политика
        ПУБЛИКАТОРА, и она обязана уцелеть внутри объединённой сборки, а не
        исчезнуть вместе со снятым методом. Соседний уровень при этом едет."""
        services = _Services(name="zero")
        services.worker_manager.get_all_workers_status = lambda: {}  # type: ignore[attr-defined]
        services.router_manager = _ZeroRouter()
        hb = _boot_hb(services)
        ctx = PluginContext(services=services, config={}, plugin_name="zero_plugin")
        ctx.declare_metric("zero_level")
        ctx.publish_metric("zero_level", 1.0)

        hb._publish_telemetry_to_tree({}, None)

        assert len(services._state_proxy.merges) == 1, services._state_proxy.merges
        _path, data = services._state_proxy.merges[0]
        assert "shm" not in data["state"], data
        assert data["state"]["zero_level"] == 1.0

    def test_nothing_at_all_sends_zero_merges(self):
        """ЛОВУШКА 3: данных нет вовсе → НОЛЬ вызовов merge, а не пустой merge."""
        services = _Services(name="void")
        services.worker_manager.get_all_workers_status = lambda: {}  # type: ignore[attr-defined]
        services.router_manager = None
        hb = _boot_hb(services)

        hb._publish_telemetry_to_tree({}, None)

        assert services._state_proxy.merges == []

    def test_the_framework_aggregate_lies_on_top_of_plugin_levels(self):
        """Fail-safe порядок наложения (а НЕ политика разрешения конфликта).

        Спор за имя сюда не доходит — его снимает проверка владельца в сборщике,
        и это сторожит соседний тест. Здесь проверяется само расположение: если
        отбор когда-нибудь протечёт, поверх ляжет величина ФРЕЙМВОРКА, а не
        подменённая. Судится сборкой payload'а напрямую, потому что через боевой
        путь протечка (по построению отбора) не воспроизводится.
        """
        services = self._services_with_worker("order")
        hb = _boot_hb(services)
        # Подменяем шов сбора уровней так, будто отбор протёк и отдал 'fps'.
        hb._collect_plugin_levels = lambda allowed, *, voice: {"fps": 999.0}  # type: ignore[assignment]

        hb._publish_telemetry_to_tree(services.worker_manager.get_all_workers_status(), None)

        _path, data = services._state_proxy.merges[0]
        assert data["state"]["fps"] == 8.0, f"протёкший уровень плагина лёг ПОВЕРХ агрегата фреймворка: {data['state']}"


# --------------------------------------------------------------------------- #
# Р3.5-14 — свежесть жизненным циклом.
# --------------------------------------------------------------------------- #
class _ShutdownPublishingPlugin(ProcessModulePlugin):
    """Плагин, который отдаёт ПОСЛЕДНЕЕ значение в собственном ``shutdown``.

    Не выдумка ради теста: ровно так устроен ``CapturePlugin`` — на остановке
    захвата он обнуляет частоту и публикует её, потому что следующего такта
    метрик уже не будет.
    """

    category = "utility"

    def configure(self, ctx: PluginContext) -> None:
        ctx.declare_metric("dying_level")
        ctx.publish_metric("dying_level", 5.0)

    def shutdown(self, ctx: PluginContext) -> None:
        ctx.publish_metric("dying_level", 0.0)


class TestLifecycleRetract:
    def test_retract_runs_after_the_plugins_own_shutdown(self):
        """Снятие ПОСЛЕ пользовательского ``shutdown``, а не до.

        До — и последнее значение, отданное в самом ``shutdown``, осталось бы
        висеть в дереве навсегда: снимать было бы уже нечего. Это единственный
        порядок, при котором работают обе половины.
        """
        services, _hb = _boot(name="dying")
        ctx = PluginContext(services=services, config={}, plugin_name="dying_plugin")
        plugin = _ShutdownPublishingPlugin()
        plugin.name = "dying_plugin"
        plugin._do_configure(ctx)
        store = getattr(services, PLUGIN_LEVELS_ATTR)
        assert store.snapshot() == {"dying_level": 5.0}

        plugin._do_shutdown(ctx)

        assert store.snapshot() == {}, (
            f"уровень пережил остановку плагина: {store.snapshot()} "
            "— снятие идёт ДО пользовательского shutdown либо не идёт вовсе"
        )

    def test_retract_takes_only_this_owners_levels(self):
        services, _hb = _boot(name="pair")
        base = PluginContext(services=services, config={})
        ctx_a = base.with_config({}, plugin_name="pair_a")
        ctx_b = base.with_config({}, plugin_name="pair_b")
        ctx_a.declare_metric("pair_level_a")
        ctx_b.declare_metric("pair_level_b")
        ctx_a.publish_metric("pair_level_a", 1.0)
        ctx_b.publish_metric("pair_level_b", 2.0)

        assert ctx_a._retract_metrics() == 1
        store = getattr(services, PLUGIN_LEVELS_ATTR)
        assert store.snapshot() == {"pair_level_b": 2.0}

    def test_retract_without_a_store_is_a_named_zero_not_an_error(self):
        """Процесс без телеметрии останавливает плагины как обычно."""
        services = MockProcessServices(name="bare_retract")
        ctx = PluginContext(services=services, config={}, plugin_name="bare_retract_plugin")
        assert ctx._retract_metrics() == 0

    def test_the_declaration_survives_the_retract(self):
        """Снимается ПУБЛИКАЦИЯ, не объявление: поднятый заново плагин объявится
        тем же владельцем (это не конфликт), а забытое объявление восстанавливать
        было бы некому."""
        services, hb = _boot(name="redeclare")
        ctx = PluginContext(services=services, config={}, plugin_name="redeclare_plugin")
        ctx.declare_metric("survivor_level")
        ctx.publish_metric("survivor_level", 3.0)
        ctx._retract_metrics()

        assert "survivor_level" in declared_metrics()
        ctx.publish_metric("survivor_level", 4.0)
        _tick_levels(hb)
        assert _tree(services, "survivor_level") == 4.0


# --------------------------------------------------------------------------- #
# Владелец считается в ОДНОМ месте — судится эффектом на боевой тройке.
# --------------------------------------------------------------------------- #
class TestOwnerIsComputedOnce:
    def test_declare_publish_and_retract_agree_on_the_owner(self):
        """Три дороги, один владелец. Разойдись хоть одна — уровень либо не
        поедет (владелец не равен публикатору), либо не снимется на остановке.
        Судится эффектом: объявил → уехало → сняли → исчезло."""
        services, hb = _boot(name="triple")
        ctx = PluginContext(services=services, config={}, plugin_name="triple_plugin")
        ctx.declare_metric("triple_level")
        ctx.publish_metric("triple_level", 7.0)

        _tick_levels(hb)
        assert _tree(services, "triple_level") == 7.0, "объявление и публикация разошлись во владельце"

        assert ctx._retract_metrics() == 1, "снятие разошлось во владельце с публикацией"
        assert _polled_state(services).get("triple_level") is None

    def test_a_context_without_a_plugin_name_owns_by_process_on_all_three(self):
        """Тот же треугольник для базового ctx (владелец — имя процесса)."""
        services, hb = _boot(name="proc_owner")
        ctx = PluginContext(services=services, config={})
        ctx.declare_metric("proc_owned_level")
        ctx.publish_metric("proc_owned_level", 2.0)

        _tick_levels(hb)
        assert _tree(services, "proc_owned_level") == 2.0
        assert ctx._retract_metrics() == 1
