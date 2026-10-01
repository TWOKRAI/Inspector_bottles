"""Task 4.7a (P-1) — слепые приёмочные тесты: join не должен терять ``_shm_views``.

Контракт (дизайн лида): ``_shm_views`` — локальная мета «входы item'а — zero-copy view на
чужие SHM-слоты». При слиянии входов join ВСЕГДА конкатенирует ``_shm_views`` (primary-вход
первым), независимо от настроенного ``list_merge_keys``; ключ присутствует и тогда, когда
его несёт только вторичный вход. Иначе дверь отправки не видит view второго входа и не
может проверить, что он пережил обработку.

Тесты идут через публичную поверхность (``on_item`` -> ``on_ready``), ожидания — литералы.
"""

from __future__ import annotations

from Plugins._shared.fanin.join_inspector_manager import JoinInspectorManager

REF_FRAME = {"owner": "camA", "slot": "output_frames", "idx": 0, "gen": 2, "name": "shm_camA_0"}
REF_OVERLAY = {"owner": "lineB", "slot": "output_frames", "idx": 1, "gen": 4, "name": "shm_lineB_1"}


def _mgr(results: list, **kw) -> tuple:
    kw.setdefault("required_inputs", {"frame", "overlay"})
    kw.setdefault("primary", "frame")
    kw.setdefault("timeout_sec", 0.05)
    kw.setdefault("inactive_sec", 5.0)
    return JoinInspectorManager(on_ready=results.append, **kw), results


def _join(mgr_and_results: tuple, overlay_item: dict, frame_item: dict) -> dict:
    """Overlay первым (регистрирует активность входа), затем frame — полный набор -> один merged."""
    mgr, results = mgr_and_results
    mgr.on_item(overlay_item)
    assert results == [], "стенд неисправен: набор не должен быть готов до прихода frame"
    mgr.on_item(frame_item)
    assert len(results) == 1 and len(results[0]) == 1, f"стенд неисправен: ожидался один merged, получено {results}"
    return results[0][0]


def test_views_concatenated_both_inputs():
    """RED сегодня: оба входа несут ``_shm_views`` -> в merged ссылки primary, затем вторичного.
    Сегодня второй вход падает в ``elif k not in merged`` и теряется (merged == [REF_FRAME])."""
    results: list = []
    merged = _join(
        _mgr(results),
        {"data_type": "overlay", "seq_id": 7, "overlay": [{"type": "line"}], "_shm_views": [REF_OVERLAY]},
        {"data_type": "frame", "seq_id": 7, "frame": "F", "_shm_views": [REF_FRAME]},
    )
    assert merged["_shm_views"] == [REF_FRAME, REF_OVERLAY]


def test_views_concatenated_regardless_of_list_keys():
    """RED сегодня: конкатенация не зависит от настроенных ``list_merge_keys`` — ни дефолт
    ("overlay",), ни пустой набор, ни чужой ключ не должны её отключать."""
    for list_keys in ((), ("something_else",)):
        results: list = []
        merged = _join(
            _mgr(results, list_merge_keys=list_keys),
            {"data_type": "overlay", "seq_id": 7, "_shm_views": [REF_OVERLAY]},
            {"data_type": "frame", "seq_id": 7, "frame": "F", "_shm_views": [REF_FRAME]},
        )
        assert merged["_shm_views"] == [REF_FRAME, REF_OVERLAY], f"list_merge_keys={list_keys!r}"


def test_views_only_secondary_kept():
    """GREEN-by-accident (сегодня): ``_shm_views`` только у вторичного входа — попадает в merged через
    ветку ``k not in merged``. Предсказание лида «RED» не подтвердилось — см. отчёт. Тест фиксирует
    требование «присутствует, когда его несёт только вторичный вход»;
    обязан остаться зелёным после правки."""
    results: list = []
    merged = _join(
        _mgr(results),
        {"data_type": "overlay", "seq_id": 7, "_shm_views": [REF_OVERLAY]},
        {"data_type": "frame", "seq_id": 7, "frame": "F"},
    )
    assert merged["_shm_views"] == [REF_OVERLAY]


def test_views_secondary_kept_when_primary_has_empty_list():
    """RED сегодня: primary несёт пустой ``_shm_views`` (``[]``), вторичный — ссылку. Конкатенация
    ``[] + [REF]`` = ``[REF]``; сегодня ключ уже занят пустым списком primary -> ссылка вторичного
    теряется (merged == []). Граничный случай «всегда конкатенируется» (в проде restore_frame пустой
    список не ставит — граница выбрана тестером, не лидом)."""
    results: list = []
    merged = _join(
        _mgr(results),
        {"data_type": "overlay", "seq_id": 7, "_shm_views": [REF_OVERLAY]},
        {"data_type": "frame", "seq_id": 7, "frame": "F", "_shm_views": []},
    )
    assert merged["_shm_views"] == [REF_OVERLAY]


def test_views_primary_only_kept():
    """GREEN сегодня (preservation): ``_shm_views`` только у primary — остаётся как есть."""
    results: list = []
    merged = _join(
        _mgr(results),
        {"data_type": "overlay", "seq_id": 7},
        {"data_type": "frame", "seq_id": 7, "frame": "F", "_shm_views": [REF_FRAME]},
    )
    assert merged["_shm_views"] == [REF_FRAME]


def test_views_merge_does_not_mutate_input_lists():
    """Guard (GREEN сегодня, красный при реализации через ``.extend`` на списке входа): после слияния
    списки ``_shm_views`` самих входных item'ов не изменены — они ещё принадлежат DataReceiver."""
    results: list = []
    overlay_views = [REF_OVERLAY]
    frame_views = [REF_FRAME]
    _join(
        _mgr(results),
        {"data_type": "overlay", "seq_id": 7, "_shm_views": overlay_views},
        {"data_type": "frame", "seq_id": 7, "frame": "F", "_shm_views": frame_views},
    )
    assert frame_views == [REF_FRAME]
    assert overlay_views == [REF_OVERLAY]
