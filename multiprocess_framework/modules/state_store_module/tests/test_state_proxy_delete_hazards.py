"""Task 2.1 (Ф2) — ``StateProxy.delete`` и префикс-чистка кэша: авторские hazard-тесты.

Приёмка от независимого тестера живёт отдельно
(``process_module/tests/test_f2_acceptance_writer_retraction.py``) и написана вслепую
от критериев. Здесь — опасности самого механизма, которые видно только автору правки:
граница префикса, идемпотентность, точность пути, порядок внутри пакета дельт.

MockRouter переиспользуется из ``test_state_proxy`` — второй копии мока не заводим.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta
from multiprocess_framework.modules.state_store_module.manager.state_store_manager import StateStoreManager
from multiprocess_framework.modules.state_store_module.proxy.state_proxy import StateProxy

from ._deterministic_delivery import apply_deterministic_delivery
from .test_state_proxy import MockRouter

#: Маркер отсутствия ключа. При промахе кэша ``get`` уходит в IPC, MockRouter отвечает
#: ``"success"`` (не ``"ok"``), значение не подставляется и возвращается default.
#: Отдельный объект вместо ``None`` принципиален: ``None`` — законное ЗНАЧЕНИЕ листа,
#: а путать «значение None» с «ключа нет» — ровно тот дефект, который Ф2 убирает.
ОТСУТСТВУЕТ = object()

ПИСАТЕЛЬ = "processes.camera_0.state.plugins.capture"
СОСЕД = "processes.camera_0.state.plugins.capture2"


@pytest.fixture(autouse=True)
def _deterministic_state_delivery(monkeypatch):
    """Доставка дельт детерминированная — тесты проверяют ЧТО, а не КОГДА."""
    apply_deterministic_delivery(monkeypatch)


@pytest.fixture
def pair():
    """Связка proxy + живой StateStoreManager на общем MockRouter."""
    router = MockRouter()
    mgr = StateStoreManager(router=router)
    mgr.initialize()
    proxy = StateProxy("camera_0", router=router)
    yield proxy, mgr, router
    mgr.shutdown()


def _установить(proxy, mgr, router, path, value):
    """Положить лист в дерево через прокси и скормить сообщение менеджеру."""
    proxy.set(path, value)
    mgr.handle_state_set(router.last_sent("state.set"))


class TestDeleteReachesTheStore:
    """delete() через прокси доходит до живого менеджера."""

    def test_delete_removes_the_whole_subtree_and_spares_the_neighbour(self, pair):
        proxy, mgr, router = pair

        _установить(proxy, mgr, router, ПИСАТЕЛЬ + ".fps", 21.3)
        _установить(proxy, mgr, router, ПИСАТЕЛЬ + ".frame_count", 5)
        _установить(proxy, mgr, router, СОСЕД + ".fps", 852.3)

        # Якорь существования: до удаления в дереве лежат ЛИТЕРАЛЫ.
        assert mgr.store.get(ПИСАТЕЛЬ + ".fps") == 21.3
        assert mgr.store.get(ПИСАТЕЛЬ + ".frame_count") == 5
        assert mgr.store.get(СОСЕД + ".fps") == 852.3

        proxy.delete(ПИСАТЕЛЬ)
        msg = router.last_sent("state.delete")
        assert msg is not None, "delete() обязан уйти в роутер командой state.delete"
        result = mgr.handle_state_delete(msg)
        assert result["status"] == "ok", result

        # store.get на отсутствующем пути БРОСАЕТ KeyError — маркер отличает
        # «ключа нет» от «значение None» (None — законное значение листа).
        assert mgr.store.get(ПИСАТЕЛЬ + ".fps", ОТСУТСТВУЕТ) is ОТСУТСТВУЕТ
        assert mgr.store.get(ПИСАТЕЛЬ + ".frame_count", ОТСУТСТВУЕТ) is ОТСУТСТВУЕТ
        # Пара-контроль: сосед с ОБЩИМ ТЕКСТОВЫМ префиксом не задет.
        assert mgr.store.get(СОСЕД + ".fps") == 852.3

    def test_delete_of_an_absent_path_is_not_an_error(self, pair):
        """Идемпотентность: удаление того, чего нет, — не ошибка."""
        proxy, mgr, router = pair

        proxy.delete("processes.camera_0.state.plugins.никогда_не_было")
        result = mgr.handle_state_delete(router.last_sent("state.delete"))

        assert result["status"] == "ok", f"удаление отсутствующего пути не ошибка: {result}"
        assert result.get("changed") is False, f"ничего не изменилось: {result}"

    def test_delete_twice_leaves_the_tree_in_the_same_state(self, pair):
        """Повтор delete по уже удалённому поддереву — тоже не ошибка."""
        proxy, mgr, router = pair

        _установить(proxy, mgr, router, ПИСАТЕЛЬ + ".fps", 21.3)
        assert mgr.store.get(ПИСАТЕЛЬ + ".fps") == 21.3

        proxy.delete(ПИСАТЕЛЬ)
        первый = mgr.handle_state_delete(router.last_sent("state.delete"))
        proxy.delete(ПИСАТЕЛЬ)
        второй = mgr.handle_state_delete(router.last_sent("state.delete"))

        assert первый["status"] == "ok" and первый.get("changed") is True, первый
        assert второй["status"] == "ok" and второй.get("changed") is False, второй
        assert mgr.store.get(ПИСАТЕЛЬ + ".fps", ОТСУТСТВУЕТ) is ОТСУТСТВУЕТ

    def test_delete_carries_the_exact_path_and_source(self, pair):
        """Род 1: путь в сообщении — ровно переданный, не родитель и не лист."""
        proxy, mgr, router = pair

        proxy.delete(ПИСАТЕЛЬ)

        msg = router.last_sent("state.delete")
        assert msg["data"]["path"] == ПИСАТЕЛЬ
        assert msg["data"]["source"] == "camera_0"


class TestCachePurgesBySubtree:
    """Кэш прокси: дельта КОРНЯ обязана выбить все листья под ним."""

    @staticmethod
    def _proxy_с_тремя_листьями() -> StateProxy:
        proxy = StateProxy("camera_0", router=MockRouter())
        proxy._update_cache(
            [
                Delta(path=ПИСАТЕЛЬ + ".fps", old_value=MISSING, new_value=21.3, source="hb"),
                Delta(path=ПИСАТЕЛЬ + ".frame_count", old_value=MISSING, new_value=5, source="hb"),
                Delta(path=СОСЕД + ".fps", old_value=MISSING, new_value=852.3, source="hb"),
            ]
        )
        return proxy

    def test_root_delta_drops_every_leaf_under_it(self):
        proxy = self._proxy_с_тремя_листьями()

        # Якорь существования: кэш отдаёт ЛИТЕРАЛЫ, а не «что-то не None».
        assert proxy.get(ПИСАТЕЛЬ + ".fps", ОТСУТСТВУЕТ) == 21.3
        assert proxy.get(ПИСАТЕЛЬ + ".frame_count", ОТСУТСТВУЕТ) == 5

        proxy._update_cache([Delta(path=ПИСАТЕЛЬ, old_value={"fps": 21.3}, new_value=MISSING, source="hb")])

        assert proxy.get(ПИСАТЕЛЬ + ".fps", ОТСУТСТВУЕТ) is ОТСУТСТВУЕТ
        assert proxy.get(ПИСАТЕЛЬ + ".frame_count", ОТСУТСТВУЕТ) is ОТСУТСТВУЕТ

    def test_neighbour_with_a_shared_text_prefix_survives(self):
        """Граница — точка: ``capture2`` начинается с ``capture``, но это другой сегмент."""
        proxy = self._proxy_с_тремя_листьями()
        assert proxy.get(СОСЕД + ".fps", ОТСУТСТВУЕТ) == 852.3

        proxy._update_cache([Delta(path=ПИСАТЕЛЬ, old_value={"fps": 21.3}, new_value=MISSING, source="hb")])

        assert proxy.get(СОСЕД + ".fps", ОТСУТСТВУЕТ) == 852.3

    def test_exact_leaf_delta_still_drops_that_leaf(self):
        """Точечное снятие одного листа не сломано префикс-чисткой."""
        proxy = StateProxy("camera_0", router=MockRouter())
        лист = "processes.camera_0.state.fps"

        proxy._update_cache([Delta(path=лист, old_value=MISSING, new_value=21.3, source="hb")])
        assert proxy.get(лист, ОТСУТСТВУЕТ) == 21.3

        proxy._update_cache([Delta(path=лист, old_value=21.3, new_value=MISSING, source="hb")])
        assert proxy.get(лист, ОТСУТСТВУЕТ) is ОТСУТСТВУЕТ

    def test_root_delta_for_a_writer_with_no_leaves_is_harmless(self):
        """Дельта корня пришла раньше, чем у писателя появились листья."""
        proxy = self._proxy_с_тремя_листьями()

        proxy._update_cache(
            [
                Delta(
                    path="processes.camera_0.state.plugins.ещё_не_публиковал",
                    old_value={},
                    new_value=MISSING,
                    source="hb",
                )
            ]
        )

        assert proxy.get(ПИСАТЕЛЬ + ".fps", ОТСУТСТВУЕТ) == 21.3
        assert proxy.get(СОСЕД + ".fps", ОТСУТСТВУЕТ) == 852.3

    def test_order_inside_one_batch_last_delta_wins(self):
        """Гонка в одном пакете: фиксирую ФАКТИЧЕСКИЙ порядок, а не желаемый.

        Дельты применяются последовательно, поэтому побеждает последняя. Тест держит
        это поведение: если однажды кто-то начнёт сортировать пакет или выносить
        удаления вперёд — сломается здесь, а не на живом стенде.
        """
        proxy = StateProxy("camera_0", router=MockRouter())

        proxy._update_cache(
            [
                Delta(path=ПИСАТЕЛЬ, old_value={"fps": 1.0}, new_value=MISSING, source="hb"),
                Delta(path=ПИСАТЕЛЬ + ".fps", old_value=MISSING, new_value=99.9, source="hb"),
            ]
        )
        assert proxy.get(ПИСАТЕЛЬ + ".fps", ОТСУТСТВУЕТ) == 99.9

        proxy._update_cache(
            [
                Delta(path=ПИСАТЕЛЬ + ".fps", old_value=MISSING, new_value=77.7, source="hb"),
                Delta(path=ПИСАТЕЛЬ, old_value={"fps": 77.7}, new_value=MISSING, source="hb"),
            ]
        )
        assert proxy.get(ПИСАТЕЛЬ + ".fps", ОТСУТСТВУЕТ) is ОТСУТСТВУЕТ


class TestNonLeafDeltaIsExpanded:
    """Кэш держит ЛИСТЬЯ — инвариант, который половина кода нарушала.

    ``_apply_resync_snapshot`` словари пропускает явно, а приёмная сторона
    дельт клала ``delta.new_value`` сырым. Дельта СОЗДАНИЯ поддерева приходит
    словарём целиком — и такая запись протухала (обновления идут полистовыми
    дельтами) и переживала префикс-чистку: удаление ``…plugins.capture``
    снимает лист, но ПРЕДКА ``…plugins`` не трогает.
    """

    def test_dict_delta_lands_as_leaves_not_as_one_entry(self):
        proxy = StateProxy("camera_0", router=MockRouter())
        родитель = "processes.camera_0.state.plugins"

        proxy._update_cache(
            [
                Delta(
                    path=родитель,
                    old_value=MISSING,
                    new_value={"capture": {"fps": 21.3}, "capture2": {"fps": 852.3}},
                    source="hb",
                )
            ]
        )

        assert proxy.get(родитель + ".capture.fps", ОТСУТСТВУЕТ) == 21.3
        assert proxy.get(родитель + ".capture2.fps", ОТСУТСТВУЕТ) == 852.3
        # Нелистовой записи в кэше не появилось.
        assert proxy.get(родитель, ОТСУТСТВУЕТ) is ОТСУТСТВУЕТ

    def test_the_expanded_leaves_are_purged_by_a_subtree_delete(self):
        """Развёрнутые листья уходят по дельте корня — призрака не остаётся."""
        proxy = StateProxy("camera_0", router=MockRouter())
        родитель = "processes.camera_0.state.plugins"

        proxy._update_cache(
            [
                Delta(
                    path=родитель,
                    old_value=MISSING,
                    new_value={"capture": {"fps": 21.3}, "capture2": {"fps": 852.3}},
                    source="hb",
                )
            ]
        )
        assert proxy.get(родитель + ".capture.fps", ОТСУТСТВУЕТ) == 21.3

        proxy._update_cache(
            [Delta(path=родитель + ".capture", old_value={"fps": 21.3}, new_value=MISSING, source="hb")]
        )

        assert proxy.get(родитель + ".capture.fps", ОТСУТСТВУЕТ) is ОТСУТСТВУЕТ
        assert proxy.get(родитель + ".capture2.fps", ОТСУТСТВУЕТ) == 852.3

    def test_empty_dict_puts_nothing_in_the_cache(self):
        """Пустой словарь листьев не даёт — в кэш не кладём вовсе."""
        proxy = StateProxy("camera_0", router=MockRouter())
        путь = "processes.camera_0.state.plugins"

        proxy._update_cache([Delta(path=путь, old_value=MISSING, new_value={}, source="hb")])

        assert proxy.get(путь, ОТСУТСТВУЕТ) is ОТСУТСТВУЕТ
