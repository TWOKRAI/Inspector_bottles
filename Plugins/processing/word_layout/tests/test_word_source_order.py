"""C-37: слово с порта и запись регистра ``target_word`` равноправны — действует последнее пришедшее.

Приёмочные тесты B1–B20 (plans/word-layout/tasks/C-37.md, «Приёмка»), написаны до правки кода.
Регистр ``target_word`` — единственное хранилище слова: слово с порта плагин записывает в него же.

Ячейки: «МИР» — М0 И1 Р2; «РИМ» — Р0 И1 М2; «слот» = ``robot_job["slot"]`` или ``None``.
Плагин «управляемый»: ``PluginContext(registers=rm)`` с настоящим ``RegistersManager``, где
``rm.get_register("word_layout")`` — тот самый регистр, что держит плагин. Внешняя запись —
``rm.set_field_value`` (тот же вызов, что в ``PluginOrchestrator._on_register_update``).
B9 — без менеджера (``ctx.registers`` is None), запись через ``p._reg.update_field``.
Ожидаемые значения — литералы из спеки; в тестах нет присваивания ``p._reg.target_word = …``.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.registers_module import RegistersManager

from Plugins.processing.word_layout.plugin import WordLayoutPlugin
from Plugins.processing.word_layout.registers import WordLayoutRegisters

_BASE = {"require_pick": False, "word_source": "signal_2", "settle_frames": 1, "target_word": ""}
_CHANGE_MARK = "смена слова"
_REJECT_MARK = "пустое слово в регистре не принято"
_REG = "word_layout"


def _make(
    cfg: dict | None = None, *, managed: bool = True
) -> tuple[WordLayoutPlugin, MockProcessServices, RegistersManager | None]:
    full = dict(_BASE)
    full.update(cfg or {})
    services = MockProcessServices(name="layout", config=full)
    rm = RegistersManager(registers={_REG: WordLayoutRegisters()}) if managed else None
    plugin = WordLayoutPlugin()
    plugin.configure(PluginContext(services=services, config=full, registers=rm))
    return plugin, services, rm


def _pred(label: str, angle: float = 0.0, conf: float = 0.9) -> dict:
    return {"label": label, "confidence": conf, "angle_deg": angle, "angle_valid": True}


def _disk(label: str, tid: object, angle: float = 0.0) -> dict:
    return {"predictions": [_pred(label, angle)], "sidecar": {"track_id": tid}}


def _slot(p: WordLayoutPlugin, item: dict) -> int | None:
    out = p.process([item])[0]
    job = out.get("robot_job")
    return job["slot"] if job else None


def _port(p: WordLayoutPlugin, value: object) -> dict:
    """Item со словом на порту ``signal_2`` (без диска)."""
    return p.process([{"signal_2": value}])[0]


def _write(rm: RegistersManager, value: str) -> None:
    """Внешняя запись регистра — тот же вызов, что ``_on_register_update``."""
    assert rm.set_field_value(_REG, "target_word", value) == (True, None)


def _stored(rm: RegistersManager) -> str:
    return rm.get_register(_REG).target_word


def _lines(services: MockProcessServices, mark: str) -> list[str]:
    return [e["msg"] for e in services.logs if mark in e["msg"]]


# --- B1–B3: кто последний, тот и действует ------------------------------------


def test_port_then_register_register_wins() -> None:
    p, _, rm = _make()
    _port(p, "МИР")
    assert _slot(p, _disk("Р", 1)) == 2
    _write(rm, "РИМ")
    assert _slot(p, _disk("Р", 2)) == 0
    assert p._reg.word_norm == "РИМ"


def test_register_then_port_port_wins() -> None:
    p, _, rm = _make()
    _write(rm, "РИМ")
    assert _slot(p, _disk("Р", 1)) == 0
    _port(p, "МИР")
    assert _slot(p, _disk("Р", 2)) == 2
    assert p._reg.word_norm == "МИР"


def test_rewrite_previous_register_word_is_arrival() -> None:
    # О1: оператор снова пишет в регистр слово, которое стояло там до слова с телефона, — это приход.
    p, _, rm = _make()
    _write(rm, "РИМ")
    _port(p, "МИР")
    assert _slot(p, _disk("Р", 1)) == 2
    _write(rm, "РИМ")
    assert _slot(p, _disk("Р", 2)) == 0
    assert p._reg.word_norm == "РИМ"
    assert p._reg.slots_filled == 1


# --- B4, B5, B17, B20: пустое слово — не приход -------------------------------


def test_empty_register_write_rejected() -> None:
    # О2: пустая запись регистра ('', пробелы) — не приход; плагин возвращает действующее слово.
    p, services, rm = _make()
    _port(p, "МИР")
    _write(rm, "")
    p.process([{"predictions": []}])
    _write(rm, "  ")
    p.process([{"predictions": []}])
    assert _slot(p, _disk("Р", 1)) == 2
    assert p._reg.word_norm == "МИР"
    assert _stored(rm) == "МИР"
    assert _lines(services, _CHANGE_MARK) == []
    assert len(_lines(services, _REJECT_MARK)) == 2


def test_empty_port_ignored() -> None:
    p, _, rm = _make()
    _write(rm, "РИМ")
    _port(p, "")
    _port(p, {"word": "  "})
    assert _slot(p, _disk("Р", 1)) == 0
    assert _stored(rm) == "РИМ"


def test_empty_write_keeps_initial_word() -> None:
    # О2 на начальном слове из конфига, порт отключён (word_source '').
    p, _, rm = _make({"target_word": "РИМ", "word_source": ""})
    _write(rm, "")
    assert _slot(p, _disk("Р", 1)) == 0
    assert _stored(rm) == "РИМ"


def test_empty_write_without_word() -> None:
    # Пока слова нет (_own_word пуст), пустая запись не откатывается и ничего не пишет в журнал.
    p, services, rm = _make()
    _write(rm, "  ")
    out = p.process([{"predictions": []}])[0]
    assert out.get("robot_job") is None
    assert _lines(services, _REJECT_MARK) == []
    assert _stored(rm) == "  "
    _port(p, "МИР")
    assert _stored(rm) == "МИР"


# --- B6: журнал называет источник ---------------------------------------------


def test_journal_names_source() -> None:
    p, services, rm = _make()
    _port(p, "МИР")
    _slot(p, _disk("Р", 1))
    _write(rm, "РИМ")
    _slot(p, _disk("Р", 2))
    _port(p, "МИР")
    _slot(p, _disk("Р", 3))

    changes = _lines(services, _CHANGE_MARK)
    assert len(changes) == 2
    assert "смена слова 'МИР' → 'РИМ'" in changes[0]
    assert "источник: регистр" in changes[0]
    assert "смена слова 'РИМ' → 'МИР'" in changes[1]
    assert "источник: порт signal_2" in changes[1]

    first_build = _lines(services, "слово 'МИР' (источник: порт signal_2)")
    assert len(first_build) == 1
    assert _CHANGE_MARK not in first_build[0]


# --- B7, B14: то же слово — не смена ------------------------------------------


def test_same_word_from_register_keeps_cells() -> None:
    p, services, rm = _make()
    _port(p, "МИР")
    assert _slot(p, _disk("Р", 1)) == 2
    _write(rm, "МИР")
    assert _slot(p, _disk("И", 2)) == 1
    assert p._reg.slots_filled == 2
    assert _lines(services, _CHANGE_MARK) == []


def test_case_insensitive_same_word() -> None:
    p, services, rm = _make()
    _port(p, "МИР")
    assert _slot(p, _disk("Р", 1)) == 2
    _write(rm, "мир")
    assert _slot(p, _disk("И", 2)) == 1
    assert p._reg.slots_filled == 2
    assert _lines(services, _CHANGE_MARK) == []


# --- B8–B11: правила C-32 при смене источника ---------------------------------


def test_source_switch_cells_from_zero() -> None:
    p, services, rm = _make()
    _port(p, "МИР")
    assert _slot(p, _disk("М", 1)) == 0
    assert _slot(p, _disk("И", 2)) == 1
    _write(rm, "РИМ")
    assert _slot(p, _disk("Р", 3)) == 0
    assert p._reg.slots_filled == 1
    changes = _lines(services, _CHANGE_MARK)
    assert len(changes) == 1
    assert "было заполнено 2/3" in changes[0]


def test_unmanaged_register_value_change() -> None:
    # Без менеджера: ctx.registers is None, регистр локальный; запись — update_field.
    p, _, rm = _make(managed=False)
    assert rm is None
    _port(p, "МИР")
    assert _slot(p, _disk("Р", 1)) == 2
    assert p._reg.update_field("target_word", "РИМ") == (True, None)
    assert _slot(p, _disk("Р", 2)) == 0


def test_source_switch_keeps_taken_track() -> None:
    p, _, rm = _make()
    _port(p, "МИР")
    assert _slot(p, _disk("Р", 1)) == 2
    _write(rm, "РИМ")
    assert _slot(p, _disk("Р", 1)) is None
    assert _slot(p, _disk("Р", 2)) == 0


def test_reset_keeps_active_word() -> None:
    p, _, rm = _make()
    _port(p, "МИР")
    assert _slot(p, _disk("Р", 1)) == 2
    p.cmd_reset({})
    assert _slot(p, _disk("Р", 2)) == 2
    assert p._reg.word_norm == "МИР"
    assert _stored(rm) == "МИР"


# --- B12, B19: слово с порта лежит в регистре ---------------------------------


def test_initial_register_word() -> None:
    p, _, rm = _make({"target_word": "РИМ"})
    assert _slot(p, _disk("Р", 1)) == 0
    _port(p, "МИР")
    assert _slot(p, _disk("Р", 2)) == 2
    assert _stored(rm) == "МИР"


def test_port_word_lands_in_register() -> None:
    p, _, rm = _make()
    _port(p, "МИР")
    assert _stored(rm) == "МИР"
    assert p._reg.target_word == "МИР"
    _port(p, {"word": "РИМ"})
    assert _stored(rm) == "РИМ"
    assert p._reg.target_word == "РИМ"


# --- B13: путь GUI set_config -------------------------------------------------


def test_set_config_write_is_arrival() -> None:
    p, _, _ = _make()
    _port(p, "МИР")
    assert _slot(p, _disk("Р", 1)) == 2
    assert p.cmd_set_config({"target_word": "РИМ"})["status"] == "ok"
    assert _slot(p, _disk("Р", 2)) == 0
    _port(p, "МИР")
    assert _slot(p, _disk("Р", 3)) == 2
    assert p.cmd_set_config({"target_word": "РИМ"})["status"] == "ok"
    assert _slot(p, _disk("Р", 4)) == 0


# --- B15, B16, B18: порядок внутри item и батча -------------------------------


def test_return_right_after_word_change_has_nothing() -> None:
    p, _, rm = _make({"return_trigger_source": "signal_1"})
    _port(p, "МИР")
    assert _slot(p, _disk("М", 1)) == 0
    _write(rm, "РИМ")
    out = p.process([{"signal_1": 1}])[0]
    assert "robot_return_jobs" not in out
    assert p._reg.word_norm == "РИМ"
    assert p._reg.slots_filled == 0


def test_port_wins_on_same_item() -> None:
    p, _, rm = _make()
    _port(p, "МИР")
    _write(rm, "РИМ")
    assert _slot(p, {**_disk("Р", 1), "signal_2": "МИР"}) == 2
    assert p._reg.word_norm == "МИР"
    assert _stored(rm) == "МИР"


def test_batch_order() -> None:
    p, _, rm = _make()
    _write(rm, "РИМ")
    outs = p.process([{"signal_2": "МИР"}, _disk("Р", 1)])
    assert outs[1]["robot_job"]["slot"] == 2
    assert p._reg.word_norm == "МИР"

    q, _, rm2 = _make()
    _write(rm2, "РИМ")
    outs = q.process([_disk("Р", 1), {"signal_2": "МИР"}])
    assert outs[0]["robot_job"]["slot"] == 0
    assert q._reg.word_norm == "МИР"
