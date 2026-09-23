# -*- coding: utf-8 -*-
"""``SimRobotHostPlugin`` — хост ``Services.robot_comm.server.sim_robot.SimRobotServer``.

Обычный side-effect плагин ``ProcessModulePlugin`` в ``GenericProcessApp`` (форма —
как у ``Plugins/io/otel_export``: сервис в ``Services``, тонкий плагин здесь). Он
поднимает Modbus TCP-симулятор робота на своём порту, считает записи обмена
(``writes_seen``) и отдаёт статус командой ``sim_robot.status``.

**Деградация без ``pymodbus`` — состояние, не отказ процесса** (образец:
``OtelExportPlugin`` без extra ``[otel]``, Р-14 из его докстринга). Импорт
``Services.robot_comm.server.sim_robot`` и конструктор ``SimRobotServer`` живут
ВНУТРИ ``try`` в :meth:`_start_server`: без ``pymodbus`` конструктор бросает
``ModbusNotAvailableError`` (текст уже содержит слово «modbus» —
``Services/robot_comm/server/sim_robot.py:109``), плагин ловит её, уходит в
``_state = "error"`` и зовёт ``ctx.health.report_error(...)`` — тот же коннектор,
что кладёт факт в плоскость ошибок (``errors.log``) И пишет строку журнала одним
вызовом (ADR-PM-030). Процесс при этом поднимается: `start()` не пробрасывает
исключение наружу.

**Порт занят — обнаруживается СВОИМ пробным bind'ом, а не исключением
``SimRobotServer``.** ``SimRobotServer.start()`` не блокирует до подтверждения
бинда: он запускает ``pymodbus`` (``StartTcpServer``) в фоновом daemon-потоке
(``sim_robot.py:121-126``) и возвращается немедленно, а ошибка ``bind()`` при
занятом порту случится ВНУТРИ этого потока — синхронный ``try/except`` вокруг
``.start()`` её никогда не поймает (поток просто тихо умирает). Поэтому
:meth:`_start_server` сперва сам биндит и сразу закрывает пробный сокет на том же
``host``/``port`` — если ОС отказала (``OSError``, порт занят), это ловится здесь,
синхронно, ДО обращения к ``pymodbus``. Окно гонки между пробным закрытием и
реальным биндом сервера теоретически есть, но для одиночного процесса-симулятора
на выделенном порту (5021, out of scope — гонка с параллельным конкурентом) этого
достаточно; более сильная гарантия потребовала бы правки ``Services/robot_comm``,
которая вне области задачи.

**Счёт записей — под ``Lock``, публикация метрики — с чужого потока не зовётся.**
``on_write`` вызывается ``pymodbus``-сервером на ЕГО СОБСТВЕННОМ потоке
(``sim_robot.py:69`` — корутина ``binder`` исполняется event-loop'ом сервера, не
приёмным потоком процесса). ``PluginContext.record_metric`` документирован как
безопасный только со штатного потока плагина (``_stats_call`` держит свой
``_counters_lock`` не всегда — у ``StatsManager``/порта наблюдений явных
гарантий межпотокового вызова в докстринге ``base.py`` нет). Поэтому
:meth:`_on_write` только инкрементирует счётчик под ``self._lock`` (примитив,
безопасный из любого потока по построению) и НЕ зовёт ``ctx.record_metric``
напрямую; перенос в плоскость stats делает :meth:`_sync_writes_metric` —
дельтой, тем же приёмом, что ``OtelExportPlugin._sync_queue_counters`` — и
зовётся она только из :meth:`cmd_status` и :meth:`shutdown`, то есть с потока
диспетчера команд/останова процесса, а не с потока ``pymodbus``.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from collections import deque
from typing import Any

from multiprocess_framework.modules.process_module.plugins import (
    ExecutionMode,
    PluginContext,
    ProcessModulePlugin,
    ThreadConfig,
    register_plugin,
)
from Plugins.hub.device_hub.client import DeviceHubClient
from Services.robot_comm.server.sim_core import VFD_CMD_ADDR, RobotSimCore
from Services.robot_comm.server.sim_journal import SimJournal

#: Теги строк журнала, попадающих в ``recent`` команды ``sim_robot.journal``
#: (Контракт лида 5.1, §2) — служебные теги ``""``/``"flag"`` туда не идут.
_JOURNAL_RECENT_TAGS = {"job", "dup", "repeat", "done"}

#: Ёмкость кольца недавних строк журнала, отдаваемых командой ``sim_robot.journal``.
_JOURNAL_RECENT_MAXLEN = 50

#: Дефолты конфига (Task 1.1 плана line-sim, §Task 1.1 pipeline.yaml).
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 5021
_DEFAULT_UNIT_ID = 2

#: Task 3.5: процесс сцены, куда уходит событие «задание выполнено» (``scene.job_done``).
_DEFAULT_SCENE_PROCESS = "camera"

#: Троттл отчёта о сбое пересылки события (как у ``DeviceHubClient.request``).
_JOB_DONE_ERROR_THROTTLE_S = 30.0

#: Период публикации энкодера в общий мир (Task 2.2 плана line-sim, §Task 2.2).
_DEFAULT_PUBLISH_MS = 50

#: Dead-man jog (Task 2.3a плана line-sim, §Task 2.3a): без подкачки команда
#: сама гасится через jog_timeout_ms; дефолтная частота джога, если клиент её
#: не передал.
_DEFAULT_JOG_TIMEOUT_MS = 500
_DEFAULT_JOG_FREQ_HZ = 10.0

#: Масштаб частоты ПЧ в mailbox — 0.01 Гц/LSB (см. gd20_bridge.yaml
#: cmd_freq.scale; тот же множитель приватно продублирован в
#: ``Services/robot_comm/server/sim_core.py`` как ``_VFD_FREQ_SCALE``).
#: Нужен здесь, чтобы cmd_belt_jog считал ``_jog_regs`` ИЗ АРГУМЕНТОВ
#: команды, а не читал их обратно из mailbox (ревью Task 2.3a, п.2).
_VFD_CMD_FREQ_SCALE = 100.0


@register_plugin("sim_robot_host", category="io", description="Хост Modbus TCP-симулятора робота (SimRobotServer)")
class SimRobotHostPlugin(ProcessModulePlugin):
    """Плагин-хост ``SimRobotServer``: конфиг → пробный порт → сервер → счёт записей."""

    name = "sim_robot_host"
    category = "io"

    VERSION = "1.0.0"
    REQUIRES: tuple[str, ...] = ("manager:command_manager",)

    inputs: list = []
    outputs: list = []

    commands = {
        "sim_robot.status": "cmd_status",
        "belt.run": "cmd_belt_run",
        "belt.stop": "cmd_belt_stop",
        "belt.jog": "cmd_belt_jog",
        "belt.calibrate": "cmd_belt_calibrate",
        "belt.status": "cmd_belt_status",
        "sim_robot.journal": "cmd_journal",
        "sim_robot.journal_reset": "cmd_journal_reset",
    }

    def configure(self, ctx: PluginContext) -> None:
        """READY: разобрать конфиг, завести состояние. Сеть здесь не трогаем."""
        self._ctx = ctx
        cfg = ctx.config
        self._host: str = cfg.get("host", _DEFAULT_HOST)
        self._port: int = cfg.get("port", _DEFAULT_PORT)
        self._unit_id: int = cfg.get("unit_id", _DEFAULT_UNIT_ID)
        self._scene_process: str = cfg.get("scene_process", _DEFAULT_SCENE_PROCESS)
        self._auto_start: bool = cfg.get("auto_start", True)
        self._publish_ms: int = cfg.get("publish_ms", _DEFAULT_PUBLISH_MS)
        # Task 2.3a: командная поверхность ленты.
        self._jog_timeout_ms: float = cfg.get("jog_timeout_ms", _DEFAULT_JOG_TIMEOUT_MS)
        self._jog_freq_hz: float = cfg.get("jog_freq_hz", _DEFAULT_JOG_FREQ_HZ)
        self._belt_mm_s_at_max_freq: float | None = cfg.get("belt_mm_s_at_max_freq")

        self._server: Any = None
        self._lock = threading.Lock()
        self._writes_seen = 0
        # Журнал заданий (Контракт лида 5.1, §2) — заводится в _start_server,
        # ДО сервера, чтобы on_write/on_event сервера сразу видели живой объект.
        self._journal: SimJournal | None = None
        # Кольцо строк для команды sim_robot.journal — наполняется ТОЛЬКО тиком
        # паблишера (_publish_once), drain() журнала разрушающий — забирает один владелец.
        self._journal_recent: deque[dict[str, Any]] = deque(maxlen=_JOURNAL_RECENT_MAXLEN)
        # Dead-man jog (под self._lock — пишут и команда, и паблишер):
        # _jog_regs — что jog записал в mailbox (RUN, DIR, FREQ), _jog_deadline —
        # когда watchdog должен проверить, не перебит ли jog другим писателем.
        self._jog_deadline: float | None = None
        self._jog_regs: tuple[int, int, int] | None = None
        self._jogging = False
        # Сколько записей уже перенесено в плоскость stats (дельта, не абсолют —
        # тот же приём, что у ``OtelExportPlugin._queue_dropped_seen``).
        self._writes_reported = 0
        self._state = "configured"
        self._reason = ""

        # Task 2.0 не влит → ctx.state_proxy is None: запись в общий мир
        # пропускается (см. _publish_once), но паблишер уровней работает всегда.
        ctx.declare_metric("encoder")
        ctx.declare_metric("belt_mm_s")
        ctx.declare_metric("writes_seen")
        # Уровни журнала заданий (Контракт лида 5.1, §2). ``repeats_frozen_xy`` ушёл
        # отсюда в 5.1b — причина «те же X/Y» теперь считается TruthLedger'ом на
        # стороне сцены (Services/line_sim/core/truth.py), не журналом робота.
        ctx.declare_metric("jobs_seen")
        ctx.declare_metric("dups_seen")
        ctx.declare_metric("dups_same_capture")
        ctx.declare_metric("dups_tracked")
        ctx.declare_metric("jobs_done")

        ctx.log_info(f"sim_robot_host: конфиг принят, {self._host}:{self._port}, unit_id={self._unit_id}")

    def start(self, ctx: PluginContext) -> None:
        """RUNNING: поднять сервер, если ``auto_start``, и паблишер уровней/мира.

        Паблишер стартует ВСЕГДА (ревью Task 2.2, находка №2): без
        ``state_proxy`` (Task 2.0 не влита) уровни ``encoder``/``belt_mm_s``/
        ``writes_seen`` всё равно обязаны течь — молчали они раньше только
        потому, что ``_publish_once`` возвращалась до вызова
        ``ctx.publish_metric``, путая «мира нет» с «наблюдать нечего». В
        общий мир (``ctx.state_proxy.set``) запись пропускается — это делает
        сама :meth:`_publish_once`.
        """
        if self._auto_start:
            self._start_server(ctx)

        if ctx.state_proxy is None:
            ctx.log_info("sim_robot_host: ctx.state_proxy is None — мир недоступен, метрики публикуются без world.set")
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker("sim_robot_world_publisher", self._publish_loop, cfg, auto_start=True)

    def shutdown(self, ctx: PluginContext) -> None:
        """STOPPED: дожать счётчик, остановить сервер симметрично ``start()``."""
        self._sync_writes_metric()
        if self._server is not None:
            self._server.stop()
            self._server = None
        self._state = "stopped"
        ctx.log_info(f"sim_robot_host: остановлен, writes_seen={self._writes_seen}")

    # ------------------------------------------------------------------ #
    # Старт сервера
    # ------------------------------------------------------------------ #

    def _start_server(self, ctx: PluginContext) -> None:
        """Поднять ``SimRobotServer``. Живой сервер — no-op (повторный ``start``)."""
        if self._server is not None:
            return

        try:
            self._probe_port_free()
        except OSError as exc:
            self._fail(ctx, exc)
            return

        with self._lock:
            # Рестарт сервера — новый журнал; строки прошлого запуска в recent остаться
            # не должны (ревью 3.5/5.1, minor 2: было counters.jobs=0 при recent=[job, dup]).
            self._journal = SimJournal()
            self._journal_recent.clear()
        try:
            from Services.modbus.sdk.errors import ModbusNotAvailableError
            from Services.robot_comm.server.sim_robot import SimRobotServer

            core = RobotSimCore(
                on_job_done=self._on_job_done,
                on_event=self._journal.on_event,
            )
            server = SimRobotServer(self._host, self._port, self._unit_id, core=core, on_write=self._on_write)
            server.start()
        except (ModbusNotAvailableError, ImportError, OSError) as exc:  # noqa: BLE001 — деградация, не отказ
            self._fail(ctx, exc)
            return

        self._server = server
        self._state = "running"
        self._reason = ""
        if self._belt_mm_s_at_max_freq is not None:
            # Решение ведущего 2026-09-22 (план line-sim §Task 2.3a, DESIGN п.5):
            # лента едет с первого тика, как раньше, но зеркало ПЧ/belt.status
            # согласованы с самого старта — "run=True при нулевом зеркале" не
            # бывает.
            server.core.belt.set_calibration(self._belt_mm_s_at_max_freq)
            server.core.command_vfd(run=True, freq_hz=server.core.belt.freq_max_hz, reverse=False)
        ctx.log_info(f"sim_robot_host: SimRobotServer поднят на {self._host}:{self._port}")

    def _on_job_done(self, event: dict) -> None:
        """Task 3.5: переслать событие «задание выполнено» в процесс сцены.

        Исполняется в потоке тикера ``SimRobotServer`` — поэтому только
        fire-and-forget (неблокирующая постановка в очередь) и НИКОГДА не бросает:
        исключение из колбэка ядро не ловит, оно уронило бы тикер робота.
        Исключение или ``False`` (нет роутера/``send_async``) -> ``ctx.health.report_error``
        с троттлом."""
        try:
            client = DeviceHubClient(self._ctx, target_process=self._scene_process)
            if not client.send_fire_and_forget("scene.job_done", event):
                self._ctx.health.report_error(
                    RuntimeError("scene.job_done не поставлен в очередь"),
                    context="sim_robot_host.job_done",
                    throttle=_JOB_DONE_ERROR_THROTTLE_S,
                )
        except Exception as exc:  # noqa: BLE001 — колбэк тикера не должен бросать
            self._ctx.health.report_error(exc, context="sim_robot_host.job_done", throttle=_JOB_DONE_ERROR_THROTTLE_S)

    def _probe_port_free(self) -> None:
        """Синхронно проверить, что порт свободен, ДО обращения к pymodbus.

        См. докстринг модуля: ``SimRobotServer.start()`` биндит порт в фоновом
        потоке и не сообщает об ошибке синхронно вызывающему.
        """
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # SO_REUSEADDR — как у самого сервера (pymodbus передаёт reuse_address=True):
            # порт в TIME_WAIT после прошлого запуска не считается занятым, а живой
            # слушатель на том же адресе всё равно даёт EADDRINUSE (тесты AC1/AC2 в
            # tests/test_acceptance_time_wait.py). Без него рестарт в течение ~30 с на
            # macOS падал в error при свободном порту (стенд Task 1.3, 2026-09-21).
            # Только POSIX: на Windows SO_REUSEADDR разрешает bind поверх живого
            # слушателя, и проба перестала бы замечать ещё живой прошлый сим.
            if os.name == "posix":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((self._host, self._port))
        finally:
            probe.close()

    def _fail(self, ctx: PluginContext, exc: Exception) -> None:
        """Перевести плагин в ``error``: факт в плоскость ошибок + голос, процесс живёт."""
        self._state = "error"
        self._reason = str(exc)
        ctx.health.report_error(exc, context="sim_robot_host.start", host=self._host, port=self._port)

    # ------------------------------------------------------------------ #
    # Приём обмена
    # ------------------------------------------------------------------ #

    def _on_write(self, fc: int, addr: int, values: list[int] | None) -> None:
        """Наблюдатель обмена ``SimRobotServer`` (чужой поток — см. докстринг модуля).

        Каждый доступ (чтения ТОЖЕ, ``values is None``) форвардится в
        ``self._journal.on_write`` — журнал сам считает чтения отдельным
        счётчиком (Контракт лида 5.1, §2); ``SimJournal.on_write`` дешёвый
        (свой ``Lock``, без IPC) — публикация метрик сюда НЕ переносится
        (этот метод зовётся с потока ``pymodbus``).
        ``values is None`` — чтение, не считаем в ``_writes_seen``. Иначе —
        запись, инкремент под локом; публикация в plane stats отложена до
        :meth:`_sync_writes_metric`.
        """
        if self._journal is not None:
            self._journal.on_write(fc, addr, values)
        if values is None:
            return
        with self._lock:
            self._writes_seen += 1

    def _sync_writes_metric(self) -> None:
        """Перенести накопленные записи в ``ctx.record_metric`` ДЕЛЬТОЙ.

        Зовётся только со штатных потоков плагина (диспетчер команд —
        :meth:`cmd_status`, либо останов — :meth:`shutdown`), никогда с потока
        ``pymodbus``.
        """
        with self._lock:
            delta = self._writes_seen - self._writes_reported
            if delta <= 0:
                return
            self._writes_reported = self._writes_seen
        self._ctx.record_metric("sim_robot.writes", delta)

    # ------------------------------------------------------------------ #
    # Паблишер мира (Task 2.2) — энкодер в ``sim.belt.encoder`` + уровни
    # ------------------------------------------------------------------ #

    def _publish_loop(self, stop_event: Any, pause_event: Any) -> None:
        """Тик паблишера: ``publish_ms`` (форма — ``TelemetrySinkPlugin._sample_loop``).

        Сторож jog (:meth:`_check_jog_watchdog`) зовётся КАЖДУЮ итерацию,
        включая паузу (ревью Task 2.3a, п.6): на паузе никто не опрашивает
        ``belt.status`` — единственный другой путь к сторожу (см.
        ``README.md``) — и без этого вызова dead-man jog не сработал бы,
        пока процесс стоит на паузе. ``_publish_once`` — по-прежнему только
        вне паузы.

        Ошибка одного тика (например, сервер ещё не поднят) не должна убивать
        воркер — иначе публикация мира молча умирает навсегда.
        """
        interval_s = self._publish_ms / 1000.0
        while not stop_event.is_set():
            paused = pause_event.is_set()
            time.sleep(0.1 if paused else interval_s)
            try:
                self._check_jog_watchdog()
                if not paused:
                    self._publish_once()
            except Exception as exc:  # noqa: BLE001 — тик не должен убить воркер
                self._ctx.health.report_error(exc, context="sim_robot_host.publish")

    def _check_jog_watchdog(self) -> None:
        """Dead-man jog (Task 2.3a, ревью — находка «гонка сторожа jog»): без
        сервера ленты нет — рано выходим ДО каких-либо проверок (сам
        ``self._server`` под замком не мутируется, трогать его безопасно и
        без ``self._lock``). Иначе — ВЕСЬ путь ниже (дедлайн, чтение mailbox,
        сравнение, ``command_vfd``) идёт ПОД ОДНИМ ``self._lock`` — тем же
        замком и тем же неразрывным куском, что ``cmd_belt_run``/
        ``cmd_belt_stop``/``cmd_belt_jog`` держат вокруг своего
        ``command_vfd`` (см. их докстринги). Без единого замка на весь путь
        ``belt.run`` из другого потока мог записать mailbox МЕЖДУ чтением
        сторожа и его стопом — сторож гасил уже НОВУЮ команду, а не свой jog
        (найдено ревью; воспроизведено детерминированно в
        ``tests/test_hazards.py``, стохастически — 3/20000 без форсинга до
        фикса). Компромисс безопасен: ``core.read``/``core.command_vfd``
        только мутируют список регистров в памяти, IPC внутри замка не
        зовём (TRAPS ведущего).

        Если дедлайн настал, стопим ленту, но ТОЛЬКО если mailbox всё ещё
        равен тому, что записал jog (``_jog_regs``, читается через
        ``VFD_CMD_ADDR`` — тот же адрес, что и приёмка); если mailbox уже
        переписан другим мастером (боевой ``VfdClient`` или
        ``belt.run``/``belt.stop`` — те чистят jog сами под тем же замком,
        см. :meth:`_clear_jog_locked`), jog считается перебитым: флаг
        снимается, лента не трогается. Отдельной повторной проверки
        ``self._jog_deadline == deadline`` перед очисткой больше не нужно —
        под одним замком новый jog не может вклиниться между чтением и
        очисткой.
        """
        if self._server is None:
            return
        core = self._server.core
        with self._lock:
            deadline = self._jog_deadline
            regs = self._jog_regs
            if deadline is None or time.monotonic() < deadline:
                return
            current = tuple(core.read(VFD_CMD_ADDR, 3))
            if current == regs:
                core.command_vfd(run=False)
            self._jog_deadline = None
            self._jog_regs = None
            self._jogging = False

    def _publish_once(self) -> None:
        """Один тик: снять энкодер+скорость сервера, отдать уровни, и (если мир
        есть) положить те же числа в общий мир.

        ``mm_s`` — ТОЧНАЯ команда ПЧ (``RobotSimCore.belt_mm_s`` ->
        ``BeltDrive.mm_s``, добавлено ревью Task 2.2), не производная энкодера
        между двумя тиками публикации: старая производная давала смешанное
        среднее на пульсе смены команды, а не мгновенную скорость (находка
        ревью №1).

        Публикация уровней и запись в мир — РАЗНЫЕ дороги (находка ревью №2):
        без ``ctx.state_proxy`` (Task 2.0 не влита) пропускается ТОЛЬКО
        ``ctx.state_proxy.set`` — уровни ``encoder``/``belt_mm_s``/
        ``writes_seen`` публикуются всегда, пока сервер поднят.
        """
        if self._server is None:
            return

        core = self._server.core
        encoder = core.encoder
        mm_s = core.belt_mm_s

        if self._ctx.state_proxy is not None:
            self._ctx.state_proxy.set("sim.belt.encoder", {"value": encoder, "mm_s": mm_s, "t": time.monotonic()})

        with self._lock:
            writes_seen = self._writes_seen
        self._ctx.publish_metric("encoder", encoder)
        self._ctx.publish_metric("belt_mm_s", mm_s)
        self._ctx.publish_metric("writes_seen", writes_seen)
        self._publish_journal_once()

    def _publish_journal_once(self) -> None:
        """Уровни журнала + перенос новых строк в ``_journal_recent`` (Контракт §2).

        ``journal.drain()`` разрушающий (``SimJournal.drain``: «журнал очищается»)
        — забирает его строго ОДИН владелец, тик
        паблишера; сам приём (``_on_write``) в журнал только пишет, никогда
        не читает и не чистит.
        """
        if self._journal is None:
            return
        counters = self._journal.counters()
        self._ctx.publish_metric("jobs_seen", counters["jobs"])
        self._ctx.publish_metric("dups_seen", counters["dups"])
        self._ctx.publish_metric("dups_same_capture", counters["dups_same_capture"])
        self._ctx.publish_metric("dups_tracked", counters["dups_tracked"])
        self._ctx.publish_metric("jobs_done", counters["done"])

        with self._lock:
            for entry in self._journal.drain():
                if entry.tag in _JOURNAL_RECENT_TAGS:
                    self._journal_recent.append(
                        {"t": entry.t, "side": entry.side, "text": entry.text, "tag": entry.tag}
                    )

    # ------------------------------------------------------------------ #
    # Команды
    # ------------------------------------------------------------------ #

    def cmd_status(self, data: dict | None = None) -> dict:
        """``sim_robot.status`` → running/host/port/unit_id/writes_seen/state/world/journal."""
        self._sync_writes_metric()
        with self._lock:
            writes_seen = self._writes_seen
        return {
            "running": self._state == "running",
            "host": self._host,
            "port": self._port,
            "unit_id": self._unit_id,
            "writes_seen": writes_seen,
            "state": self._state,
            "world": "unavailable" if self._ctx.state_proxy is None else "ok",
            "journal": self._journal.counters() if self._journal is not None else {},
        }

    # ------------------------------------------------------------------ #
    # Журнал заданий (Контракт лида 5.1, §2)
    # ------------------------------------------------------------------ #

    def cmd_journal(self, data: dict | None = None) -> dict:
        """``sim_robot.journal`` → ``{counters, recent}``; без сервера — ошибка."""
        if self._server is None or self._journal is None:
            return {"status": "error", "message": "server_not_running"}
        with self._lock:
            recent = list(self._journal_recent)
        return {"status": "ok", "counters": self._journal.counters(), "recent": recent}

    def cmd_journal_reset(self, data: dict | None = None) -> dict:
        """``sim_robot.journal_reset`` → обнулить счётчики журнала и очистить ``recent``."""
        if self._server is None or self._journal is None:
            return {"status": "error", "message": "server_not_running"}
        # Сброс и очистка — под ОДНИМ self._lock, как drain в такте публикации (ревью 3.5/5.1,
        # minor 1): иначе тик между ними переносил строку задания в recent, а clear её стирал.
        # Порядок замков тот же, что у drain: self._lock -> SimJournal._lock.
        with self._lock:
            self._journal.reset()
            self._journal_recent.clear()
        return {"status": "ok"}

    # ------------------------------------------------------------------ #
    # Команды ленты (Task 2.3a) — исполняются на потоке диспетчера команд
    # процесса ("message_processor", см. README: не блокировать — ни sleep,
    # ни router.request внутри cmd_belt_*).
    # ------------------------------------------------------------------ #

    @staticmethod
    def _bad_args(msg: str) -> dict:
        return {"ok": False, "error": f"bad_args: {msg}"}

    @staticmethod
    def _no_server() -> dict:
        return {"ok": False, "error": "server_not_running"}

    def _validate_freq(self, freq_hz: Any) -> dict | None:
        """``None`` если ``freq_hz`` валиден, иначе — готовый ``bad_args`` ответ.

        Отказ, не клэмп — как ``VfdClient._validate_freq`` (``client.py:140-145``).
        """
        if not isinstance(freq_hz, (int, float)) or isinstance(freq_hz, bool):
            return self._bad_args("freq_hz обязателен и должен быть числом")
        freq_max_hz = self._server.core.belt.freq_max_hz
        if not (0 <= freq_hz <= freq_max_hz):
            return self._bad_args(f"freq_hz={freq_hz} вне диапазона [0, {freq_max_hz}]")
        return None

    def _clear_jog_locked(self) -> None:
        """Снять jog безусловно. Вызывать ТОЛЬКО под ``self._lock`` — так его
        зовут ``cmd_belt_run``/``cmd_belt_stop`` одним куском со своим
        ``command_vfd`` (ревью Task 2.3a, п.1: до этого замок здесь был
        отдельный и короткий, а ``command_vfd`` шёл уже без него)."""
        self._jog_deadline = None
        self._jog_regs = None
        self._jogging = False

    def _belt_status(self) -> dict:
        # Watchdog проверяется здесь ТОЖЕ (не только на тике паблишера) —
        # чтение статуса не должно ждать publish_ms, чтобы увидеть остывший
        # dead-man jog: клиент, опрашивающий belt.status в цикле, сам
        # выступает "тиком" для watchdog на потоке диспетчера команд, то же,
        # что уже проверяет _publish_loop. Идемпотентно (early-return при
        # отсутствии дедлайна) — двойной вызов на один тик безвреден.
        self._check_jog_watchdog()
        core = self._server.core
        state = core.belt.state
        with self._lock:
            jogging = self._jogging
        return {
            "ok": True,
            "run": state["run"],
            "freq_hz": state["freq_hz"],
            "reverse": state["reverse"],
            "mm_s": core.belt_mm_s,
            "encoder": core.encoder,
            "jogging": jogging,
            "mm_s_at_max_freq": core.belt.mm_s_at_max_freq,
        }

    def cmd_belt_run(self, data: dict | None = None) -> dict:
        """``belt.run{freq_hz, reverse=False}`` — команда ПЧ через mailbox,
        снимает jog безусловно.

        ``reverse`` обязан быть НАСТОЯЩИМ ``bool`` (ревью Task 2.3a, п.5):
        ``bool("false")`` в Python — ``True``, старый ``bool(data.get(...))``
        принимал за истину любую непустую строку.

        Снятие jog + ``command_vfd`` — ПОД ``self._lock`` одним куском (ревью,
        п.1): сериализовано со сторожем, см. докстринг
        :meth:`_check_jog_watchdog`. Замок короткий, IPC внутри не зовём."""
        if self._server is None:
            return self._no_server()
        data = data or {}
        freq_hz = data.get("freq_hz")
        err = self._validate_freq(freq_hz)
        if err is not None:
            return err
        reverse = data.get("reverse", False)
        if not isinstance(reverse, bool):
            return self._bad_args("reverse должен быть bool")
        with self._lock:
            self._clear_jog_locked()
            self._server.core.command_vfd(run=True, freq_hz=float(freq_hz), reverse=reverse)
        return self._belt_status()

    def cmd_belt_stop(self, data: dict | None = None) -> dict:
        """``belt.stop`` — пишет ТОЛЬКО RUN=0 (CMD_FREQ не трогается), снимает
        jog под тем же замком, что ``cmd_belt_run`` (см. его докстринг)."""
        if self._server is None:
            return self._no_server()
        with self._lock:
            self._clear_jog_locked()
            self._server.core.command_vfd(run=False)
        return self._belt_status()

    def cmd_belt_jog(self, data: dict | None = None) -> dict:
        """``belt.jog{direction: +-1, freq_hz?}`` — dead-man: без подкачки в
        течение ``jog_timeout_ms`` watchdog (:meth:`_check_jog_watchdog`,
        тикает в ``_publish_loop`` и опортунистически в ``_belt_status``) сам
        остановит ленту, если mailbox к тому моменту не переписан другим
        мастером.

        ``direction`` обязан быть НАСТОЯЩИМ ``int`` ``+-1`` (ревью Task 2.3a,
        п.5): ``bool`` — подкласс ``int``, ``True in (1, -1)`` истинно, старая
        проверка принимала ``direction=True`` за ``+1``.

        ``_jog_regs`` считается ИЗ АРГУМЕНТОВ команды (``run=1``, ``dir``,
        ``round(freq_hz*100)``), а НЕ читается обратно из mailbox (ревью,
        п.2): Modbus-запись другого мастера, попавшая в окно между записью и
        обратным чтением, была бы принята за СВОЙ же jog и потом остановлена
        сторожем как чужая — обратное чтение убрано целиком.

        Запись mailbox + установка дедлайна — ПОД ``self._lock`` одним куском,
        как у ``cmd_belt_run``/``cmd_belt_stop`` (см. докстринг
        :meth:`_check_jog_watchdog`)."""
        if self._server is None:
            return self._no_server()
        data = data or {}
        direction = data.get("direction")
        if not isinstance(direction, int) or isinstance(direction, bool) or direction not in (1, -1):
            return self._bad_args("direction должен быть +1 или -1")
        freq_hz = data.get("freq_hz", self._jog_freq_hz)
        err = self._validate_freq(freq_hz)
        if err is not None:
            return err
        freq_hz_f = float(freq_hz)
        reverse = direction < 0
        regs = (1, 1 if reverse else 0, round(freq_hz_f * _VFD_CMD_FREQ_SCALE))
        with self._lock:
            self._server.core.command_vfd(run=True, freq_hz=freq_hz_f, reverse=reverse)
            self._jog_regs = regs
            self._jog_deadline = time.monotonic() + self._jog_timeout_ms / 1000.0
            self._jogging = True
        return self._belt_status()

    def cmd_belt_calibrate(self, data: dict | None = None) -> dict:
        """``belt.calibrate{mm_s_at_max_freq}`` — ``BeltDrive.set_calibration``
        под её собственным локом; mailbox не трогает."""
        if self._server is None:
            return self._no_server()
        data = data or {}
        value = data.get("mm_s_at_max_freq")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return self._bad_args("mm_s_at_max_freq обязателен и должен быть числом")
        try:
            self._server.core.belt.set_calibration(float(value))
        except ValueError as exc:
            return self._bad_args(str(exc))
        return self._belt_status()

    def cmd_belt_status(self, data: dict | None = None) -> dict:
        """``belt.status`` → эффективное состояние ленты (``core.belt.state``),
        не последняя команда КОНКРЕТНО этого плагина — см. DESIGN п.6 (арбитраж
        два мастера одного mailbox)."""
        if self._server is None:
            return self._no_server()
        return self._belt_status()
