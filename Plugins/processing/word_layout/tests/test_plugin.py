"""Тесты WordLayoutPlugin — потоковая раскладка слова из predictions в robot_job."""

from __future__ import annotations

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Plugins.processing.word_layout.plugin import WordLayoutPlugin


def _make_plugin(config: dict | None = None) -> WordLayoutPlugin:
    # По умолчанию require_pick=False (раскладка без робота) — большинство тестов проверяют
    # логику слотов, а не координату забора. Тесты pick/калибровки задают require_pick явно.
    cfg = {"require_pick": False}
    cfg.update(config or {})
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
    assert (job["place_x_mm"], job["place_y_mm"], job["place_z_mm"]) == (0.0, 0.0, -90.0)
    assert job["place_rz_deg"] == -30.0  # доворот до прямой
    assert job["raw_angle_deg"] == 30.0
    # Без pick_xy (демо, require_pick=False) — координаты забора не добавляются.
    assert "pick_x_mm" not in job


def test_word_latched_from_signal_persists() -> None:
    """Слово приходит ОДНИМ item (signal_2 пульта), распознавание — ДРУГИМИ items.

    Латч: слово взводится сигналом и держится на последующих кадрах предсказаний.
    Без латча word_source='signal_2' терялся бы на кадре без сигнала → диск не брался.
    """
    p = _make_plugin(
        {
            "word_source": "signal_2",
            "use_pitch": False,
            "first_x": 0.0,
            "first_y": 0.0,
            "last_x": 100.0,
            "last_y": 0.0,
            "settle_frames": 1,
        }
    )
    # Кадр 1: только сигнал слова (без predictions) — задаёт слово, латчится.
    out1 = _feed(p, {"signal_2": "КО", "data_type": "signal"})
    assert "robot_job" not in out1  # диска нет — класть нечего
    # Кадр 2: предсказание БЕЗ слова в item — слово берётся из латча, выдаётся job.
    out2 = _feed(p, {"predictions": [_pred("К", angle=0.0, valid=True)]})
    assert out2["robot_job"]["char"] == "К"
    assert out2["robot_job"]["slot"] == 0


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
    assert (a["place_x_mm"], a["place_y_mm"]) == (300.0, -100.0)
    assert (b["place_x_mm"], b["place_y_mm"]) == (300.0, 10.0)  # +110 по Y, X тот же


def test_streaming_sequence_fills_word() -> None:
    p = _make_plugin({"target_word": "КО", "word_source": "", "use_pitch": False, "last_x": 100.0, "settle_frames": 1})
    j1 = _feed(p, {"predictions": [_pred("К")]}).get("robot_job")
    assert j1["slot"] == 0
    _feed(p, {"predictions": []})  # разрыв — диск ушёл, взвестись заново
    j2 = _feed(p, {"predictions": [_pred("О")]}).get("robot_job")
    assert j2["slot"] == 1
    assert j2["place_x_mm"] == 100.0
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
    assert out["robot_job"]["place_rz_deg"] == 0.0


def test_pick_and_encoder_forwarded() -> None:
    # Полный тракт: pick_xy (калибровка) + e_capture едут в job рядом с укладкой.
    p = _make_plugin(
        {
            "target_word": "К",
            "word_source": "",
            "use_pitch": False,
            "first_x": 10.0,
            "first_y": 20.0,
            "place_z_mm": -90.0,
            "settle_frames": 1,
            "require_pick": True,
        }
    )
    out = _feed(
        p,
        {"predictions": [_pred("К", angle=30.0)], "pick_xy": {"x_mm": 333.0, "y_mm": -150.0}, "e_capture": 12345},
    )
    job = out["robot_job"]
    assert (job["pick_x_mm"], job["pick_y_mm"]) == (333.0, -150.0)  # забор с ленты
    assert job["e_capture"] == 12345
    assert (job["place_x_mm"], job["place_y_mm"], job["place_z_mm"]) == (10.0, 20.0, -90.0)  # укладка
    assert job["place_rz_deg"] == -30.0


def test_require_pick_blocks_without_calibration() -> None:
    # require_pick=True + нет pick_xy → диск не берём, слот не занимаем (раскладка не desync).
    p = _make_plugin({"target_word": "К", "word_source": "", "settle_frames": 1, "require_pick": True})
    out = _feed(p, {"predictions": [_pred("К")]})  # без pick_xy
    assert "robot_job" not in out
    assert p._reg.slots_filled == 0
    assert p._reg.done is False


# ----------------------------------------------------------------------------- #
# ВОЗВРАТ на ленту
# ----------------------------------------------------------------------------- #


def _make_word_plugin(**extra) -> WordLayoutPlugin:
    cfg = {
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
    cfg.update(extra)
    return _make_plugin(cfg)


def test_return_emits_jobs_for_filled_slots() -> None:
    p = _make_word_plugin()
    _feed(p, {"predictions": [_pred("К")]})
    _feed(p, {"predictions": [_pred("О")]})
    assert p._reg.slots_filled == 2

    out = _feed(p, {"signal_1": {"value": 1}})  # сигнал возврата
    jobs = out["robot_return_jobs"]
    assert len(jobs) == 2
    assert jobs[0]["char"] == "К" and (jobs[0]["x_mm"], jobs[0]["y_mm"], jobs[0]["z_mm"]) == (0.0, 0.0, -90.0)
    assert jobs[1]["char"] == "О" and jobs[1]["x_mm"] == 100.0
    # После возврата раскладка сброшена — можно вводить новое слово.
    assert p._reg.slots_filled == 0
    assert p._reg.done is False


def test_return_fires_once_per_signal_edge() -> None:
    # Второй кадр с тем же удерживаемым сигналом не повторяет возврат (фронт).
    p = _make_word_plugin()
    _feed(p, {"predictions": [_pred("К")]})
    out1 = _feed(p, {"signal_1": 1})
    assert "robot_return_jobs" in out1
    out2 = _feed(p, {"signal_1": 1})  # сигнал ещё держится — повтора нет
    assert "robot_return_jobs" not in out2


def test_return_nothing_when_empty() -> None:
    p = _make_word_plugin()
    out = _feed(p, {"signal_1": 1})  # ничего не выложено
    assert "robot_return_jobs" not in out


def test_return_then_new_word_places_again() -> None:
    p = _make_word_plugin()
    _feed(p, {"predictions": [_pred("К")]})
    _feed(p, {"signal_1": 1})  # возврат + сброс
    assert p._reg.slots_filled == 0
    # Спад сигнала → взвод, затем снова кладём.
    out = _feed(p, {"predictions": [_pred("К")]})
    assert out["robot_job"]["char"] == "К"
    assert p._reg.slots_filled == 1
