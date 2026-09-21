# -*- coding: utf-8 -*-
"""Приёмочные тесты (RED, Task 1.4 плана line-sim) на CLI-параметризацию зонда
`backend_ctl/probes/probe_observability_consumer_acceptance.py` под `--app
{prototype,line_sim}`.

Независимый тестировщик, ДО реализации: контракт CLI взят из брифа лида (см.
`plans/line-sim/phase-1-vertical-slice.md`, Task 1.4), а не из чтения зонда —
сегодняшний файл вообще не парсит `sys.argv` (`argparse` в нём отсутствует,
grep подтверждён). Поэтому большинство тестов здесь красные из-за
`TypeError`/содержимого stdout, не из-за отсутствующего файла.

HARD SAFETY (обязательно к соблюдению всеми тестами этого файла): зонд с
СВОБОДНЫМ портом поднимает ПОЛНЫЙ многопроцессный стенд. Каждый прогон зонда
здесь либо (а) занимает целевой порт САМ (bind+listen до запуска) или
подтверждает чужую занятость через `connect_ex`, либо (б) использует
`--help`/заведомо невалидный `--app` — оба пути, если контракт реализован
честно (argparse), обязаны вернуться до порт-чека. Ничего не запускается с
`LINE_SIM_LIVE=1` — эта переменная включает единственный тест, который годами
живёт под явным skip.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE = "backend_ctl.probes.probe_observability_consumer_acceptance"

#: Порты по умолчанию — литералы из брифа лида, не из чтения кода зонда.
PROTOTYPE_PORT = 8765
LINE_SIM_PORT = 8766

#: Процессы сима (apps/line_sim/pipeline.yaml, три штуки: robot/camera/mjpeg) —
#: любой из этих пяти в отчёте о составе процессов был бы утечкой прототипа.
PROTOTYPE_ONLY_PROCS = {"renderer", "storage", "inspector", "processor", "gui"}


# ---------------------------------------------------------------------------
# Хелперы: запуск зонда сабпроцессом (в процессе — запрещено ТЗ) + занятость порта
# ---------------------------------------------------------------------------


def _run_probe(args: List[str], timeout: float) -> subprocess.CompletedProcess:
    """Сабпроцесс зонда с ЖЁСТКИМ дедлайном — зависший зонд не должен повесить сюиту.

    `MULTIPROCESS_LOG_DIR`/`INSPECTOR_LOG_DIR` из окружения тестового процесса
    намеренно вычищены: сегодняшний зонд подхватывает их и переиспользует чужой
    каталог логов вместо собственного `--log-dir` — контракт CLI это как раз и
    должен были заменить.

    ``start_new_session=True`` + на таймауте `killpg` всей ГРУППЫ, не только
    листового процесса — НАЙДЕНО НА ЭТОМ ПРОГОНЕ (см. отчёт тестера): дефолтный
    `subprocess.run(timeout=…)` убивает только прямого потомка, а
    `BackendHarness.start()` плодит multiprocessing-детей поднятого стенда,
    которые от гибели листа не гибнут и остаются висеть, держа порты.
    """
    env = dict(os.environ)
    env.pop("MULTIPROCESS_LOG_DIR", None)
    env.pop("INSPECTOR_LOG_DIR", None)
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        [sys.executable, "-m", MODULE, *args],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            stdout, stderr = proc.communicate(timeout=5.0)
        except Exception:  # noqa: BLE001
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            stdout, stderr = proc.communicate(timeout=5.0)
        pytest.fail(
            f"зонд не уложился в дедлайн {timeout} с (args={args}) — завис вместо ошибки/аборта; "
            f"вся группа процессов принудительно погашена.\n"
            f"stdout(хвост)={stdout[-2000:]!r}\nstderr(хвост)={stderr[-2000:]!r}"
        )
    return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)


def _port_accepts(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


class _BusyPort:
    """Гарантирует занятость `port` на время блока: свой listening-сокет ИЛИ
    подтверждённая чужая занятость (foreign-busy — трогать её нельзя, стенд
    может быть боевым прогоном). Ничего не биндит и не проверяет, если порт
    свободен — в этом случае `__enter__` падает явно, а не тихо запускает зонд
    в опасном режиме."""

    def __init__(self, port: int) -> None:
        self.port = port
        self._sock: Optional[socket.socket] = None

    def __enter__(self) -> "_BusyPort":
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", self.port))
            s.listen(16)  # запас очереди — см. _bind_random_port
            self._sock = s
        except OSError:
            s.close()
            if not _port_accepts(self.port):
                raise AssertionError(
                    f"порт {self.port} свободен, и я не смог его занять — "
                    f"по HARD SAFETY тест обязан остановиться, не подняв зонд вслепую"
                )
            # foreign-busy подтверждена — держать нечего, чужой процесс уже слушает.
        return self

    def __exit__(self, *exc_info) -> None:
        if self._sock is not None:
            self._sock.close()

    def still_up(self) -> bool:
        """`True`, если держатель порта (наш сокет или чужой процесс) всё ещё отвечает —
        проверка «зонд не задел то, что держало порт»."""
        return _port_accepts(self.port)


@contextlib.contextmanager
def _all_busy(*ports: int):
    """Занять НЕСКОЛЬКО портов сразу (уникальные) — оборачивает каждый `_BusyPort`.

    ОБЯЗАТЕЛЕН для КАЖДОГО прогона зонда в этом файле (кроме
    `test_live_line_sim_run`, которому подъём стенда разрешён явно): сегодняшний
    зонд игнорирует `sys.argv` целиком и всегда проверяет захардкоженный
    `PORT = 8765` — НАЙДЕНО НА ЭТОМ ПРОГОНЕ (см. отчёт), когда тест, занявший
    только 8766 (сценарный порт `--app line_sim`), пропустил зонд мимо
    порт-чека и тот реально поднял стенд `inspection_full` (7 процессов,
    подтверждено `ps`), провисев до отдельного SIGTERM/SIGKILL моего
    процесса-раннера. С этого момента 8765 занимается ВСЕГДА, вдобавок к
    сценарному порту теста — иначе КАЖДЫЙ прогон до появления реального
    argparse рискует повторить инцидент.
    """
    unique = sorted(set(ports))
    with contextlib.ExitStack() as stack:
        holders = [stack.enter_context(_BusyPort(p)) for p in unique]
        yield holders


def _bind_random_port() -> tuple[socket.socket, int]:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 0))
    # Очередь с запасом: зонд и проверка держателя коннектятся без accept(); при backlog 1
    # второй connect на macOS получал отказ — флак 1 из 15 (замер ведущего 2026-09-21).
    s.listen(16)
    return s, s.getsockname()[1]


# ---------------------------------------------------------------------------
# --help / невалидный --app — не требуют занятого порта по контракту (argparse
# обязан перехватить их РАНЬШЕ порт-чека), но мы всё равно подстраховываемся
# занятостью 8765: сегодняшний файл argparse не использует вовсе, так что
# --help без подстраховки рискует реально поднять стенд.
# ---------------------------------------------------------------------------


def test_help_lists_app_port_logdir():
    """`--help` завершается success и описывает контракт CLI без подъёма стенда."""
    with _all_busy(PROTOTYPE_PORT):
        t0 = time.perf_counter()
        proc = _run_probe(["--help"], timeout=20.0)
        elapsed = time.perf_counter() - t0
    assert proc.returncode == 0, f"--help должен вернуть 0; rc={proc.returncode} stderr={proc.stderr!r}"
    assert elapsed < 15.0, f"--help занял {elapsed:.1f} с — подозрение на реальный подъём стенда вместо argparse"
    out = proc.stdout + proc.stderr
    for needle in ("--app", "--port", "--log-dir", "prototype", "line_sim"):
        assert needle in out, f"--help не упомянул {needle!r}; полный вывод={out!r}"


def test_invalid_app_rejected(tmp_path):
    """Невалидный `--app` — argparse-ошибка, ненулевой код, никакого прогона.

    8765 занят как защита (см. `_all_busy`), но НЕ как источник ожидаемого
    отказа: если зонд абортировал по общей метке «порт занят», это значит
    `--app` вообще не валидируется (аргумент молча игнорируется, как сегодня) —
    для этого теста такой отказ ЛОЖНО-зелёный и явно отвергается ниже.
    """
    with _all_busy(PROTOTYPE_PORT):
        t0 = time.perf_counter()
        proc = _run_probe(["--app", "not-a-real-app-xyz", "--log-dir", str(tmp_path)], timeout=20.0)
        elapsed = time.perf_counter() - t0
    assert proc.returncode != 0, f"невалидный --app обязан вернуть ненулевой код; stdout={proc.stdout!r}"
    assert elapsed < 15.0, f"отказ занял {elapsed:.1f} с — argparse обязан отбить это мгновенно, до подъёма стенда"
    out = proc.stdout + proc.stderr
    assert "[abort] порт" not in out, (
        "отказ пришёл из общего порт-чека, а не из валидации --app — значит --app "
        f"вообще не парсится (ложно-зелёный путь), полный вывод={out!r}"
    )
    assert not (tmp_path / "acceptance_results.json").exists(), "невалидный --app не должен запускать прогон"


# ---------------------------------------------------------------------------
# Занятый целевой порт → быстрый абот, [abort] + номер порта в stdout,
# держатель порта не задет.
# ---------------------------------------------------------------------------


def test_line_sim_default_port_busy_aborts(tmp_path):
    """`--app line_sim` без `--port` бьёт в дефолт 8766 (не в 8765 прототипа).

    8765 занят ЗАЩИТНО в дополнение к сценарному 8766 (см. `_all_busy`
    докстринг про инцидент этого прогона) — до появления реального `--app`
    зонд всё равно смотрит только на захардкоженный 8765, так что без этой
    страховки он проскочил бы порт-чек мимо 8766 и поднял бы стенд по-настоящему.
    """
    with _all_busy(PROTOTYPE_PORT, LINE_SIM_PORT) as holders:
        line_sim_holder = next(h for h in holders if h.port == LINE_SIM_PORT)
        t0 = time.perf_counter()
        proc = _run_probe(["--app", "line_sim", "--log-dir", str(tmp_path)], timeout=30.0)
        elapsed = time.perf_counter() - t0
        assert line_sim_holder.still_up(), "зонд задел держателя порта 8766 (не должен трогать чужой процесс)"
    assert proc.returncode != 0, f"занятый порт line_sim обязан абортировать; stdout={proc.stdout!r}"
    assert elapsed < 15.0, f"аборт занял {elapsed:.1f} с, ожидали быстрый отказ (< 15 с)"
    out = proc.stdout + proc.stderr
    assert "[abort]" in out, f"нет метки [abort] в выводе: {out!r}"
    assert str(LINE_SIM_PORT) in out, f"номер занятого порта {LINE_SIM_PORT} не назван в выводе: {out!r}"


def test_port_override_busy_aborts(tmp_path):
    """`--port` переопределяет дефолт для ОБОИХ `--app` — занятый порт быстро абортирует.

    8765 занят защитно в дополнение к случайному сценарному порту (тот же
    инцидент-мотив, что и в `test_line_sim_default_port_busy_aborts`).
    """
    sock, port = _bind_random_port()
    try:
        with _all_busy(PROTOTYPE_PORT):
            for extra_args, label in (([], "prototype-default-app"), (["--app", "line_sim"], "line_sim")):
                t0 = time.perf_counter()
                proc = _run_probe([*extra_args, "--port", str(port), "--log-dir", str(tmp_path / label)], timeout=30.0)
                elapsed = time.perf_counter() - t0
                assert proc.returncode != 0, f"[{label}] занятый --port {port} обязан абортировать"
                assert elapsed < 15.0, f"[{label}] аборт занял {elapsed:.1f} с"
                out = proc.stdout + proc.stderr
                assert "[abort]" in out, f"[{label}] нет метки [abort]: {out!r}"
                assert str(port) in out, f"[{label}] номер порта {port} не назван: {out!r}"
                assert _port_accepts(port), f"[{label}] держатель случайного порта {port} перестал отвечать"
    finally:
        sock.close()


def test_no_args_busy_8765_aborts():
    """Контроль без единого CLI-флага — существующий абортный путь (PORT=8765
    жёстко зашит СЕГОДНЯ). Может оказаться уже GREEN до реализации CLI —
    это не проверка нового контракта, а проверка того, что новый CLI его не
    сломал (дефолт `--app` = prototype = порт 8765)."""
    with _all_busy(PROTOTYPE_PORT) as holders:
        t0 = time.perf_counter()
        proc = _run_probe([], timeout=30.0)
        elapsed = time.perf_counter() - t0
        assert holders[0].still_up(), "зонд задел держателя порта 8765"
    assert proc.returncode != 0, f"занятый 8765 без аргументов обязан абортировать; stdout={proc.stdout!r}"
    assert elapsed < 15.0, f"аборт занял {elapsed:.1f} с"
    assert "[abort]" in (proc.stdout + proc.stderr)


# ---------------------------------------------------------------------------
# Живой прогон на симе — только с LINE_SIM_LIVE=1. НИКОГДА не запускать
# по умолчанию (полный многопроцессный стенд, минуты работы).
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("LINE_SIM_LIVE") != "1",
    reason="живой прогон полного стенда сима — только явно, LINE_SIM_LIVE=1",
)
@pytest.mark.timeout(1260)
def test_live_line_sim_run(tmp_path):
    """`--app line_sim` end-to-end: сим поднимается, отчёт валиден, порт сима
    освобождается, состав процессов — только сим, telemetry.levels отвечает.

    Сопоставление строк отчёта — ПО СОДЕРЖИМОМУ (`id`/весь JSON строки), не по
    стабильным id: реализация зонда мне не видна (worktree на коммите ДО неё),
    и точных id из брифа не дано.
    """
    proc = _run_probe(["--app", "line_sim", "--log-dir", str(tmp_path)], timeout=1200.0)
    assert proc.returncode == 0, f"live-прогон обязан завершиться success; stderr(хвост)={proc.stderr[-2000:]!r}"

    results_path = tmp_path / "acceptance_results.json"
    assert results_path.exists(), f"нет {results_path}; stdout(хвост)={proc.stdout[-2000:]!r}"
    data = json.loads(results_path.read_text(encoding="utf-8"))
    rows = data.get("rows")
    assert isinstance(rows, list) and rows, f"rows пуст или не список: {data.get('rows')!r}"

    # Словарь вердиктов зонда на 2026-09-21 (baseline) + новый N/A; поправка ведущего к брифу.
    valid_verdicts = {"PASS", "FAIL", "PARTIAL", "NOT_REACHED", "UNVERIFIED", "N/A"}
    for row in rows:
        assert row.get("id"), f"строка без id: {row}"
        verdict = row.get("verdict")
        assert verdict in valid_verdicts, f"верdict вне контракта: {row}"
        if verdict in {"PASS", "N/A"}:
            assert row.get("observed"), f"{verdict}-строка без observed: {row}"

    # Состав процессов — искать по содержимому (не по стабильному id).
    roster_row = None
    for row in rows:
        blob = json.dumps(row, ensure_ascii=False).lower()
        if "robot" in blob and "camera" in blob and "mjpeg" in blob:
            roster_row = row
            break
    assert roster_row is not None, (
        "не нашли строку о составе процессов сима (искал по содержимому robot+camera+mjpeg "
        f"во всех {len(rows)} строках) — сопоставление по контенту, не по id"
    )
    roster_blob = json.dumps(roster_row, ensure_ascii=False).lower()
    leaked = [p for p in PROTOTYPE_ONLY_PROCS if p in roster_blob]
    assert not leaked, f"строка о составе процессов сима упоминает прототипные процессы {leaked}: {roster_row}"

    assert not _port_accepts(LINE_SIM_PORT), f"порт сима {LINE_SIM_PORT} не освободился после выхода зонда"

    telemetry_row = None
    for row in rows:
        blob = json.dumps(row, ensure_ascii=False).lower()
        if "levels" in blob or "introspect_telemetry" in blob or "telemetry" in blob:
            telemetry_row = row
            break
    assert telemetry_row is not None, "не нашли строку про telemetry (введите introspect_telemetry/levels)"
    assert telemetry_row.get("verdict") != "N/A", f"telemetry-строка осталась N/A: {telemetry_row}"
