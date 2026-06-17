"""RobotDriver — драйвер робота Delta для device_hub.

Порт семантики из Plugins/io/robot_io (feeder-очередь CVT, throttled reconnect,
телеметрия) + draw-очереди из Plugins/control/robot_draw (рисование фигур).

ПОТОКОБЕЗОПАСНОСТЬ: быстрые операции (send_job, set_*, чтения) могут вызываться
из чужого потока (командный поток процесса) параллельно tick(). Безопасность
обеспечивается:
    - RLock внутри ModbusDevice (атомарность транзакций)
    - deque (thread-safe append/popleft для job-очереди)
    - queue.Queue (thread-safe для draw-очереди)
Draw-операции блокирующие — допустимо, т.к. tick() крутится в выделенном
per-device воркере. Команды draw_abort минуют очередь через client.draw_abort().

Mode: ``cvt`` (конвейер, дефолт) | ``draw`` (рисование) — expose в snapshot,
нужен VfdDriver для gating и GUI.
"""

from __future__ import annotations

import queue
import threading
from collections import deque
from typing import Any

from Services.device_hub.drivers.base import BaseDeviceDriver

# Минимальный интервал между попытками переподключения, сек
_RECONNECT_THROTTLE_SEC = 2.0
# Ожидание освобождения робота перед переключением в DRAW, сек
_MODE_SWITCH_WAIT_S = 5.0


class RobotDriver(BaseDeviceDriver):
    """Драйвер робота Delta: feeder CVT + draw-очередь + телеметрия.

    Args:
        entry:     DeviceEntry с kind=robot.
        protocol:  DeviceProtocol (delta_universal3).
        transport: Инъекция RegisterTransport для тестов (FakeRobotTransport).
                   Если None — строится в connect() через build_transport.
        clock:     Источник монотонного времени.
        sleep:     Функция паузы.
    """

    kind = "robot"

    def __init__(
        self,
        entry: Any,
        protocol: Any = None,
        *,
        transport: Any = None,
        clock: Any = None,
        sleep: Any = None,
    ) -> None:
        super().__init__(entry, protocol, clock=clock, sleep=sleep)

        # Транспорт (инъекция для тестов, иначе None до connect)
        self._transport = transport

        # RobotClient (лениво в connect)
        self._client: Any = None

        # Feeder-очередь CVT: (x_mm, y_mm, e_capture, place) — place=(x,y,z,rz)|None
        # deque — thread-safe append/popleft. maxlen — защита от роста при отвале робота
        # (H-1: без лимита очередь росла бесконечно, пока робот недоступен).
        _qmax = int(entry.params.get("job_queue_maxlen", 256))
        self._job_queue: deque[tuple] = deque(maxlen=_qmax)

        # Draw-очередь: dict с заданиями рисования
        # queue.Queue — thread-safe
        self._draw_queue: queue.Queue[dict] = queue.Queue()

        # Return-очередь: (x, y, z) слотов для возврата букв на ленту (MODE=3).
        # deque — thread-safe append/popleft (ставится из командного потока). maxlen — см. H-1 выше.
        self._return_queue: deque[tuple] = deque(maxlen=_qmax)

        # Режим: cvt | draw
        self._mode: str = "cvt"

        # Ручной режим: пауза авто-подачи из очереди
        self.manual_mode: bool = False

        # Throttled reconnect
        self._last_reconnect: float = 0.0

        # Wire-обмен для панели «Вход/Выход»: последние TX (запись) и RX (чтение).
        # Заполняется из on_data ModbusDevice (каждый read/write); публикуется
        # супервизором как devices.state.<id>.io_peek. Захватывает и трафик
        # bridged-ПЧ (она пишет через транспорт робота).
        self._last_io: dict[str, Any] = {"input": None, "output": None}

        # Интервал телеметрии (из params или дефолт)
        self._telemetry_interval_s: float = float(entry.params.get("telemetry_interval_s", 0.5))
        self._feed_poll_s: float = float(entry.params.get("feed_poll_s", 0.05))
        self._last_telemetry: float = 0.0

        # Счётчики заданий
        self.jobs_sent: int = 0
        self.jobs_done: int = 0
        self.jobs_failed: int = 0
        self.draws_done: int = 0
        self.returns_done: int = 0
        self.returns_failed: int = 0

        # Draw-параметры (дефолты из robot_draw)
        self._pen_down_mm: float = float(entry.params.get("pen_down_mm", -50.0))
        self._pen_up_mm: float = float(entry.params.get("pen_up_mm", -40.0))
        self._draw_speed_pct: int = int(entry.params.get("draw_speed_pct", 30))
        self._overlap_mm: float = float(entry.params.get("overlap_mm", 1.0))
        self._draw_timeout_s: float = float(entry.params.get("draw_timeout_s", 120.0))
        self._lift_mm: float = float(entry.params.get("lift_mm", 10.0))

        # Компенсация задержки конвейера (CVT lead compensation).
        # Оператор задаёт в мм вдоль ленты: положительное значение = целиться
        # ДАЛЬШЕ по ходу (компенсация задержки камера→робот). Применяется к
        # e_capture ПЕРЕД send_job. Живо-тюнится через call("set_encoder_offset").
        self._pick_lead_mm: float = float(entry.params.get("pick_lead_mm", 0.0))

        # Состояние рисования
        self._draw_busy: bool = False
        self._draw_state: str = "idle"

        # Запрос аборта рисования: ставит _op_draw_abort (командный поток),
        # client.draw() проверяет между проходами. Без этого abort прерывает лишь
        # текущий проход (REG_DRAW_ABORT в прошивке), а остальные уходят роботу.
        self._draw_abort_evt = threading.Event()

        # Доставка задания в полёте (feeder в _deliver). Нужно мосту ПЧ: пока
        # робот занят движением, ПЧ НЕ должна пульсировать VFD_FLAG — иначе
        # высокоприоритетная ветка handle_vfd в Lua перехватывает единственный
        # Motion-цикл робота и servo/job голодают (см. busy ниже).
        self._delivering: bool = False

    # ------------------------------------------------------------------ #
    # Соединение
    # ------------------------------------------------------------------ #

    @property
    def is_connected(self) -> bool:
        """Установлено ли соединение с роботом."""
        return self._client is not None and self._client.is_connected

    @property
    def transport(self) -> Any:
        """RegisterTransport клиента (для bridge-устройств типа VFD)."""
        return self._client

    @property
    def mode(self) -> str:
        """Текущий режим: ``cvt`` | ``draw``."""
        return self._mode

    @property
    def busy(self) -> bool:
        """Робот занят полезной работой: есть задания / идёт доставка / рисование.

        Используется мостом ПЧ (VfdDriver): пока робот busy, ПЧ НЕ пульсирует
        VFD_FLAG — высокоприоритетная ветка handle_vfd в Lua не должна перехватывать
        единственный Motion-цикл робота во время движения. Приоритет — всегда робот.
        """
        return bool(self._job_queue) or self._draw_busy or self._delivering or bool(self._return_queue)

    def connect(self) -> bool:
        """Подключиться к роботу. Создаёт RobotClient если ещё нет."""
        if self._client is None:
            self._client = self._build_client()
        try:
            ok = self._client.connect()
        except Exception:
            self._record_err()
            self._last_quality = "bad"
            return False
        if ok:
            self._last_quality = "good"
        else:
            self._last_quality = "bad"
        return ok

    def disconnect(self) -> None:
        """Закрыть соединение."""
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
        self._last_quality = "bad"

    # ------------------------------------------------------------------ #
    # Tick — главный цикл (крутится в per-device воркере)
    # ------------------------------------------------------------------ #

    def tick(self, stop_event: Any = None) -> dict | None:
        """Один шаг: reconnect -> телеметрия -> feeder -> draw -> snapshot.

        н8 ревью Fable: quality snapshot'а отражает результат текущего тика.
        Если в этом тике произошла IO-ошибка (tx_err вырос) — quality="bad",
        а не "good". is_connected (ModbusDevice._fail) падает лишь после этого
        тика — snapshot не должен маскировать ошибку.
        """
        if not self._ensure_connected():
            return self.snapshot(quality="bad")

        # Запоминаем счётчик ошибок до операций тика (н8)
        _err_before = self._stats["tx_err"]

        self._publish_telemetry_maybe()

        # Draw-очередь приоритет (если есть задания рисования)
        if not self._draw_queue.empty():
            self._execute_draw(stop_event)

        # н3 ревью Fable: после опустошения draw-очереди и завершения текущего
        # рисования — вернуть режим cvt. Без этого _mode навсегда застревает
        # в "draw", VfdDriver вечно получает stale, CVT-feeder выключен.
        if self._mode == "draw" and self._draw_queue.empty() and not self._draw_busy:
            self._client.set_mode("cvt")
            self._mode = "cvt"

        # RETURN-очередь: возврат букв на ленту (одно задание за тик, как CVT-доставка).
        if self._return_queue:
            self._execute_return(stop_event)
        # После опустошения очереди возврата — вернуть режим cvt (иначе CVT-feeder заглушен).
        if self._mode == "return" and not self._return_queue and not self._delivering:
            self._client.set_mode("cvt")
            self._mode = "cvt"

        # CVT feeder (если не manual_mode и не draw)
        if not self.manual_mode and self._mode == "cvt" and self._job_queue:
            try:
                if self._client.is_free():
                    job = self._job_queue.popleft() if self._job_queue else None
                    if job is not None:
                        self._deliver(job, stop_event)
            except Exception:
                self._record_err()

        # н8: если в этом тике возникла IO-ошибка — quality="bad"
        _tick_had_err = self._stats["tx_err"] > _err_before
        quality = "bad" if _tick_had_err else "good"
        return self.snapshot(quality=quality)

    # ------------------------------------------------------------------ #
    # Feeder CVT (порт robot_io/plugin.py:151-263)
    # ------------------------------------------------------------------ #

    # Коэффициент мм/счёт энкодера (из cvt_universal_full.lua:121 FACTOR_MM).
    # Единственный источник истины — прошивка. Дублируем для конверсии offset.
    _FACTOR_MM: float = 0.144473

    def _apply_pick_lead(self, e_capture: int) -> int:
        """Применить компенсацию задержки к снимку энкодера.

        pick_lead_mm > 0 → целиться ДАЛЬШЕ по ходу ленты.
        Lua: trav = (enc_now - job_enc) * FACTOR_MM; py = job_y + UY * trav (UY=1).
        Чтобы trav стал больше (цель дальше), уменьшаем job_enc: вычитаем offset_counts.
        Результат: 32-bit signed int (как REG_JOB_ECAP — RegDW signed).
        """
        if self._pick_lead_mm == 0.0:
            return e_capture
        offset_counts = round(self._pick_lead_mm / self._FACTOR_MM)
        compensated = e_capture - offset_counts
        # 32-bit signed wrap (Lua DW signed): clamp to [-2^31, 2^31-1]
        compensated = compensated & 0xFFFFFFFF
        if compensated >= 0x80000000:
            compensated -= 0x100000000
        return int(compensated)

    def enqueue_job(
        self,
        x_mm: float,
        y_mm: float,
        place: tuple[float, float, float, float] | None = None,
        e_capture: int | None = None,
        z_mm: float = 0.0,
    ) -> bool:
        """Поставить CVT-задание в очередь со снимком энкодера.

        ``place=(x, y, z, rz)`` — опц. поза укладки (доворот); None → укладка в фикс.
        config-место (обратная совместимость). ``e_capture`` — энкодер НА МОМЕНТ КАДРА
        (снят рано, до инференса, узлом pixel_to_robot для точного CVT-трекинга); если
        None — читаем энкодер сейчас (как раньше). ``z_mm`` — глубина захвата на picke
        (0 = дефолт прошивки Z_PICK). Вызывается из командного потока (thread-safe:
        deque.append).

        ``pick_lead_mm`` — компенсация задержки (мм вдоль ленты). Применяется к
        e_capture автоматически (и к поданному извне, и к считанному здесь).
        """
        if not self.is_connected:
            return False
        if e_capture is None:
            try:
                e_capture = self._client.read_encoder()
            except Exception:
                self._record_err()
                return False
        e_capture = self._apply_pick_lead(e_capture)
        self._job_queue.append((x_mm, y_mm, z_mm, e_capture, place))
        return True

    def _deliver(self, job: tuple, stop_event: Any) -> None:
        """Отдать задание: send_job -> ждать приёма -> ждать завершения.

        Порт _deliver из robot_io.
        """

        x_mm, y_mm, z_mm, e_capture, place = job
        # PC-опрос: при позе укладки доворот (относительный) переводим в АБСОЛЮТНЫЙ R
        # инструмента — читаем РЕАЛЬНЫЙ R робота (телеметрия) и кладём под R = реальный + доворот.
        # Робот сейчас idle (фидер доставляет только при is_free) → R = поза захвата.
        if place is not None:
            px, py, pz, dovorot = place
            try:
                rz_now = self._client.read_position().rz_deg
            except Exception:
                rz_now = 0.0
                self._record_err()
            place = (px, py, pz, rz_now + dovorot)
        # Помечаем доставку — мост ПЧ не будет дёргать mailbox робота, пока идёт
        # движение (приоритет робота, см. busy).
        self._delivering = True
        try:
            try:
                self._client.send_job(x_mm, y_mm, e_capture, place, z_mm=z_mm)
            except Exception:
                self.jobs_failed += 1
                self._record_err()
                return
            self.jobs_sent += 1
            self._record_ok()

            # Ждать приёма (job_flag -> 0)
            accept_wait_s = float(self.entry.params.get("accept_wait_s", 5.0))
            if not self._wait_condition(self._client.job_accepted, accept_wait_s, stop_event):
                # Не принял — вернуть в начало очереди
                self._job_queue.appendleft(job)
                return

            # Ждать завершения (is_free)
            job_wait_s = float(self.entry.params.get("job_wait_s", 10.0))
            if not self._wait_condition(self._client.is_free, job_wait_s, stop_event):
                self.jobs_failed += 1
                return

            self.jobs_done += 1
        finally:
            self._delivering = False

    # ------------------------------------------------------------------ #
    # Draw (порт robot_draw/plugin.py)
    # ------------------------------------------------------------------ #

    def _execute_draw(self, stop_event: Any) -> None:
        """Исполнить одно задание рисования из очереди."""
        try:
            task = self._draw_queue.get_nowait()
        except queue.Empty:
            return

        self._draw_state = "drawing"
        self._draw_busy = True
        self._draw_abort_evt.clear()  # свежий старт: прошлый abort не должен оборвать новый рисунок

        try:
            self._prepare_draw(task, stop_event)
            ok = self._run_figure(task)
        except Exception:
            self._draw_state = "failed"
            self._draw_busy = False
            self._record_err()
            return
        finally:
            self._draw_busy = False

        if ok:
            self._draw_state = "done"
            self.draws_done += 1
            self._record_ok()
        else:
            self._draw_state = "failed"

    def _prepare_draw(self, task: dict, stop_event: Any) -> None:
        """Переключить в DRAW (дождавшись free) и применить параметры пера."""
        t_end = self._clock() + _MODE_SWITCH_WAIT_S
        while self._clock() < t_end:
            if stop_event is not None and stop_event.is_set():
                break
            try:
                if self._client.is_free():
                    break
            except Exception:
                break
            self._sleep(0.05)

        self._client.set_mode("draw")
        self._mode = "draw"

        z = task.get("z")
        if z is not None:
            self._client.set_pen(float(z), float(z) + self._lift_mm)
        else:
            self._client.set_pen(self._pen_down_mm, self._pen_up_mm)
        self._client.set_draw_speed(self._draw_speed_pct)
        self._client.set_overlap(self._overlap_mm)

    def _run_figure(self, task: dict) -> bool:
        """Исполнить фигуру задания."""
        from Services.robot_comm.core.datatypes import DrawPoint

        kind = task.get("kind", "points")
        timeout = self._draw_timeout_s

        if kind == "circle":
            return self._client.draw_circle(task["cx"], task["cy"], task["r"], timeout=timeout)

        # Полилиния
        points_raw = task.get("points", [])
        points = [
            p if isinstance(p, DrawPoint) else DrawPoint(float(p["x_mm"]), float(p["y_mm"]), int(p.get("pen", 1)))
            for p in points_raw
        ]
        if not points:
            return False
        return self._client.draw(points, timeout=timeout, should_abort=self._draw_abort_evt.is_set)

    # ------------------------------------------------------------------ #
    # RETURN (возврат буквы на ленту, MODE=3)
    # ------------------------------------------------------------------ #

    def enqueue_return(self, x_mm: float, y_mm: float, z_mm: float) -> bool:
        """Поставить задание возврата буквы (координата СЛОТА) в очередь.

        Вызывается из командного потока (thread-safe: deque.append). Робот возьмёт диск
        из (x,y,z) и вернёт на ленту линейной траекторией (смещения — константы Lua).
        """
        if not self.is_connected:
            return False
        self._return_queue.append((float(x_mm), float(y_mm), float(z_mm)))
        return True

    def _execute_return(self, stop_event: Any) -> None:
        """Исполнить одно задание возврата из очереди (одно за тик, режим RETURN)."""
        # Переключиться в RETURN один раз (дождавшись свободы робота).
        if self._mode != "return":
            self._wait_condition(self._client.is_free, _MODE_SWITCH_WAIT_S, stop_event)
            try:
                self._client.set_mode("return")
            except Exception:
                self._record_err()
                return
            self._mode = "return"

        try:
            x, y, z = self._return_queue.popleft()
        except IndexError:
            return

        ret_timeout = float(self.entry.params.get("return_timeout_s", 30.0))
        # Помечаем доставку — мост ПЧ не дёргает робота во время движения (приоритет робота).
        self._delivering = True
        try:
            ok = self._client.do_return(x, y, z, timeout=ret_timeout)
        except Exception:
            self.returns_failed += 1
            self._record_err()
            return
        finally:
            self._delivering = False
        if ok:
            self.returns_done += 1
            self._record_ok()
        else:
            self.returns_failed += 1
            self._record_err()

    # ------------------------------------------------------------------ #
    # Reconnect (throttled, порт robot_io)
    # ------------------------------------------------------------------ #

    def _ensure_connected(self) -> bool:
        """Гарантировать соединение: throttled-reconnect с лимитом попыток.

        НР-1: при desired_connected=False — НЕ реконнектиться.
        Лимит: после max_reconnect_attempts неудач драйвер «сдаётся»
        (_note_reconnect_failed выставляет desired_connected=False) — без железа
        не спамим connect вечно; возобновление — ручным «Подключить».
        """
        if self.is_connected:
            return True
        if not self.desired_connected:
            return False
        now = self._clock()
        if now - self._last_reconnect < _RECONNECT_THROTTLE_SEC:
            return False
        self._last_reconnect = now
        self._record_reconnect()
        if self.connect():
            self.reset_reconnect()
            return True
        self._note_reconnect_failed()
        return False

    # ------------------------------------------------------------------ #
    # Телеметрия
    # ------------------------------------------------------------------ #

    def _publish_telemetry_maybe(self) -> None:
        """Раз в telemetry_interval_s: прочитать телеметрию."""
        now = self._clock()
        if now - self._last_telemetry < self._telemetry_interval_s:
            return
        self._last_telemetry = now
        try:
            t0 = self._clock()
            self._client.read_telemetry()
            latency = (self._clock() - t0) * 1000
            self._record_ok(latency)
        except Exception:
            self._record_err()

    # ------------------------------------------------------------------ #
    # Call — диспетчер операций (таблица из плана Р7)
    # ------------------------------------------------------------------ #

    def call(self, op: str, args: dict) -> dict:
        """Диспетчер операций робота.

        Быстрые операции (send_job, set_*, чтения) потокобезопасны благодаря
        RLock внутри ModbusDevice + thread-safe коллекции.
        """
        handler = self._OPS.get(op)
        if handler is None:
            return {"status": "error", "message": f"Неизвестная операция робота: {op!r}"}
        try:
            return handler(self, args)
        except Exception as exc:
            self._record_err()
            return {"status": "error", "message": str(exc)}

    # --- обработчики операций ---

    def _op_send_test_job(self, args: dict) -> dict:
        x_mm, y_mm = float(args["x"]), float(args["y"])
        z_mm = float(args.get("z", 0.0))  # глубина захвата; 0 = дефолт прошивки (Z_PICK)
        ok = self.enqueue_job(x_mm, y_mm, z_mm=z_mm)
        return {"status": "ok" if ok else "error", "queue_len": len(self._job_queue)}

    def _op_abort(self, args: dict) -> dict:
        mode = int(args.get("mode", 1))
        self._client.stop(mode)
        return {"status": "ok", "mode": mode}

    def _op_set_mode(self, args: dict) -> dict:
        mode = str(args.get("mode", "cvt"))
        self._client.set_mode(mode)
        self._mode = mode
        return {"status": "ok", "mode": mode}

    def _op_jog(self, args: dict) -> dict:
        """Ручной ход: {device_id, dx, dy, spd?, absolute?} — смещение мм + Override %."""
        dx = float(args.get("dx", 0.0))
        dy = float(args.get("dy", 0.0))
        spd = args.get("spd")
        absolute = bool(args.get("absolute", False))
        self._client.jog(dx, dy, int(spd) if spd is not None else None, absolute=absolute)
        self._mode = "manual"
        return {"status": "ok", "dx": dx, "dy": dy, "absolute": absolute}

    def _op_jog_abort(self, _args: dict) -> dict:
        """Прервать ручной ход (man_abort=1)."""
        self._client.jog_abort()
        return {"status": "ok"}

    def _op_set_servo(self, args: dict) -> dict:
        on = bool(args.get("on", True))
        self._client.set_servo(on)
        return {"status": "ok", "on": on}

    def _op_set_robot_config(self, args: dict) -> dict:
        fields = {k: v for k, v in args.items() if isinstance(v, (int, float))}
        if not fields:
            return {"status": "error", "message": "нет числовых полей конфига"}
        self._client.set_config(**fields)
        return {"status": "ok", "fields": fields}

    def _op_get_robot_config(self, _args: dict) -> dict:
        return {"status": "ok", "config": self._client.get_config()}

    def _op_get_telemetry(self, _args: dict) -> dict:
        t = self._client.read_telemetry()
        free = self._client.is_free()
        enc = self._client.read_encoder()
        return {
            "status": "ok",
            "telemetry": t.to_dict(),
            "free": free,
            "encoder": enc,
            "queue_len": len(self._job_queue),
        }

    def _op_read_echo(self, _args: dict) -> dict:
        return {"status": "ok", "echo": self._client.read_echo().to_dict()}

    def _op_set_manual_mode(self, args: dict) -> dict:
        self.manual_mode = bool(args.get("on", True))
        return {"status": "ok", "manual_mode": self.manual_mode}

    def _op_clear_queue(self, _args: dict) -> dict:
        dropped = len(self._job_queue)
        self._job_queue.clear()
        return {"status": "ok", "dropped": dropped}

    def _op_enqueue_job(self, args: dict) -> dict:
        x_mm, y_mm = float(args["x_mm"]), float(args["y_mm"])
        # Опц. поза укладки (доворот): place_x/y/z/rz. Без неё — укладка в фикс. config-место.
        place = None
        if "place_x" in args and "place_y" in args:
            place = (
                float(args["place_x"]),
                float(args["place_y"]),
                float(args.get("place_z", 0.0)),
                float(args.get("place_rz", 0.0)),
            )
        # Опц. энкодер на момент кадра (снят рано pixel_to_robot); None → драйвер читает сам.
        e_cap = args.get("e_capture")
        e_cap = int(e_cap) if e_cap is not None else None
        # Глубина забора Z (мм); 0 = дефолт прошивки Z_PICK.
        z_mm_raw = args.get("z_mm")
        z_mm = float(z_mm_raw) if z_mm_raw is not None else 0.0
        ok = self.enqueue_job(x_mm, y_mm, place, e_cap, z_mm=z_mm)
        return {"status": "ok" if ok else "error", "queue_len": len(self._job_queue)}

    def _op_return_job(self, args: dict) -> dict:
        """Возврат буквы на ленту: координата слота {x_mm, y_mm, z_mm} → очередь возврата."""
        x_mm, y_mm = float(args["x_mm"]), float(args["y_mm"])
        z_mm = float(args.get("z_mm", 0.0))
        ok = self.enqueue_return(x_mm, y_mm, z_mm)
        return {"status": "ok" if ok else "error", "return_queue_len": len(self._return_queue)}

    def _op_set_encoder_offset(self, args: dict) -> dict:
        """Живая подстройка компенсации задержки конвейера (pick_lead_mm).

        Положительное значение = целиться ДАЛЬШЕ по ходу ленты (компенсация
        системной задержки камера→инференс→робот). Конвертируется в счётчики
        энкодера (FACTOR_MM = 0.144473 мм/счёт) и вычитается из e_capture.

        Args (в data):
            lead_mm: float — смещение в мм вдоль ленты (знаковое).
        """
        lead_mm = float(args.get("lead_mm", 0.0))
        self._pick_lead_mm = lead_mm
        offset_counts = round(lead_mm / self._FACTOR_MM) if lead_mm != 0.0 else 0
        return {
            "status": "ok",
            "pick_lead_mm": lead_mm,
            "offset_counts": offset_counts,
        }

    def _op_toolchange(self, args: dict) -> dict:
        """Смена инструмента: target (0=снять/1/2), ждать завершения.

        Переключает режим в toolchange, вызывает client.do_toolchange,
        возвращает режим в cvt. Handshake: tool_flag→0 (приём) → tool_busy↑
        (старт) → tool_busy↓ (готово).
        """
        target = int(args.get("target", 0))
        timeout = args.get("timeout")
        timeout = float(timeout) if timeout is not None else None
        # Переключить в режим toolchange
        self._client.set_mode("toolchange")
        self._mode = "toolchange"
        try:
            ok = self._client.do_toolchange(target, timeout=timeout)
        except Exception as exc:
            # Вернуть режим при ошибке
            self._client.set_mode("cvt")
            self._mode = "cvt"
            raise exc
        # Вернуть режим в cvt после смены
        self._client.set_mode("cvt")
        self._mode = "cvt"
        tool_cur = self._client.tool_current()
        return {
            "status": "ok" if ok else "error",
            "tool_current": tool_cur,
        }

    # --- draw-операции ---

    def _op_draw_polyline(self, args: dict) -> dict:
        points = args.get("points", [])
        if not points:
            return {"status": "error", "message": "пустой список точек"}
        self._draw_queue.put({"kind": "points", "points": points, "z": args.get("z")})
        return {"status": "ok", "queued": self._draw_queue.qsize()}

    def _op_draw_circle(self, args: dict) -> dict:
        task = {
            "kind": "circle",
            "cx": float(args["cx"]),
            "cy": float(args["cy"]),
            "r": float(args["r"]),
            "z": args.get("z"),
        }
        self._draw_queue.put(task)
        return {"status": "ok", "queued": self._draw_queue.qsize()}

    def _op_draw_square(self, args: dict) -> dict:
        from Services.robot_comm.core.datatypes import DrawPoint

        x1, y1 = float(args["x1"]), float(args["y1"])
        x2, y2 = float(args["x2"]), float(args["y2"])
        corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
        points = [DrawPoint(corners[0][0], corners[0][1], 0), DrawPoint(corners[0][0], corners[0][1], 1)]
        points += [DrawPoint(cx, cy, 1) for cx, cy in corners[1:] + [corners[0]]]
        self._draw_queue.put({"kind": "points", "points": points, "z": args.get("z")})
        return {"status": "ok", "queued": self._draw_queue.qsize()}

    def _op_draw_set_pen(self, args: dict) -> dict:
        # Частичное обновление: можно прислать только down ИЛИ только up (дашборд-пульт
        # держит два независимых контрола); второе значение сохраняется. Оба → оба.
        if "down" in args and args["down"] is not None:
            self._pen_down_mm = float(args["down"])
        if "up" in args and args["up"] is not None:
            self._pen_up_mm = float(args["up"])
        return {"status": "ok", "down": self._pen_down_mm, "up": self._pen_up_mm}

    def _op_draw_set_speed(self, args: dict) -> dict:
        self._draw_speed_pct = max(1, min(100, int(args["pct"])))
        return {"status": "ok", "pct": self._draw_speed_pct}

    def _op_draw_set_overlap(self, args: dict) -> dict:
        self._overlap_mm = max(0.1, float(args["mm"]))
        return {"status": "ok", "mm": self._overlap_mm}

    def _op_draw_abort(self, _args: dict) -> dict:
        """Стоп рисования: прервать + домой + сбросить память + очистить очередь.

        Запрос владельца: на Стоп робот должен «выбросить точки из памяти и вернуться
        домой», а следующее «Рисовать» начинать рисунок С НАЧАЛА (robot_draw шлёт весь
        путь заново — рестарт структурно гарантирован). Порядок важен:
          1) draw_home_after(True) — взвести заезд домой в финале прерванного прохода
             (в DRAW Mirror не опрашивает REG_STOP, отдельной «домой» нет);
          2) draw_abort() — прервать текущий проход (перо вверх → финал → домой);
          3) draw_abort_evt — остановить многопроходный draw() между проходами;
          4) очистить очередь заданий;
          5) draw_flush() — обнулить управляющие регистры (чистый старт).
        """
        homed = False
        flushed = False
        try:
            homed = self._client.draw_home_after(True)
            self._client.draw_abort()
        except Exception:
            self._record_err()
        self._draw_abort_evt.set()  # остановить многопроходный draw() между проходами
        # Очистить невыполненные задания
        dropped = 0
        while not self._draw_queue.empty():
            try:
                self._draw_queue.get_nowait()
                dropped += 1
            except queue.Empty:
                break
        try:
            flushed = self._client.draw_flush()
        except Exception:
            self._record_err()
        self._draw_busy = False
        self._draw_state = "idle"
        return {"status": "ok", "dropped_tasks": dropped, "homed": homed, "flushed": flushed}

    def _op_draw_progress(self, _args: dict) -> dict:
        result: dict[str, Any] = {
            "status": "ok",
            "state": self._draw_state,
            "draws_done": self.draws_done,
            "queued": self._draw_queue.qsize(),
        }
        if self.is_connected:
            try:
                result["busy"] = self._client.draw_busy()
                result["progress_point"] = self._client.draw_progress()
            except Exception as exc:
                result["read_error"] = str(exc)
        return result

    # Таблица операций
    _OPS: dict[str, Any] = {
        "send_test_job": _op_send_test_job,
        "abort": _op_abort,
        "set_mode": _op_set_mode,
        "jog": _op_jog,
        "jog_abort": _op_jog_abort,
        "set_servo": _op_set_servo,
        "set_robot_config": _op_set_robot_config,
        "get_robot_config": _op_get_robot_config,
        "get_telemetry": _op_get_telemetry,
        "read_echo": _op_read_echo,
        "set_manual_mode": _op_set_manual_mode,
        "clear_queue": _op_clear_queue,
        "enqueue_job": _op_enqueue_job,
        "return_job": _op_return_job,
        "set_encoder_offset": _op_set_encoder_offset,
        "toolchange": _op_toolchange,
        "draw_polyline": _op_draw_polyline,
        "draw_circle": _op_draw_circle,
        "draw_square": _op_draw_square,
        "draw_set_pen": _op_draw_set_pen,
        "draw_set_speed": _op_draw_set_speed,
        "draw_set_overlap": _op_draw_set_overlap,
        "draw_abort": _op_draw_abort,
        "draw_progress": _op_draw_progress,
    }

    # ------------------------------------------------------------------ #
    # Snapshot (с mode для VfdDriver gating и GUI)
    # ------------------------------------------------------------------ #

    def snapshot(self, data: dict | None = None, quality: str | None = None) -> dict:
        """Snapshot с mode и job-счётчиками."""
        base = {
            "mode": self._mode,
            "manual_mode": self.manual_mode,
            "queue_len": len(self._job_queue),
            "jobs_sent": self.jobs_sent,
            "jobs_done": self.jobs_done,
            "jobs_failed": self.jobs_failed,
            "draws_done": self.draws_done,
            "draw_state": self._draw_state,
            "draw_queued": self._draw_queue.qsize(),
            "returns_done": self.returns_done,
            "returns_failed": self.returns_failed,
            "return_queued": len(self._return_queue),
            "pick_lead_mm": self._pick_lead_mm,
        }
        if data:
            base.update(data)
        return super().snapshot(base, quality)

    # ------------------------------------------------------------------ #
    # Служебное
    # ------------------------------------------------------------------ #

    @property
    def last_io(self) -> dict:
        """Последний wire-обмен {input, output} для панели «Вход/Выход»."""
        return self._last_io

    def _on_wire(self, payload: dict) -> None:
        """on_data ModbusDevice: запомнить последний TX (запись) и RX (чтение).

        Дёшево (без публикации) — публикует супервизор раз в тик. payload:
        чтение ``{op, address, values}``; запись ``{op, address, value}``;
        транзакция ``{op, count}``.
        """
        op = str(payload.get("op", ""))
        addr = payload.get("address")
        reg = f"0x{addr:04X}" if isinstance(addr, int) else None
        if op.startswith("read"):
            self._last_io["input"] = {"op": op, "reg": reg, "values": payload.get("values")}
        else:
            self._last_io["output"] = {
                "op": op,
                "reg": reg,
                "value": payload.get("value", payload.get("count")),
            }

    def _build_client(self) -> Any:
        """Создать RobotClient с правильным конфигом."""
        from Services.robot_comm import RobotClient, RobotConfig

        if self._transport is not None:
            # Инъекция транспорта (тесты)
            config = RobotConfig.from_dict(
                {
                    **self.entry.transport,
                    **self.entry.params,
                }
            )
            return RobotClient(
                config,
                transport=self._transport,
                clock=self._clock,
                sleep=self._sleep,
            )

        # Боевой режим — конфиг из entry.transport + entry.params
        from Services.robot_comm.core.registers import PTS_MAX

        t = self.entry.transport
        p = self.entry.params
        config = RobotConfig(
            host=t.get("host", "192.168.1.7"),
            port=int(t.get("port", 502)),
            unit_id=int(t.get("unit_id", 2)),
            timeout_sec=float(t.get("timeout_sec", 1.0)),
            word_order=str(p.get("word_order", "little")),
            # Точность рисования: мельче пачки + read-back ACK (см. RobotConfig).
            draw_pass_size=int(p.get("draw_pass_size", PTS_MAX)),
            draw_verify=bool(p.get("draw_verify", True)),
            draw_retry=int(p.get("draw_retry", 1)),
        )
        return RobotClient(config, on_data=self._on_wire, clock=self._clock, sleep=self._sleep)

    def _wait_condition(self, condition: Any, timeout: float, stop_event: Any) -> bool:
        """Поллить условие до timeout (прерываемо stop_event)."""
        t_end = self._clock() + timeout
        while self._clock() < t_end:
            if stop_event is not None and stop_event.is_set():
                return False
            try:
                if condition():
                    return True
            except Exception:
                self._record_err()
                return False
            self._sleep(self._feed_poll_s)
        return False
