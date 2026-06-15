"""PhoneCameraPlugin — source-плагин «фото с телефона по WiFi».

Поднимает HTTP-сервер (Services.phone_gateway.PhoneGateway) внутри своего
процесса. Сервер можно включать/выключать (команды start_server/stop_server) —
процесс живёт always-on (в base.yaml), а приём телефона — по требованию.

Телефон в той же сети открывает страницу в браузере и отправляет:
    - фото  -> produce() отдаёт его как кадр источника (вместо вебкамеры);
    - слово -> публикуется в state store (processes.<proc>.state.phone.word)
               для режима распознавания букв.

SHM write и IPC send выполняет SourceProducer (GenericProcess) — как у любой камеры.
"""

from __future__ import annotations

import base64
import threading
import time
from typing import Any

import cv2
import numpy as np

from multiprocess_framework.modules.process_module.plugins import PluginContext
from multiprocess_framework.modules.process_module.plugins import Port
from multiprocess_framework.modules.process_module.plugins import ProcessModulePlugin
from multiprocess_framework.modules.process_module.plugins import register_plugin

from Services.phone_gateway import qr as qr_mod
from Services.phone_gateway.gateway import PhoneGateway
from Services.phone_gateway.imaging import letterbox
from Services.phone_gateway.netinfo import local_ip, local_ips

from .registers import PhoneCameraRegisters

# Модуль frame_id для wrap-around (совместим с camera_service/hikvision)
_FRAME_ID_MODULO = 121


@register_plugin(
    "phone_camera",
    category="source",
    description="Фото с телефона по WiFi (вместо вебкамеры) + приём слова",
)
class PhoneCameraPlugin(ProcessModulePlugin):
    """Источник кадров из фотографий, присланных с телефона по WiFi.

    Сервер включается/выключается на лету (Services-вкладка): процесс always-on,
    а приём с телефона — toggle.
    """

    name = "phone_camera"
    category = "source"

    register_class = PhoneCameraRegisters

    inputs: list[Port] = []
    outputs: list[Port] = [
        Port(
            name="frame",
            dtype="image/bgr",
            shape="(H, W, 3)",
            description="BGR-кадр — последнее фото с телефона",
        ),
        # Сигналы пульта (Этап 2): эмитятся по нажатию кнопки в GUI. Вяжи порт к
        # потребителю в редакторе Pipeline (напр. signal_1 → robot_io.job_source
        # для {x_mm,y_mm}; signal_2 → потребитель слова). Полезная нагрузка — dict
        # или строка, кладётся в item[signal_N].
        Port(name="signal_1", dtype="dict", optional=True, description="Сигнал-кнопка 1 (пульт)"),
        Port(name="signal_2", dtype="dict", optional=True, description="Сигнал-кнопка 2 (пульт)"),
        Port(name="signal_3", dtype="dict", optional=True, description="Сигнал-кнопка 3 (пульт)"),
    ]

    commands = {
        "start_server": "cmd_start_server",
        "stop_server": "cmd_stop_server",
        "server_status": "cmd_server_status",
        "get_connection_info": "cmd_get_connection_info",
        "get_word": "cmd_get_word",
        "emit_signal": "cmd_emit_signal",
    }

    # --- Lifecycle ---

    def configure(self, ctx: PluginContext) -> None:
        cfg = ctx.config
        self._ctx = ctx
        self._reg = self._init_register(ctx)

        self._camera_id: int = cfg.get("camera_id", 0)
        self._host: str = cfg.get("host", "0.0.0.0")  # nosec B104 — приём с телефона по LAN
        self._port: int = cfg.get("http_port", 8080)
        self._width: int = cfg.get("resolution_width", 640)
        self._height: int = cfg.get("resolution_height", 480)
        self._auto_start: bool = cfg.get("auto_start", False)
        self._show_hint: bool = cfg.get("show_hint", True)
        self._wifi_ssid: str = cfg.get("wifi_ssid", "")
        self._wifi_password: str = cfg.get("wifi_password", "")

        self._state_proxy = ctx.state_proxy
        self._gateway = PhoneGateway(host=self._host, port=self._port)
        self._frame_count = 0
        self._last_word_seq = -1
        self._last_photo_seq = -1
        self._placeholder: np.ndarray | None = None
        self._url = ""
        # Пульт (Этап 2): очередь сигналов от GUI-кнопок (emit_signal). Команда
        # пишется из потока message_processor, produce() читает из source-потока.
        self._pending_signals: list[tuple[str, Any]] = []
        self._signal_lock = threading.Lock()

        ctx.log_info(
            f"PhoneCameraPlugin[{self._camera_id}]: configured "
            f"(port={self._port}, {self._width}x{self._height}, auto_start={self._auto_start})"
        )

    def start(self, ctx: PluginContext) -> None:
        # Сервер поднимается сразу только если auto_start; иначе — по команде из GUI.
        if self._auto_start:
            self._start_server()
        else:
            self._publish_connection()  # опубликовать running=False (GUI видит «выключен»)

    def shutdown(self, ctx: PluginContext) -> None:
        ctx.log_info(f"PhoneCameraPlugin[{self._camera_id}]: shutdown")
        self._gateway.stop()

    def produce(self) -> list[dict]:
        """Кадр-фото (как камера) + сигнал-items пульта (по нажатию кнопок GUI).

        Возвращает список items: сначала накопленные сигналы (отдельные items без
        кадра — едут в chain_targets, потребитель читает item[signal_N]), затем
        кадр-фото (если сервер включён и есть кадр).
        """
        # Слово и превью-миниатюра — в state (для панели Services → Телефон).
        self._maybe_publish_word()
        self._maybe_publish_thumb()

        items = self._drain_signals()
        frame_item = self._produce_frame()
        if frame_item is not None:
            items.append(frame_item)
        return items

    def _produce_frame(self) -> dict | None:
        """Сформировать кадр-item (или None, если сервер выключен / нет кадра)."""
        if not self._gateway.running:
            return None
        hold = bool(getattr(self._reg, "hold_last", True))
        frame = self._gateway.take_frame(consume=not hold)
        if frame is None:
            if self._placeholder is None:
                return None
            out = self._placeholder
        else:
            out = letterbox(frame, self._width, self._height)

        self._frame_count = (self._frame_count + 1) % _FRAME_ID_MODULO
        return {
            "frame": out,
            "camera_id": self._camera_id,
            "seq_id": self._frame_count,
            "frame_id": self._frame_count,
            "timestamp": time.monotonic(),
            "camera_type": "phone",
            "width": self._width,
            "height": self._height,
            "channels": 3,
            "dtype": "uint8",
        }

    def _drain_signals(self) -> list[dict]:
        """Слить накопленные сигналы пульта в items (по одному на сигнал)."""
        with self._signal_lock:
            if not self._pending_signals:
                return []
            pending = self._pending_signals
            self._pending_signals = []
        items: list[dict] = []
        for port, value in pending:
            items.append({port: value, "data_type": "signal", "camera_id": self._camera_id})
            self._ctx.log_info(f"PhoneCameraPlugin[{self._camera_id}]: сигнал {port} = {value!r}")
        return items

    # --- Управление сервером (toggle) ---

    def _start_server(self) -> dict:
        """Поднять HTTP-сервер (идемпотентно) и опубликовать адрес/QR."""
        self._gateway.start()
        port = self._gateway.port
        self._url = f"http://{local_ip()}:{port}/"
        candidates = ", ".join(f"http://{ip}:{port}/" for ip in local_ips())
        self._ctx.log_info(
            f"PhoneCameraPlugin[{self._camera_id}]: сервер ВКЛ. Адреса для телефона "
            f"(откройте тот, что в сети WiFi телефона): {candidates}. "
            f"При первом запуске разрешите Python в брандмауэре Windows (частные сети)."
        )
        if self._show_hint:
            self._placeholder = self._make_hint(self._url)
        self._publish_connection()
        return {"status": "ok", "running": True, "url": self._url}

    def _stop_server(self) -> dict:
        """Погасить HTTP-сервер (идемпотентно)."""
        self._gateway.stop()
        self._ctx.log_info(f"PhoneCameraPlugin[{self._camera_id}]: сервер ВЫКЛ")
        self._publish_connection()
        return {"status": "ok", "running": False}

    # --- Внутренние методы ---

    def _maybe_publish_word(self) -> None:
        """Опубликовать слово в state store, если пришло новое."""
        if self._state_proxy is None:
            return
        snap = self._gateway.word_snapshot()
        if snap["seq"] == self._last_word_seq:
            return
        self._last_word_seq = snap["seq"]
        if snap["seq"] <= 0:
            return
        path = f"processes.{self._ctx.process_name}.state.phone"
        self._state_proxy.merge(
            path,
            {"word": snap["word"], "word_seq": snap["seq"], "word_ts": snap["ts"]},
        )
        self._ctx.log_info(f"PhoneCameraPlugin[{self._camera_id}]: принято слово '{snap['word']}' (seq={snap['seq']})")

    def _maybe_publish_thumb(self) -> None:
        """Опубликовать base64-миниатюру в state при НОВОМ фото (раз на снимок).

        Это превью для панели Services → Телефон (подтверждение приёма). Полный
        кадр в pipeline идёт через SHM — здесь только лёгкое превью, и только при
        смене кадра (не каждый цикл), иначе спам тяжёлых state-дельт.
        """
        if self._state_proxy is None:
            return
        seq = self._gateway.frame_info()["seq"]
        if seq == self._last_photo_seq or seq <= 0:
            return
        frame = self._gateway.take_frame(consume=False)
        if frame is None:
            return
        self._last_photo_seq = seq
        thumb = self._encode_thumb(frame)
        if thumb:
            self._state_proxy.merge(
                f"processes.{self._ctx.process_name}.state.phone",
                {"photo_thumb": thumb, "photo_seq": seq},
            )

    @staticmethod
    def _encode_thumb(frame: np.ndarray, max_w: int = 320) -> str:
        """BGR-кадр -> base64 JPEG-миниатюра (str). "" при ошибке."""
        try:
            h, w = frame.shape[:2]
            if w > max_w:
                new_h = max(1, int(round(h * max_w / w)))
                frame = cv2.resize(frame, (max_w, new_h), interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
            if not ok:
                return ""
            return base64.b64encode(buf.tobytes()).decode("ascii")
        except Exception:
            return ""

    def _connection_info(self) -> dict:
        """Собрать инфо о подключении (URL + QR + running) для state/команды."""
        info: dict = {
            "running": self._gateway.running,
            "url": self._url,
            "have_qr": qr_mod.have_qr(),
            "qr_svg": qr_mod.make_qr_svg(self._url) or "",
        }
        if self._wifi_ssid:
            info["wifi_qr_svg"] = qr_mod.make_wifi_qr_svg(self._wifi_ssid, self._wifi_password) or ""
        return info

    def _publish_connection(self) -> None:
        """Опубликовать URL + QR + running для отображения в GUI."""
        if self._state_proxy is None:
            return
        self._state_proxy.merge(
            f"processes.{self._ctx.process_name}.state.phone.connection",
            self._connection_info(),
        )

    def _make_hint(self, url: str) -> np.ndarray:
        """Кадр-подсказка с адресом (показывается, пока нет фото).

        cv2.putText (Hershey) не умеет кириллицу — поэтому URL (ASCII) и
        латинская метка. Полные инструкции на русском — в GUI и логах.
        """
        img = np.full((self._height, self._width, 3), 30, dtype=np.uint8)
        cy = self._height // 2
        cv2.putText(
            img,
            "Open on phone (same WiFi):",
            (16, cy - 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (200, 200, 200),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            img,
            url,
            (16, cy + 14),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (80, 200, 255),
            2,
            cv2.LINE_AA,
        )
        return img

    # --- Команды ---

    def cmd_start_server(self, data: dict) -> dict:
        """Включить приём с телефона (поднять HTTP-сервер)."""
        return self._start_server()

    def cmd_stop_server(self, data: dict) -> dict:
        """Выключить приём с телефона (погасить HTTP-сервер)."""
        return self._stop_server()

    def cmd_server_status(self, data: dict) -> dict:
        """Текущий статус сервера + адрес/QR."""
        return {"status": "ok", **self._connection_info()}

    def cmd_get_connection_info(self, data: dict) -> dict:
        """Вернуть URL + QR + running (для GUI)."""
        return {"status": "ok", **self._connection_info()}

    def cmd_get_word(self, data: dict) -> dict:
        """Вернуть последнее принятое слово."""
        snap = self._gateway.word_snapshot()
        return {"status": "ok", **snap}

    def cmd_emit_signal(self, data: dict) -> dict:
        """Эмитировать сигнал пульта на выходной порт (кнопка GUI).

        data: {"port": "signal_1".."signal_3", "value": <payload>}. На ближайшем
        цикле produce() уйдёт item {port: value} в chain_targets — вяжи порт к
        потребителю в редакторе (signal_N → robot_io.job_source для {x_mm,y_mm};
        signal_N → потребитель слова и т.п.).
        """
        port = str(data.get("port", "signal_1"))
        value = data.get("value")
        with self._signal_lock:
            self._pending_signals.append((port, value))
        return {"status": "ok", "port": port}
