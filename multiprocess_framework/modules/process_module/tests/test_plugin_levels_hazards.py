# -*- coding: utf-8 -*-
"""Опасности МЕХАНИЗМА уровней плагина — авторский набор Task 3.5 (ADR-PM-038).

Дополнение к приёмочному ``test_plugin_levels_acceptance.py`` (независимый тестер,
от критериев), а НЕ замена. Здесь то, что видно только автору механизма: порядок
объявления и отдачи, два потока вокруг одного хранилища, столкновение имени
плагина с именем фреймворка, асимметрия push/poll относительно гейта, поведение
разъёма без хранилища.

Что каждый тест сторожит, если сформулировать до прогона:

ОБНОВЛЕНО Ф1 «порт наблюдений» (Task 1.2). Уровни переехали в поддерево писателя
``state.plugins.<писатель>.<имя>``; арбитраж владения, голос про самозванца и
поимённое снятие с ``None``-надгробиями удалены целиком (§9 плана, блок Ф1).
Классы, сторожившие ИМЕННО эти механизмы, ушли вместе с ними; классы, сторожившие
свойства, которые Ф1 не трогает, переписаны под новую ФОРМУ пути. Опасности самой
новой формы — в ``test_writer_subtree_hazards.py``.

* **необъявленное имя едет легально, и это не дыра, а тотальность гейта.**
  ``TelemetryPublishConfig.resolve`` тотальна, гейт спрашивает её и про имена, о
  которых каталог не знает. Прежний порядок («объявил → поехало») больше не
  свойство: объявление стало каталожной записью для гейта и авто-строк GUI;
* **опрос гейту не подчиняется, а push подчиняется** — это не оплошность, а
  ADR-PM-035: гейт про трафик, а не про то, что процесс знает о себе. Свойство
  парное: закрытый гейт даёт ноль в дереве И ненулевое в опросе;
* **имя-дубль не разрешается и не отбрасывается — его больше не бывает.** Писатель
  есть сегмент пути: ``fps`` плагина лежит под ``state.plugins.<он>.fps``, агрегат
  фреймворка — под ``state.fps``, ключа для спора нет. Сторожится в ОБЕИХ дорогах
  значениями обоих листьев;
* **весь тик — ОДИН merge, и объединение имеет три ловушки** (Р3.5-12): пустой
  снимок воркеров не имеет права проглотить уровни и ``shm``; политика публикатора
  «все счётчики ``shm`` нулевые — не грузим дерево» обязана уцелеть внутри общей
  сборки; «данных нет вовсе» обязано давать НОЛЬ вызовов merge, а не пустой;
* **писатель считается в трёх местах — объявлении, публикации и снятии.** Разойдись
  они хоть в одном звене, публикация уехала бы в одно поддерево, а снятие чистило
  бы другое. Сторожится ЭФФЕКТОМ на боевой тройке, а не чтением кода;
* **свежесть держится жизненным циклом.** ``retract`` зовёт фреймворк на остановке
  плагина, ПОСЛЕ пользовательского ``shutdown`` — плагин вправе отдать последнее
  значение в нём самом (``CapturePlugin`` обнуляет частоту на остановке захвата), и
  снятие до него оставило бы это значение висеть навсегда;
* **у хранилища три потока.** Писатель — воркер плагина, читатель — heartbeat,
  третий снимает уровни на остановке; копия словаря, растущего одновременно, без
  лока поднимает ``RuntimeError``. С поддеревом писателя копия стала ДВУХУРОВНЕВОЙ,
  то есть гонок стало две — внешняя (новый писатель) и внутренняя (новое имя);
* **точка в имени — отказ и на ПУБЛИКАЦИИ, не только на объявлении** (дыра,
  открытая Ф1). Пока необъявленное имя до дерева не доходило, guard'а на объявлении
  хватало; с Ф1 точечное имя поехало бы и дало вечно-мёртвый лист-двойник.
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
    PluginState,
    ProcessModulePlugin,
    SubPluginContext,
)
from multiprocess_framework.modules.process_module.plugins.testing import (
    MockProcessServices,
)


class _MinimalHazardPlugin(ProcessModulePlugin):
    """Плагин без поведения — нужен только его ЖИЗНЕННЫЙ ЦИКЛ."""

    category = "utility"

    def configure(self, ctx: PluginContext) -> None:
        pass


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

    **``delete`` появился с Ф2, и его отсутствие было дырой ХАРНЕССА, а не
    экономией.** Тик стал утверждать снятие поддерева ушедшего писателя через
    ``proxy.delete``; дубль без этого метода отвечал на него ``AttributeError``,
    который публикатор ловит как отказ транспорта, — и тест ниже
    (``TestShutdownFailureStillRetracts``) оставался зелёным на утверждении
    «лист живёт в дереве», проверяя на самом деле пробел дубля, а не поведение
    механизма. Форма — дословно ``TreeStore.delete``: снимается РОВНО последний
    сегмент пути у его родителя, никогда не подстрока соседнего ключа.
    """

    def __init__(self) -> None:
        self.tree: dict[str, Any] = {}
        self.merges: list[tuple[str, dict]] = []
        self.deletes: list[str] = []

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

    def delete(self, path: str) -> bool:
        """Снять ровно последний сегмент пути у родителя — как ``TreeStore.delete``.

        Идемпотентен, как настоящий: путь отсутствует → ``False``, а не
        исключение (``TreeStore.delete`` возвращает None, обработчик отвечает
        ``changed=False``).
        """
        self.deletes.append(path)
        *head, last = path.split(".")
        node: Any = self.tree
        for part in head:
            if not isinstance(node, dict) or part not in node:
                return False
            node = node[part]
        if not isinstance(node, dict) or last not in node:
            return False
        del node[last]
        return True


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
    """Лист секции ``state`` НАПРЯМУЮ — для агрегатов фреймворка (``fps``, ``shm``)."""
    return services._state_proxy.get(f"processes.{services.name}.state.{leaf}")


def _level(services: _Services, writer: str, leaf: str) -> Any:
    """Уровень плагина по НОВОМУ пути ``state.plugins.<писатель>.<имя>`` (Ф1)."""
    return services._state_proxy.get(f"processes.{services.name}.state.plugins.{writer}.{leaf}")


def _writer_subtree(services: _Services, writer: str) -> Any:
    """ВЕСЬ узел писателя — адрес, которым Ф2 снимает показания ушедшего."""
    return services._state_proxy.get(f"processes.{services.name}.state.plugins.{writer}")


def _polled_state(services: _Services) -> dict:
    """Секция ``state`` снимка уровней — ТА ЖЕ форма пути, что у тика.

    ``levels`` зеркалит поддерево ``processes.<name>`` (``workers.*`` + ``state.*``),
    поэтому уровень адресуется ``levels["state"]["plugins"][писатель][имя]``, ровно
    там же, где его пишет push. Плоского ``levels[имя]`` быть не может:
    ``TelemetryPoller._flatten_levels`` склеивает ключи ответа с префиксом
    ``processes.<name>``, и плоское имя уехало бы в ``processes.<name>.<имя>`` —
    мимо пути push'а.
    """
    levels = _poll(services).get("levels") or {}
    return levels.get("state") or {}


def _polled_level(services: _Services, writer: str, leaf: str) -> Any:
    """Тот же лист опросом — по той же форме пути, что у push'а."""
    plugins = _polled_state(services).get("plugins") or {}
    return (plugins.get(writer) or {}).get(leaf)


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
        assert _level(services, "made_up_plugin", MADE_UP) == 12.0
        assert _polled_level(services, "made_up_plugin", MADE_UP) == 12.0

    def test_the_made_up_name_enters_the_gate_catalog(self):
        """И оно же становится управляемым: гейт обходит каталог объявлений."""
        services, _hb = _boot(name="uni2")
        ctx = PluginContext(services=services, config={}, plugin_name="made_up_plugin")
        ctx.declare_metric(MADE_UP)
        assert MADE_UP in declared_metrics()


# --------------------------------------------------------------------------- #
# Повторное объявление: конфликта больше нет — есть два поддерева.
# --------------------------------------------------------------------------- #
class TestRedeclaration:
    def test_same_plugin_may_redeclare(self):
        """Плагин переимпортируют (reload, spawn) — падать на этом нельзя."""
        services, _hb = _boot(name="re")
        ctx = PluginContext(services=services, config={}, plugin_name="same_plugin")
        ctx.declare_metric("re_level")
        ctx.declare_metric("re_level")

    def test_two_plugins_of_one_process_share_a_name_and_get_two_leaves(self):
        """Прежде ``ValueError``, теперь — два листа (Ф1: писатель = сегмент пути).

        Пара к «объявление стало no-op'ом»: отсутствие исключения само по себе
        неотличимо от механизма, который вообще ничего не публикует. Судится
        ЭФФЕКТОМ — оба литерала в дереве, каждый под своим писателем.
        """
        services, hb = _boot(name="conf")
        a = PluginContext(services=services, config={}, plugin_name="plugin_a")
        b = PluginContext(services=services, config={}, plugin_name="plugin_b")
        a.declare_metric("conf_level")
        b.declare_metric("conf_level")  # прежде отказ — теперь идемпотентный no-op
        a.publish_metric("conf_level", 1.0)
        b.publish_metric("conf_level", 2.0)

        _tick_levels(hb)
        assert _level(services, "plugin_a", "conf_level") == 1.0
        assert _level(services, "plugin_b", "conf_level") == 2.0

    def test_context_without_plugin_name_writes_under_the_process(self):
        """Базовый ctx без имени плагина пишет от имени ПРОЦЕССА, не 'None'."""
        services, hb = _boot(name="owner_proc")
        ctx = PluginContext(services=services, config={})
        ctx.declare_metric("owner_level")
        ctx.publish_metric("owner_level", 5.0)
        _tick_levels(hb)
        assert _level(services, "owner_proc", "owner_level") == 5.0, (
            "писатель без имени плагина обязан назваться именем процесса"
        )


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
        assert _level(services, "gated_plugin", "gated_level") is None, "закрытый гейт не остановил push"

        hb.reconfigure_telemetry({"metrics": {"gated_level": {"enabled": True}}})
        _tick_levels(hb, hb._telemetry_gate.due_metrics(now=1.0))
        assert _level(services, "gated_plugin", "gated_level") == 9.0, (
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

        assert _level(services, "gated_plugin2", "gated_level2") is None
        assert _polled_level(services, "gated_plugin2", "gated_level2") == 4.0, (
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
        assert _level(services, "same_road", "same_level") == pytest.approx(15.3)
        assert _polled_level(services, "same_road", "same_level") == pytest.approx(15.3), (
            "опрос и push разошлись в округлении — 'одна дорога' стало бы ложью"
        )

    def test_a_plugin_level_named_like_a_framework_metric_coexists_with_the_aggregate(self):
        """Имя-дубль (``fps``) больше не спор: ДВА листа, оба со своими числами.

        Здесь стояло два предыдущих теста, и оба — про арбитраж. Первый требовал
        «уровень плагина обязан лечь ПОСЛЕ агрегата и победить» (политика наложения
        ADR-PM-038); Р3.5-11 сменила его на «плагин отброшен, показание владельца
        цело» (отбор по владению). Ф1 сняла и это: писатель — сегмент пути, и
        столкнуться двум ``fps`` больше негде.

        Свойство, которое тест сторожил всё это время, уцелело и стало сильнее:
        **дерево и опрос отвечают на имя-дубль ОДИНАКОВО**. Изменился ответ — не
        «побеждает плагин» и не «плагин отброшен», а «оба на месте, каждый под
        своим путём». Судится значениями ОБОИХ листьев, а не отсутствием вызова;
        голоса нет вовсе — отсеивать нечего.
        """
        services, hb = _boot(name="dup")
        services.worker_manager.get_all_workers_status = lambda: {  # type: ignore[attr-defined]
            "w": {"status": "running", "effective_hz": 8.0, "cycle_duration_ms": 3.0}
        }
        ctx = PluginContext(services=services, config={}, plugin_name="dup_plugin")
        ctx.publish_metric("fps", 21.0)  # 'fps' объявлен фреймворком — раньше «чужое имя»

        hb._publish_telemetry_to_tree(services.worker_manager.get_all_workers_status(), None)

        assert _tree(services, "fps") == 8.0, "агрегат воркеров подменён публикацией плагина"
        assert _level(services, "dup_plugin", "fps") == 21.0, (
            "уровень плагина с именем метрики фреймворка потерялся — поддерево писателя не работает"
        )
        assert _polled_state(services)["fps"] == 8.0, "опрос разошёлся с деревом на агрегате"
        assert _polled_level(services, "dup_plugin", "fps") == 21.0, "опрос разошёлся с деревом на уровне"
        assert not [msg for msg in services.warnings() if "fps" in msg], (
            f"голос про имя-дубль звучит, хотя спорить не о чем: {services.warnings()}"
        )

    def test_two_plugins_on_one_name_land_in_two_subtrees_in_both_roads(self):
        """Два плагина процесса, одно имя листа — ДВА листа, оба с литералами.

        **Тест наследует адрес инъекции И1** (2026-08-17), которая вскрыла, что
        соседние сторожа держались не на владении, а на fail-safe порядке сборки:
        все они брали имя ФРЕЙМВОРКА (``fps``), а его в дереве накрывал агрегат.
        Здесь этой страховки нет по построению — оба участника плагины, оба листа
        едут ОДНИМ проходом сборщика. До Ф1 победил бы порядок обхода dict'а (то
        есть порядок вызовов ``publish_metric``), после Ф1 побеждать некому: ключ
        первого уровня — писатель.

        Порядок публикаций намеренно ОБРАТНЫЙ алфавитному: совпади он с порядком
        вставки, тест был бы зелен и у механизма, который просто берёт последнего.
        """
        services, hb = _boot(name="neighbours")
        ctx_a = PluginContext(services=services, config={}, plugin_name="plugin_a")
        ctx_a.declare_metric("shared_gauge")
        ctx_b = PluginContext(services=services, config={}, plugin_name="plugin_b")
        ctx_b.publish_metric("shared_gauge", 99.0)  # сосед публикует ПЕРВЫМ
        ctx_a.publish_metric("shared_gauge", 11.0)

        _tick_levels(hb)

        assert _level(services, "plugin_a", "shared_gauge") == pytest.approx(11.0)
        assert _level(services, "plugin_b", "shared_gauge") == pytest.approx(99.0)
        assert _polled_level(services, "plugin_a", "shared_gauge") == pytest.approx(11.0)
        assert _polled_level(services, "plugin_b", "shared_gauge") == pytest.approx(99.0)
        assert not [msg for msg in services.warnings() if "shared_gauge" in msg], services.warnings()


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
        assert _level(services, "parent_plugin", "sub_level") == pytest.approx(3.5), (
            "дороги проброшены по имени, но не делегируют в механизм родителя"
        )

    def test_sub_level_is_written_under_the_parent_plugin(self):
        """Вложенный пишет В ПОДДЕРЕВО родителя — своего сегмента пути у него нет.

        Судится ЭФФЕКТОМ, а не отсутствием исключения: прежняя редакция проверяла
        «повторное объявление тем же владельцем не конфликт», и после Ф1 такой тест
        стал бы вакуумным — конфликта нет ни у кого. Здесь адрес листа: публикация
        родителя и публикация вложенного обязаны попасть в ОДНУ ветку.
        """
        services, hb = _boot(name="sub2")
        parent = PluginContext(services=services, config={}, plugin_name="parent_plugin2")
        SubPluginContext.from_parent(parent).publish_metric("sub_owned", 1.0)
        parent.publish_metric("parent_owned", 2.0)
        _tick_levels(hb)
        assert _level(services, "parent_plugin2", "sub_owned") == 1.0
        assert _level(services, "parent_plugin2", "parent_owned") == 2.0, "ЯКОРЬ: родитель пишет туда же"


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
        assert _level(services, "text_plugin", "text_level") == "не число"

    def test_a_gate_that_holds_everything_publishes_nothing(self):
        """Гейт придержал всё — ни одного merge: не грузим дерево пустым сообщением.

        Прежде тот же ноль давало «имя не объявлено» — с Ф1 необъявленное имя едет
        легально, и прежняя посылка стала ложной (тест зеленел бы, публикуя лист).
        Причина закрытого гейта здесь не важна; важно, что ПУСТОЙ payload не шлётся.
        ЯКОРЬ рядом: тот же вход при открытом гейте даёт ровно один merge с листом.
        """
        services, hb = _boot(name="empty")
        PluginContext(services=services, config={}, plugin_name="empty_plugin").publish_metric("x", 1)

        _tick_levels(hb, allowed_metrics=set())  # гейт закрыт наглухо
        assert services._state_proxy.merges == [], services._state_proxy.merges

        _tick_levels(hb, allowed_metrics=None)  # ЯКОРЬ: механизм подключён и работает
        assert len(services._state_proxy.merges) == 1
        assert _level(services, "empty_plugin", "x") == 1


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
_GROWTH_WINDOW = 5_000


class TestConcurrency:
    def test_a_copy_survives_a_writer_growing_the_store(self):
        """Без лока ``dict(...)`` растущего словаря поднимает RuntimeError.

        Писатель здесь — отдельный поток, как в проде (воркер плагина против
        потока heartbeat), и он именно РАСТИТ словарь новыми ключами: перезапись
        существующего ключа копию не ломает, и тест на ней был бы вакуумным.

        Проверяются ОБА чтения. ``publications`` — вход сборщика тика и опроса,
        то есть тот, чей отказ погасил бы телеметрию; ``names`` — дешёвое чтение
        имён, которым тик кормит гейт ДО сборки, и у него свой обход (два уровня
        вложенности вместо одного). ``retract`` крутится тем же потоком — третий
        писатель, появившийся с Р3.5-14, ходит в то же хранилище.

        **С Ф1 гонок стало ДВЕ, и тест растит обе.** Внешний словарь растёт новыми
        ПИСАТЕЛЯМИ, внутренний — новыми ИМЕНАМИ у одного писателя. Расти только
        внутренний — и копия ``{w: dict(v) for ...}`` не ломалась бы на внешнем
        обходе; расти только внешний — не ломалась бы на внутреннем.
        """
        store = PluginLevels()
        stop = threading.Event()
        errors: list[BaseException] = []

        def writer() -> None:
            i = 0
            while not stop.is_set():
                # чётные — новое ИМЯ у одного писателя, нечётные — новый ПИСАТЕЛЬ
                store.publish(f"level_{i}", i, "writer_plugin")
                store.publish("same_leaf", i, f"writer_{i}")
                i += 1
                if i >= _GROWTH_WINDOW:
                    store.retract("writer_plugin")
                    for k in range(i):
                        store.retract(f"writer_{k}")
                    i = 0

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        try:
            for n in range(2000):
                try:
                    store.publications() if n % 2 else store.names()
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
    def test_two_writers_of_one_name_give_two_branches(self):
        """Проекция, а не отбор: одно имя у двух писателей — две ветки.

        Здесь стояли три теста отсева (``rejected``-тройки, сортировка пар,
        «чужое имя против необъявленного»). Отсева больше нет — сборщик вернулся
        к тому, чем и должен быть: чистой проекции хранилища в поддерево.
        Порядок вставки обратный алфавитному намеренно — чтобы тест краснел и у
        механизма, который просто берёт последнего.
        """
        out = build_plugin_levels({"pub_b": {"shared": 2}, "pub_a": {"shared": 1}}, None)
        assert out == {"plugins": {"pub_b": {"shared": 2}, "pub_a": {"shared": 1}}}

    def test_a_writer_whose_every_leaf_is_gated_out_leaves_no_empty_branch(self):
        """Пустая ветка — запись в дерево, которая ничего не сообщает.

        ``{"plugins": {"тихий": {}}}`` создал бы узел и дельту на КАЖДОМ тике,
        не неся ни одного показания. Якорь в том же тесте: сосед, чей лист гейт
        пропустил, ветку получает.
        """
        out = build_plugin_levels({"тихий": {"off": 1}, "громкий": {"on": 2}}, {"on"})
        assert out == {"plugins": {"громкий": {"on": 2}}}, out

    def test_nothing_survived_gives_an_empty_dict_not_an_empty_subtree(self):
        """Ноль уцелевших листьев — ПУСТО, а не ``{"plugins": {}}``.

        Иначе публикатор увидел бы непустую секцию ``state`` и послал бы merge,
        то есть «нечего слать — не шлём» перестало бы работать этажом выше.
        """
        assert build_plugin_levels({"w": {"x": 1}}, set()) == {}
        assert build_plugin_levels({}, None) == {}

    def test_the_collector_does_not_mutate_its_input(self):
        levels = {"p": {"x": 1}}
        build_plugin_levels(levels, None)
        assert levels == {"p": {"x": 1}}, "сборщик обязан быть чистым — вход тот же"

    def test_booleans_are_not_rounded_into_numbers(self):
        """``round(True, 1)`` вернул бы 1 — фронт, просочившийся в уровни, обязан
        остаться распознаваемым как фронт, а не превратиться в число."""
        out = build_plugin_levels({"bool_plugin": {"bool_level": True}}, None)
        assert out["plugins"]["bool_plugin"]["bool_level"] is True


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
                pushed = services._state_proxy.get("processes.wire.state.plugins.wire_plugin.wired_level")
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
        assert data["state"]["plugins"]["one_plugin"]["one_level"] == 4.0
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
        assert data["state"]["plugins"]["nw_plugin"]["nw_level"] == 6.0
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
        assert data["state"]["plugins"]["zero_plugin"]["zero_level"] == 1.0

    def test_nothing_at_all_sends_zero_merges(self):
        """ЛОВУШКА 3: данных нет вовсе → НОЛЬ вызовов merge, а не пустой merge."""
        services = _Services(name="void")
        services.worker_manager.get_all_workers_status = lambda: {}  # type: ignore[attr-defined]
        services.router_manager = None
        hb = _boot_hb(services)

        hb._publish_telemetry_to_tree({}, None)

        assert services._state_proxy.merges == []

    def test_the_aggregate_and_a_same_named_level_no_longer_share_a_key(self):
        """Столкновение имён исчезло структурно — сторожится ОБОИМИ листьями.

        Здесь стоял тест fail-safe порядка наложения («агрегат фреймворка ложится
        ПОВЕРХ уровня плагина»). Ревью З1 честно измерило эту страховку: она
        покрывала **1 случай из 5** — только ``fps``/``latency_ms`` и только когда
        агрегат есть на том же тике. Единственным настоящим предохранителем была
        проверка владельца в сборщике; Ф1 убрала её вместе с поводом, потому что
        ключа для спора больше нет: уровень плагина живёт в
        ``state.plugins.<писатель>.<имя>``, агрегат — в ``state.<имя>``.

        Прежний тест подменял шов сбора (``hb._collect_plugin_levels = ...``),
        то есть проверял вторую линию на выдуманной протечке. Здесь протечку
        выдумывать не нужно: боевой путь публикует ОБА листа, и оба проверяются
        литералами.
        """
        services = self._services_with_worker("order")
        hb = _boot_hb(services)
        PluginContext(services=services, config={}, plugin_name="order_plugin").publish_metric("fps", 999.0)

        hb._publish_telemetry_to_tree(services.worker_manager.get_all_workers_status(), None)

        _path, data = services._state_proxy.merges[0]
        assert data["state"]["fps"] == 8.0, f"агрегат фреймворка подменён уровнем плагина: {data['state']}"
        assert data["state"]["plugins"]["order_plugin"]["fps"] == 999.0, (
            f"уровень плагина потерян — поддерево писателя не отделило его от агрегата: {data['state']}"
        )


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
        assert store.publications() == {"dying_plugin": {"dying_level": 5.0}}

        plugin._do_shutdown(ctx)

        assert store.publications() == {}, (
            f"уровень пережил остановку плагина: {store.publications()} "
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
        assert store.publications() == {"pair_b": {"pair_level_b": 2.0}}, "снятие писателя задело соседнее поддерево"

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
        assert _level(services, "redeclare_plugin", "survivor_level") == 4.0


# --------------------------------------------------------------------------- #
# Владелец считается в ОДНОМ месте — судится эффектом на боевой тройке.
# --------------------------------------------------------------------------- #
class TestWriterIsComputedOnce:
    def test_publish_and_retract_agree_on_the_writer(self):
        """Три дороги, один писатель. Разойдись публикация со снятием — уровень
        уехал бы в одно поддерево, а чистилось бы другое, и лист остановленного
        плагина жил бы вечно. Судится эффектом: уехало под ИМЕНЕМ писателя →
        сняли → в опросе поддерева нет."""
        services, hb = _boot(name="triple")
        ctx = PluginContext(services=services, config={}, plugin_name="triple_plugin")
        ctx.declare_metric("triple_level")
        ctx.publish_metric("triple_level", 7.0)

        _tick_levels(hb)
        assert _level(services, "triple_plugin", "triple_level") == 7.0, (
            "публикация уехала не под именем писателя — объявление и публикация разошлись"
        )

        assert ctx._retract_metrics() == 1, "снятие разошлось с публикацией в имени писателя"
        assert _polled_level(services, "triple_plugin", "triple_level") is None

    def test_a_context_without_a_plugin_name_writes_under_the_process_on_all_three(self):
        """Тот же треугольник для базового ctx (писатель — имя процесса)."""
        services, hb = _boot(name="proc_owner")
        ctx = PluginContext(services=services, config={})
        ctx.declare_metric("proc_owned_level")
        ctx.publish_metric("proc_owned_level", 2.0)

        _tick_levels(hb)
        assert _level(services, "proc_owner", "proc_owned_level") == 2.0
        assert ctx._retract_metrics() == 1


# --------------------------------------------------------------------------- #
# Ключ-пара, поимённое снятие и голос про самозванца — механизмы удалены Ф1.
#
# Здесь стояли ДЕВЯТЬ тестов: «перехватчик не стирает ячейку владельца» (ключ-пара),
# «снятый уровень уходит из дерева» (``None``-надгробия с запасом переутверждений) и
# «голос отсева имеет потолок». Все три механизма срезаны §9 плана (блок Ф1): спорить
# за имя нельзя синтаксически, отсеивать нечего, а поимённое надгробие во вложенной
# форме легло бы на плоский путь при живом писателе. Снятие ПОДДЕРЕВА и его сторожа
# приносит Ф2 — Ф1 и Ф2 поставляются одной парой (§11.7).
# --------------------------------------------------------------------------- #


class _BoomPlugin(ProcessModulePlugin):
    """Плагин, чей ``shutdown`` бросает. Не гипотеза: «камера не отпустила устройство»."""

    category = "utility"

    def configure(self, ctx: PluginContext) -> None:
        ctx.declare_metric("boom_level")
        ctx.publish_metric("boom_level", 7.7)

    def shutdown(self, ctx: PluginContext) -> None:
        raise RuntimeError("камера не отпустила устройство")


class TestShutdownFailureStillRetracts:
    """Н2: отказная дорога остановки.

    Прежняя редакция ставила снятие ПОСЛЕ незавёрнутого ``self.shutdown(ctx)``,
    и бросок оставлял уровни навсегда: ``STOPPED`` не наступал, оркестратор
    бросок логировал и шёл дальше, тики публиковали мёртвое значение. То есть
    симптом «камера остановлена, а частота идёт» воскресал ровно там, где
    диагностика нужнее всего.
    """

    def test_levels_are_retracted_even_when_shutdown_raises(self):
        services, hb = _boot(name="boom")
        ctx = PluginContext(services=services, config={}, plugin_name="boom_plugin")
        plugin = _BoomPlugin()
        plugin.name = "boom_plugin"
        plugin._do_configure(ctx)
        _tick_levels(hb)
        assert _level(services, "boom_plugin", "boom_level") == pytest.approx(7.7), "предпосылка"

        with pytest.raises(RuntimeError, match="камера не отпустила"):
            plugin._do_shutdown(ctx)

        # Бросок ушёл наружу как раньше — состояние НЕ STOPPED.
        assert plugin.state != PluginState.STOPPED
        # ...но уровни сняты из ХРАНИЛИЩА, и следующий тик их уже не публикует.
        assert getattr(services, PLUGIN_LEVELS_ATTR).publications() == {}, (
            "уровень пережил отказавший shutdown — снятие стоит вне finally"
        )
        before = len(services._state_proxy.merges)
        _tick_levels(hb)
        assert len(services._state_proxy.merges) == before, "тик после снятия всё ещё публикует уровни ушедшего плагина"
        # И ЛИСТ УХОДИТ ИЗ ДЕРЕВА — с Ф2 отказная дорога остановки доводится до
        # конца, а не до половины. До Ф2 здесь стояло обратное утверждение («лист
        # остаётся — известная цена неделимой поставки Ф1+Ф2»), и оно было верным
        # ровно до появления ``state.delete``: снятие ПОДДЕРЕВА писателя ставит
        # тик, а тик после отказавшего ``shutdown`` идёт как обычно — плагин не
        # STOPPED, но писателя в порту уже нет и его ведомость взведена.
        assert _writer_subtree(services, "boom_plugin") is None, (
            f"поддерево писателя пережило отказавший shutdown и тик Ф2 — снятие держится "
            f"на успешном пути остановки. Дерево: {services._state_proxy.tree}"
        )


class TestDottedLevelNameIsRefused:
    """Н3: точка в имени уровня — отказ, а не резидуал.

    Объединение трёх merge в один сделало достижимыми ОБЕ ветки резолва точки
    (литеральный ключ на первом тике, вложенный путь со второго), и в дереве
    оставался вечно-мёртвый лист-двойник без голоса. Двойника добавила эта
    задача — она его и закрывает.
    """

    def test_declare_refuses_a_dotted_name_and_says_why(self):
        services, _hb = _boot(name="dotted")
        ctx = PluginContext(services=services, config={}, plugin_name="dotted_plugin")
        with pytest.raises(ValueError) as exc:
            ctx.declare_metric("a.b.c")
        text = str(exc.value)
        assert "a.b.c" in text and "точку" in text, text
        assert "a_b_c" in text, f"отказ не предложил годного имени: {text}"

    def test_a_dotted_name_never_reaches_the_tree(self):
        """Отказа на ОБЪЯВЛЕНИИ больше не достаточно — guard стоит и на публикации.

        **Дыру открыл шаг 5 самой Ф1, и она воспроизведена, а не предположена.**
        Прежний довод звучал так: «второй guard не нужен — публикация в
        необъявленное имя уже отвергается по владению». Ф1 сняла и владение, и
        требование объявления: необъявленное имя стало ехать легально, а вместе с
        ним поехало бы и точечное. Прогон на дубле ``TreeStore._merge_recursive``
        (тот же резолв, что у настоящего стора) дал ровно тот лист-двойник, ради
        которого точка запрещена::

            тик 1: {'plugins': {'dotter': {'a.b.c': 1.0}}}
            тик 2: {'plugins': {'dotter': {'a.b.c': 1.0, 'a': {'b': {'c': 2.0}}}}}
                                            ^^^^^^^^^^^^ заморожен навсегда

        Поэтому ``publish_metric`` отвергает точку сам — голосом, а не исключением
        (уровень не имеет права ронять линию), один раз на имя.

        ЯКОРЬ в том же тесте: соседнее имя БЕЗ точки от того же плагина едет.
        Без него тест зелен и у механизма, который не публикует вовсе.
        """
        services, hb = _boot(name="dotted2")
        ctx = PluginContext(services=services, config={}, plugin_name="dotted_plugin2")
        ctx.publish_metric("x.y", 1.0)  # объявить нельзя, публикуем всё равно
        ctx.publish_metric("x.y", 2.0)  # второй тик — та ветка, что рождала двойника
        ctx.publish_metric("plain", 3.0)

        _tick_levels(hb)

        assert _level(services, "dotted_plugin2", "x.y") is None
        assert services._state_proxy.get("processes.dotted2.state.plugins.dotted_plugin2.x") is None
        assert _level(services, "dotted_plugin2", "plain") == 3.0, "ЯКОРЬ: годное имя того же плагина едет"
        said = [msg for msg in services.warnings() if "x.y" in msg]
        assert len(said) == 1, f"ожидали ОДИН голос на имя, получили {len(said)}: {said}"

    def test_stats_plane_keeps_dotted_names(self):
        """Ограничение — только у уровней: в stats имя путём дерева не становится."""
        services, _hb = _boot(name="dotted3")
        ctx = PluginContext(services=services, config={}, plugin_name="dotted_plugin3")
        ctx.gauge("capture.fps", 12.5)  # не бросает — плоскость другая


# --------------------------------------------------------------------------- #
# З3 — форма merge, которую реально шлёт тик, а не удобная для теста.
#
# Приёмочный П10 мержит прямо в ``processes.<p>.state`` и потому измеряет
# per-leaf дельты всегда. Тик шлёт ДРУГОЕ: ``merge("processes.<p>",
# {"state": {...}})`` — на один уровень выше. На СВЕЖЕМ поддереве это даёт одну
# ГРУБУЮ дельту, и разница видна только здесь.
# --------------------------------------------------------------------------- #
class _CapturingRouterZ3:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send_async(self, msg: dict, priority: str = "normal") -> None:
        self.sent.append(msg)

    def register_message_handler(self, key, handler, expects_full_message=True) -> None:
        pass


def _delta_paths(router: _CapturingRouterZ3, subscriber: str = "watcher") -> list[str]:
    out: list[str] = []
    for msg in router.sent:
        if msg.get("targets") == [subscriber]:
            out.extend(d["path"] for d in msg["data"]["deltas"])
    router.sent.clear()
    return sorted(out)


class TestProductionMergeShapeDeltas:
    def test_first_tick_gives_one_coarse_delta_then_per_leaf(self):
        """Первый тик на свежем поддереве — ОДНА грубая дельта, дальше per-leaf.

        Следствие названо, а не замаскировано: путь ``processes.<p>.state`` имеет
        ТРИ части, а сток телеметрии берёт только ``len(parts) >= 4``
        (``Plugins/io/telemetry_sink/plugin.py``), поэтому первый тик после старта
        процесса он пропускает целиком. До объединения merge это касалось
        ``fps``/``latency_ms`` (они и раньше ехали под ``processes.<p>``), а
        группа ``shm`` мержилась ГЛУБЖЕ (``…state.shm``) и была per-leaf с первого
        тика — теперь она едет вместе с остальными. Один тик, не поток.
        """
        from multiprocess_framework.modules.state_store_module.core.delta import (
            STATE_ENVELOPE_MARKER,
        )
        from multiprocess_framework.modules.state_store_module.manager.state_store_manager import (
            StateStoreManager,
        )

        router = _CapturingRouterZ3()
        mgr = StateStoreManager(router=router)
        mgr.initialize()
        try:
            mgr.subscription_manager.subscribe("processes.P.**", "watcher")

            def _tick(payload: dict) -> list[str]:
                mgr.handle_state_merge(
                    {
                        "path": "processes.P",
                        "data": {"state": payload},
                        "source": "hb",
                        STATE_ENVELOPE_MARKER: True,
                    }
                )
                mgr.dispatcher._flush_once()
                return _delta_paths(router)

            first = _tick({"fps": 8.1, "capture_fps": 12.5})
            second = _tick({"fps": 9.1, "capture_fps": 13.5})
        finally:
            mgr.shutdown()

        assert first == ["processes.P.state"], (
            f"первый тик дал не одну грубую дельту, а {first} — следствие в ADR описано неверно"
        )
        assert second == ["processes.P.state.capture_fps", "processes.P.state.fps"], second
        # Именно тот предикат, по которому сток отбирает записи.
        assert len(first[0].split(".")) == 3, first
        assert all(len(p.split(".")) >= 4 for p in second), second
