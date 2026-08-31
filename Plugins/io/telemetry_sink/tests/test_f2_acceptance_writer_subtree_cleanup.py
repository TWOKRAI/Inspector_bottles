# -*- coding: utf-8 -*-
"""Независимая приёмка Ф2, критерий С5 — сток чистит строки БД по уходу писателя.

Дословно из задания: «сток: ключи ушедшего писателя исчезают из строк БД за
≤1 семпл. Якорь: ДО стопа те же ключи в строках с литералами. Пара-контроль:
ключи соседа-писателя в тех же строках живы».

Свободный бриф без формального заголовка MODE/INTERFACE — с поимённым списком
запрещённых путей и явной красно/зелёной рамкой (эквивалент MODE: red по
проектной памяти). Писался ДО реализации Ф2, обязан быть КРАСНЫМ на текущем
HEAD (48d4ed09, ветка feat/observation-port).

ЗАПРЕЩЕНО: ``plans/`` целиком, любые файлы с ``telemetry_stage6``/
``observation-port`` в имени. Разрешено и изучено: ``Plugins/io/telemetry_sink/
plugin.py`` (+ существующий ``tests/test_telemetry_sink_plugin.py``, откуда
взяты вспомогательные фабрики ``make_ctx``/``make_sql``/``make_plugin`` —
идентичный, не выдуманный харнесс), ``state_store_module/core/tree_store.py``
(``TreeStore.merge``/``TreeStore.delete``), ``state_store_module/manager/
state_store_manager.py`` (``handle_state_delete``).

## Форма Delta, которую реально порождает уход писателя (изучено по коду)

Ф2 удаляет поддерево писателя ЦЕЛИКОМ, ОДНИМ вызовом ``state.delete`` на путь
``processes.<P>.state.plugins.<writer>`` (дословно из задания и из
``heartbeat/telemetry.py``: «Замена — удаление ПОДДЕРЕВА писателя дорогой
``state.delete``»). ``TreeStore.delete`` (``core/tree_store.py:323``) снимает
РОВНО один узел по ЭТОМУ ПУТИ и возвращает ОДНУ ``Delta`` (``old_value`` — весь
снятый поддерево-dict, ``new_value=MISSING``) — НЕ по одной дельте на лист.
``StateStoreManager.handle_state_delete`` (``manager/state_store_manager.py:308``)
рассылает эту ОДНУ дельту дальше (``dispatcher.dispatch_single(delta)``) — тоже
без разворота в поштучные дельты листьев.

Плагин же кэширует ЛИСТЬЯ (``TelemetrySinkPlugin._on_deltas``: ``self._cache[d.path]
= d.new_value`` — по одной записи на каждый MERGE-лист, например
``processes.camera_0.state.plugins.capture.fps``), а снятие делает
``self._cache.pop(d.path, None)`` — ТОЧНОЕ совпадение пути. Путь delete-дельты —
путь ПОДДЕРЕВА (``processes.camera_0.state.plugins.capture``), а не путь листа
(``...capture.fps``) — точного совпадения с кэшем НЕТ, ``pop`` — молчаливый
no-op, и лист остаётся в кэше НАВСЕГДА (каждый следующий семпл пишет его снова).

Это ТЕКУЩИЙ, наблюдаемый на этом коммите механизм — не гипотеза о будущем Ф2.
Тест ниже кормит плагину РОВНО такую дельту (путь поддерева, не листа) и
проверяет, что она переживает семпл — что и есть красный критерий С5.

Отдельная находка (не критерий С5, но relevant): у client-side ``StateProxy``
(``state_store_module/proxy/state_proxy.py``) на этом коммите вообще НЕТ
метода ``delete`` (только ``set``/``merge``/``get``/``get_subtree``) — Ф2
обязана будет как минимум завести способ ПОСЛАТЬ ``state.delete`` с
process-стороны, прежде чем что-либо из этого файла сможет стать зелёным
по-настоящему (не только починкой ``_on_deltas``).
"""

from __future__ import annotations

import json

import pytest

from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta

from .test_telemetry_sink_plugin import make_plugin


def _subtree_delete_delta(path: str, old_subtree: dict) -> Delta:
    """Дельта, которую реально порождает ``TreeStore.delete`` на ПОДДЕРЕВЕ
    писателя — путь поддерева (не листа), ``new_value=MISSING`` (форма
    ``core/delta.py:Delta.is_delete`` — ``new_value is MISSING``)."""
    return Delta(path=path, old_value=dict(old_subtree), new_value=MISSING, source="heartbeat")


def _extra_of(plugin, process_name: str) -> dict:
    row = plugin._sql.query(
        f"SELECT * FROM telemetry_snapshots WHERE process_name='{process_name}' ORDER BY id DESC LIMIT 1"
    )[0]
    return json.loads(row["extra"]) if row["extra"] else {}


class TestC5SinkDropsStaleWriterKeysAfterSubtreeDelete:
    def test_stale_writer_keys_disappear_from_the_next_sample_row(self) -> None:
        plugin = make_plugin()

        # --- Публикация: писатель "capture" + сосед "capture2" (пара-контроль) ---
        plugin._on_deltas(
            [
                Delta(
                    path="processes.camera_0.state.plugins.capture.fps", old_value=MISSING, new_value=741.2, source="hb"
                ),
                Delta(
                    path="processes.camera_0.state.plugins.capture.frame_count",
                    old_value=MISSING,
                    new_value=5,
                    source="hb",
                ),
                Delta(
                    path="processes.camera_0.state.plugins.capture2.fps",
                    old_value=MISSING,
                    new_value=852.3,
                    source="hb",
                ),
            ]
        )
        written_before = plugin._sample_once()
        assert written_before == 1, "одна строка на процесс camera_0 (оба писателя внутри extra)"

        extra_before = _extra_of(plugin, "camera_0")
        # Якорь: ДО стопа те же ключи в строках БД С ЛИТЕРАЛАМИ.
        assert extra_before["state.plugins.capture.fps"] == 741.2, f"предпосылка: якорь-литерал есть: {extra_before}"
        assert extra_before["state.plugins.capture.frame_count"] == 5, (
            f"предпосылка: якорь-литерал есть: {extra_before}"
        )
        assert extra_before["state.plugins.capture2.fps"] == 852.3, f"предпосылка соседа: {extra_before}"

        # --- Уход писателя "capture": РОВНО такую дельту порождает state.delete
        # поддерева (см. докстринг модуля) ---
        plugin._on_deltas(
            [_subtree_delete_delta("processes.camera_0.state.plugins.capture", {"fps": 741.2, "frame_count": 5})]
        )

        written_after = plugin._sample_once()
        assert written_after == 1, "сосед capture2 всё ещё в кэше — строка camera_0 пишется снова"
        extra_after = _extra_of(plugin, "camera_0")

        assert "state.plugins.capture.fps" not in extra_after, (
            f"ключ ушедшего писателя пережил ≤1 семпл после state.delete поддерева — "
            f"сток чистит кэш ТОЛЬКО по точному совпадению d.path (self._cache.pop(d.path, None)), "
            f"а delete поддерева даёт ОДНУ дельту с путём ПОДДЕРЕВА "
            f"('processes.camera_0.state.plugins.capture'), а не путём листа "
            f"('...capture.fps') — точного совпадения нет, pop — молчаливый no-op: {extra_after}"
        )
        assert "state.plugins.capture.frame_count" not in extra_after, (
            f"второй ключ того же ушедшего писателя тоже обязан исчезнуть: {extra_after}"
        )
        assert extra_after.get("state.plugins.capture2.fps") == 852.3, (
            f"пара-контроль: ключ СОСЕДА-писателя обязан остаться живым в тех же строках: {extra_after}"
        )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
