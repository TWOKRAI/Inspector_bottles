"""Источник состояния робота ЛИНИИ для окна ``sim_view --line`` (T3.8).

Purpose:
    Отдать видам ``SimView``/``ZScale``/``TimeTape`` то же чтение, что у
    ``RobotSimCoreV2`` (``read``/``joints``/``model``/``_workspace``/``_active``), но
    из снимка ``sim.robot.state``, который публикует ``robot_host`` линии. Своего
    ядра и писателя нет: окно только читает.

Public API:
    ``LINE_STATE_PATH`` — путь снимка в общем мире.
    ``LineRobotState`` — источник: ``update(state)``, ``read``, ``joints``, ``model``,
    ``_workspace``, ``_active``, ``age_s``, ``state_t``. Метода ``write`` нет.
    ``LineLink`` — связь с линией по сокету отладочной двери линии: ``open``,
    ``tick``, ``close``; режимы ``push`` (подписка) и ``poll`` (опрос).

Stability: lite

Потоки. Колбэки ``subscribe`` и ``request_async`` идут на reader-потоке клиента: из них
только ``LineRobotState.update`` (замена одной ссылки). ``connect``, ``on_reconnected`` и
разовые чтения ``state.get_subtree`` вызываются из главного потока (``open``/``tick``).
Своих потоков нет.

Модуль не использует Qt (транзитивно фреймворк подтягивает Qt-модули при импорте
``RemoteStateProxy`` — на работу не влияет).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any

from multiprocess_framework.modules.frontend_module.bridge.remote_state_proxy import RemoteStateProxy
from multiprocess_framework.modules.logger_module import get_std_logger
from multiprocess_framework.modules.router_module.channels.socket_client import SocketClient, SocketConnectionLost
from Services.robot_comm.core.params_v2 import PARAM_ID, PARAMS, to_eng
from Services.robot_comm.core.protocol_v2 import REG
from Services.robot_comm.kinematics import ScaraModel
from Services.robot_comm.programs.geometry import Workspace
from Services.robot_comm.server.sim_core_v2 import _WS_PARAM_NAMES

__all__ = ["LineRobotState", "LineLink", "LINE_STATE_PATH"]

_log = get_std_logger(__name__)

#: путь снимка робота в общем мире линии (публикует ``robot_host``, ``robot_state_hz``)
LINE_STATE_PATH = "sim.robot.state"

#: имя модели, которую вид умеет рисовать
_MODEL_NAME = "ScaraModel"

#: ключи снимка (схема ``_robot_state_snapshot`` в ``Plugins/sim/robot_host/plugin.py``)
_STATE_KEYS = ("pose", "moving", "hand", "joints", "target", "model", "regs", "t")

#: опубликованные блоки регистров: имя в ``regs`` -> (адрес первого слова, длина)
_BLOCKS = {
    "res": (REG["RES_SEQ"], 12),
    "tlm": (REG["TLM_PROTO_VER"], 32),
    "pmir": (REG["PMIR"], 128),
}

#: сколько ждёт разовое чтение ``state.get_subtree`` (главный поток)
_READ_TIMEOUT_S = 2.0

#: адресат команд ``state.*`` на хосте двери
_SERVER_TARGET = "ProcessManager"

_MODES = ("push", "poll")


class LineRobotState:
    """Чтение регистров, суставов и зоны робота из снимка линии (аналог ``RobotSimCoreV2``)."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        #: ``(снимок, момент приёма)`` — заменяется одним присваиванием (поток reader / главный)
        self._data: tuple[dict, float] | None = None
        #: модель вида — одна на источник, по имени класса из снимка
        self.model = ScaraModel()

    def update(self, state: dict) -> None:
        """Принять снимок ``sim.robot.state``.

        Pre:  ``state`` — словарь схемы ``_robot_state_snapshot`` (ключи ``pose``, ``moving``,
              ``hand``, ``joints``, ``target``, ``model``, ``regs``, ``t``); блоки ``regs``
              — списки целых длиной 12 / 32 / 128.
        Post: ``read``/``joints``/``_active`` отдают этот снимок; ``age_s() == 0`` по часам
              источника. Чужая модель или неполная схема — ``ValueError`` с фиксированным
              текстом (значения с провода в текст не входят), прежний снимок не тронут.
        """
        if not isinstance(state, dict) or any(key not in state for key in _STATE_KEYS):
            raise ValueError("снимок линии не по схеме sim.robot.state")
        if state["model"] != _MODEL_NAME:
            raise ValueError(f"модель линии не поддерживается видом: нужна {_MODEL_NAME}")
        regs = state["regs"]
        if not isinstance(regs, dict):
            raise ValueError("снимок линии не по схеме sim.robot.state")
        for name, (_base, length) in _BLOCKS.items():
            block = regs.get(name)
            if not isinstance(block, list) or len(block) != length:
                raise ValueError("снимок линии не по схеме sim.robot.state")
        self._data = (state, self._clock())

    def read(self, address: int, count: int = 1) -> list[int]:
        """Слова ``[address, address + count)`` из блока, целиком содержащего диапазон.

        Pre:  диапазон лежит внутри одного из блоков RES (0x1010, 12), TLM (0x1040, 32),
              PMIR (0x3000, 128).
        Post: копия слов; до первого ``update`` — нули. Диапазон вне блоков или на стыке —
              ``KeyError`` (адрес в текст не входит).
        """
        for name, (base, length) in _BLOCKS.items():
            if base <= address and address + count <= base + length:
                offset = address - base
                if self._data is None:
                    return [0] * count
                return list(self._data[0]["regs"][name][offset : offset + count])
        raise KeyError("адрес вне опубликованных блоков RES/TLM/PMIR")

    def joints(self) -> tuple[float, ...] | None:
        """Суставы из снимка; ``None`` — поза недостижима для модели либо данных ещё нет."""
        if self._data is None:
            return None
        joints = self._data[0]["joints"]
        return None if joints is None else tuple(joints)

    def _workspace(self) -> Workspace:
        """Рабочая зона из зеркала ``PMIR`` (до первого ``update`` — значения по умолчанию).

        ponytail: те же ``_WS_PARAM_NAMES``, что у ядра; публичного списка имён нет, а свой
        список был бы второй правдой о составе зоны.
        """
        eng: dict[str, float] = {}
        for name in _WS_PARAM_NAMES:
            pid = PARAM_ID[name]
            meta = PARAMS[pid]
            if self._data is None:
                value = meta["default"]
            else:
                value = self._data[0]["regs"]["pmir"][pid]
                if meta["signed"] and value >= 0x8000:
                    value -= 65536
            eng[name] = to_eng(name, value)
        return Workspace.from_params(eng)

    @property
    def _active(self) -> dict | None:
        """``{"target": (x, y, z, rz)}`` пока ход идёт, иначе ``None`` (как ``core._active``)."""
        if self._data is None:
            return None
        target = self._data[0]["target"]
        return None if target is None else {"target": tuple(target)}

    def state_t(self) -> float | None:
        """Метка ``t`` последнего снимка по часам публикатора (строка ``[line-view]``); ``None`` — снимка не было."""
        if self._data is None:
            return None
        return float(self._data[0]["t"])

    def age_s(self) -> float | None:
        """Секунд с последнего ``update`` по часам источника; ``None`` — снимка не было."""
        if self._data is None:
            return None
        return self._clock() - self._data[1]


def _subtree_value(envelope: Any) -> dict:
    """Значение поддерева из ответа ``state.get_subtree`` ({} — ответа нет или он не ok).

    Ответ клиента — конверт ``{"success", "result": {"status", "value", ...}}``; ошибки
    клиента (таймаут, обрыв) — ``{"success": False, "error": ...}``.
    """
    if not isinstance(envelope, dict) or envelope.get("success") is False:
        return {}
    inner = envelope.get("result")
    if not isinstance(inner, dict):
        inner = envelope
    if inner.get("status") != "ok":
        return {}
    value = inner.get("value")
    return value if isinstance(value, dict) else {}


class LineLink:
    """Связь окна с линией: сокет отладочной двери, режимы ``push`` и ``poll``, возврат связи.

    ``source`` — :class:`LineRobotState`, который читают виды; ``lost`` — связь потеряна
    (источник держит последний снимок); ``last_error`` — текст последней отвергнутой
    ``update`` либо ``None``.
    """

    def __init__(
        self,
        host: str,
        port: int,
        *,
        mode: str = "push",
        poll_ms: int = 100,
        retry_ms: int = 1000,
        connect_timeout_s: float = 0.5,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if mode not in _MODES:
            raise ValueError("LineLink: mode: допустимо push|poll")
        self.source = LineRobotState(clock=clock)
        self.lost = False
        self.last_error: str | None = None
        self._mode = mode
        self._poll_s = poll_ms / 1000.0
        self._retry_s = retry_ms / 1000.0
        self._connect_timeout_s = connect_timeout_s
        self._clock = clock
        self._client = SocketClient(host, port, sender="sim_view_line")
        self._proxy: RemoteStateProxy | None = None
        self._sub_id: str | None = None
        self._in_flight = False
        self._next_poll_at = 0.0
        self._last_attempt: float | None = None
        self._closed = False

    # ------------------------------------------------------------------ жизненный цикл

    def open(self) -> None:
        """Подключиться, (push) подписаться и прочитать текущий снимок.

        Pre:  вызов из главного потока, один раз.
        Post: сокет открыт; push — подписка на ``sim.robot.state.**``; снимок линии (если он
              есть) принят в ``source``, иначе ``source.age_s() is None``. Хост недоступен —
              ``OSError`` (клиент закрыт); обрыв при чтении — тоже ``OSError``.
        """
        self._client.connect(self._connect_timeout_s)
        try:
            if self._mode == "push":
                self._proxy = RemoteStateProxy(self._client, dispatch=lambda fn: fn())
                self._sub_id = self._proxy.subscribe(
                    LINE_STATE_PATH + ".**", self._on_deltas, exclude_self=True, sync=True
                )
            # Ресинк колбэков не зовёт: текущий снимок берётся разовым чтением.
            self._apply(self._read_subtree())
        except SocketConnectionLost as exc:
            self._client.close()
            raise ConnectionError(f"связь с линией оборвалась при открытии: {exc}") from exc

    def tick(self) -> None:
        """Шаг из таймера окна: учесть обрыв, переподключиться, выдать запрос опроса.

        Pre:  вызов из главного потока.
        Post: обрыв клиента -> ``lost = True`` (``source`` не чистится); пока ``lost`` — одна
              попытка раз в ``retry_ms`` (``close`` -> ``connect`` -> push: ``on_reconnected``
              -> чтение снимка), ``lost = False`` только после всех шагов; poll без
              запроса в полёте — не чаще раза в ``poll_ms`` один ``request_async``.
              Ошибки попытки не бросаются наружу. После ``close`` — no-op.
        """
        if self._closed:
            return
        now = self._clock()
        if self._client.connection_lost:
            self.lost = True
        if self.lost:
            if self._last_attempt is None or now - self._last_attempt >= self._retry_s:
                self._last_attempt = now
                self._reconnect()
            return
        if self._mode == "poll":
            self._poll(now)

    def close(self) -> None:
        """Отписаться (push) и закрыть сокет. Идемпотентна.

        Post: ``tick`` больше ничего не делает; клиент закрыт.
        """
        self._closed = True
        if self._proxy is not None and self._sub_id is not None:
            try:
                self._proxy.unsubscribe(self._sub_id)
            except (OSError, SocketConnectionLost) as exc:
                _log.warning("LineLink.close: отписка не удалась: %s", exc)
            self._sub_id = None
        self._client.close()

    # ------------------------------------------------------------------ внутреннее

    def _reconnect(self) -> None:
        """Один заход протокола реконнекта владельца; неудача оставляет ``lost = True``."""
        try:
            self._client.close()
            self._client.connect(self._connect_timeout_s)
            if self._proxy is not None:
                self._proxy.on_reconnected()
            self._apply(self._read_subtree())
        except (OSError, SocketConnectionLost):
            return
        self._in_flight = False  # запрос старого соединения не вернёт колбэк с флагом
        self.lost = False

    def _poll(self, now: float) -> None:
        if self._in_flight or now < self._next_poll_at:
            return
        self._next_poll_at = now + self._poll_s
        # Флаг — ДО вызова: колбэк может прийти синхронно, ещё внутри request_async.
        self._in_flight = True
        try:
            self._client.request_async(
                self._subtree_message(), self._on_poll_response, timeout=max(1.0, 2 * self._poll_s)
            )
        except BaseException:
            self._in_flight = False
            raise

    def _subtree_message(self) -> dict:
        return {
            "type": "command",
            "sender": self._client.subscriber_address,
            "targets": [_SERVER_TARGET],
            "command": "state.get_subtree",
            "data": {"path": LINE_STATE_PATH, "request_id": str(uuid.uuid4())},
        }

    def _read_subtree(self) -> dict:
        """Разовое чтение снимка (главный поток). Обрыв — ``SocketConnectionLost``."""
        return _subtree_value(self._client.request(self._subtree_message(), timeout=_READ_TIMEOUT_S))

    def _apply(self, value: dict) -> None:
        """Принять снимок в источник; пустой словарь — пути нет, ничего не делаем."""
        if not value:
            return
        try:
            self.source.update(value)
        except ValueError as exc:
            self.last_error = str(exc)
        else:
            self.last_error = None

    def _on_deltas(self, deltas: list) -> None:
        """Колбэк подписки (reader-поток): последняя дельта узла ``sim.robot.state`` со словарём.

        Дельты по листьям ``sim.robot.state.*`` пропускаются: кэш прокси листьевой, а вид
        берёт снимок целиком (образец — ``Plugins/sim/scene_source/plugin.py``).
        """
        value: dict | None = None
        for delta in deltas:
            if delta.path == LINE_STATE_PATH and isinstance(delta.new_value, dict):
                value = delta.new_value
        if value is not None:
            self._apply(value)

    def _on_poll_response(self, envelope: Any) -> None:
        """Колбэк ``request_async`` (reader-поток либо синхронно внутри вызова)."""
        try:
            self._apply(_subtree_value(envelope))
        finally:
            self._in_flight = False
