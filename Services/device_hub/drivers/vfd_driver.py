"""VfdDriver — драйвер ПЧ INVT GD20 для device_hub.

Порт семантики из Plugins/control/vfd_control (poll + ensure_alive + команды).

DRAW-gating (У4): если носитель-робот (bridge) в режиме DRAW, Lua не обслуживает
VFD_FLAG -> heartbeat замёрзнет -> ложный VfdBridgeStaleError. Вместо poll
возвращаем snapshot quality=stale, reason="carrier busy".

Для tcp-транспорта (будущий прямой RTU) carrier'а нет — poll всегда.
"""

from __future__ import annotations

from typing import Any

from Services.device_hub.drivers.base import BaseDeviceDriver

# Минимальный интервал между попытками (ре)подключения VFD, сек
_VFD_RECONNECT_THROTTLE_SEC = 3.0


class VfdDriver(BaseDeviceDriver):
    """Драйвер ПЧ: run/stop/set_freq/reset_fault + poll-зеркало.

    Args:
        entry:          DeviceEntry с kind=vfd.
        protocol:       DeviceProtocol (gd20_bridge / gd20_direct).
        resolve_device: Функция (id) -> driver для получения носителя (bridge).
        transport:      Инъекция RegisterTransport для тестов.
        clock/sleep:    Инъекция времени.
    """

    kind = "vfd"

    def __init__(
        self,
        entry: Any,
        protocol: Any = None,
        *,
        resolve_device: Any = None,
        transport: Any = None,
        clock: Any = None,
        sleep: Any = None,
    ) -> None:
        super().__init__(entry, protocol, clock=clock, sleep=sleep)
        self._resolve_device = resolve_device
        self._injected_transport = transport
        self._vfd_client: Any = None
        self._bridge_alive: bool = False

        # Параметры из entry.params
        self._poll_interval_s: float = float(entry.params.get("poll_interval_s", 0.5))
        self._last_poll: float = 0.0

        # НР-2: throttle для reconnect при desired=True + not connected.
        # -inf чтобы первая попытка прошла сразу (аналог robot_driver).
        self._last_reconnect: float = float("-inf")

    # ------------------------------------------------------------------ #
    # Соединение
    # ------------------------------------------------------------------ #

    @property
    def is_connected(self) -> bool:
        """ПЧ подключён, если его транспорт (мост) подключён."""
        if self._vfd_client is not None:
            return self._vfd_client.is_connected
        return False

    def connect(self) -> bool:
        """Создать VfdClient поверх транспорта (bridge -> носитель, tcp -> own).

        н7: транспорт получается исключительно через build_transport, который
        валидирует kind носителя и цикл. TransportBuildError -> quality=bad +
        сообщение в last_error (через _record_err и пробрасывание исключения).
        """
        if self._vfd_client is not None:
            return self._vfd_client.is_connected

        from Services.device_hub.errors import TransportBuildError

        try:
            transport = self._get_transport()
        except TransportBuildError:
            # Понятная ошибка: носитель не существует / не robot / цикл
            self._last_quality = "bad"
            self._record_err()
            raise  # Пусть caller (DeviceManager.connect) логирует
        if transport is None:
            self._last_quality = "bad"
            return False

        from Services.vfd_comm import VfdClient, VfdConfig

        register_map = None
        if self.protocol is not None:
            register_map = self.protocol.register_map

        vfd_config = VfdConfig.from_dict(self.entry.params)

        kwargs: dict[str, Any] = {}
        if register_map is not None:
            kwargs["register_map"] = register_map

        self._vfd_client = VfdClient(transport, vfd_config, **kwargs)

        # VFD не имеет собственного connect — делегирует транспорту
        connected = self._vfd_client.is_connected
        self._last_quality = "good" if connected else "bad"
        return connected

    def disconnect(self) -> None:
        """VFD не владеет соединением — просто отпускаем клиента."""
        self._vfd_client = None
        self._last_quality = "bad"

    def set_degraded(self) -> None:
        """Перевести в деградированное состояние (носитель отключился)."""
        self._vfd_client = None
        self._last_quality = "bad"
        self._bridge_alive = False

    # ------------------------------------------------------------------ #
    # Tick
    # ------------------------------------------------------------------ #

    def tick(self, stop_event: Any = None) -> dict | None:
        """Один шаг: reconnect при desired + not connected, DRAW-gating, poll.

        НР-2 ревью Fable: если desired_connected=True но VFD не подключён
        (напр. носитель-робот был offline при первом connect), пытаемся
        (ре)подключиться через build_transport с throttle. Это позволяет
        bridged-VFD автоматически подняться когда робот-носитель появится.
        """
        if self._vfd_client is None or not self.is_connected:
            if not self.desired_connected:
                return self.snapshot(quality="bad")
            # НР-2: throttled reconnect — пробуем (ре)подключиться
            return self._attempt_reconnect()

        # DRAW-gating (У4): проверяем режим носителя
        if self._is_carrier_in_draw():
            return self.snapshot(
                data={"reason": "carrier busy", "bridge_alive": self._bridge_alive},
                quality="stale",
            )

        # Throttle poll
        now = self._clock()
        if now - self._last_poll < self._poll_interval_s:
            return None
        self._last_poll = now

        try:
            t0 = self._clock()
            status = self._vfd_client.poll()
            latency = (self._clock() - t0) * 1000
            self._record_ok(latency)
        except Exception:
            self._record_err()
            return self.snapshot(quality="bad")

        # Проверка живости моста
        try:
            self._vfd_client.ensure_alive()
            self._bridge_alive = True
        except Exception:
            self._bridge_alive = False

        return self.snapshot(
            data={**status.to_dict(), "bridge_alive": self._bridge_alive},
            quality="good" if self._bridge_alive else "stale",
        )

    # ------------------------------------------------------------------ #
    # Call — диспетчер операций ПЧ
    # ------------------------------------------------------------------ #

    def call(self, op: str, args: dict) -> dict:
        """Диспетчер операций ПЧ."""
        handler = self._OPS.get(op)
        if handler is None:
            return {"status": "error", "message": f"Неизвестная операция ПЧ: {op!r}"}
        try:
            return handler(self, args)
        except Exception as exc:
            self._record_err()
            return {"status": "error", "message": str(exc)}

    def _op_run(self, args: dict) -> dict:
        freq = args.get("freq")
        reverse = bool(args.get("reverse", False))
        self._vfd_client.run(
            float(freq) if freq is not None else None,
            reverse=reverse,
        )
        self._record_ok()
        return {"status": "ok", "freq": freq, "reverse": reverse}

    def _op_set_freq(self, args: dict) -> dict:
        hz = float(args["hz"])
        self._vfd_client.set_freq(hz)
        self._record_ok()
        return {"status": "ok", "hz": hz}

    def _op_stop(self, _args: dict) -> dict:
        self._vfd_client.stop()
        self._record_ok()
        return {"status": "ok"}

    def _op_reset_fault(self, _args: dict) -> dict:
        self._vfd_client.reset_fault()
        self._record_ok()
        return {"status": "ok"}

    def _op_get_status(self, _args: dict) -> dict:
        status = self._vfd_client.poll()
        self._record_ok()
        return {
            "status": "ok",
            "vfd": status.to_dict(),
            "bridge_alive": self._bridge_alive,
        }

    _OPS: dict[str, Any] = {
        "run": _op_run,
        "set_freq": _op_set_freq,
        "stop": _op_stop,
        "reset_fault": _op_reset_fault,
        "get_status": _op_get_status,
    }

    # ------------------------------------------------------------------ #
    # Reconnect (НР-2)
    # ------------------------------------------------------------------ #

    def _attempt_reconnect(self) -> dict:
        """Throttled reconnect при desired=True + not connected.

        Возвращает snapshot: quality=bad + reason при неудаче.
        Не спамит connect каждый тик — throttle через _last_reconnect.
        """
        now = self._clock()
        if now - self._last_reconnect < _VFD_RECONNECT_THROTTLE_SEC:
            return self.snapshot(
                data={"reason": "ожидание повторного подключения"},
                quality="bad",
            )
        self._last_reconnect = now
        self._record_reconnect()
        try:
            ok = self.connect()
        except Exception:
            ok = False
        if ok:
            return self.snapshot(quality="good")
        return self.snapshot(
            data={"reason": "носитель не готов или транспорт недоступен"},
            quality="bad",
        )

    # ------------------------------------------------------------------ #
    # Служебное
    # ------------------------------------------------------------------ #

    def _get_transport(self) -> Any:
        """Получить RegisterTransport: инъекция или build_transport (единый путь, н7).

        Ранее bridge резолвился напрямую через resolve_device, минуя валидацию
        в build_transport (_build_bridge: проверка kind носителя, цикл, None-transport).
        Теперь все типы (bridge/tcp/rtu) проходят через build_transport, который
        кидает TransportBuildError с понятным сообщением — silent-None исключён.
        """
        if self._injected_transport is not None:
            return self._injected_transport

        from Services.device_hub.errors import TransportBuildError
        from Services.device_hub.transports import build_transport

        try:
            return build_transport(self.entry, self._resolve_device or (lambda _: None))
        except TransportBuildError:
            # Пробрасываем как есть — caller (connect) обработает и вернёт quality=bad
            raise

    def _is_carrier_in_draw(self) -> bool:
        """Проверить, в режиме ли DRAW носитель-робот (bridge gating)."""
        t_type = self.entry.transport.get("type", "")
        if t_type != "bridge":
            return False  # tcp/rtu — poll всегда

        bridge_id = self.entry.transport.get("bridge", "")
        if not bridge_id or self._resolve_device is None:
            return False

        carrier = self._resolve_device(bridge_id)
        if carrier is None:
            return False

        mode = getattr(carrier, "mode", "cvt")
        return mode == "draw"
