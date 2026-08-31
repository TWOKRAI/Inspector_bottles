# -*- coding: utf-8 -*-
"""Независимая приёмка Ф2 «удаление поддерева писателя из дерева StateStore»
(критерии С1–С4 задания; С5 — сток — отдельным файлом рядом с
``Plugins/io/telemetry_sink/tests/``).

Свободный бриф без формального заголовка MODE/INTERFACE — с поимённым списком
запрещённых путей и явной красно/зелёной рамкой (по проектной памяти это
эквивалентно MODE: red). Тесты писались ДО реализации Ф2 и обязаны быть
КРАСНЫМИ на текущем HEAD (48d4ed09, ветка feat/observation-port, ДО Ф2).

ЗАПРЕЩЕНО (не открывалось при подготовке файла): ``plans/`` целиком, и любые
файлы с ``telemetry_stage6``/``observation-port`` в имени. Разрешено и
изучено: ``heartbeat/process_heartbeat.py``, ``heartbeat/telemetry.py``,
``plugins/base.py``, ``state_store_module`` (``core/tree_store.py``,
``manager/state_store_manager.py``, ``proxy/state_proxy.py``) — код механизма,
а не план.

Источник контракта — ПЯТЬ критериев из задания, дословно:
  С1 — стоп писателя убирает его поддерево за ≤K тиков, с якорем существования
       (литерал ДО стопа).
  С2 — сосед не задет: обычный сосед и сосед с ОБЩИМ ТЕКСТОВЫМ ПРЕФИКСОМ имени
       (``capture``/``capture2``) — граница режется по точке, не по подстроке.
  С3 — переподнятый писатель: отложенное удаление его не догоняет, ≥2 тика
       после возврата, лист жив на КАЖДОМ.
  С4 — то же самое на poll-дороге (``ProcessHeartbeat.current_levels_snapshot`` /
       команда ``introspect.telemetry`` → секция ``levels`` — второй сборщик
       телеметрии, ADR-PM-035 «push и poll — один сборщик»).

Путь поддерева писателя — дословно из задания:
``processes.<процесс>.state.plugins.<плагин>.<метрика>``.

## Как устроен механизм на ЭТОМ коммите (изучено по коду, не по плану)

``PluginLevels.retract(writer)`` (``heartbeat/telemetry.py``) уже существует и
уже вызывается фреймворком из ``ProcessModulePlugin._do_shutdown`` (через
``PluginContext._retract_metrics()``, ``plugins/base.py``) ПОСЛЕ пользовательского
``shutdown``. Он полностью и НЕМЕДЛЕННО убирает писателя из ХРАНИЛИЩА
(``self._values.pop(writer)``) — это уже реализовано (Ф1, Task 1.2) и НЕ
предмет этого файла.

Но ``retract()`` НЕ трогает дерево StateStore. ``_publish_telemetry_to_tree``
шлёт только ``proxy.merge(...)`` — merge умеет добавлять/перезаписывать листья,
но никогда не удаляет узлы. Поэтому лист, once попавший в дерево тиком push'а
ДО стопа, остаётся там с последним значением НАВСЕГДА — своими словами это
подтверждают ``README.md``/``STATUS.md``/``DECISIONS.md`` модуля («между Ф1 и
Ф2 механизма снятия ИЗ ДЕРЕВА нет вовсе, осознанно») и комментарий внутри
``_publish_telemetry_to_tree`` (« (4) Снятия здесь больше НЕТ ... Замена —
удаление ПОДДЕРЕВА писателя дорогой ``state.delete`` (Ф2) »).

Отсюда — важное следствие для конструкции тестов ниже, зафиксированное ЗАРАНЕЕ
(до прогона), а не найденное постфактум:

  Свойства С1/С2 (писатель ДОЛЖЕН исчезнуть) — красные СЕЙЧАС по прямой причине:
  ничего никогда не удаляет узел дерева.

  Свойство С3 (воскресший писатель НЕ должен быть ошибочно стёрт отложенным
  удалением) само по себе тривиально ИСТИННО уже сейчас — раз ничего не
  удаляет НИКОГДА, то и воскресшего писателя точно не заденет. Проверка ТОЛЬКО
  этого была бы «зелёным тестом не о том» (правило проекта: подтверждающий
  ноль без контроля, дающего ненулевое, ничего не доказывает — используется тот
  же довод, что у памяти tester'а «unconnected driver reads as a clean zero»).
  Поэтому тест С3 ниже — ПАРНЫЙ: постоянно уходящий писатель-КОНТРОЛЬ (обязан
  исчезнуть — красный якорь) плюс писатель-феникс (обязан выжить). Так тест
  красный по настоящей причине (контроль не исчезает), а не по совпадению.

  Критерий С4 (то же на poll-дороге) я НЕ смог сделать красным — см. класс
  ``TestC4PollPathIsAlreadyGreenNotARedTest`` ниже и итоговый отчёт. Poll
  (``current_levels_snapshot``) читает ХРАНИЛИЩЕ ``PluginLevels`` НАПРЯМУЮ (не
  дерево, не merge), и ``retract()`` уже полностью решает эту дорогу — Ф2 её
  вообще не касается. Тест оставлен как регрессионный контроль (сейчас
  ЗЕЛЁНЫЙ), а не как приёмочный критерий Ф2.

## О «K тиков»

Литеральное значение K нигде не объявлено на этом коммите (механизм
отсутствует). Ниже используется заведомо щедрая, но КОНЕЧНАЯ верхняя граница
``_MANY_TICKS = 30`` как временная замена «K»: истинное К неизвестно, но при
ЛЮБОМ конечном К меньше 30 тест обязан стать зелёным после реализации Ф2, а
сейчас краснеет при любом К (узел не удаляется вообще, хоть 30 тиков, хоть
300).

## Дисциплина блокировки

Весь пуш идёт через синхронный прямой вызов
``hb._publish_telemetry_to_tree(...)`` (тот же приём, что у
``test_plugin_levels_hazards.py:_tick_levels``) — без потоков, без
``time.sleep``, без стоп-событий: зависнуть тут нечему.
"""

from __future__ import annotations

from typing import Any

import pytest

from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import (
    ProcessHeartbeat,
)
from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.testing import (
    MockProcessServices,
)

#: Щедрая, заведомо конечная замена неизвестного К (см. докстринг модуля).
_MANY_TICKS = 30


# --------------------------------------------------------------------------- #
# Дерево — та же дотированная семантика, что у настоящего TreeStore
# (``core/tree_store.py:_merge_recursive``/``delete``): merge разворачивает
# точку в путь рекурсивно, delete снимает РОВНО один сегмент-ключ (никогда не
# подстроку) — поэтому «capture» и «capture2» физически разные ветки словаря,
# граница режется структурой, а не фильтром внутри теста.
# --------------------------------------------------------------------------- #
class _Proxy:
    def __init__(self) -> None:
        self.tree: dict[str, Any] = {}
        self.merges: list[tuple[str, dict]] = []
        self.deletes: list[str] = []

    def merge(self, path: str, data: dict) -> None:
        self.merges.append((path, dict(data)))
        self._merge_recursive(path, data)

    def _merge_recursive(self, path: str, data: dict) -> None:
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

    def delete(self, path: str, source: str = "") -> bool:
        """Форма — дословно ``TreeStore.delete``: снимает РОВНО последний
        сегмент пути у его родителя (``del parent[last_key]``), никогда не
        подстроку соседнего ключа. Метод НЕ существует на настоящем
        client-side ``StateProxy`` на этом коммите (проверено —
        ``proxy/state_proxy.py`` объявляет только ``set``/``merge``/``get``/
        ``get_subtree``); добавлен здесь как форма, которую Ф2, вероятно,
        обязана будет завести, чтобы вообще было что звать. Отдельная
        находка, названа в отчёте.
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
    """Дубль сервисов — heartbeat читает ``_state_proxy`` (приватный, с
    подчёркиванием), НЕ публичный ``state_proxy`` родителя (сверено чтением
    ``_publish_telemetry_to_tree``: ``getattr(self._services, "_state_proxy",
    None)``)."""

    def __init__(self, name: str = "proc") -> None:
        super().__init__(name=name)
        self._state_proxy = _Proxy()


def _boot(name: str = "proc") -> tuple[_Services, ProcessHeartbeat]:
    services = _Services(name=name)
    hb = ProcessHeartbeat(services)
    return services, hb


def _tick(hb: ProcessHeartbeat, times: int = 1) -> None:
    """N синхронных тиков публикации телеметрии, без воркеров (см. docstring
    ``test_plugin_levels_hazards.py:_tick_levels`` — тот же приём)."""
    for _ in range(times):
        hb._publish_telemetry_to_tree({}, None)


def _writer_leaf(services: _Services, writer: str, metric: str) -> Any:
    return services._state_proxy.get(f"processes.{services.name}.state.plugins.{writer}.{metric}")


def _writer_subtree(services: _Services, writer: str) -> Any:
    return services._state_proxy.get(f"processes.{services.name}.state.plugins.{writer}")


class _LevelPlugin(ProcessModulePlugin):
    """Плагин без прикладного поведения — публикует РОВНО один литерал уровня
    на ``configure``. Метрика/значение задаются ПОСЛЕ конструктора (тот же
    приём, что ``plugin.name = ...`` у ``_ShutdownPublishingPlugin``,
    ``test_plugin_levels_hazards.py``)."""

    category = "utility"
    metric_name: str = "fps"
    metric_value: float = 0.0

    def configure(self, ctx: PluginContext) -> None:
        ctx.publish_metric(self.metric_name, self.metric_value)


def _make_plugin(writer: str, metric: str, value: float, services: _Services) -> tuple[_LevelPlugin, PluginContext]:
    plugin = _LevelPlugin()
    plugin.name = writer
    plugin.metric_name = metric
    plugin.metric_value = value
    ctx = PluginContext(services=services, config={}, plugin_name=writer)
    plugin._do_configure(ctx)
    return plugin, ctx


# =========================================================================== #
# С1 — стоп писателя убирает поддерево за ≤K тиков (якорь: литерал ДО стопа)
# =========================================================================== #
class TestC1SubtreeDisappearsAfterStop:
    def test_subtree_disappears_within_a_bounded_number_of_ticks(self) -> None:
        services, hb = _boot(name="c1proc")
        plugin, ctx = _make_plugin("capture", "fps", 741.2, services)
        _tick(hb)

        # Якорь существования — ДО стопа поддерево есть и отдаёт КОНКРЕТНЫЙ ЛИТЕРАЛ.
        assert _writer_leaf(services, "capture", "fps") == 741.2, "предпосылка: писатель опубликовал литерал"

        plugin._do_shutdown(ctx)  # PluginLevels.retract("capture") — уже работает (Ф1)
        _tick(hb, times=_MANY_TICKS)

        assert _writer_subtree(services, "capture") is None, (
            f"поддерево остановленного писателя пережило {_MANY_TICKS} тиков публикации — "
            f"узел дерева не удаляется НИКОГДА на этом коммите: retract() снимает писателя "
            f"только из хранилища PluginLevels (Ф1), а merge никогда не удаляет узлы дерева; "
            f"механизма state.delete для поддерева писателя нет (Ф2). "
            f"Дерево сейчас: {services._state_proxy.tree}"
        )


# =========================================================================== #
# С2 — сосед не задет: обычный сосед И сосед с общим текстовым префиксом
# =========================================================================== #
class TestC2NeighboursSurviveTheRetraction:
    def test_unrelated_neighbour_survives(self) -> None:
        services, hb = _boot(name="c2proc")
        dying, dying_ctx = _make_plugin("capture", "fps", 741.2, services)
        neighbour, _neighbour_ctx = _make_plugin("sensor_reader", "temperature_c", 36.6, services)
        _tick(hb)
        assert _writer_leaf(services, "capture", "fps") == 741.2, "предпосылка"
        assert _writer_leaf(services, "sensor_reader", "temperature_c") == 36.6, "предпосылка соседа"

        dying._do_shutdown(dying_ctx)
        _tick(hb, times=_MANY_TICKS)

        assert _writer_subtree(services, "capture") is None, (
            f"поддерево остановленного писателя пережило {_MANY_TICKS} тиков (см. С1) — "
            f"без этого пара про соседа проверяет только зелёный шум"
        )
        assert _writer_leaf(services, "sensor_reader", "temperature_c") == 36.6, (
            "снятие ЧУЖОГО писателя задело несвязанного соседа"
        )

    def test_neighbour_with_a_shared_text_prefix_survives(self) -> None:
        """capture / capture2 — общий ТЕКСТОВЫЙ префикс имени. Граница обязана
        резаться по СЕГМЕНТУ пути (точка), а не по подстроке символов: снятие
        ``processes.<p>.state.plugins.capture`` не имеет права зацепить
        СОСЕДНИЙ КЛЮЧ ``capture2`` того же родительского dict'а."""
        services, hb = _boot(name="c2bproc")
        dying, dying_ctx = _make_plugin("capture", "fps", 741.2, services)
        prefixed, _prefixed_ctx = _make_plugin("capture2", "fps", 852.3, services)
        _tick(hb)
        assert _writer_leaf(services, "capture", "fps") == 741.2, "предпосылка"
        assert _writer_leaf(services, "capture2", "fps") == 852.3, "предпосылка соседа-префикса"

        dying._do_shutdown(dying_ctx)
        _tick(hb, times=_MANY_TICKS)

        assert _writer_subtree(services, "capture") is None, (
            f"поддерево остановленного писателя пережило {_MANY_TICKS} тиков (см. С1)"
        )
        assert _writer_leaf(services, "capture2", "fps") == 852.3, (
            "снятие 'capture' задело 'capture2' — граница резалась ПОДСТРОКОЙ имени, а не сегментом пути"
        )


# =========================================================================== #
# С3 — переподнятый писатель: отложенное удаление его не догоняет, ≥2 тика
# после возврата, лист жив на КАЖДОМ. ПАРНЫЙ тест — см. докстринг модуля про
# «подтверждающий ноль без контроля не доказывает».
# =========================================================================== #
class TestC3ResurrectedWriterOutrunsTheDeferredDeletion:
    def test_resurrected_writer_stays_live_across_multiple_ticks_while_a_dead_control_is_actually_removed(
        self,
    ) -> None:
        services, hb = _boot(name="c3proc")

        # Контроль: уходит НАВСЕГДА, обязан реально исчезнуть (см. С1) — без
        # него пара про феникса судила бы «ничего не удаляется вообще», а не
        # «отложенное удаление не догоняет воскресшего».
        control, control_ctx = _make_plugin("dead_control", "fps", 100.1, services)
        # Феникс: публикует, уходит, ПОДНИМАЕТСЯ ЗАНОВО другим значением —
        # штатный сценарий (плагин поднят заново после остановки рецептом).
        phoenix, phoenix_ctx = _make_plugin("phoenix", "fps", 200.2, services)
        _tick(hb)
        assert _writer_leaf(services, "dead_control", "fps") == 100.1, "предпосылка контроля"
        assert _writer_leaf(services, "phoenix", "fps") == 200.2, "предпосылка феникса"

        control._do_shutdown(control_ctx)
        phoenix._do_shutdown(phoenix_ctx)
        # Феникс публикует СНОВА до истечения любого разумного К — новый ctx,
        # как при настоящем перезапуске плагина рецептом.
        phoenix_ctx2 = PluginContext(services=services, config={}, plugin_name="phoenix")
        phoenix_ctx2.publish_metric("fps", 303.3)

        for i in range(1, 6):  # ≥2 тика после возврата — здесь пять, каждый проверяется
            _tick(hb)
            assert _writer_leaf(services, "phoenix", "fps") == 303.3, (
                f"тик {i} после возврата: воскресший писатель потерял лист — "
                f"отложенное удаление догнало резидентный путь"
            )

        assert _writer_subtree(services, "dead_control") is None, (
            f"писатель-КОНТРОЛЬ (ушедший навсегда, без возврата) не исчез за 5 тиков — "
            f"без этого пара про феникса проверяет только то, что ничего не удаляется НИКОГДА "
            f"(см. С1), а не то, что отложенное удаление избирательно щадит воскресшего. "
            f"Дерево сейчас: {services._state_proxy.tree}"
        )


# =========================================================================== #
# С4 — то же самое на poll-дороге. НЕ ПОКРЫТО как красный тест — см. отчёт.
# =========================================================================== #
class TestC4PollPathIsAlreadyGreenNotARedTest:
    """poll = :meth:`ProcessHeartbeat.current_levels_snapshot` — второй
    сборщик телеметрии (ADR-PM-035 «push и poll — один сборщик», буквально
    процитировано ``heartbeat/telemetry.py``/``heartbeat/process_heartbeat.py``:
    «Тот же сборщик обслуживает push (тик heartbeat) и poll
    (``current_levels_snapshot``)»; команда ``introspect.telemetry`` —
    тонкая IPC-обёртка над тем же методом, см.
    ``commands/builtin_commands.py:_cmd_introspect_telemetry`` докстринг,
    секция ``levels``).

    **Почему это НЕ приёмочный тест Ф2, а контроль.** ``current_levels_snapshot``
    читает ХРАНИЛИЩЕ ``PluginLevels`` НАПРЯМУЮ на каждый вызов (не дерево, не
    результат прошлого merge) — а ``retract()``/повторный ``publish()`` уже
    полностью и немедленно корректны (Ф1, подтверждено существующим
    ``test_plugin_levels_hazards.py::TestPushAndPollShareTheStore`` и
    ``TestWriterBranchIsThreadSafe::test_publish_after_retract_recreates_the_branch``
    — оба на этом же коммите, ОБА зелёные). Ф2 (``state.delete`` дерева,
    K-тиковое подтверждение) poll вообще не касается: снимок не идёт через
    merge и не может унаследовать его дефект. Дословный сценарий С4
    («ушедший навсегда — пропал, воскресший — жив на каждом из нескольких
    опросов») уже ИСТИНЕН на этом коммите — тест ниже ЗЕЛЁНЫЙ и остаётся
    зелёным ПОСЛЕ Ф2 (регрессионный контроль, а не приёмка новой работы).
    Форсировать красноту здесь значило бы либо проверить не то, либо
    подождать бага, которого Ф2 не вносит по своему заявленному объёму.
    """

    def test_dead_control_gone_and_resurrected_writer_live_on_every_poll(self) -> None:
        services, hb = _boot(name="c4proc")
        control, control_ctx = _make_plugin("dead_control", "fps", 111.9, services)
        phoenix, phoenix_ctx = _make_plugin("phoenix", "fps", 222.8, services)

        snap0 = hb.current_levels_snapshot() or {}
        assert snap0["state"]["plugins"]["dead_control"]["fps"] == 111.9, "предпосылка контроля (poll)"
        assert snap0["state"]["plugins"]["phoenix"]["fps"] == 222.8, "предпосылка феникса (poll)"

        control._do_shutdown(control_ctx)
        phoenix._do_shutdown(phoenix_ctx)
        phoenix_ctx2 = PluginContext(services=services, config={}, plugin_name="phoenix")
        phoenix_ctx2.publish_metric("fps", 333.7)

        for _ in range(3):
            snap = hb.current_levels_snapshot() or {}
            plugins = (snap.get("state") or {}).get("plugins") or {}
            assert "dead_control" not in plugins, f"poll обязан не показывать ушедшего писателя: {plugins}"
            assert plugins.get("phoenix", {}).get("fps") == 333.7, f"poll обязан показывать живого феникса: {plugins}"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
