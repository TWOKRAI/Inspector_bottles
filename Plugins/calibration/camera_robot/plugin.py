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
# Каждые N пустых поллингов публикуем live-снапшот (для real-time px/счётчика в GUI).
# 6 × 0.05с ≈ 0.3с — достаточно «живо», без флуда state-дерева.
_LIVE_PUBLISH_EVERY = 6
# Роли 5 точек (порядок order_points: 4 угла + центр).
_ROLES = ("corner_tl", "corner_tr", "corner_br", "corner_bl", "center")
_CENTER_IDX = 4  # роль "center" — репер по умолчанию для масштаба ленты
# Защита от переполнения энкодера (16-бит wrap-around): разница E2−E1 больше — мусор.
# ИНВАРИАНТ: энкодер ленты — ОДИН сквозной на всю трассу камера→робот (один датчик),
# иначе вычитание E1−E0 (дистанция камера→робот) и E2−E1 (масштаб) бессмысленны.
_MAX_SANE_ENC_DELTA = 100_000


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
        "cal_set_point": "cmd_set_point",
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
        """Нарисовать live-детекции (зелёные, нумерованные 1-5) + захваченные точки (красные)."""
        out = frame.copy()  # не мутировать SHM-буфер
        # Live-точки: если ровно 5 — упорядочиваем (order_points) и нумеруем 1-5,
        # чтобы оператор видел, какая точка какой номер, ещё до захвата. Иначе — просто точки.
        live_pts = [
            (float(d["center"][0]), float(d["center"][1]))
            for d in detections
            if isinstance(d, dict) and isinstance(d.get("center"), (list, tuple)) and len(d["center"]) >= 2
        ]
        ordered_live = None
        if len(live_pts) == 5:
            try:
                corners, center = geometry.order_points(live_pts)
                ordered_live = [*corners, center]
            except ValueError:
                ordered_live = None
        if ordered_live is not None:
            for i, (x, y) in enumerate(ordered_live):
                cx, cy = int(round(x)), int(round(y))
                cv2.circle(out, (cx, cy), 5, (0, 255, 0), -1)
                cv2.putText(out, str(i + 1), (cx + 8, cy - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        else:
            for x, y in live_pts:
                cv2.circle(out, (int(round(x)), int(round(y))), 4, (0, 255, 0), -1)
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

    def cmd_set_point(self, data: dict) -> dict:
        return self._enqueue("set_point", data)

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
        idle = 0
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            try:
                action = self._queue.get(timeout=_QUEUE_POLL_S)
            except Empty:
                # Нет команд — периодически публикуем live-снапшот (real-time px/счётчик).
                idle += 1
                if idle >= _LIVE_PUBLISH_EVERY:
                    idle = 0
                    self._publish()
                continue
            idle = 0
            self._dispatch(action)

    def _dispatch(self, action_item: dict) -> None:
        action = action_item.get("action")
        args = action_item.get("args") or {}
        handler = {
            "begin": self._do_begin,
            "capture_image": self._do_capture_image,
            "set_robot_point": self._do_set_robot_point,
            "set_point": self._do_set_point_manual,
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
        self._capture_from_detections()

    def _capture_from_detections(self) -> None:
        """Зафиксировать px из текущих 5 детекций (упорядочить) + энкодер захвата.

        Общий код «Снять кадр» и авто-захвата при первом «Точка N».
        """
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
            e_belt2=None,
            belt_ref=None,
            camera_to_robot_mm=None,
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
        # Авто-захват при первом нажатии «Точка N» (отдельная кнопка «Снять кадр» не нужна).
        if self._state["px"] is None:
            self._capture_from_detections()
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

    def _do_set_point_manual(self, args: dict) -> None:
        """Ручная правка координат точки (data: index, px=[x,y]?, mm=[x,y]?).

        Позволяет оператору поправить px (пиксели) и/или mm (координаты робота)
        вручную — для контроля/коррекции. mm без предшествующего касания роботом
        (enc_i=None) трактуем как замер на момент захвата кадра (enc_i=e_capture).
        """
        idx = int(args.get("index", -1))
        if not 0 <= idx < 5:
            raise CalibrationError(f"index {idx} вне диапазона 0..4")
        px = args.get("px")
        mm = args.get("mm")
        enc = args.get("enc")
        if px is not None and len(px) >= 2:
            if self._state["px"] is None:
                self._state["px"] = [None] * 5
                self._state["roles"] = list(_ROLES)
            self._state["px"][idx] = [float(px[0]), float(px[1])]
            # Обновить overlay (нумерованные точки на кадре), если все 5 px заданы.
            if all(p is not None for p in self._state["px"]):
                self._set_overlay(self._state["px"])
        if mm is not None and len(mm) >= 2:
            self._state["mm"][idx] = [float(mm[0]), float(mm[1])]
            if enc is not None:
                # Энкодер пришёл с GUI (push-телеметрия). Первый зафиксированный = опорный E0.
                self._state["enc_i"][idx] = int(enc)
                if self._state["e_capture"] is None:
                    self._state["e_capture"] = int(enc)
            elif self._state["enc_i"][idx] is None:
                self._state["enc_i"][idx] = self._state["e_capture"]
        self._state["message"] = f"Точка {idx + 1}: записана"

    def _do_encoder_scale(self, args: dict) -> None:
        ref = int(args.get("ref_index", 0))
        if not 0 <= ref < 5:
            raise CalibrationError(f"ref_index {ref} вне диапазона 0..4")
        mm = self._state["mm"]
        enc_i = self._state["enc_i"]
        if mm[ref] is None or enc_i[ref] is None:
            raise CalibrationError(f"Точка {ref + 1} ещё не снята роботом — нельзя взять её как репер.")
        pos2, enc_b = self._read_telemetry()  # E2 — повторное касание репера после прогона ленты
        e1 = int(enc_i[ref])  # E1 — энкодер 1-го касания репера
        # Guard переполнения: разница E2−E1 за разумным пределом = wrap-around 16-бит энкодера.
        if abs(enc_b - e1) > _MAX_SANE_ENC_DELTA:
            raise CalibrationError(
                f"Энкодер: разница E2−E1={enc_b - e1} нереально велика (вероятно переход через ноль). "
                f"Повторите замер на меньшем прогоне ленты."
            )
        mm_per_count, belt_dir = geometry.belt_vector(
            (mm[ref][0], mm[ref][1]), pos2, e1, enc_b
        )  # ValueError → _dispatch
        self._state["mm_per_count"] = mm_per_count
        self._state["belt_dir"] = [belt_dir[0], belt_dir[1]]
        self._state["e_belt2"] = enc_b
        self._state["belt_mm2"] = [pos2[0], pos2[1]]  # новые координаты робота репера (Шаг 3)
        self._state["belt_ref"] = ref
        # Дистанция камера→зона робота: за (E1−E0) импульсов деталь проезжает столько мм.
        e0 = self._state["e_capture"]
        cam_to_robot = (e1 - int(e0)) * mm_per_count if e0 is not None else None
        self._state["camera_to_robot_mm"] = cam_to_robot
        dist_txt = f", камера→робот {cam_to_robot:.1f} мм" if cam_to_robot is not None else ""
        self._state["message"] = (
            f"Масштаб ленты: {mm_per_count:.5f} мм/count, направление ({belt_dir[0]:.3f}, {belt_dir[1]:.3f}){dist_txt}"
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
        if px is None or any(p is None for p in px):
            raise CalibrationError("Не заданы пиксельные координаты всех 5 точек.")
        if any(m is None for m in mm):
            raise CalibrationError("Сняты роботом не все 5 точек.")
        if mpc is None or belt is None:
            # Статическая калибровка (без ленты): px[i]↔mm[i] напрямую, без belt-компенсации.
            mm_fixed = [(float(mm[i][0]), float(mm[i][1])) for i in range(5)]
        else:
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
                "e_capture": s["e_capture"],  # E0 — камера
                "e_belt2": s["e_belt2"],  # E2 — повторное касание репера после ленты
                "belt_ref": s["belt_ref"],  # индекс реперной точки масштаба
                "mm_per_count": s["mm_per_count"],
                "belt_dir_mm": s["belt_dir"],
                "camera_to_robot_mm": s["camera_to_robot_mm"],  # (E1−E0)·mm_per_count
            },
            "reproj_error_mm": s["reproj"],
            "points": points,
        }

    def _read_telemetry(self) -> tuple[tuple[float, float], int]:
        """Блокирующий запрос телеметрии робота → ((x_mm, y_mm), encoder).

        Устойчиво к структуре ответа: telemetry/encoder ищем на верхнем уровне И
        во вложенных result/data (разные обёртки IPC). Энкодер необязателен —
        для статической калибровки (без ленты) важны только x_mm/y_mm; если энкодер
        недоступен (нет ленты/мгновенный сбой чтения) — берём 0, не валим точку.
        """
        res = self._hub_call("robot_get_telemetry", {"device_id": self._state["robot_id"]})
        tel, enc = self._extract_telemetry(res)
        if "x_mm" not in tel or "y_mm" not in tel:
            raise CalibrationError(f"Телеметрия робота без x_mm/y_mm. Ответ: {res}")
        return (float(tel["x_mm"]), float(tel["y_mm"])), int(enc if enc is not None else 0)

    @staticmethod
    def _extract_telemetry(res: Any) -> tuple[dict, int | None]:
        """Достать (telemetry, encoder) из ответа hub — верхний уровень или вложенный."""
        if not isinstance(res, dict):
            return {}, None
        if isinstance(res.get("telemetry"), dict):
            return res["telemetry"], res.get("encoder")
        for key in ("result", "data"):
            sub = res.get(key)
            if isinstance(sub, dict) and isinstance(sub.get("telemetry"), dict):
                return sub["telemetry"], sub.get("encoder")
        return {}, None

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
            "e_capture": None,  # E0 — энкодер на момент захвата кадра камерой
            "mm": [None] * 5,
            "enc_i": [None] * 5,  # энкодер на момент касания робота по точкам (E1 = enc_i[репер])
            "e_belt2": None,  # E2 — энкодер при повторном касании репера после прогона ленты
            "belt_mm2": None,  # новые координаты робота репера после прогона ленты (Шаг 3)
            "belt_ref": None,  # индекс реперной точки масштаба ленты
            "camera_to_robot_mm": None,  # (E1−E0)·mm_per_count — дистанция камера→зона робота, мм
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
            live_dets = list(self._last_detections)
        live_found = len(live_dets)
        # live_px: упорядоченные текущие детекции (для real-time показа px ДО захвата).
        live_px = None
        live_pts = [
            (float(d["center"][0]), float(d["center"][1]))
            for d in live_dets
            if isinstance(d, dict) and isinstance(d.get("center"), (list, tuple)) and len(d["center"]) >= 2
        ]
        if len(live_pts) == 5:
            try:
                corners, center = geometry.order_points(live_pts)
                live_px = [list(p) for p in [*corners, center]]
            except ValueError:
                live_px = None
        px_state = s["px"]
        # px_state — список из 5, отдельные точки могут быть None (записана не вся плата) →
        # list(None) бросает TypeError и валит воркер. Защищаем поэлементно (как mm_out ниже).
        px_out = [list(p) if p is not None else None for p in px_state] if px_state else [None] * 5
        mm_out = [list(m) if m is not None else None for m in s["mm"]]
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
            # Энкодер: E0 (камера), E1 (робот, репер/центр), E2 (после ленты) + дистанция.
            "e0": s["e_capture"],
            "e1": s["enc_i"][s["belt_ref"] if s["belt_ref"] is not None else _CENTER_IDX],
            "e2": s["e_belt2"],
            "belt_mm2": list(s["belt_mm2"]) if s["belt_mm2"] else None,  # новый робот репера (Шаг 3)
            "camera_to_robot_mm": s["camera_to_robot_mm"],
            "reproj": s["reproj"],
            "passed": s["passed"],
            "saved_path": s["saved_path"],
            "reproj_threshold_mm": float(self._reg.reproj_threshold_mm),
            # Покоординатно для GUI (визард показывает + правит вручную).
            "px": px_out,  # [[x,y]|None]·5 — пиксели (после захвата/ручной правки)
            "live_px": live_px,  # [[x,y]]·5 | None — упорядоченные live-детекции (real-time до захвата)
            "mm": mm_out,  # [[x,y]|None]·5 — координаты робота (после касания/правки)
            "roles": s["roles"] or list(_ROLES),
        }
        self._ctx.state_proxy.set(f"calibration.state.{s['camera_id']}.progress", snap)
