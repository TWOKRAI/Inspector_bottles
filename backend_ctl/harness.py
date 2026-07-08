# -*- coding: utf-8 -*-
"""BackendHarness — headless-запуск прототипа для тестов + гарантированный teardown.

Назначение (Ф1 Task 1.3): поднять реальную систему прототипа **без GUI**, подключить
``BackendDriver`` и — главное — гарантировать, что после теста НЕ остаётся висящих
процессов (урок Ф0.4: shutdown мог зависать 8+ минут из-за gui/LoginDialog).

Честный headless (не костыль в проде):
    Процесс презентации (``gui``) исключается из топологии на стороне harness —
    :func:`strip_gui` фильтрует его из blueprint ДО сборки ``SystemBuilder``. Прод-код
    (multiprocess_prototype/multiprocess_framework) не трогается: harness лишь собирает
    launcher из тех же публичных помощников (``load_topology_dict``/``merge_topologies``/
    ``SystemBuilder``), но с урезанной топологией. Так gui-процесс физически не спавнит
    Qt/LoginDialog — источник Ф0.4-зависания устранён в корне.

Гарантированный teardown:
    ``stop()`` зовёт ``launcher.shutdown()`` в watchdog-потоке с таймаутом; независимо от
    того, завершился ли штатный shutdown, добивает поддерево процессов (psutil terminate→
    kill) и логирует, что убито. Ни один сценарий не оставляет процессы висеть.

Запуск по умолчанию — рецепт ``region_pipeline`` (синтетический, без реального железа;
тот же, что использует ``smoke_proof``). С ``with_base=True`` подмешивается фундамент
(``base.yaml``), где как раз и живёт ``gui`` — тогда :func:`strip_gui` реально срабатывает.
"""

from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, List, Optional

from backend_ctl.driver import BackendDriver, _find_payload

if TYPE_CHECKING:
    from multiprocess_framework.modules.process_manager_module.launcher.system_launcher import (
        SystemLauncher,
    )

#: Имя процесса презентации в топологии (исключается для честного headless).
GUI_PROCESS_NAME = "gui"


# ---------------------------------------------------------------------------
# Топология: честный headless через фильтрацию gui-процесса
# ---------------------------------------------------------------------------


def strip_gui(blueprint: dict, *, gui_name: str = GUI_PROCESS_NAME) -> dict:
    """Вернуть топологию без процесса презентации (``gui``) — честный headless.

    Чистая функция над dict-контрактом (Dict-at-Boundary): не мутирует вход,
    возвращает либо исходный dict (если gui и так нет — no-op), либо мелкую копию
    с отфильтрованным ``processes``. Ссылки на ``gui`` в wires/chain_targets/displays
    остаются, но без процесса-приёмника просто не доставляются (router логирует, не
    падает) — для headless-инспекции этого достаточно.
    """
    if not isinstance(blueprint, dict):
        return blueprint
    procs = blueprint.get("processes")
    if not isinstance(procs, list):
        return blueprint
    filtered = [p for p in procs if not (isinstance(p, dict) and p.get("process_name") == gui_name)]
    if len(filtered) == len(procs):
        return blueprint  # gui-процесса не было — топологию не трогаем
    bp = dict(blueprint)
    bp["processes"] = filtered
    return bp


def build_headless_launcher(
    *,
    recipe: Optional[Path | str] = None,
    with_base: bool = False,
) -> "SystemLauncher":
    """Собрать ``SystemLauncher`` из топологии прототипа БЕЗ gui-процесса.

    Args:
        recipe: путь к рецепту/топологии; None → дефолтный ``region_pipeline``
            (тот же, что у ``smoke_proof`` — синтетический, без реального железа).
        with_base: подмешать фундамент (``base.yaml``) — там объявлен ``gui``,
            так что ``strip_gui`` реально что-то удаляет (демонстрация честного headless).

    Использует только ПУБЛИЧНЫЕ помощники прототипа — прод-код не меняется.
    """
    from multiprocess_prototype.backend.config.schemas import load_system_config
    from multiprocess_prototype.backend.launch import (
        SystemBuilder,
        load_topology_dict,
        merge_topologies,
    )
    from multiprocess_prototype.main import CONFIG_PATH, DEFAULT_BLUEPRINT, HERE

    bp_path = Path(recipe) if recipe else DEFAULT_BLUEPRINT
    blueprint = load_topology_dict(bp_path)
    if with_base:
        base_path = HERE / "backend" / "topology" / "base.yaml"
        blueprint = merge_topologies(load_topology_dict(base_path), blueprint)
    blueprint = strip_gui(blueprint)

    builder = SystemBuilder(
        sys_config=load_system_config(CONFIG_PATH),
        blueprint=blueprint,
        topology_path=bp_path,
        system_path=CONFIG_PATH,
    )
    return builder.build()


# ---------------------------------------------------------------------------
# Teardown: watchdog + гарантированный kill поддерева
# ---------------------------------------------------------------------------


def _subtree(orchestrator_pid: Optional[int]) -> list:
    """Снимок поддерева ОРКЕСТРАТОРА (сам PM + рекурсивно потомки), psutil.Process.

    Скоуп строго по pid оркестратора — НЕ по всем детям тест-процесса. Это принципиально:
    в одном pytest-процессе может жить второй бэкенд (session-фикстура), и добивать надо
    только своё дерево, не чужое. Снимок кэширует create_time → terminate по идентичности
    переживает репарентинг осиротевших внуков. Best-effort: при любой ошибке — пусто.
    """
    if orchestrator_pid is None:
        return []
    try:
        import psutil

        p = psutil.Process(orchestrator_pid)
        return [p] + p.children(recursive=True)
    except Exception:  # noqa: BLE001 — снимок не критичен
        return []


def _force_kill_tree(
    orchestrator_pid: Optional[int],
    snapshot: list,
    *,
    log: Callable[[str], None],
) -> List[int]:
    """Добить дерево ОРКЕСТРАТОРА (terminate→kill). Вернуть PID'ы, которых пришлось убить.

    Кандидаты = снимок (снятый на старте, пока цепочка цела) ∪ живое поддерево
    оркестратора сейчас (если PM ещё жив). Скоуп строго по дереву своего PM — чужой
    бэкенд (session-фикстура на другом порту/оркестраторе) не затрагивается. Гарантия
    контракта harness: после stop() висящих процессов ЭТОГО бэкенда не остаётся.
    """
    try:
        import psutil
    except Exception:  # noqa: BLE001 — без psutil форсировать нечем
        return []

    procs: list = list(snapshot) + _subtree(orchestrator_pid)
    seen: set = set()
    unique: list = []
    for p in procs:
        pid = getattr(p, "pid", None)
        if pid is None or pid in seen or pid == os.getpid():
            continue
        seen.add(pid)
        unique.append(p)

    killed: List[int] = []
    for p in unique:
        try:
            if p.is_running():
                p.terminate()
                killed.append(p.pid)
        except Exception:  # noqa: BLE001 — процесс уже мог умереть
            pass
    if unique:
        try:
            _gone, alive = psutil.wait_procs(unique, timeout=3.0)
            for p in alive:
                try:
                    p.kill()
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass
    if killed:
        log(f"[harness] принудительно снято процессов дерева PM: {sorted(killed)}")
    return killed


def _shutdown_with_watchdog(
    launcher: "SystemLauncher",
    timeout: float,
    orchestrator_pid: Optional[int],
    snapshot: list,
    *,
    log: Callable[[str], None],
) -> None:
    """Штатный shutdown в watchdog-потоке + гарантированный добой поддерева.

    Даже если ``launcher.shutdown()`` зависнет (урок Ф0.4), watchdog отпустит через
    ``timeout``, а ``_force_kill_tree`` доведёт teardown до конца — процессы не виснут.
    """
    done = threading.Event()

    def _run() -> None:
        try:
            launcher.shutdown()
        except Exception as exc:  # noqa: BLE001 — teardown обязан пережить любую ошибку
            log(f"[harness] launcher.shutdown() бросил {exc!r} — добиваю дерево")
        finally:
            done.set()

    t = threading.Thread(target=_run, name="harness-shutdown", daemon=True)
    t.start()
    if not done.wait(timeout):
        log(f"[harness] shutdown не завершился за {timeout}s — форсирую kill дерева")
    # Независимо от исхода shutdown — гарантируем отсутствие висящих процессов.
    _force_kill_tree(orchestrator_pid, snapshot, log=log)


# ---------------------------------------------------------------------------
# BackendHarness — фасад start/stop + контекст-менеджер
# ---------------------------------------------------------------------------


class BackendHarness:
    """Headless-запуск прототипа + подключённый driver с гарантированным teardown.

    Пример::

        with BackendHarness() as drv:
            print(drv.worker_status("preprocessor"))

    Или через фикстуру ``headless_backend`` (см. ``backend_ctl/tests/conftest.py``).
    """

    def __init__(
        self,
        *,
        recipe: Optional[Path | str] = None,
        with_base: bool = False,
        port: int = 8765,
        ready_timeout: float = 30.0,
        warmup: float = 1.0,
        teardown_timeout: float = 15.0,
        log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._recipe = recipe
        self._with_base = with_base
        self._port = port
        self._ready_timeout = ready_timeout
        self._warmup = warmup
        self._teardown_timeout = teardown_timeout
        self._log = log or (lambda m: print(m))

        self._launcher: Optional["SystemLauncher"] = None
        self._driver: Optional[BackendDriver] = None
        self._descendants: list = []
        self._orch_pid: Optional[int] = None

    @property
    def driver(self) -> BackendDriver:
        if self._driver is None:
            raise RuntimeError("BackendHarness не запущен — сперва start()")
        return self._driver

    def start(self) -> BackendDriver:
        """Поднять headless-систему, дождаться готовности, подключить driver."""
        # Гейт сокета: env — escape-hatch (yaml тоже enabled). Порт driver'а должен
        # совпасть с endpoint'ом — фиксируем BACKEND_CTL_PORT (его читает endpoint).
        os.environ["BACKEND_CTL"] = "1"
        os.environ["BACKEND_CTL_PORT"] = str(self._port)
        # PID-реестр (INSPECTOR_PID_FILE) — свой файл на инстанс harness. Общий
        # дефолт рассчитан на «одна система на машину»: reap_and_reset при старте
        # ВТОРОГО бэкенда (test_harness при живой session-фикстуре) убил бы процессы
        # первого как «хвосты прошлого запуска». Осиротевшие хвосты harness добивает
        # сам (watchdog + kill дерева в stop()) — глобальный reap ему не нужен.
        import tempfile

        os.environ["INSPECTOR_PID_FILE"] = str(
            Path(tempfile.gettempdir()) / f"inspector_pids_harness_{os.getpid()}_{self._port}.jsonl"
        )

        self._launcher = build_headless_launcher(recipe=self._recipe, with_base=self._with_base)
        self._launcher.start()
        if not self._launcher.wait_until_ready(self._ready_timeout):
            self._log(f"[harness] система не готова за {self._ready_timeout}s — останавливаю")
            self.stop()
            raise RuntimeError("headless-бэкенд не поднялся (wait_until_ready timeout)")

        # pid оркестратора + снимок его поддерева ПОСЛЕ старта — для scoped-kill в teardown.
        self._orch_pid = self._orchestrator_pid()
        self._descendants = _subtree(self._orch_pid)

        time.sleep(self._warmup)  # прогрев: introspect к холодному процессу может таймаутить
        drv = BackendDriver(port=self._port)
        drv.connect()
        time.sleep(0.3)  # дать сокету зарегистрировать клиента
        self._driver = drv
        return drv

    def stop(self) -> None:
        """Закрыть driver и гарантированно погасить систему (watchdog + kill дерева)."""
        if self._driver is not None:
            try:
                self._driver.close()
            except Exception:  # noqa: BLE001
                pass
            self._driver = None
        if self._launcher is not None:
            _shutdown_with_watchdog(
                self._launcher,
                self._teardown_timeout,
                self._orch_pid,
                self._descendants,
                log=self._log,
            )
            self._launcher = None
        self._descendants = []
        self._orch_pid = None
        # Свой PID-файл больше не нужен (дерево гарантированно добито выше).
        try:
            pid_file = os.environ.get("INSPECTOR_PID_FILE", "")
            if f"_harness_{os.getpid()}_{self._port}" in pid_file:
                Path(pid_file).unlink(missing_ok=True)
        except OSError:
            pass

    def kill_child(self, name: str) -> int:
        """Fault-injection (Ф3.7): жёстко убить дочерний процесс по имени (SIGKILL).

        PID берётся через driver ``introspect.status`` (честная наблюдаемость —
        сам процесс отдаёт ``os.getpid()``). SIGKILL, а НЕ ``process.stop``:
        graceful stop → exitcode 0 → статус "stopped" → авто-рестарт не триггерится.
        SIGKILL → crash (exitcode != 0) → монитор ловит по ``is_alive()`` за ≤ poll
        (0.5с), а не ждёт heartbeat_timeout 15с. Так тест проверяет реальную
        супервизию: смерть → авто-рестарт → поток данных возобновился.

        Args:
            name: имя дочернего процесса в топологии (source/hub).

        Returns:
            PID убитого процесса.

        Raises:
            RuntimeError: имя не найдено / нет pid в ответе / driver не поднят.
        """
        res = self.driver.introspect_status(name)
        payload = _find_payload(res, "pid", "process")
        pid = payload.get("pid") if isinstance(payload, dict) else None
        if not isinstance(pid, int) or pid <= 0:
            raise RuntimeError(f"kill_child('{name}'): pid не найден в introspect.status (ответ: {res!r})")
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError as exc:  # процесс уже мёртв — считаем как «убит»
            self._log(f"[harness] kill_child('{name}'): процесс pid={pid} уже мёртв ({exc})")
        self._log(f"[harness] kill_child('{name}') → SIGKILL pid={pid}")
        return pid

    def _orchestrator_pid(self) -> Optional[int]:
        """pid процесса-оркестратора (ProcessManager) для scoped-teardown. None если нет."""
        if self._launcher is None:
            return None
        try:
            proc = (self._launcher.get_status() or {}).get("process") or {}
            return proc.get("pid")
        except Exception:  # noqa: BLE001 — pid не критичен, есть штатный shutdown
            return None

    def __enter__(self) -> BackendDriver:
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()
