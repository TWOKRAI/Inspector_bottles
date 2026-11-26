"""Task 2.2d: слепая приёмка ``presence_watch`` — «нет изделия» / «слабое распознавание».

Тесты написаны ДО реализации, по тексту задачи (поля регистра, REDS 1–8, ACCEPTANCE).
Харнес: настоящий плагин + ``MockProcessServices``; часы — шов ``pw._clock``; хуки зовутся напрямую.
Тесты 7–8 — настоящий ``PluginOrchestrator`` с ``threading.Event`` в роли ``run_event``.

Плагин импортируется внутри тестов (``_pw``): пока пакета нет, каждый тест красный сам по себе,
а не одна ошибка сбора на весь файл. Ожидаемые значения — литералы.
"""

from __future__ import annotations

import copy
import importlib
import threading
from types import ModuleType
from typing import Any

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator
from multiprocess_framework.modules.process_module.plugins.base import PluginContext, PluginState
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

ABSENT_DEF = [{"severity": "out_of_spec", "reason": "нет изделия"}]
WEAK_DEF = [{"severity": "out_of_spec", "reason": "слабое распознавание"}]
NO_B = [{"severity": "out_of_spec", "reason": "нет бутылки"}]
WEAK_B = [{"severity": "out_of_spec", "reason": "не читается"}]

CFG_B = {
    "presence_keys": "bottle.id,cap",
    "predictions_key": "bottle.checks",
    "label_key": "cls",
    "below_threshold_key": "low",
    "confidence_key": "score",
    "min_confidence": 0.5,
    "absent_after_s": 3.0,
    "text_absent": "нет бутылки",
    "text_weak": "не читается",
}

#: Единственный элемент ``reasons`` снимка оркестратора в тестах 7–8.
NODE_REASON = {"node": "recog.presence_watch", "severity": "out_of_spec", "reason": "нет диска", "source": "readiness"}


# --- item-ы (каждый вызов — свежий dict) -------------------------------------


def _letter(confidence: float, below: bool) -> dict:
    return {
        "predictions": [{"label": "А", "confidence": confidence, "below_threshold": below}],
        "sidecar": {"track_id": 1},
    }


def _weak_conf() -> dict:
    return _letter(0.30, False)


def _weak_flag() -> dict:
    return _letter(0.90, True)


def _conf() -> dict:
    return _letter(0.90, False)


def _nan() -> dict:
    return _letter(float("nan"), False)


def _empty() -> dict:
    return {"predictions": [], "sidecar": {"track_id": 3}}


def _no_ml() -> dict:
    return {"sidecar": {"track_id": 4}}


def _no_label() -> dict:
    return {"predictions": [{"confidence": 0.9}], "sidecar": {"track_id": 1}}


def _phone() -> dict:
    return {"signal_2": "АБ"}


def _frame() -> dict:
    return {"frame": np.zeros((4, 4, 3), np.uint8)}


def _bottle(**top: Any) -> dict:
    return {"bottle": {"id": 1, "checks": [top]}}


# --- харнес ------------------------------------------------------------------


def _pw() -> ModuleType:
    return importlib.import_module("Plugins.processing.presence_watch.plugin")


def _fake_clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Подменить ``pw._clock``; время двигается записью в ``t[0]``."""
    t = [1000.0]
    monkeypatch.setattr(_pw(), "_clock", lambda: t[0])
    return t


def _make(cfg: dict | None = None) -> tuple[Any, MockProcessServices]:
    conf = dict(cfg or {})
    services = MockProcessServices(name="recog", config=conf)
    plugin = _pw().PresenceWatchPlugin()
    plugin.configure(PluginContext(services=services, config=conf))
    return plugin, services


def _poll_after(t: list[float], cfg: dict, *items: dict) -> list[dict]:
    """Новый экземпляр: ``start`` 1000.0, каждый item отдельным вызовом в 1001.0, опрос 1001.5."""
    plugin, _ = _make(cfg)
    t[0] = 1000.0
    plugin.start(None)
    t[0] = 1001.0
    for item in items:
        batch = [item]
        assert plugin.process(batch) is batch
    t[0] = 1001.5
    return plugin.readiness(None)


# --- REDS 1–8 ----------------------------------------------------------------


def _assert_passes_through(plugin: Any, phase: str) -> None:
    items = [_conf(), _phone(), _frame(), _weak_conf()]
    originals = list(items)
    before = copy.deepcopy(items)

    out = plugin.process(items)

    assert out is items, phase
    assert len(out) == 4, phase
    for i in range(4):
        assert out[i] is originals[i], (phase, i)
    for i in (0, 1, 3):
        assert out[i] == before[i], (phase, i)
    assert list(out[2]) == ["frame"], phase
    assert out[2]["frame"].dtype == np.uint8, phase
    assert np.array_equal(out[2]["frame"], before[2]["frame"]), phase
    assert plugin.process([]) == [], phase


def test_process_passes_items_through_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    t = _fake_clock(monkeypatch)
    plugin, _ = _make()

    _assert_passes_through(plugin, "вне работы: без start")
    plugin.start(None)
    t[0] = 1001.0
    _assert_passes_through(plugin, "в работе")
    plugin.pause(None)
    _assert_passes_through(plugin, "вне работы: после pause")


def test_not_running_disabled_and_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    t = _fake_clock(monkeypatch)

    # до configure
    assert _pw().PresenceWatchPlugin().readiness(None) == []

    # без хуков
    plugin, _ = _make()
    t[0] = 1000.0
    assert plugin.readiness(None) == []
    t[0] = 5000.0
    assert plugin.readiness(None) == []
    plugin.process([_weak_conf()])
    assert plugin.readiness(None) == []
    plugin.process([_weak_flag()])  # слабое и при пороге 0: вне работы всё равно молчим
    assert plugin.readiness(None) == []

    # после pause
    plugin, _ = _make()
    t[0] = 1000.0
    plugin.start(None)
    t[0] = 1001.0
    plugin.pause(None)
    t[0] = 1500.0
    assert plugin.readiness(None) == []

    # выключенный узел
    plugin, _ = _make()
    t[0] = 1000.0
    plugin.start(None)
    plugin.enabled = False
    t[0] = 1020.0
    assert plugin.readiness(None) == []

    # часы бросают: readiness не бросает, одна строка ERROR на тип исключения
    plugin, services = _make()
    t[0] = 1000.0
    plugin.start(None)

    def _raise_runtime() -> float:
        raise RuntimeError("часы сломаны")

    def _raise_value() -> float:
        raise ValueError("часы сломаны иначе")

    seen = len(services.logs)
    monkeypatch.setattr(_pw(), "_clock", _raise_runtime)
    assert plugin.readiness(None) == []
    assert plugin.readiness(None) == []
    errors = [r["msg"] for r in services.logs[seen:] if r["level"] == "ERROR"]
    assert len(errors) == 1, errors
    assert "RuntimeError" in errors[0]

    seen = len(services.logs)
    monkeypatch.setattr(_pw(), "_clock", _raise_value)
    assert plugin.readiness(None) == []
    assert plugin.readiness(None) == []
    errors = [r["msg"] for r in services.logs[seen:] if r["level"] == "ERROR"]
    assert len(errors) == 1, errors
    assert "ValueError" in errors[0]


def test_other_product_by_recipe_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    t = _fake_clock(monkeypatch)

    assert _poll_after(t, CFG_B, _bottle(cls="ok", score=0.5, low=False)) == []
    assert _poll_after(t, CFG_B, _bottle(cls=0, score=0.9, low=False)) == []

    weak_tops: list[dict] = [
        {"cls": "ok", "score": 0.49, "low": False},
        {"cls": "ok", "score": 0.9, "low": True},
        {"score": 0.9, "low": False},
        {"cls": "ok", "score": None, "low": False},
    ]
    for top in weak_tops:
        assert _poll_after(t, CFG_B, _bottle(**top)) == WEAK_B, top

    assert _poll_after(t, CFG_B, {"cap": True}) == WEAK_B

    # только item букв: для этого рецепта изделия нет
    plugin, _ = _make(CFG_B)
    t[0] = 1000.0
    plugin.start(None)
    t[0] = 1001.0
    plugin.process([_conf()])
    t[0] = 1002.5
    assert plugin.readiness(None) == []
    t[0] = 1003.0
    assert plugin.readiness(None) == NO_B

    # проверки выключены ключами и порогом
    cfg = {**CFG_B, "label_key": "", "below_threshold_key": "", "min_confidence": 0.0}
    assert _poll_after(t, cfg, _bottle(low=True)) == []

    # пустой text_absent: причины нет
    plugin, _ = _make({**CFG_B, "text_absent": ""})
    t[0] = 1000.0
    plugin.start(None)
    t[0] = 1010.0
    assert plugin.readiness(None) == []

    # пустой text_weak: причины нет
    cfg = {**CFG_B, "text_weak": ""}
    assert _poll_after(t, cfg, _bottle(cls="ok", score=0.49, low=False)) == []


def test_weak_product_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    t = _fake_clock(monkeypatch)

    for make_item in (_weak_flag, _empty, _no_ml, _no_label):
        assert _poll_after(t, {}, make_item()) == WEAK_DEF, make_item.__name__

    for make_item in (_weak_conf, _nan):
        assert _poll_after(t, {"min_confidence": 0.5}, make_item()) == WEAK_DEF, make_item.__name__

    for make_item in (_weak_conf, _nan, _conf):
        assert _poll_after(t, {}, make_item()) == [], make_item.__name__

    # последний item изделия решает: уверенный после слабого снимает причину
    assert _poll_after(t, {}, _weak_flag(), _conf()) == []


def test_no_flicker_default_ten_seconds_and_switch_to_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    t = _fake_clock(monkeypatch)
    plugin, _ = _make()
    t[0] = 1000.0
    plugin.start(None)

    schedule: dict[float, list[dict]] = {
        1001.0: [_conf()],
        1005.0: [_conf()],
        1009.0: [_conf()],
        1013.0: [_conf()],
        1015.0: [_phone(), _frame()],
        1020.0: [_phone(), _frame()],
    }
    quiet: list[list[dict]] = []
    absent: list[list[dict]] = []
    for step in range(61):  # 1000.0 … 1030.0 через 0,5 с
        now = 1000.0 + 0.5 * step
        t[0] = now
        for item in schedule.get(now, []):
            plugin.process([item])
        (quiet if now <= 1022.5 else absent).append(plugin.readiness(None))

    assert len(quiet) == 46
    assert quiet == [[]] * 46
    assert len(absent) == 15
    assert absent == [ABSENT_DEF] * 15

    t[0] = 1030.5
    plugin.process([_conf()])
    assert plugin.readiness(None) == []

    t[0] = 1031.0
    plugin.process([_weak_flag()])
    t[0] = 1040.5
    assert plugin.readiness(None) == WEAK_DEF
    t[0] = 1041.0
    assert plugin.readiness(None) == ABSENT_DEF


def test_pause_resume_restarts_timer_and_forgets(monkeypatch: pytest.MonkeyPatch) -> None:
    t = _fake_clock(monkeypatch)
    plugin, _ = _make()
    t[0] = 1000.0
    plugin.start(None)
    t[0] = 1020.0
    assert plugin.readiness(None) == ABSENT_DEF

    t[0] = 1021.0
    plugin.process([_weak_flag()])
    assert plugin.readiness(None) == WEAK_DEF

    plugin.pause(None)
    t[0] = 1021.5
    assert plugin.readiness(None) == []
    t[0] = 1100.0
    assert plugin.readiness(None) == []

    plugin.resume(None)
    t[0] = 1101.0
    assert plugin.readiness(None) == []  # слабое до паузы забыто, таймер начат заново
    t[0] = 1109.5
    assert plugin.readiness(None) == []
    t[0] = 1110.0
    assert plugin.readiness(None) == ABSENT_DEF


def _orchestrator(event: threading.Event) -> PluginOrchestrator:
    """Настоящий оркестратор процесса ``recog``: center_crop + presence_watch (до ``boot()``)."""
    services = MockProcessServices(name="recog")
    services._current_process_status = "running"  # type: ignore[attr-defined]
    services._run_event = event  # type: ignore[attr-defined]
    services._run_watch_enabled = lambda: True  # type: ignore[attr-defined]
    orch = PluginOrchestrator(services=services)
    orch.load_and_configure_managers(
        [
            {
                "plugin_class": "Plugins.processing.center_crop.plugin.CenterCropPlugin",
                "plugin_name": "center_crop",
                "config": {},
            },
            {
                "plugin_class": "Plugins.processing.presence_watch.plugin.PresenceWatchPlugin",
                "plugin_name": "presence_watch",
                "config": {"text_absent": "нет диска"},
            },
        ]
    )
    return orch


def test_orchestrator_booted_in_ready_is_silent_until_start(monkeypatch: pytest.MonkeyPatch) -> None:
    t = _fake_clock(monkeypatch)
    event = threading.Event()  # снято: система в «готов»
    orch = _orchestrator(event)
    t[0] = 1000.0
    orch.boot()
    assert [(p.name, p.state) for p in orch.plugins] == [
        ("center_crop", PluginState.PAUSED),
        ("presence_watch", PluginState.PAUSED),
    ]

    t[0] = 1020.0
    assert orch.readiness_snapshot()["reasons"] == []

    event.set()
    orch.reconcile_run_event()
    t[0] = 1029.5
    assert orch.readiness_snapshot()["reasons"] == []  # срок считается от START, а не от boot
    t[0] = 1030.0
    snap = orch.readiness_snapshot()
    assert snap["reasons"] == [NODE_REASON]
    assert snap["ready"] is True

    event.clear()
    orch.reconcile_run_event()
    assert orch.readiness_snapshot()["reasons"] == []


def test_orchestrator_raised_during_running_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    t = _fake_clock(monkeypatch)
    cls = _pw().PresenceWatchPlugin
    original_resume = cls.resume
    resumed: list[str] = []

    def _spy_resume(self: Any, ctx: Any) -> None:
        resumed.append(self.name)
        original_resume(self, ctx)

    monkeypatch.setattr(cls, "resume", _spy_resume)
    event = threading.Event()
    event.set()  # рестарт в работе: событие взведено ДО boot()
    orch = _orchestrator(event)
    t[0] = 1000.0
    orch.boot()
    assert [(p.name, p.state) for p in orch.plugins] == [
        ("center_crop", PluginState.RUNNING),
        ("presence_watch", PluginState.RUNNING),
    ]
    orch.reconcile_run_event()
    assert resumed == []

    t[0] = 1009.5
    assert orch.readiness_snapshot()["reasons"] == []
    t[0] = 1010.0
    snap = orch.readiness_snapshot()
    assert snap["reasons"] == [NODE_REASON]
    assert snap["ready"] is True

    event.clear()
    orch.reconcile_run_event()
    assert orch.readiness_snapshot()["reasons"] == []


# --- сверх REDS: две строки таблицы полей, которые REDS не закрепляют --------


def test_presence_is_not_none_and_missing_confidence_is_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """``presence_keys``: изделие, если путь не ``None``; ``confidence_key``: нет в топе — 1.0."""
    t = _fake_clock(monkeypatch)

    # False — не None: это изделие
    assert _poll_after(t, CFG_B, {"cap": False}) == WEAK_B

    # ключа уверенности в топе нет: 1.0, порог 0.5 пройден
    assert _poll_after(t, CFG_B, _bottle(cls="ok", low=False)) == []

    # все пути None: изделия нет, срок идёт от start
    plugin, _ = _make(CFG_B)
    t[0] = 1000.0
    plugin.start(None)
    t[0] = 1001.0
    plugin.process([{"cap": None, "bottle": {"id": None}}])
    t[0] = 1001.5
    assert plugin.readiness(None) == []
    t[0] = 1003.0
    assert plugin.readiness(None) == NO_B


def test_top_prediction_is_the_first_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """``predictions_key``: топ — элемент ``[0]``; остальные элементы списка не решают."""
    t = _fake_clock(monkeypatch)
    good = {"label": "А", "confidence": 0.90, "below_threshold": False}
    bad = {"label": "Б", "confidence": 0.30, "below_threshold": True}
    cfg = {"min_confidence": 0.5}

    assert _poll_after(t, cfg, {"predictions": [good, bad]}) == []
    assert _poll_after(t, cfg, {"predictions": [bad, good]}) == WEAK_DEF
