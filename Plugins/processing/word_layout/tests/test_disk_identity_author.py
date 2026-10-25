"""C-32, тесты автора: опасные места id-ветки ``_should_take`` (settle внутри одного track_id).

Ячейки слова «ПЕРЕМИРИЕ»: П0 Е1 Р2 Е3 М4 И5 Р6 И7 Е8; «слот» = ``robot_job["slot"]`` или ``None``.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Plugins.processing.word_layout.plugin import WordLayoutPlugin

_BASE = {"require_pick": False, "word_source": "", "settle_frames": 1, "target_word": "ПЕРЕМИРИЕ"}


def _make(cfg: dict | None = None) -> WordLayoutPlugin:
    full = dict(_BASE)
    full.update(cfg or {})
    services = MockProcessServices(name="layout", config=full)
    plugin = WordLayoutPlugin()
    plugin.configure(PluginContext(services=services, config=full))
    return plugin


def _pred(label: str, angle: float = 0.0, conf: float = 0.9) -> dict:
    return {"label": label, "confidence": conf, "angle_deg": angle, "angle_valid": True}


def _disk(label: str, tid: object, conf: float = 0.9) -> dict:
    return {"predictions": [_pred(label, conf=conf)], "sidecar": {"track_id": tid}}


def _slots(p: WordLayoutPlugin, items: list[dict]) -> list[int | None]:
    outs = [p.process([it])[0] for it in items]
    return [o["robot_job"]["slot"] if o.get("robot_job") else None for o in outs]


def test_pause_within_track_resets_settle() -> None:
    # Слабый кадр того же диска обнуляет счёт стабильности: два «Р» не подряд — не взяты.
    p = _make({"settle_frames": 2})
    assert _slots(p, [_disk("Р", 1), _disk("Р", 1, conf=0.1), _disk("Р", 1)]) == [None, None, None]


def test_letter_change_within_track_restarts_settle() -> None:
    # Смена буквы внутри диска начинает счёт заново с 1: «Р» не копится в «Е».
    p = _make({"settle_frames": 2})
    assert _slots(p, [_disk("Р", 1), _disk("Е", 1), _disk("Е", 1)]) == [None, None, 1]


def test_skip_marks_track_taken() -> None:
    # «Щ» в слове нет — диск пропущен, но id занят: «Р» с тем же id не берётся, со следующим — берётся.
    p = _make()
    assert _slots(p, [_disk("Щ", 1), _disk("Р", 1), _disk("Р", 2)]) == [None, None, 2]
