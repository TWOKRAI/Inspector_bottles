"""Тесты WordLayoutPlugin — потоковая раскладка слова из predictions в robot_job."""

from __future__ import annotations

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Plugins.processing.word_layout.plugin import WordLayoutPlugin


def _make_plugin(config: dict | None = None) -> WordLayoutPlugin:
    cfg = config or {}
    services = MockProcessServices(name="layout", config=cfg)
    ctx = PluginContext(services=services, config=cfg)
    plugin = WordLayoutPlugin()
    plugin.configure(ctx)
    return plugin


def _pred(label: str, angle: float = 0.0, valid: bool = True, conf: float = 0.9) -> dict:
    return {"label": label, "confidence": conf, "angle_deg": angle, "angle_valid": valid}


def _feed(plugin: WordLayoutPlugin, item: dict) -> dict:
    """Прогнать один кадр, вернуть выходной item."""
    return plugin.process([item])[0]


def test_registered() -> None:
    from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry
    import Plugins.processing.word_layout.plugin  # noqa: F401

    entry = PluginRegistry.get("word_layout")
    assert entry is not None
    assert entry.category == "processing"


def test_passthrough_without_word() -> None:
    p = _make_plugin({"word_source": ""})  # ни слова в порту, ни target_word
    out = _feed(p, {"predictions": [_pred("К")], "frame": "X"})
    assert "robot_job" not in out
    assert out["frame"] == "X"


def test_emits_pose_xyzr() -> None:
    p = _make_plugin(
        {
            "target_word": "КО",
            "word_source": "",
            "use_pitch": False,
            "first_x": 0.0,
            "first_y": 0.0,
            "last_x": 100.0,
            "last_y": 0.0,
            "place_z_mm": -90.0,
            "settle_frames": 1,
        }
    )
    out = _feed(p, {"predictions": [_pred("К", angle=30.0, valid=True)]})
    job = out["robot_job"]
    assert job["char"] == "К"
    assert job["slot"] == 0
    assert (job["x_mm"], job["y_mm"], job["z_mm"]) == (0.0, 0.0, -90.0)
    assert job["r_deg"] == -30.0  # доворот до прямой
    assert job["raw_angle_deg"] == 30.0


def test_pitch_mode_along_y() -> None:
    # Раскладка от первого диска вдоль +Y: X постоянный, Y растёт с шагом = диаметр.
    p = _make_plugin(
        {
            "target_word": "АБ",
            "word_source": "",
            "use_pitch": True,
            "first_x": 300.0,
            "first_y": -100.0,
            "line_angle_deg": 90.0,
            "pitch_mm": 0.0,  # авто = 2*55 = 110
            "disk_radius_mm": 55.0,
            "settle_frames": 1,
        }
    )
    a = _feed(p, {"predictions": [_pred("А")]})["robot_job"]
    _feed(p, {"predictions": []})
    b = _feed(p, {"predictions": [_pred("Б")]})["robot_job"]
    assert (a["x_mm"], a["y_mm"]) == (300.0, -100.0)
    assert (b["x_mm"], b["y_mm"]) == (300.0, 10.0)  # +110 по Y, X тот же


def test_streaming_sequence_fills_word() -> None:
    p = _make_plugin({"target_word": "КО", "word_source": "", "use_pitch": False, "last_x": 100.0, "settle_frames": 1})
    j1 = _feed(p, {"predictions": [_pred("К")]}).get("robot_job")
    assert j1["slot"] == 0
    _feed(p, {"predictions": []})  # разрыв — диск ушёл, взвестись заново
    j2 = _feed(p, {"predictions": [_pred("О")]}).get("robot_job")
    assert j2["slot"] == 1
    assert j2["x_mm"] == 100.0
    assert p._reg.done is True


def test_skips_unneeded_letter() -> None:
    p = _make_plugin({"target_word": "К", "word_source": "", "settle_frames": 1})
    out = _feed(p, {"predictions": [_pred("Я")]})
    assert "robot_job" not in out


def test_duplicate_letter_then_skip_when_full() -> None:
    # «определённое количество раз; если буква заполнила — в след. раз пропускаем».
    p = _make_plugin({"target_word": "ОКО", "word_source": "", "settle_frames": 1})

    def take(label: str) -> dict | None:
        job = _feed(p, {"predictions": [_pred(label)]}).get("robot_job")
        _feed(p, {"predictions": []})  # разрыв перед следующим диском
        return job

    assert take("О")["slot"] == 0
    assert take("О")["slot"] == 2
    assert take("О") is None  # оба слота «О» заполнены → пропуск
    assert take("К")["slot"] == 1
    assert p._reg.done is True


def test_word_from_input_port() -> None:
    p = _make_plugin({"settle_frames": 1, "last_x": 100.0})  # word_source="word" по умолчанию
    out = _feed(p, {"word": "СОК", "predictions": [_pred("С")]})
    assert out["robot_job"]["char"] == "С"
    assert p._reg.word_norm == "СОК"


def test_debounce_emits_once_per_disk() -> None:
    p = _make_plugin({"target_word": "КК", "word_source": "", "settle_frames": 2})
    # Диск «К» висит 3 кадра подряд — взять РОВНО один раз (после 2 кадров стабильности).
    jobs = [_feed(p, {"predictions": [_pred("К")]}).get("robot_job") for _ in range(3)]
    emitted = [j for j in jobs if j is not None]
    assert len(emitted) == 1
    assert emitted[0]["slot"] == 0


def test_consecutive_different_letters_no_gap() -> None:
    # Триггерный тракт: ~1 кадр на диск, без пауз между разными буквами.
    # Смена буквы = новый диск → берём каждую, даже без пустых кадров.
    p = _make_plugin({"target_word": "КОТ", "word_source": "", "last_x": 200.0, "settle_frames": 1})
    slots = [_feed(p, {"predictions": [_pred(ch)]}).get("robot_job", {}).get("slot") for ch in "КОТ"]
    assert slots == [0, 1, 2]
    assert p._reg.done is True


def test_trigger_mode() -> None:
    p = _make_plugin({"target_word": "К", "word_source": "", "use_trigger": True})
    # Без триггера — не берём, даже если буква уверенно видна.
    assert "robot_job" not in _feed(p, {"predictions": [_pred("К")]})
    # С триггером — берём.
    out = _feed(p, {"predictions": [_pred("К")], "trigger": True})
    assert out["robot_job"]["char"] == "К"


def test_low_confidence_ignored() -> None:
    p = _make_plugin({"target_word": "К", "word_source": "", "settle_frames": 1, "min_confidence": 0.8})
    assert "robot_job" not in _feed(p, {"predictions": [_pred("К", conf=0.5)]})


def test_symmetry_letter_zero_correction() -> None:
    p = _make_plugin({"target_word": "О", "word_source": "", "settle_frames": 1})
    out = _feed(p, {"predictions": [_pred("О", angle=123.0, valid=False)]})
    assert out["robot_job"]["r_deg"] == 0.0
