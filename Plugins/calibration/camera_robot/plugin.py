"""CameraRobotCalibrationPlugin — оркестратор разовой калибровки камера↔робот↔энкодер.

Сидит в калибровочном рецепте после circle_detector: кэширует найденные центры
(``detections``), общается с роботом/лентой через DeviceHubClient и собирает
гомографию px→мм + вектор ленты (см. :mod:`geometry`), результат пишет в
``config/calibration/<camera_id>.yaml`` (см. :mod:`store`).

Потоковая модель (паттерн robot_io, потокобезопасность критична):
  - ``process()`` (приёмный поток): кэширует detections/overlay под ``_lock``,
    рисует аннотации на КОПИИ кадра, пробрасывает дальше. НЕ блокирует.
  - Командные методы (IPC-поток): кладут действие в очередь и сразу возвращают ack.
  - LOOP-worker ``_calibration_worker`` — ЕДИНСТВЕННЫЙ владелец state машины:
    забирает действие, делает блокирующий ``DeviceHubClient.request``, считает
    математику, публикует прогресс в ``calibration.state.<camera_id>.progress``.

Refs: plans/camera-robot-calibration.md (Ф3)
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from queue import Empty, Queue
from typing import Any

import cv2
import numpy as np

from multiprocess_framework.modules.process_module.plugins import (
    ExecutionMode,
    PluginContext,
    Port,
    ProcessModulePlugin,
    ThreadConfig,
    register_plugin,
)

from Plugins.hub.device_hub.client import DeviceHubClient

from . import geometry
from .registers import CameraRobotCalibrationRegisters
from .store import save_calibration

# Таймаут IPC-запроса к hub, сек.
_HUB_TIMEOUT = 2.0
# Интервал поллинга очереди действий в воркере, сек.
_QUEUE_POLL_S = 0.05
# Роли 5 точек (порядок order_points: 4 угла + центр).
_ROLES = ("corner_tl", "corner_tr", "corner_br", "corner_bl", "center")


class CalibrationError(Exception):
    """Ожидаемая ошибка хода калибровки (предусловие/валидация) — публикуется в state."""


@register_plugin(
    "camera_robot_calibration",
    category="calibration",
    description="Визард калибровки камера↔робот: гомография px→мм + вектор ленты по энкодеру",
)
class CameraRobotCalibrationPlugin(ProcessModulePlugin):
    """Оркестратор калибровки: detections + телеметрия робота → config/calibration/<id>.yaml."""

    name = "camera_robot_calibration"
    category = "calibration"
    thread_safe = False  # stateful: накапливает px/mm/enc по шагам визарда

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Кадр (аннотируется точками)"),
        Port(name="detections", dtype="list[dict]", optional=True, description="Круги от circle_detector"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Кадр с найденными/нумерованными точками"),
    ]

    commands = {
        "cal_begin": "cmd_begin",
        "cal_capture_image": "cmd_capture_image",
        "cal_set_robot_point": "cmd_set_robot_point",
        "cal_encoder_scale": "cmd_encoder_scale",
        "cal_belt_run": "cmd_belt_run",
        "cal_belt_stop": "cmd_belt_stop",
        "cal_compute": "cmd_compute",
        "cal_save": "cmd_save",
        "cal_reset": "cmd_reset",
    }

    register_class = CameraRobotCalibrationRegisters

    @classmethod
    def config_class(cls) -> type | None:
        """Явный config_class → резолв register_bindings при discovery."""
        from .config import CameraRobotCalibrationConfig

        return CameraRobotCalibrationConfig

    # ------------------------------------------------------------------ #
    # LIFECYCLE
    # ------------------------------------------------------------------ #

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._reg: CameraRobotCalibrationRegisters = self._init_register(ctx)
        self._lock = threading.Lock()
        self._queue: Queue[dict] = Queue()
        self._client: DeviceHubClient | None = None
        self._last_detections: list[dict] = []
        self._overlay: list[tuple[float, float, str]] | None = None
        self._reset_state()
        ctx.log_info(
            f"CameraRobotCalibration: configured (camera={self._reg.camera_id}, "
            f"robot={self._reg.robot_id}, vfd={self._reg.vfd_id})"
        )

    def start(self, ctx: PluginContext) -> None:
        self._client = DeviceHubClient(ctx)
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker("calibration_worker", self._calibration_worker, cfg, auto_start=True)
        ctx.log_info("CameraRobotCalibration: started (calibration_worker запущен)")

    def shutdown(self, ctx: PluginContext) -> None:
        with self._lock:
            self._client = None
        ctx.log_info("CameraRobotCalibration: shutdown")

    # ------------------------------------------------------------------ #
    # PROCESS — кэш detections + аннотация кадра (НЕ блокирует)
    # ------------------------------------------------------------------ #

    def process(self, items: list[dict]) -> list[dict]:
        for item in items:
            dets = item.get("detections")
            with self._lock:
                if isinstance(dets, list):
                    self._last_detections = dets
                overlay = self._overlay
                live = list(self._last_detections)
            frame = item.get("frame")
            if isinstance(frame, np.ndarray) and frame.ndim == 3:
                item["frame"] = self._annotate(frame, live, overlay)
        return items

    def _annotate(
        self,
        frame: np.ndarray,
        detections: list[dict],
        overlay: list[tuple[float, float, str]] | None,
    ) -> np.ndarray:
        """Нарисовать live-детекции (зелёные) + захваченные нумерованные точки (красные)."""
        out = frame.copy()  # не мутировать SHM-буфер
        for d in detections:
            if not isinstance(d, dict):
                continue
            ctr = d.get("center")
            if isinstance(ctr, (list, tuple)) and len(ctr) >= 2:
                cx, cy = int(round(float(ctr[0]))), int(round(float(ctr[1])))
                cv2.circle(out, (cx, cy), 4, (0, 255, 0), -1)
        if overlay:
            for x, y, label in overlay:
                cx, cy = int(round(x)), int(round(y))
                cv2.circle(out, (cx, cy), 9, (0, 0, 255), 2)
                cv2.putText(out, label, (cx + 10, cy - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        return out

    # ------------------------------------------------------------------ #
    # COMMANDS (IPC-поток) — только enqueue + ack
    # ------------------------------------------------------------------ #

    def cmd_begin(self, data: dict) -> dict:
        return self._enqueue("begin", data)

    def cmd_capture_image(self, data: dict) -> dict:
        return self._enqueue("capture_image", data)

    def cmd_set_robot_point(self, data: dict) -> dict:
        return self._enqueue("set_robot_point", data)

    def cmd_encoder_scale(self, data: dict) -> dict:
        return self._enqueue("encoder_scale", data)

    def cmd_belt_run(self, data: dict) -> dict:
        return self._enqueue("belt_run", data)

    def cmd_belt_stop(self, data: dict) -> dict:
        return self._enqueue("belt_stop", data)

    def cmd_compute(self, data: dict) -> dict:
        return self._enqueue("compute", data)

    def cmd_save(self, data: dict) -> dict:
        return self._enqueue("save", data)

    def cmd_reset(self, data: dict) -> dict:
        return self._enqueue("reset", data)

    def _enqueue(self, action: str, args: dict | None) -> dict:
        self._queue.put({"action": action, "args": args or {}})
        return {"status": "accepted", "action": action}

    # ------------------------------------------------------------------ #
    # WORKER — единственный владелец state-машины
    # ------------------------------------------------------------------ #

    def _calibration_worker(self, stop_event: Any, pause_event: Any) -> None:
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            try:
                action = self._queue.get(timeout=_QUEUE_POLL_S)
            except Empty:
                continue
            self._dispatch(action)

    def _dispatch(self, action_item: dict) -> None:
        action = action_item.get("action")
        args = action_item.get("args") or {}
        handler = {
            "begin": self._do_begin,
            "capture_image": self._do_capture_image,
            "set_robot_point": self._do_set_robot_point,
            "encoder_scale": self._do_encoder_scale,
            "belt_run": self._do_belt_run,
            "belt_stop": self._do_belt_stop,
            "compute": self._do_compute,
            "save": self._do_save,
            "reset": self._do_reset,
        }.get(action)
        self._state["error"] = None
        if handler is None:
            self._state["error"] = f"неизвестное действие: {action}"
        else:
            try:
                handler(args)
            except (CalibrationError, ValueError) as exc:
                self._state["error"] = str(exc)
            except Exception as exc:  # noqa: BLE001 — не валим воркер
                self._state["error"] = f"внутренняя ошибка: {exc}"
                if self._ctx is not None:
                    self._ctx.log_error(f"CameraRobotCalibration: {action} упало: {exc}")
        self._publish()

    # --- Действия (исполняются в воркере) ---

    def _do_begin(self, args: dict) -> None:
        for key in ("camera_id", "robot_id", "vfd_id"):
            if args.get(key):
                self._reg.update_field(key, str(args[key]))
        self._reset_state()
        self._state["message"] = "Сессия калибровки начата. Снимите кадр эталона."

    def _do_capture_image(self, args: dict) -> None:
        with self._lock:
            dets = list(self._last_detections)
        expected = int(self._reg.expected_points)
        if len(dets) != expected:
            raise CalibrationError(
                f"Найдено {len(dets)} точек вместо {expected}. Подстройте hsv_mask/circle_detector и повторите."
            )
        pts = []
        for d in dets:
            ctr = d.get("center")
            if not isinstance(ctr, (list, tuple)) or len(ctr) < 2:
                raise CalibrationError("Детекция без поля center — несовместимый формат detections.")
            pts.append((float(ctr[0]), float(ctr[1])))
        corners, center = geometry.order_points(pts)  # ValueError → ловится в _dispatch
        ordered = [*corners, center]
        _, enc = self._read_telemetry()
        self._state.update(
            px=ordered,
            roles=list(_ROLES),
            e_capture=enc,
            mm=[None] * 5,
            enc_i=[None] * 5,
            mm_per_count=None,
            belt_dir=None,
            homography=None,
            reproj=None,
            passed=False,
            saved_path=None,
            phase="points",
            message=f"Кадр снят: {expected} точек, E0={enc}. Наводите робота по номерам 1..{expected}.",
        )
        self._set_overlay(ordered)

    def _do_set_robot_point(self, args: dict) -> None:
        if self._state["px"] is None:
            raise CalibrationError("Сначала снимите кадр (cal_capture_image).")
        idx = int(args.get("index", -1))
        if not 0 <= idx < 5:
            raise CalibrationError(f"index {idx} вне диапазона 0..4")
        pos, enc = self._read_telemetry()
        self._state["mm"][idx] = [pos[0], pos[1]]
        self._state["enc_i"][idx] = enc
        collected = sum(1 for m in self._state["mm"] if m is not None)
        self._state["message"] = (
            f"Точка {idx + 1} ({_ROLES[idx]}): x={pos[0]:.1f} y={pos[1]:.1f} enc={enc} — собрано {collected}/5"
        )

    def _do_encoder_scale(self, args: dict) -> None:
        ref = int(args.get("ref_index", 0))
        if not 0 <= ref < 5:
            raise CalibrationError(f"ref_index {ref} вне диапазона 0..4")
        mm = self._state["mm"]
        enc_i = self._state["enc_i"]
        if mm[ref] is None or enc_i[ref] is None:
            raise CalibrationError(f"Точка {ref + 1} ещё не снята роботом — нельзя взять её как репер.")
        pos2, enc_b = self._read_telemetry()
        mm_per_count, belt_dir = geometry.belt_vector(
            (mm[ref][0], mm[ref][1]), pos2, enc_i[ref], enc_b
        )  # ValueError → _dispatch
        self._state["mm_per_count"] = mm_per_count
        self._state["belt_dir"] = [belt_dir[0], belt_dir[1]]
        self._state["message"] = (
            f"Масштаб ленты: {mm_per_count:.5f} мм/count, направление ({belt_dir[0]:.3f}, {belt_dir[1]:.3f})"
        )

    def _do_belt_run(self, args: dict) -> None:
        freq = float(args.get("freq", args.get("freq_hz", 0.0)))
        self._hub_call("vfd_run", {"device_id": self._state["vfd_id"], "freq_hz": freq})
        self._state["message"] = f"Лента пущена: {freq} Гц"

    def _do_belt_stop(self, args: dict) -> None:
        self._hub_call("vfd_stop", {"device_id": self._state["vfd_id"]})
        self._state["message"] = "Лента остановлена"

    def _do_compute(self, args: dict) -> None:
        px = self._state["px"]
        mm = self._state["mm"]
        enc_i = self._state["enc_i"]
        e0 = self._state["e_capture"]
        mpc = self._state["mm_per_count"]
        belt = self._state["belt_dir"]
        if px is None:
            raise CalibrationError("Нет снятого кадра.")
        if any(m is None for m in mm):
            raise CalibrationError("Сняты роботом не все 5 точек.")
        if mpc is None or belt is None:
            raise CalibrationError("Не задан масштаб ленты (cal_encoder_scale).")
        belt_dir = (belt[0], belt[1])
        mm_fixed = [geometry.compensate((mm[i][0], mm[i][1]), enc_i[i], e0, mpc, belt_dir) for i in range(5)]
        h = geometry.fit_homography(px[:4], mm_fixed[:4])  # ValueError → _dispatch
        err = geometry.reprojection_error(h, px, mm_fixed, center_index=4)
        passed = err["center_mm"] <= float(self._reg.reproj_threshold_mm)
        self._state["homography"] = h.tolist()
        self._state["reproj"] = {
            "center": round(err["center_mm"], 4),
            "mean": round(err["mean_mm"], 4),
            "max": round(err["max_mm"], 4),
        }
        self._state["passed"] = bool(passed)
        verdict = "OK" if passed else f"ПРЕВЫШЕН ПОРОГ {self._reg.reproj_threshold_mm} мм"
        self._state["message"] = (
            f"reproj центр={err['center_mm']:.3f}мм mean={err['mean_mm']:.3f} max={err['max_mm']:.3f} → {verdict}"
        )

    def _do_save(self, args: dict) -> None:
        if self._state["homography"] is None:
            raise CalibrationError("Сначала вычислите (cal_compute).")
        if not self._state["passed"]:
            raise CalibrationError("Калибровка не прошла порог reproj — сохранение отклонено.")
        payload = self._build_payload()
        path = save_calibration(self._state["camera_id"], payload)
        self._state["saved_path"] = str(path)
        self._state["phase"] = "saved"
        self._state["message"] = f"Калибровка сохранена: {path}"

    def _do_reset(self, args: dict) -> None:
        self._reset_state()
        self._state["message"] = "Сброшено."

    # --- Вспомогательные ---

    def _build_payload(self) -> dict:
        s = self._state
        points = [
            {
                "px": [s["px"][i][0], s["px"][i][1]],
                "mm": [s["mm"][i][0], s["mm"][i][1]],
                "enc": s["enc_i"][i],
                "role": s["roles"][i],
            }
            for i in range(5)
        ]
        return {
            "camera_id": s["camera_id"],
            "robot_id": s["robot_id"],
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "transform": "homography",
            "px_to_mm": s["homography"],
            "encoder": {
                "e_capture": s["e_capture"],
                "mm_per_count": s["mm_per_count"],
                "belt_dir_mm": s["belt_dir"],
            },
            "reproj_error_mm": s["reproj"],
            "points": points,
        }

    def _read_telemetry(self) -> tuple[tuple[float, float], int]:
        """Блокирующий запрос телеметрии робота → ((x_mm, y_mm), encoder)."""
        res = self._hub_call("robot_get_telemetry", {"device_id": self._state["robot_id"]})
        tel = res.get("telemetry") or {}
        if "x_mm" not in tel or "y_mm" not in tel or res.get("encoder") is None:
            raise CalibrationError("Телеметрия робота без x_mm/y_mm/encoder.")
        return (float(tel["x_mm"]), float(tel["y_mm"])), int(res["encoder"])

    def _hub_call(self, command: str, args: dict) -> dict:
        if self._client is None:
            raise CalibrationError("DeviceHubClient не инициализирован (плагин не запущен).")
        res = self._client.request(command, args, timeout=_HUB_TIMEOUT)
        if not isinstance(res, dict) or res.get("status") != "ok":
            msg = res.get("message") if isinstance(res, dict) else "нет ответа"
            raise CalibrationError(f"{command}: {msg}")
        return res

    def _reset_state(self) -> None:
        self._state: dict[str, Any] = {
            "phase": "ready",
            "camera_id": self._reg.camera_id,
            "robot_id": self._reg.robot_id,
            "vfd_id": self._reg.vfd_id,
            "px": None,
            "roles": None,
            "e_capture": None,
            "mm": [None] * 5,
            "enc_i": [None] * 5,
            "mm_per_count": None,
            "belt_dir": None,
            "homography": None,
            "reproj": None,
            "passed": False,
            "saved_path": None,
            "message": "",
            "error": None,
        }
        self._set_overlay(None)

    def _set_overlay(self, points: list | None) -> None:
        with self._lock:
            if points is None:
                self._overlay = None
            else:
                self._overlay = [(float(p[0]), float(p[1]), str(i + 1)) for i, p in enumerate(points)]

    def _publish(self) -> None:
        if self._ctx is None or getattr(self._ctx, "state_proxy", None) is None:
            return
        s = self._state
        with self._lock:
            live_found = len(self._last_detections)
        snap = {
            "phase": s["phase"],
            "message": s["message"],
            "error": s["error"],
            "captured": s["px"] is not None,
            "live_found": live_found,
            "expected_points": int(self._reg.expected_points),
            "points_collected": sum(1 for m in s["mm"] if m is not None),
            "scale_done": s["mm_per_count"] is not None,
            "mm_per_count": s["mm_per_count"],
            "belt_dir": s["belt_dir"],
            "reproj": s["reproj"],
            "passed": s["passed"],
            "saved_path": s["saved_path"],
            "reproj_threshold_mm": float(self._reg.reproj_threshold_mm),
        }
        self._ctx.state_proxy.set(f"calibration.state.{s['camera_id']}.progress", snap)
