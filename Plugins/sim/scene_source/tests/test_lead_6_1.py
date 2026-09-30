# -*- coding: utf-8 -*-
"""Task 6.1 — тесты лида: то, что инъекции показали незакрытым.

Два повода, оба найдены прогоном матрицы поломок 2026-09-28 (а не чтением диффа):

1. **Дефект очереди управления.** Первая редакция `_drain_control()` держала не
   выпущенный `defect_now` в ГОЛОВЕ очереди (`break`), пока фабрика его не потратит.
   На паузе фабрика его не тратит никогда, поэтому всё, что встало за ним — в том
   числе снятие паузы — не применялось. Воспроизведение: пауза → `defect_now` →
   `defect_now` → `pause:false` → 20 кадров с едущим энкодером → `scene.status`
   отдавал `paused=True`. Оператор пульта в этом состоянии не мог снять паузу
   ничем, кроме рестарта процесса. Починка — кредиты вместо головы очереди.

2. **Незакрытое свойство `set_flow`.** Инъекция «убрать `_next_spacing_mm = None`
   из `set_flow`» не уронила НИ ОДНОГО теста: приёмочные переключают режим только
   с `interval_s` на `spacing_mm`, а там порог ещё не взведён и сброс — пустая
   операция. Настоящий случай (сменить ШАГ, пока старый порог уже отсчитывается)
   не проверял никто. Тест, остающийся зелёным под собственной поломкой, не
   существует — ниже он заведён.
"""

from __future__ import annotations

import pytest

from Services.line_sim.core.belt import FACTOR_MM
from Plugins.sim.scene_source.tests.test_scene_controls_acceptance import (
    _call,
    _make_plugin_with_engine,
    _push_encoder,
)


def _enc(mm: float) -> float:
    """Миллиметры пути ленты -> единицы энкодера (`FACTOR_MM` = мм на единицу)."""
    return mm / FACTOR_MM


pytestmark = pytest.mark.timeout(30)


def _spawn_encoders(plugin) -> list[float]:
    """Энкодеры спавна активных объектов — по ним виден фактический шаг."""
    return [obj.passport.spawn_encoder for obj in plugin._spawner.active_objects()]


# --------------------------------------------------------------------------- #
# 1. Очередь управления не блокируется не выпущенным defect_now              #
# --------------------------------------------------------------------------- #


def test_unpause_applies_even_with_unspent_defect_now(tmp_path):
    """Регрессия дефекта 1: снятие паузы не должно ждать, пока форс-брак потратится."""
    plugin, _ctx, sp = _make_plugin_with_engine(
        tmp_path, {"spawn_spacing_mm": [10.0, 10.0], "scene_length_mm": 10000.0}
    )
    _push_encoder(sp, 0.0, t=0.0)
    plugin.produce()

    _call(plugin, "scene.pause", {"paused": True})
    plugin.produce()
    assert _call(plugin, "scene.status")["paused"] is True

    _call(plugin, "scene.defect_now")
    plugin.produce()
    assert _call(plugin, "scene.status")["force_defect_pending"] is True

    # второе нажатие + снятие паузы ЗА ним: заявка на паузу не имеет права ждать брака
    _call(plugin, "scene.defect_now")
    _call(plugin, "scene.pause", {"paused": False})
    plugin.produce()

    assert _call(plugin, "scene.status")["paused"] is False


def test_flow_change_applies_even_with_unspent_defect_now(tmp_path):
    """Тот же дефект, второй потребитель очереди: смена потока не ждёт форс-брака."""
    plugin, _ctx, sp = _make_plugin_with_engine(
        tmp_path, {"spawn_spacing_mm": [10.0, 10.0], "scene_length_mm": 10000.0}
    )
    _push_encoder(sp, 0.0, t=0.0)
    plugin.produce()

    _call(plugin, "scene.pause", {"paused": True})
    _call(plugin, "scene.defect_now")
    plugin.produce()

    _call(plugin, "scene.defect_now")
    _call(plugin, "scene.flow", {"spacing_mm": [25.0, 25.0]})
    plugin.produce()

    assert _call(plugin, "scene.status")["flow"] == {"spacing_mm": [25.0, 25.0]}


def test_two_defect_now_still_give_two_defects_after_fix(tmp_path):
    """Починка не имеет права схлопывать нажатия — свойство приёмки держится."""
    plugin, _ctx, sp = _make_plugin_with_engine(
        tmp_path, {"spawn_spacing_mm": [10.0, 10.0], "scene_length_mm": 10000.0}
    )
    _push_encoder(sp, 0.0, t=0.0)
    plugin.produce()

    _call(plugin, "scene.defect_now")
    _call(plugin, "scene.defect_now")

    defects = 0
    for i in range(1, 6):
        _push_encoder(sp, _enc(i * 10.0), t=float(i))
        plugin.produce()
        defects = sum(1 for obj in plugin._spawner.active_objects() if obj.passport.defect is not None)
        if defects >= 2:
            break
    assert defects == 2


# --------------------------------------------------------------------------- #
# 2. set_flow сбрасывает НЕЗАВЕРШЁННЫЙ отсчёт своего вида                    #
# --------------------------------------------------------------------------- #


def test_set_flow_spacing_to_spacing_applies_new_step_immediately(tmp_path):
    """Пробел, который показала инъекция B3: смена ШАГА при уже взведённом пороге.

    Шаг 10 мм отсчитывается, объект создан на 10 мм; меняем шаг на 500 мм — следующий
    объект обязан появиться по НОВОМУ шагу, а не по старому взведённому порогу.
    """
    plugin, _ctx, sp = _make_plugin_with_engine(
        tmp_path, {"spawn_spacing_mm": [10.0, 10.0], "scene_length_mm": 100000.0}
    )
    _push_encoder(sp, 0.0, t=0.0)
    plugin.produce()
    _push_encoder(sp, _enc(10.0), t=1.0)  # 10 мм пути -> порог 10 мм взведён и сработал
    plugin.produce()
    before = len(_spawn_encoders(plugin))

    _call(plugin, "scene.flow", {"spacing_mm": [500.0, 500.0]})
    plugin.produce()

    # +20 мм: по СТАРОМУ шагу здесь были бы два новых объекта, по новому — ни одного
    for i in range(2, 4):
        _push_encoder(sp, _enc(i * 10.0), t=float(i))
        plugin.produce()
    assert len(_spawn_encoders(plugin)) == before

    # +500 мм от последнего спавна — новый шаг обязан сработать
    _push_encoder(sp, _enc(520.0), t=10.0)
    plugin.produce()
    assert len(_spawn_encoders(plugin)) == before + 1


def test_set_flow_interval_to_interval_rearms_deadline(tmp_path, monkeypatch):
    """Симметричный случай для `interval_s`: смена интервала взводит срок заново.

    Срок 100 с уже взведён; меняем на 1 с — объект обязан появиться через 1 с от
    момента смены, а не через оставшиеся ~100 с старого срока.
    """
    now = {"t": 0.0}
    monkeypatch.setattr("time.monotonic", lambda: now["t"])

    plugin, _ctx, sp = _make_plugin_with_engine(
        tmp_path, {"spawn_interval_s": [100.0, 100.0], "scene_length_mm": 100000.0}
    )
    _push_encoder(sp, 0.0, t=0.0)
    plugin.produce()  # первый тик только взводит срок (+100 с)
    before = len(_spawn_encoders(plugin))

    now["t"] = 5.0
    _call(plugin, "scene.flow", {"interval_s": [1.0, 1.0]})
    plugin.produce()  # срок сброшен -> взводится заново от 5.0 (+1 с)
    assert len(_spawn_encoders(plugin)) == before

    now["t"] = 6.5
    plugin.produce()
    assert len(_spawn_encoders(plugin)) == before + 1
