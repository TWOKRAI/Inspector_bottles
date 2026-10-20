"""Слепые приёмочные тесты T5.3c, часть c2: параметры робота v2 из файла и отказы конфига при подключении.

Purpose:
    Закрепить по брифу ``plans/robot-protocol-v2/tasks/T5.3c.md`` (DESIGN 2, 8, 11-13; REDS 10, 11) и
    ``plans/robot-protocol-v2/tasks/T5.3c.reds.md`` (REDS 13, 14, 15): подключение берёт параметры из ``params.yaml``;
    плохие данные или конфиг оператора отказывают подключению ВИДИМО (``last_error`` с постоянным текстом, ``conn`` не
    ``connected``), а не уходят исключением в ``_process_conn_queue`` плагина (``report_error`` с контекстом
    ``device_hub.connect``); ``P_WDG_TIMEOUT_MS = 0`` отказ в продукте и до записи в робота.

Как устроено:
    * Плагин собирается на ``make_ctx`` (conftest) и работает с настоящим ``DeviceManager``; ``CommandManager`` здесь не
      нужен. Реестр — ровно ``<каталог случая>/devices.yaml``, данные робота — ``<каталог случая>/robot`` (корень данных
      плагина — ``resolved.parent / "robot"``); ``INSPECTOR_DATA_DIR`` снят. Случаи с «чистым каталогом данных» живут в
      своих подкаталогах ``tmp_path``.
    * Робот — ``E2eRig`` (sim v2 по TCP); у каждого случая свой стенд (счётчик ``TLM_CFG_EPOCH`` и события sim не
      тянутся из случая в случай).
    * Публикации хаба читаются из ``ctx.state_proxy``: ``last_error`` — ``merge``, ``conn`` — ``set`` (так их
      публикует ``_publish_state``). Свежесть: каждый случай ищет публикацию, появившуюся ПОСЛЕ отметки перед
      подключением.
    * Формат ``params.yaml`` везде ``{"version": 1, "epoch": N, "values": {...}}``; запись — ``RobotDataStore.write``;
      файл-список (не YAML-словарь) пишется сырыми байтами.
    * Блокирующий вызов идёт под дедлайном (``bounded``: daemon-поток + join).
    * Ожидаемые значения — литералы брифа. Умолчания параметров для «полной карты» берутся из таблицы ``PARAMS`` (это
      ВХОД теста, ожидание от неё не считается).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from Plugins.hub.device_hub.plugin import DeviceHubPlugin
from Plugins.hub.device_hub.tests.conftest import make_ctx
from Services.robot_comm.core.params_v2 import PARAM_ID, PARAMS
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.store import RobotDataStore
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, bounded

_CONNECT_S = 60.0
_CALL_S = 15.0

TEXT_INVALID = "Данные робота не прошли проверку"
TEXT_NOT_DICT = "Файл данных робота не YAML-словарь"
TEXT_BAD_KEY = "Недопустимое имя данных робота"
TEXT_WDG_OFF = "Сторож робота нельзя выключить: P_WDG_TIMEOUT_MS = 0"

_DEV = "r1"


# --------------------------------------------------------------------------------------------------
# Помощники
# --------------------------------------------------------------------------------------------------


def _full_values(**override: int) -> dict[str, int]:
    """Полная карта умолчаний (все имена кроме ``P_CONFIG_EPOCH``) с заменами ``override``."""
    values = {name: int(PARAMS[pid]["default"]) for name, pid in PARAM_ID.items() if name != "P_CONFIG_EPOCH"}
    assert set(override) <= set(values)
    values.update(override)
    return values


def _params_body(epoch: int, values: dict[str, int]) -> dict[str, Any]:
    return {"version": 1, "epoch": epoch, "values": values}


class _Hub:
    """Плагин ``device_hub`` над настоящим ``DeviceManager`` + робот стенда; чтение публикаций хаба."""

    def __init__(self, plugin: DeviceHubPlugin, ctx: Any, base: Path, rig: E2eRig) -> None:
        self.plugin = plugin
        self.ctx = ctx
        self.base = base
        self.rig = rig
        self.store = RobotDataStore(base / "robot")  # только запись файлов теста; плагин читает свой экземпляр

    # --- настройка --------------------------------------------------------------------------

    def upsert(self, dev_id: str = _DEV, params: dict[str, Any] | None = None) -> None:
        """Запись реестра робота v2 на порт стенда; ``params`` — ВСЕГДА заменяет прежние ``entry.params``."""
        entry = {
            "id": dev_id,
            "name": dev_id,
            "kind": "robot",
            "protocol": "delta_v2",
            "transport": {"type": "tcp", "host": "127.0.0.1", "port": self.rig.port, "unit_id": ROBOT_UNIT_ID},
            "params": dict(params or {}),
        }
        assert self.plugin.cmd_device_upsert(entry)["status"] == "ok"

    def write_params(self, epoch: int, values: dict[str, int], dev_id: str = _DEV) -> None:
        """Записать ``params.yaml`` (новый файл или замена: ``base_rev`` берётся из текущего файла)."""
        current = self.store.read(dev_id, "params")
        self.store.write(dev_id, "params", _params_body(epoch, values), base_rev=current.rev)

    # --- действия ---------------------------------------------------------------------------

    def connect(self, dev_id: str = _DEV) -> None:
        """Подключение как в продукте: команда ставит в очередь, supervisor разбирает ``_process_conn_queue``."""
        assert self.plugin.cmd_device_connect({"device_id": dev_id})["status"] == "ok"
        bounded(self.plugin._process_conn_queue, _CONNECT_S)  # исключение плагина наружу не выходит

    # --- наблюдения -------------------------------------------------------------------------

    def last_errors(self, dev_id: str = _DEV) -> list[Any]:
        path = f"devices.state.{dev_id}.last_error"
        return [c.args[1] for c in self.ctx.state_proxy.merge.call_args_list if c.args[0] == path]

    def conns(self, dev_id: str = _DEV) -> list[Any]:
        path = f"devices.state.{dev_id}.conn"
        return [c.args[1] for c in self.ctx.state_proxy.set.call_args_list if c.args[0] == path]

    def connect_health_calls(self) -> list[Any]:
        """``report_error(context="device_hub.connect")``: след перехвата в ``_process_conn_queue`` плагина."""
        return [
            c for c in self.ctx.health.report_error.call_args_list if c.kwargs.get("context") == "device_hub.connect"
        ]

    def sim_events(self, mark: int) -> list[str]:
        return [text for _stamp, text in self.rig.core.events()[mark:]]

    def mark(self, dev_id: str = _DEV) -> tuple[int, int]:
        """Отметка перед подключением: (число ``last_error``, число событий sim)."""
        return len(self.last_errors(dev_id)), len(self.rig.core.events())

    # --- проверки ---------------------------------------------------------------------------

    def assert_refused(self, mark: tuple[int, int], text: str, what: str, dev_id: str = _DEV) -> None:
        """Подключение отклонено видимо: свежий ``last_error`` ровно ``text``, ``conn`` не ``connected``, без health."""
        errors = self.last_errors(dev_id)
        assert len(errors) > mark[0], f"{what}: last_error не опубликован после отметки"
        assert errors[-1] == text, f"{what}: last_error={errors[-1]!r}"
        conns = self.conns(dev_id)
        assert conns, f"{what}: conn не публиковался"
        assert conns[-1] != {"conn": "connected"}, f"{what}: conn={conns[-1]!r}"
        assert self.connect_health_calls() == [], f"{what}: перехват ушёл в _process_conn_queue (report_error)"

    def assert_connected(self, what: str) -> None:
        conns = self.conns()
        assert conns and conns[-1] == {"conn": "connected"}, f"{what}: conn={conns[-1:] if conns else conns!r}"


@contextmanager
def _hub(base: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Hub]:
    """Стенд + плагин (configure/start) в каталоге ``base``; на выходе ``shutdown`` плагина и стенда."""
    monkeypatch.delenv("INSPECTOR_DATA_DIR", raising=False)
    base.mkdir(parents=True, exist_ok=True)
    registry = base / "devices.yaml"
    with E2eRig() as rig:
        ctx = make_ctx({"registry_path": str(registry)}, tmp_registry=registry)
        plugin = DeviceHubPlugin()
        plugin.configure(ctx)
        plugin.start(ctx)
        try:
            yield _Hub(plugin, ctx, base, rig)
        finally:
            bounded(lambda: plugin.shutdown(ctx), _CALL_S)


def _param(rig: E2eRig, name: str) -> int:
    return bounded(lambda: rig.client.param_get(name), _CALL_S)


# --------------------------------------------------------------------------------------------------
# REDS 10, 11
# --------------------------------------------------------------------------------------------------


def test_connect_takes_params_from_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RED 10: ``params.yaml`` (``P_SPD_DEFAULT: 55``, ``epoch: 9``) -> после подключения робот несёт 55 и метку 9."""
    with _hub(tmp_path, monkeypatch) as hub:
        hub.upsert()
        hub.write_params(9, _full_values(P_SPD_DEFAULT=55))
        hub.connect()
        hub.assert_connected("подключение при исправном файле")
        assert hub.rig.read("TLM_CFG_EPOCH") == [9]
        assert _param(hub.rig, "P_SPD_DEFAULT") == 55


def test_bad_params_file_rejects_connect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RED 11: вне 1..100, неизвестное имя в ``robot_params``, файл-список, id из 65 символов -> видимый отказ."""
    # (а) значение вне границ таблицы; затем файл исправлен -> следующее подключение проходит
    with _hub(tmp_path / "a", monkeypatch) as hub:
        hub.upsert()
        hub.write_params(9, _full_values(P_SPD_DEFAULT=500))
        mark = hub.mark()
        hub.connect()
        hub.assert_refused(mark, TEXT_INVALID, "файл P_SPD_DEFAULT=500")
        hub.write_params(9, _full_values(P_SPD_DEFAULT=55))
        hub.connect()
        hub.assert_connected("файл исправлен")
        assert _param(hub.rig, "P_SPD_DEFAULT") == 55

    # (б) неизвестное имя в entry.params["robot_params"], файла нет
    with _hub(tmp_path / "b", monkeypatch) as hub:
        hub.upsert(params={"robot_params": {"P_NOPE": 1}})
        mark = hub.mark()
        hub.connect()
        hub.assert_refused(mark, TEXT_INVALID, "robot_params P_NOPE без файла")

    # (в) params.yaml - не YAML-словарь (список; RobotDataStore.write со списком сам бросает, поэтому сырые байты)
    with _hub(tmp_path / "c", monkeypatch) as hub:
        hub.upsert()
        path = hub.base / "robot" / _DEV / "params.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"- 1\n- 2\n")
        mark = hub.mark()
        hub.connect()
        hub.assert_refused(mark, TEXT_NOT_DICT, "params.yaml - список")

    # (г) id реестра из 65 символов (предела длины в реестре нет; ключ хранилища - [a-z0-9_]{1,64})
    long_id = "a" * 65
    with _hub(tmp_path / "d", monkeypatch) as hub:
        hub.upsert(dev_id=long_id)
        mark = hub.mark(long_id)
        hub.connect(long_id)
        hub.assert_refused(mark, TEXT_BAD_KEY, "id из 65 символов", dev_id=long_id)


# --------------------------------------------------------------------------------------------------
# REDS 13, 14, 15
# --------------------------------------------------------------------------------------------------


def test_wdg_zero_rejects_connect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RED 13: ``P_WDG_TIMEOUT_MS = 0`` (файл, override, исправный файл + override) -> отказ с текстом сторожа.

    Ни одной записи ``PARAM_SET`` в робота до отказа. Контроль: 5000 проходит (600 дало бы период пульса 0,15 с меньше
    тика хаба 0,5 с, подключение вышло бы с ``TEXT_WDG_INTERVAL``); в контроле ``PARAM_SET`` ЕСТЬ - иначе проверка
    «нет PARAM_SET» в отказах была бы пустой.
    """
    cases = {
        "а: файл с нулём": (_full_values(P_WDG_TIMEOUT_MS=0), None),
        "б: override без файла": (None, {"robot_params": {"P_WDG_TIMEOUT_MS": 0}}),
        "в: исправный файл + override": (_full_values(), {"robot_params": {"P_WDG_TIMEOUT_MS": 0}}),
    }
    for index, (what, (file_values, entry_params)) in enumerate(cases.items()):
        with _hub(tmp_path / f"case{index}", monkeypatch) as hub:
            hub.upsert(params=entry_params)
            if file_values is not None:
                hub.write_params(1, file_values)
            mark = hub.mark()
            hub.connect()
            hub.assert_refused(mark, TEXT_WDG_OFF, what)
            writes = [t for t in hub.sim_events(mark[1]) if "op=PARAM_SET" in t]
            assert writes == [], f"{what}: в робота ушли записи {writes[:3]}"

    with _hub(tmp_path / "control", monkeypatch) as hub:
        hub.upsert()
        hub.write_params(1, _full_values(P_WDG_TIMEOUT_MS=5000))
        mark = hub.mark()
        hub.connect()
        hub.assert_connected("контроль: P_WDG_TIMEOUT_MS=5000")
        assert hub.connect_health_calls() == []
        assert any("op=PARAM_SET" in t for t in hub.sim_events(mark[1])), "контроль: синхронизации не было"
        assert _param(hub.rig, "P_WDG_TIMEOUT_MS") == 5000


def test_strict_int_overrides_rejected_visibly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RED 14: ``robot_params`` ``50.0`` / ``True`` / ``"50"`` без файла -> отказ, значение в текст не попало."""
    bad = [50.0, True, "50"]
    for index, value in enumerate(bad):
        what = f"robot_params P_SPD_DEFAULT={value!r}"
        with _hub(tmp_path / f"case{index}", monkeypatch) as hub:
            hub.upsert(params={"robot_params": {"P_SPD_DEFAULT": value}})
            mark = hub.mark()
            hub.connect()
            hub.assert_refused(mark, TEXT_INVALID, what)
            assert "50" not in hub.last_errors()[-1], what

    with _hub(tmp_path / "control", monkeypatch) as hub:
        hub.upsert(params={"robot_params": {"P_SPD_DEFAULT": 50}})
        hub.connect()
        hub.assert_connected("контроль: P_SPD_DEFAULT=50")
        assert hub.connect_health_calls() == []
        assert _param(hub.rig, "P_SPD_DEFAULT") == 50


def test_bad_override_with_existing_file_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RED 15: исправный файл + неизвестное имя в ``robot_params`` -> отказ; override при файле не применяется."""
    with _hub(tmp_path, monkeypatch) as hub:
        hub.upsert(params={"robot_params": {"P_NOPE": 1}})
        hub.write_params(9, _full_values(P_SPD_DEFAULT=55))
        mark = hub.mark()
        hub.connect()
        hub.assert_refused(mark, TEXT_INVALID, "файл 55 + robot_params P_NOPE")

        hub.upsert(params={"robot_params": {"P_SPD_DEFAULT": 30}})
        hub.connect()
        hub.assert_connected("файл 55 + override 30")
        assert _param(hub.rig, "P_SPD_DEFAULT") == 55
        assert hub.rig.read("TLM_CFG_EPOCH") == [9]
