# -*- coding: utf-8 -*-
"""Тесты FrameShmMiddleware — Claim Check frame↔SHM, в т.ч. переаллокация при resize.

Ключевой инвариант (resize-safe): когда кадр становится больше выделенного блока
(увеличили ROI / сменили разрешение), middleware ПЕРЕаллоцирует SHM под новый
размер и продолжает писать через SHM (а не сваливается в вечный pickle-fallback).
Любой размер кадра восстанавливается на приёме корректно.
"""

from __future__ import annotations

import numpy as np
import pytest

from multiprocess_framework.modules.router_module.core.router_manager import RouterManager
from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import (
    FrameShmMiddleware,
)
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import (
    MemoryManager,
)


def _mw() -> FrameShmMiddleware:
    return FrameShmMiddleware(MemoryManager(), owner="test_owner", slot="output_frames", coll=3)


def _frame(h: int, w: int, val: int = 50) -> np.ndarray:
    return np.full((h, w, 3), val, dtype=np.uint8)


def _roundtrip(mw: FrameShmMiddleware, frame: np.ndarray) -> tuple[bool, np.ndarray | None]:
    """strip_and_write → restore_frame. Возвращает (через_shm, восстановленный_кадр)."""
    out = mw.strip_and_write({"frame": frame.copy(), "seq_id": 1})
    via_shm = "shm_actual_name" in out
    restored = mw.restore_frame({"data": out}).get("frame")
    return via_shm, restored


class TestBasicRoundtrip:
    def test_first_frame_via_shm(self):
        mw = _mw()
        via_shm, restored = _roundtrip(mw, _frame(600, 800))
        assert via_shm is True
        assert restored is not None and restored.shape == (600, 800, 3)

    def test_smaller_frame_fits_existing_block(self):
        mw = _mw()
        _roundtrip(mw, _frame(600, 800))
        via_shm, restored = _roundtrip(mw, _frame(600, 80))  # меньше — влезает
        assert via_shm is True
        assert restored is not None and restored.shape == (600, 80, 3)


class TestResizeReallocation:
    """Регресс: рост кадра → переаллокация → SHM (не pickle), размер корректен."""

    def test_grow_reallocates_and_stays_on_shm(self):
        mw = _mw()
        _roundtrip(mw, _frame(600, 800))
        # Кадр вырос за пределы блока (увеличили ROI) — должна сработать переаллокация.
        via_shm, restored = _roundtrip(mw, _frame(1080, 1440, val=99))
        assert via_shm is True, "после роста кадр должен идти через SHM (переаллокация), а не pickle"
        assert restored is not None and restored.shape == (1080, 1440, 3)
        assert mw._alloc_shape == (1080, 1440, 3)

    def test_grow_then_smaller_all_via_shm_correct_size(self):
        mw = _mw()
        sizes = [(600, 800), (1080, 1440), (600, 801), (600, 80), (1200, 1600)]
        for h, w in sizes:
            via_shm, restored = _roundtrip(mw, _frame(h, w))
            assert via_shm is True, f"{h}x{w} должен идти через SHM"
            assert restored is not None and restored.shape == (h, w, 3), f"размер {h}x{w} искажён"

    def test_capacity_grows_only_never_shrinks(self):
        mw = _mw()
        _roundtrip(mw, _frame(1080, 1440))
        _roundtrip(mw, _frame(600, 800))  # меньше — ёмкость НЕ должна уменьшиться
        assert mw._alloc_shape == (1080, 1440, 3)

    def test_width_plus_one_does_not_break(self):
        """Точный кейс владельца: ROI 800→801 не ломает кадр (раньше → полный кадр)."""
        mw = _mw()
        _roundtrip(mw, _frame(600, 800))
        via_shm, restored = _roundtrip(mw, _frame(600, 801))
        assert restored is not None and restored.shape == (600, 801, 3)
        assert via_shm is True


class TestFrameFitsHelper:
    def test_fits_within_capacity(self):
        mw = _mw()
        _roundtrip(mw, _frame(1080, 1440))
        assert mw._frame_fits(_frame(600, 800)) is True
        assert mw._frame_fits(_frame(1080, 1440)) is True

    def test_does_not_fit_when_larger(self):
        mw = _mw()
        _roundtrip(mw, _frame(600, 800))
        assert mw._frame_fits(_frame(600, 801)) is False  # шире → не влезает
        assert mw._frame_fits(_frame(601, 800)) is False  # выше → не влезает

    def test_dtype_change_does_not_fit(self):
        mw = _mw()
        _roundtrip(mw, _frame(600, 800))
        other = np.zeros((600, 800, 3), dtype=np.float32)
        assert mw._frame_fits(other) is False


class TestFrameBoundaryCounter:
    """Ф7 G.6: счётчик границ процесса на кадр (frame_hops + frame_boundary_crossings).

    Ревью 2026-07-13: колбэк on_boundary_cross убран (F5) — middleware сам копит
    ``frame_boundary_crossings`` (plain int, читается напрямую в тестах ниже)."""

    def test_strip_and_write_increments_frame_hops(self):
        mw = _mw()
        item = {"frame": _frame(600, 800)}
        out = mw.strip_and_write(item)
        assert out["frame_hops"] == 1
        assert mw.frame_boundary_crossings == 1
        # Повторный "hop" того же item (симуляция второго звена pipeline'а) —
        # счётчик накапливается, а не сбрасывается.
        out["frame"] = _frame(600, 800)  # следующий узел снова кладёт кадр в SHM
        out2 = mw.strip_and_write(out)
        assert out2["frame_hops"] == 2
        assert mw.frame_boundary_crossings == 2

    def test_strip_and_write_increments_on_pickle_fallback(self):
        """Кадр без SHM (memory_manager=None) всё равно уходит через IPC (pickle) —
        граница должна считаться, а не только на «честном» SHM-пути."""
        mw = FrameShmMiddleware(memory_manager=None, owner="test_owner", slot="output_frames")
        item = {"frame": _frame(600, 800)}
        out = mw.strip_and_write(item)
        assert "shm_actual_name" not in out  # ушёл через pickle-fallback
        assert out["frame"] is not None  # frame не вырезан (pickle-путь)
        assert out["frame_hops"] == 1
        assert mw.frame_boundary_crossings == 1

    def test_strip_and_write_no_frame_does_not_increment(self):
        mw = _mw()
        item = {"seq_id": 1}  # нет frame — не боундари
        out = mw.strip_and_write(item)
        assert "frame_hops" not in out
        assert mw.frame_boundary_crossings == 0

    def test_on_send_increments_frame_hops_in_data(self):
        mw = _mw()
        msg = {"frame": _frame(600, 800)}
        out = mw.on_send(msg)
        assert out["data"]["frame_hops"] == 1
        assert mw.frame_boundary_crossings == 1

    def test_on_send_without_memory_manager_still_increments(self):
        """Без memory_manager frame остаётся в msg (pickle) — граница всё равно
        реальна (кадр уйдёт через IPC как есть), счётчик должен расти."""
        mw = FrameShmMiddleware(memory_manager=None, owner="test_owner", slot="output_frames")
        msg = {"frame": _frame(600, 800)}
        out = mw.on_send(msg)
        assert out["frame"] is not None
        assert out["data"]["frame_hops"] == 1
        assert mw.frame_boundary_crossings == 1

    def test_on_send_no_frame_does_not_increment(self):
        mw = _mw()
        out = mw.on_send({"command": "noop"})
        assert "data" not in out
        assert mw.frame_boundary_crossings == 0

    def test_frame_boundary_crossings_starts_at_zero(self):
        mw = FrameShmMiddleware(MemoryManager(), owner="test_owner", slot="output_frames")
        assert mw.frame_boundary_crossings == 0


class TestFanOutBoundaryCounting:
    """Ф7 G.6 ревью 2026-07-13, F1 (HIGH, CONFIRMED) — недосчёт при multicast:
    producer переиспользует ОДИН item-dict для нескольких targets; router
    send-middleware зовётся per-target (per-send), но второй вызов раньше видел
    уже стрипнутый item (frame=None) и no-op'ил — граница терялась. Агрегатный
    счётчик обязан быть точным на fan-out; per-item frame_hops — приближение
    (общий mutable item, см. класс-докстринг FrameShmMiddleware)."""

    def test_strip_data_frame_on_send_fan_out_two_targets_counts_boundary_twice(self):
        """Прод-сценарий: SourceProducer._send_item шлёт ОДИН item в 2 chain_targets —
        router send-middleware (strip_data_frame_on_send) зовётся дважды на тот же item."""
        mw = _mw()
        item = {"frame": _frame(600, 800), "camera_id": 0}
        msg_to_a = {"type": "data", "data": item}
        msg_to_b = {"type": "data", "data": item}  # тот же item — реальный fan-out паттерн

        mw.strip_data_frame_on_send(msg_to_a)
        mw.strip_data_frame_on_send(msg_to_b)

        assert mw.frame_boundary_crossings == 2  # оба send'а реальны — оба посчитаны
        assert item["frame_hops"] == 1  # per-item поле НЕ задвоено (документированное приближение)
        assert "shm_actual_name" in item  # первый send реально стрипнул кадр в SHM

    def test_strip_and_write_fan_out_three_targets(self):
        mw = _mw()
        item = {"frame": _frame(600, 800)}
        for _ in range(3):
            mw.strip_and_write(item)
        assert mw.frame_boundary_crossings == 3

    def test_on_send_fan_out_two_targets_counts_boundary_twice(self):
        """Симметрично для top-level-frame пути (wire.configure): один и тот же
        msg-объект отправляется дважды (напр. sender/receiver-пара переиспользует
        билет) — оба send'а должны быть учтены. H5c: on_send ТЕПЕРЬ делает lazy-alloc
        через общее ядро (G.3a) — предаллокация больше не нужна (первый send сам
        выделит SHM и проставит настоящий shm_name-маркер для replay-ветки)."""
        mw = _mw()
        msg = {"frame": _frame(600, 800)}
        mw.on_send(msg)  # первый send: lazy-alloc + SHM write успешен, frame стрипнут
        assert "shm_actual_name" in msg["data"]
        mw.on_send(msg)  # второй send того же msg: frame уже None, data несёт shm_name
        assert mw.frame_boundary_crossings == 2
        assert msg["data"]["frame_hops"] == 1  # приближение, как и для generic-пути


class TestOnSendDefensiveDataField:
    """Ф7 G.6 ревью 2026-07-13, F4 (MED, PLAUSIBLE) — msg["data"]=None (например,
    сообщение сконструировано с явным data=None где-то выше по стеку) не должен
    ронять on_send AttributeError'ом до попытки SHM-записи."""

    def test_on_send_with_explicit_none_data_does_not_raise(self):
        mw = _mw()
        mw._mm.create_memory_dict("test_owner", {"output_frames": (1, (600, 800, 3), "uint8")}, 3)
        msg = {"frame": _frame(600, 800), "data": None}
        out = mw.on_send(msg)  # не должно бросить
        assert isinstance(out["data"], dict)
        assert out["data"]["frame_hops"] == 1
        assert "shm_actual_name" in out["data"]  # SHM-запись всё же прошла, несмотря на data=None


class _WriteFailsMM:
    """Фейк mm: аллокация ОК, но write_images всегда None (сбой SHM-write)."""

    def create_memory_dict(self, *a, **k) -> bool:
        return True

    def close_memory(self, *a, **k) -> None:
        pass

    def write_images(self, *a, **k):
        return None


class TestG3WriteUnificationAndLoudFallback:
    """Ф7 G.3(a) — одно ядро записи (round-robin в обоих путях); G.3(d) — громкий fallback."""

    def test_on_send_uses_round_robin_slots(self):
        """G.3a: on_send теперь round-robin (снят find_free_index, всегда 0)."""
        mw = FrameShmMiddleware(MemoryManager(), owner="o", slot="s", coll=3)
        indices = []
        for _ in range(5):
            out = mw.on_send({"frame": _frame(8, 8), "data": {}})
            indices.append(out["data"]["shm_index"])
        assert indices == [0, 1, 2, 0, 1], f"ожидался round-robin, получено {indices}"
        mw._mm.close_all()

    def test_loud_pickle_fallback_counts_on_write_failure(self):
        """G.3d: сбой SHM-write (mm есть) → frame остаётся + счётчик fallback растёт."""
        mw = FrameShmMiddleware(_WriteFailsMM(), owner="o", slot="s")
        item = mw.strip_and_write({"frame": _frame(10, 10)})
        assert "frame" in item, "frame обязан остаться в item (pickle-fallback)"
        assert mw.frame_pickle_fallbacks == 1
        assert mw.frame_boundary_crossings == 1  # граница всё равно посчитана (G.6)

    def test_no_fallback_count_when_mm_none(self):
        """G.3d: mm=None — pickle-by-design (SHM не сконфигурирован), НЕ деградация."""
        mw = FrameShmMiddleware(None, owner="o", slot="s")
        item = mw.strip_and_write({"frame": _frame(10, 10)})
        assert "frame" in item
        assert mw.frame_pickle_fallbacks == 0, "mm=None не должен считаться деградацией"
        assert mw.frame_boundary_crossings == 1


class TestG3SeqlockCrossProcess:
    """Ф7 G.3(b) — seqlock-флаг едет в сообщении, cross-process reader сверяет generation."""

    def test_seqlock_flag_stamped_in_message(self):
        mw_on = FrameShmMiddleware(MemoryManager(seqlock_frames=True), owner="o", slot="s")
        item = mw_on.strip_and_write({"frame": _frame(8, 8)})
        assert item.get("shm_seqlock") is True
        mw_on._mm.close_all()

        mw_off = FrameShmMiddleware(MemoryManager(), owner="o", slot="s")
        item2 = mw_off.strip_and_write({"frame": _frame(8, 8)})
        assert item2.get("shm_seqlock") is False
        mw_off._mm.close_all()

    def test_seqlock_cross_process_raw_read_roundtrip(self):
        """Producer пишет seqlock-слот; consumer БЕЗ handle читает через raw-путь
        (read_single_frame(verify_seqlock=True)) — кадр восстанавливается корректно."""
        prod = FrameShmMiddleware(MemoryManager(seqlock_frames=True), owner="p", slot="s")
        frame = _frame(20, 30, 77)
        item = prod.strip_and_write({"frame": frame.copy()})
        assert item["shm_seqlock"] is True and "shm_actual_name" in item

        # Consumer — своя (пустая) mm: read_images промахнётся → raw seqlock-путь.
        consumer = FrameShmMiddleware(MemoryManager(), owner="c", slot="s")
        restored = consumer.restore_frame({"data": dict(item)}).get("frame")
        assert restored is not None and np.array_equal(restored, frame)
        prod._mm.close_all()


class TestG3HandleCache:
    """Ф7 G.3 — кэш SHM-handles читателя (open/mmap/close снимается с per-frame пути)."""

    def test_handle_cache_populated_and_closed(self):
        prod = FrameShmMiddleware(MemoryManager(), owner="p", slot="s")
        item = prod.strip_and_write({"frame": _frame(16, 16)})

        # H4: кэш активен только в связке с owner_incarnation.
        consumer = FrameShmMiddleware(
            MemoryManager(), owner="c", slot="s", cache_shm_handles=True, owner_incarnation=True
        )
        r1 = consumer.restore_frame({"data": dict(item)}).get("frame")
        r2 = consumer.restore_frame({"data": dict(item)}).get("frame")
        assert r1 is not None and r2 is not None
        # Один и тот же shm_actual_name → ровно 1 закэшированный handle (не переоткрыт).
        assert len(consumer._shm_handle_cache) == 1
        consumer.close_handle_cache()
        assert len(consumer._shm_handle_cache) == 0
        prod._mm.close_all()

    def test_no_cache_by_default(self):
        prod = FrameShmMiddleware(MemoryManager(), owner="p", slot="s")
        item = prod.strip_and_write({"frame": _frame(16, 16)})
        consumer = FrameShmMiddleware(MemoryManager(), owner="c", slot="s")  # cache off
        consumer.restore_frame({"data": dict(item)})
        assert len(consumer._shm_handle_cache) == 0  # без кэша handle не хранится
        prod._mm.close_all()


class TestH4CacheRealloc:
    """H4: кэш handles × переиспользование имени → жёсткая связка с owner_incarnation."""

    def test_cache_disabled_without_incarnation(self):
        """H4: cache запрошен БЕЗ incarnation → кэш ОТКЛЮЧЁН + WARNING (риск frozen frame)."""
        logs: list[str] = []
        mw = FrameShmMiddleware(
            MemoryManager(),
            owner="c",
            slot="s",
            cache_shm_handles=True,
            owner_incarnation=False,
            log_error=logs.append,
        )
        assert mw._cache_shm_handles is False, "кэш обязан быть отключён без incarnation"
        assert any("owner_incarnation" in m for m in logs), "ожидался WARNING про связку"

    def test_cache_with_incarnation_realloc_delivers_new_frame(self):
        """H4: cache+incarnation, realloc (resize) → имя меняется → кадр №2 доставлен
        (НЕ замороженный №1 из осиротевшего сегмента)."""
        prod = FrameShmMiddleware(MemoryManager(owner_incarnation=True), owner="p", slot="s")
        item1 = prod.strip_and_write({"frame": _frame(100, 100, 11)})
        consumer = FrameShmMiddleware(
            MemoryManager(),
            owner="c",
            slot="s",
            cache_shm_handles=True,
            owner_incarnation=True,
        )
        assert consumer._cache_shm_handles is True
        r1 = consumer.restore_frame({"data": dict(item1)}).get("frame")
        assert r1 is not None and int(r1.min()) == 11

        # Realloc: кадр больше блока → пересоздание со СВЕЖЕЙ инкарнацией (новое имя).
        item2 = prod.strip_and_write({"frame": _frame(300, 300, 22)})
        assert item2["shm_actual_name"] != item1["shm_actual_name"], "имя обязано смениться"
        r2 = consumer.restore_frame({"data": dict(item2)}).get("frame")
        assert r2 is not None and int(r2.min()) == 22, "кадр №2, не замороженный №1"
        consumer.close_handle_cache()
        prod._mm.close_all()


class TestH5WireLifecycle:
    """H5: двойное создание (adopt) + deconfigure освобождает память/unregister."""

    def test_h5a_adopt_existing_no_double_create(self):
        """H5a: PM уже создал (owner, slot) → свежий middleware ПРИНИМАЕТ, не создаёт второй раз."""
        mm = MemoryManager()
        mm.create_memory_dict("o", {"s": (1, (100, 100, 3), "uint8")}, 3)  # PM wire_setup
        assert mm._stats["created"] == 1
        mw = FrameShmMiddleware(mm, owner="o", slot="s")  # wire.configure
        mw.strip_and_write({"frame": _frame(100, 100)})  # первый кадр → _allocate_shm
        assert mm._stats["created"] == 1, "adopt, НЕ второе создание"
        assert mw._allocated and mw._created_slot is False
        mm.close_all()

    def test_h5b_configure_deconfigure_cycles_no_leak(self):
        """H5b: PM-память + configure/кадр/deconfigure ×3 → created==1, middlewares не копятся."""
        router = RouterManager(manager_name="r_h5b")
        mm = MemoryManager()
        mm.create_memory_dict("o", {"s": (1, (64, 64, 3), "uint8")}, 3)  # PM создал ОДИН раз
        for _ in range(3):
            mw = FrameShmMiddleware(mm, owner="o", slot="s")
            router.register_frame_middleware(mw)
            mw.strip_and_write({"frame": _frame(64, 64)})  # adopt PM-память
            # deconfigure teardown:
            router.unregister_frame_middleware(mw)
            mw.release_owned_memory()  # no-op: слот adopted (не created)
        assert mm._stats["created"] == 1, "PM-память переиспользована, не пересоздана"
        assert len(router._frame_middlewares) == 0, "middlewares не копятся"
        mm.close_all()

    def test_h5b_created_slot_released_on_deconfigure(self):
        """H5b: слот, СОЗДАННЫЙ middleware (не PM), освобождается на deconfigure."""
        mm = MemoryManager()
        mw = FrameShmMiddleware(mm, owner="o2", slot="s2")
        mw.strip_and_write({"frame": _frame(32, 32)})  # middleware сам создал
        assert mm._stats["created"] == 1 and mw._created_slot is True
        mw.release_owned_memory()
        assert not mw._allocated  # освобождён (свой слот)
        mm.close_all()


class TestM2M3Observability:
    """M2c torn-счётчик raw-read, M2d причина в fallback-логе, M3 без нового dict/кадр."""

    def test_m3_writes_coords_into_same_dict_no_new_object(self):
        """M3: координаты вписываются В переданный item (не новый dict на кадр)."""
        mw = _mw()
        item = {"frame": _frame(20, 20)}
        out = mw.strip_and_write(item)
        assert out is item, "должен вернуться ТОТ ЖЕ объект (без аллокации coords-dict)"
        assert "shm_actual_name" in item

    def test_m2d_fallback_log_includes_reason(self):
        """M2d: первый throttled fallback-лог несёт причину (repr сбоя записи)."""
        logs: list[str] = []
        mw = FrameShmMiddleware(_WriteFailsMM(), owner="o", slot="s", log_error=logs.append)
        mw.strip_and_write({"frame": _frame(10, 10)})
        assert mw.frame_pickle_fallbacks == 1
        assert any("причина=" in m for m in logs), "в логе fallback должна быть причина"

    def test_m2c_torn_raw_read_increments_counter(self):
        """M2c: cross-process seqlock-чтение поймало torn → счётчик frame_torn_reads."""
        from multiprocess_framework.modules.shared_resources_module.memory.format import (
            buffer as buf_mod,
        )

        prod = FrameShmMiddleware(MemoryManager(seqlock_frames=True), owner="p", slot="s")
        item = prod.strip_and_write({"frame": _frame(20, 20, 33)})
        assert item["shm_seqlock"] is True
        # Отравить generation слота продюсера в нечёт (writer «в процессе записи»).
        idx = item["shm_index"]
        handle = prod._mm.get_memory_data("p", "s")["handles"][idx]
        buf_mod._write_generation(handle.buf, buf_mod.read_generation(handle.buf) + 1)

        consumer = FrameShmMiddleware(MemoryManager(), owner="c", slot="s")
        out = consumer.restore_frame({"data": dict(item)})
        assert out.get("frame") is None, "torn → drop"
        assert consumer.frame_torn_reads == 1
        prod._mm.close_all()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
