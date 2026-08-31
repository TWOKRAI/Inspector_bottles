# -*- coding: utf-8 -*-
"""Task 2.3 (Ф2) — префикс-чистка накопителя стока: авторские hazard-тесты.

Слепая приёмка критерия С5 живёт в ``test_f2_acceptance_writer_subtree_cleanup.py``
и написана независимым тестером до реализации. Здесь — опасности самого
механизма ``_cache_evict``, которые видно автору правки: граница префикса,
идемпотентность, порядок внутри одного пакета дельт, и — отдельно — что
ТОЧЕЧНОЕ снятие одного листа не принесено в жертву поддеревной чистке.

Фабрики (``make_plugin``) и ``_extra_of`` переиспользуются из соседних файлов —
второй копии харнесса не заводим.
"""

from __future__ import annotations

import json

from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta

from .test_telemetry_sink_plugin import make_plugin

ПРОЦЕСС = "camera_0"
КОРЕНЬ = f"processes.{ПРОЦЕСС}.state.plugins.capture"
СОСЕД = f"processes.{ПРОЦЕСС}.state.plugins.capture2"


def _extra_of(plugin, process_name: str = ПРОЦЕСС) -> dict:
    """Ключи ``_extra`` последней записанной строки процесса."""
    row = plugin._sql.query(
        f"SELECT * FROM telemetry_snapshots WHERE process_name='{process_name}' ORDER BY id DESC LIMIT 1"
    )[0]
    return json.loads(row["extra"]) if row["extra"] else {}


def _лист(path: str, value) -> Delta:
    return Delta(path=path, old_value=MISSING, new_value=value, source="heartbeat")


def _удаление(path: str, old_subtree: dict) -> Delta:
    """Дельта, которую порождает ``TreeStore.delete`` на ПОДДЕРЕВЕ: путь корня."""
    return Delta(path=path, old_value=dict(old_subtree), new_value=MISSING, source="heartbeat")


def _плагин_с_двумя_писателями():
    """Плагин, у которого в накопителе лежат листья двух писателей."""
    plugin = make_plugin()
    plugin._on_deltas(
        [
            _лист(КОРЕНЬ + ".fps", 741.2),
            _лист(КОРЕНЬ + ".frame_count", 5),
            _лист(СОСЕД + ".fps", 852.3),
        ]
    )
    return plugin


class TestPrefixBoundary:
    """Граница чистки — точка-разделитель, а не подстрока."""

    def test_neighbour_with_a_shared_text_prefix_survives(self):
        """``capture2`` начинается с ``capture``, но это ДРУГОЙ сегмент пути."""
        plugin = _плагин_с_двумя_писателями()

        # Якорь существования: до ухода оба писателя в строке С ЛИТЕРАЛАМИ.
        plugin._sample_once()
        до = _extra_of(plugin)
        assert до["state.plugins.capture.fps"] == 741.2, до
        assert до["state.plugins.capture2.fps"] == 852.3, до

        plugin._on_deltas([_удаление(КОРЕНЬ, {"fps": 741.2, "frame_count": 5})])
        plugin._sample_once()
        после = _extra_of(plugin)

        assert "state.plugins.capture.fps" not in после, после
        assert "state.plugins.capture.frame_count" not in после, после
        # Пара-контроль: сосед жив и с тем же литералом.
        assert после["state.plugins.capture2.fps"] == 852.3, после

    def test_evict_does_not_touch_other_processes(self):
        """Уход писателя в одном процессе не трогает одноимённого в другом."""
        plugin = make_plugin()
        чужой = "processes.camera_1.state.plugins.capture"
        # Фреймворковые листья держат ОБА процесса живыми: строка процесса
        # собирается из кэша, и без единого ключа она просто не пишется —
        # тогда «ключ исчез» стало бы неотличимо от «строки больше нет».
        plugin._on_deltas(
            [
                _лист(f"processes.{ПРОЦЕСС}.state.fps", 21.3),
                _лист("processes.camera_1.state.fps", 22.4),
                _лист(КОРЕНЬ + ".fps", 741.2),
                _лист(чужой + ".fps", 333.1),
            ]
        )

        plugin._sample_once()
        assert _extra_of(plugin, "camera_0")["state.plugins.capture.fps"] == 741.2
        assert _extra_of(plugin, "camera_1")["state.plugins.capture.fps"] == 333.1

        plugin._on_deltas([_удаление(КОРЕНЬ, {"fps": 741.2})])
        plugin._sample_once()

        assert "state.plugins.capture.fps" not in _extra_of(plugin, "camera_0")
        assert _extra_of(plugin, "camera_1")["state.plugins.capture.fps"] == 333.1


class TestEvictHazards:
    """Опасности самого вызова: повторы, пустота, порядок."""

    def test_exact_leaf_delete_still_works(self):
        """Точечное снятие одного листа не принесено в жертву поддеревной чистке."""
        plugin = _плагин_с_двумя_писателями()
        plugin._sample_once()
        assert _extra_of(plugin)["state.plugins.capture.fps"] == 741.2

        plugin._on_deltas([Delta(path=КОРЕНЬ + ".fps", old_value=741.2, new_value=MISSING, source="hb")])
        plugin._sample_once()
        после = _extra_of(plugin)

        assert "state.plugins.capture.fps" not in после, после
        # Соседний лист ТОГО ЖЕ писателя не задет — снимали один лист, не поддерево.
        assert после["state.plugins.capture.frame_count"] == 5, после

    def test_root_delete_before_any_leaf_is_harmless(self):
        """Дельта корня пришла раньше, чем у писателя появились ключи."""
        plugin = _плагин_с_двумя_писателями()

        plugin._on_deltas([_удаление("processes.camera_0.state.plugins.ещё_не_публиковал", {})])
        plugin._sample_once()
        после = _extra_of(plugin)

        assert после["state.plugins.capture.fps"] == 741.2, после
        assert после["state.plugins.capture2.fps"] == 852.3, после

    def test_two_root_deletes_in_a_row_are_idempotent(self):
        """Повтор удаления по уже вычищенному корню — не ошибка и не побочный эффект."""
        plugin = _плагин_с_двумя_писателями()

        plugin._on_deltas([_удаление(КОРЕНЬ, {"fps": 741.2})])
        plugin._on_deltas([_удаление(КОРЕНЬ, {})])
        plugin._sample_once()
        после = _extra_of(plugin)

        assert "state.plugins.capture.fps" not in после, после
        assert после["state.plugins.capture2.fps"] == 852.3, после

    def test_order_inside_one_batch_last_delta_wins(self):
        """Гонка в одном пакете: фиксирую ФАКТИЧЕСКИЙ порядок, а не желаемый.

        Дельты применяются последовательно, поэтому побеждает последняя. Тест
        держит это поведение: если кто-то начнёт сортировать пакет или выносить
        удаления вперёд — сломается здесь, а не на живом стенде.
        """
        plugin = make_plugin()
        # Фреймворковый лист держит строку процесса живой (см. соседний тест).
        plugin._on_deltas([_лист(f"processes.{ПРОЦЕСС}.state.fps", 21.3)])

        # Удаление, следом свежая публикация того же писателя — публикация выживает.
        plugin._on_deltas([_удаление(КОРЕНЬ, {"fps": 1.0}), _лист(КОРЕНЬ + ".fps", 99.9)])
        plugin._sample_once()
        assert _extra_of(plugin)["state.plugins.capture.fps"] == 99.9

        # Обратный порядок — удаление последнее, ключ уходит.
        plugin._on_deltas([_лист(КОРЕНЬ + ".fps", 77.7), _удаление(КОРЕНЬ, {"fps": 77.7})])
        plugin._sample_once()
        assert "state.plugins.capture.fps" not in _extra_of(plugin)

    def test_framework_columns_are_not_collateral_damage(self):
        """Уход плагинного писателя не трогает колонки фреймворка (fps/latency)."""
        plugin = make_plugin()
        plugin._on_deltas(
            [
                _лист(f"processes.{ПРОЦЕСС}.state.fps", 21.3),
                _лист(КОРЕНЬ + ".fps", 741.2),
            ]
        )
        plugin._sample_once()
        assert _extra_of(plugin)["state.plugins.capture.fps"] == 741.2

        plugin._on_deltas([_удаление(КОРЕНЬ, {"fps": 741.2})])
        plugin._sample_once()

        row = plugin._sql.query(
            f"SELECT * FROM telemetry_snapshots WHERE process_name='{ПРОЦЕСС}' ORDER BY id DESC LIMIT 1"
        )[0]
        assert row["fps"] == 21.3, f"колонка фреймворка не задета: {row}"
        assert "state.plugins.capture.fps" not in _extra_of(plugin)


class TestNonLeafDeltaDoesNotCreateAGhost:
    """Дельта СОЗДАНИЯ поддерева приходит словарём — и это ломало Ф2.

    Найдено на живом стенде 2026-08-23: в строке БД одновременно жили
    ``state.plugins = {'capture': {'capture_fps': 14.5}}`` и
    ``state.plugins.capture.capture_fps = 14.3``. Словарь протухал (обновления
    идут полистовыми дельтами), дублировал число и — главное — переживал уход
    писателя: ``_cache_evict`` режет по границе-точке, поэтому удаление
    ``…plugins.capture`` снимало лист, но не трогало ПРЕДКА ``…plugins``.
    Числа ушедшего писателя оставались в строках навсегда, то есть ровно тот
    дефект, который Ф2 и убирает.
    """

    def test_subtree_creation_delta_is_expanded_into_leaves(self):
        plugin = make_plugin()
        plugin._on_deltas([_лист(f"processes.{ПРОЦЕСС}.state.fps", 21.3)])
        plugin._on_deltas(
            [
                Delta(
                    path=КОРЕНЬ.rsplit(".", 1)[0],
                    old_value=MISSING,
                    new_value={"capture": {"capture_fps": 14.5}},
                    source="hb",
                )
            ]
        )
        plugin._sample_once()
        до = _extra_of(plugin)

        # Развёрнуто в ЛИСТ, а не положено словарём под родительским ключом.
        assert до["state.plugins.capture.capture_fps"] == 14.5, до
        assert "state.plugins" not in до, f"нелистовая запись в накопителе: {до}"

    def test_the_ghost_does_not_survive_the_writer_departure(self):
        plugin = make_plugin()
        plugin._on_deltas([_лист(f"processes.{ПРОЦЕСС}.state.fps", 21.3)])
        plugin._on_deltas(
            [
                Delta(
                    path=КОРЕНЬ.rsplit(".", 1)[0],
                    old_value=MISSING,
                    new_value={"capture": {"capture_fps": 14.5}},
                    source="hb",
                ),
                _лист(КОРЕНЬ + ".capture_fps", 14.3),
            ]
        )
        plugin._sample_once()
        строк_до = len(plugin._sql.query(f"SELECT id FROM telemetry_snapshots WHERE process_name='{ПРОЦЕСС}'"))
        assert _extra_of(plugin)["state.plugins.capture.capture_fps"] == 14.3

        plugin._on_deltas([_удаление(КОРЕНЬ, {"capture_fps": 14.3})])
        plugin._sample_once()

        строк_после = len(plugin._sql.query(f"SELECT id FROM telemetry_snapshots WHERE process_name='{ПРОЦЕСС}'"))
        после = _extra_of(plugin)
        # Якорь наблюдения: новая строка ДЕЙСТВИТЕЛЬНО написана. Без него
        # «ключей нет» читалось бы со СТАРОЙ строки — процесс без единого ключа
        # строку не пишет вовсе, и проверка стала бы вакуумной.
        assert строк_после > строк_до, "новая строка не написана — проверка была бы вакуумной"
        assert not [k for k in после if "plugins" in k], f"призрак ушедшего писателя выжил: {после}"
        # Пара-контроль: колонка фреймворка не задета.
        row = plugin._sql.query(
            f"SELECT fps FROM telemetry_snapshots WHERE process_name='{ПРОЦЕСС}' ORDER BY id DESC LIMIT 1"
        )[0]
        assert row["fps"] == 21.3, row
