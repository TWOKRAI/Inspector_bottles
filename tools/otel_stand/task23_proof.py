# -*- coding: utf-8 -*-
"""Проба Task 2.3 — петля усиления: страж фреймворка ПРЕДЪЯВЛЕН, свой не заводится.

**Предмет.** Записи самого экспортёра не должны экспортироваться: иначе отказ сети
кормит сам себя — каждая строка «не доставлено» становится записью, которую снова
надо доставить. Фреймворк уже отказывает процессу в подписке на собственный хвост
(`process_module.py:1263`, причина «петля»). Задача — **предъявить**, что это
работает для нашего подписчика, а не поверить в комментарий.

**Правило задачи (из плана):** если петля НЕ воспроизводится — второй предохранитель
не заводить, записать в ADR сервиса. «Ноль красных = лишний слой».

**Четыре утверждения и пара к каждому.**

1. *Страж отвечает отказом с причиной.* Пара: тот же вызов с ЧУЖИМ подписчиком →
   успех. Без пары «отказ» неотличим от «команда всегда отказывает».
2. *Дорога до приёмника жива:* записи `camera_0` в `otel_records.json` есть. Это
   пара к пункту 3 — без неё «ноль своих записей» читается на пустом файле и
   доказывает только то, что коллектор не запускался (пятое прочтение нуля).
3. *Своих записей у приёмника нет:* `service.name == otel_export` → 0, при том что
   собственные строки экспортёра в журнале ЕСТЬ. Оба числа берутся в одном прогоне.
4. *Собственные голоса не кормят исходящий поток:* прирост `received` в окне, где
   экспортёр громко ругается на отказы, не больше прироста в тихом окне того же
   размера плюс число его собственных строк. Если бы петля жила, каждая строка
   отказа вернулась бы записью и прирост разошёлся бы ровно на это число.

**Отказ ИЗМЕРЕНИЯ отделён от отказа ПРЕДМЕТА.** Правило выведено из пяти ложных
опровержений пробы Task 2.2, все — на исправном механизме: зонд обязан ПОКАЗАТЬ, что
видел предмет, прежде чем сказать «нет». Темп замерен рядом, а не предположен; форма
распечатана, а не угадана; готовность дождалась события, а не таймера. Недобор фактов
даёт «НЕ ДОКАЗАНО», а не «ОПРОВЕРГНУТО».

**Приёмник здесь настоящий** (`otelcol` 0.158.0, см. README стенда), а не заглушка на
`http.server`: пункт 3 — утверждение о том, что доехало до ВНЕШНЕГО потребителя, и
собственная заглушка проверяла бы нашу же догадку о форме. Для окна отказов приёмник
подменяется на 401-заглушку: отказ по сети стоит 23 с, а 401 — 0.02 с, и только с ней
окно отказов вообще набирается (замер Task 2.2).

**Файл приёмника не удаляется.** Читается смещение ДО прогона, разбирается только
дописанное: удаление чужого артефакта — не право пробы.

**Запуск (стенд 8765 эксклюзивен — занять, объявить, освободить):**

    "$PWD/../../../.venv/Scripts/python.exe" tools/otel_stand/task23_proof.py

Выход: 0 — все утверждения доказаны; 1 — есть опровергнутое; 2 — отказало измерение,
вердиктов о предмете проба не выносит.
"""

from __future__ import annotations

import http.server
import json
import os
import subprocess  # nosec B404 — стенд поднимает приёмник-арбитр, см. _start_otelcol
import sys
import threading
import time
from pathlib import Path
from typing import Any

PROCESS = "otel_export"
_TOPOLOGY = "multiprocess_prototype/backend/topology/otel_export.yaml"
COLLECTOR_PORT = 4318

#: Настоящий приёмник-арбитр и его конфиг (tools/otel_stand/README.md).
OTELCOL_EXE = Path(os.environ.get("OTELCOL_EXE") or r"C:\Users\INNOTECH\tools\otelcol\otelcol.exe")
OTELCOL_CONFIG = Path("tools/otel_stand/collector.yaml")
#: Путь file-экспортёра из конфига — относительный, считается от рабочего каталога.
RECORDS_PATH = Path("logs_live/otel_records.json")

#: Хвосту надо натечь, иначе кольцо пустое и отправлять нечего.
_SETTLE_SEC = 12.0
#: Длина каждого из двух сравниваемых окон, сек. Одинаковая — иначе приросты
#: несравнимы, а разность окажется мерой длины окна, а не мерой петли.
_WINDOW_SEC = 30.0
#: Потолок ожидания ответа на flush: заведомо выше измеренных 42.08 с худшего случая.
FLUSH_TIMEOUT_SEC = 90.0

#: Постоянная часть строки отказа доставки (та же, что сторожит Task 2.2).
VOICE_TEXT = "записи не доставлены приёмнику OTLP"
#: Подписчик-пара для проверки живости оси: чужое имя обязано подписаться успешно.
CONTROL_SUBSCRIBER = "stand_probe_ctl"
#: Литерал причины отказа стража (`process_module.py:1263`).
LOOP_REASON_MARK = "петля"


class _RefusingCollector(http.server.BaseHTTPRequestHandler):
    """Приёмник, отвечающий **401** — то есть отказывающий БЫСТРО (0.02 с).

    Нужен, чтобы окно отказов вообще набралось: отказ по сети стоит 23 с из-за
    ретрая SDK, и за 30 с не наберётся двух собственных голосов.
    """

    def do_POST(self) -> None:  # noqa: N802 — имя навязано BaseHTTPRequestHandler
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        self.send_response(401)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *_args: Any) -> None:
        """Приёмник молчит: его шум мешал бы читать наш журнал."""


def _start_refusing() -> http.server.HTTPServer:
    server = http.server.HTTPServer(("127.0.0.1", COLLECTOR_PORT), _RefusingCollector)
    threading.Thread(target=server.serve_forever, daemon=True, name="stand-401").start()
    return server


def _start_otelcol() -> subprocess.Popen | None:
    """Поднять настоящий приёмник. None — если бинарника нет (отказ ИЗМЕРЕНИЯ)."""
    if not OTELCOL_EXE.exists():
        return None
    RECORDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    # nosec B603 — аргументы не приходят снаружи: путь к бинарнику задаёт оператор
    # машины (константа или OTELCOL_EXE), конфиг лежит в репозитории. Списком, а не
    # строкой и без shell — то есть подстановки нет по построению.
    proc = subprocess.Popen(  # nosec B603
        [str(OTELCOL_EXE), "--config", str(OTELCOL_CONFIG)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Ждём, пока порт начнёт принимать: «поднялся» — это событие, а не таймер.
    import socket

    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", COLLECTOR_PORT)) == 0:
                return proc
        time.sleep(0.3)
    proc.terminate()
    return None


def _records_since(offset: int) -> tuple[list[dict], int]:
    """Разобрать записи, дописанные ПОСЛЕ `offset`. Возврат: (записи, новое смещение).

    Записи возвращаются плоским списком словарей вида
    ``{"service": <service.name>, "body": <текст>}`` — большего пунктам 2–4 не нужно,
    а полный разбор OTLP-JSON здесь был бы второй реализацией маппера.
    """
    if not RECORDS_PATH.exists():
        return [], offset
    raw = RECORDS_PATH.read_bytes()
    chunk = raw[offset:]
    out: list[dict] = []
    for line in chunk.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except json.JSONDecodeError:
            # Хвост файла мог быть прочитан на полузаписи — это отказ ИЗМЕРЕНИЯ,
            # и он не должен выглядеть как «записей нет».
            continue
        for res_log in doc.get("resourceLogs", []):
            attrs = {
                a.get("key"): (a.get("value") or {}).get("stringValue")
                for a in (res_log.get("resource") or {}).get("attributes", [])
            }
            service = attrs.get("service.name")
            for scope_log in res_log.get("scopeLogs", []):
                for rec in scope_log.get("logRecords", []):
                    body = (rec.get("body") or {}).get("stringValue") or ""
                    out.append({"service": service, "body": body})
    return out, len(raw)


def _own_voice_lines(log_dir: Path) -> list[str]:
    """Собственные строки отказа доставки в журналах процесса."""
    lines: list[str] = []
    for path in sorted(log_dir.rglob("*.log")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines.extend(line for line in text.splitlines() if VOICE_TEXT in line)
    return lines


def _own_log_lines(log_dir: Path) -> int:
    """Сколько всего строк написал САМ процесс-экспортёр.

    Пара к пункту 3: «своих записей у приёмника ноль» осмысленно только если свои
    записи вообще существовали.
    """
    count = 0
    for path in sorted(log_dir.rglob("*.log")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        count += sum(1 for line in text.splitlines() if f"[{PROCESS}]" in line)
    return count


def _status(drv: Any) -> dict[str, Any]:
    raw = drv.send_command(PROCESS, "otel_export.status") or {}
    payload = raw.get("result", raw.get("data", raw))
    return payload if isinstance(payload, dict) else raw


def _counters(drv: Any) -> dict[str, Any]:
    return _status(drv).get("counters", {}) or {}


def _flush(drv: Any) -> dict[str, Any]:
    raw = drv.send_command(PROCESS, "otel_export.flush", timeout=FLUSH_TIMEOUT_SEC) or {}
    payload = raw.get("result", raw.get("data", raw))
    return payload if isinstance(payload, dict) else raw


def _subscribe(drv: Any, subscriber: str) -> dict[str, Any]:
    """Подписать адрес на хвост САМОГО процесса-экспортёра (команда процесса)."""
    raw = drv.send_command(PROCESS, "observability.tail.subscribe", {"subscriber": subscriber, "level": "INFO"}) or {}
    payload = raw.get("result", raw.get("data", raw))
    return payload if isinstance(payload, dict) else raw


def _unsubscribe(drv: Any, subscriber: str) -> dict[str, Any]:
    raw = drv.send_command(PROCESS, "observability.tail.unsubscribe", {"subscriber": subscriber}) or {}
    payload = raw.get("result", raw.get("data", raw))
    return payload if isinstance(payload, dict) else raw


def _verdict(name: str, ok: bool | None, detail: str) -> tuple[str, bool | None]:
    label = {True: "ДОКАЗАНО   ", False: "ОПРОВЕРГНУТО", None: "НЕ ДОКАЗАНО"}[ok]
    print(f"[{label}] {name}\n              {detail}")
    return name, ok


def _pump_window(drv: Any, seconds: float, *, flush_every: float = 4.0) -> int:
    """Прокачать окно длиной `seconds`, периодически дожимая. Возврат — число flush."""
    done = 0
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        _flush(drv)
        done += 1
        time.sleep(flush_every)
    return done


def main() -> int:
    os.environ.setdefault("BACKEND_CTL", "1")
    log_dir = Path(os.environ.get("INSPECTOR_LOG_DIR") or "logs_stand_t23").resolve()

    from backend_ctl.driver import BackendDriver

    from multiprocess_prototype.main import bootstrap

    results: list[tuple[str, bool | None]] = []

    print(f"[proof] поднимаю настоящий приёмник: {OTELCOL_EXE}")
    otelcol = _start_otelcol()
    if otelcol is None:
        print(
            "[proof] ОТКАЗ ИЗМЕРЕНИЯ: приёмник otelcol не поднялся "
            f"(бинарник {OTELCOL_EXE}, порт {COLLECTOR_PORT}). Вердиктов о предмете не будет."
        )
        return 2
    # Смещение ДО прогона: чужие записи в файле — не наши, удалять файл проба не вправе.
    _, offset = _records_since(0)
    print(f"[proof] приёмник поднят; смещение файла до прогона: {offset} Б")

    print(f"[proof] поднимаю топологию headless: {_TOPOLOGY}")
    launcher = bootstrap(_TOPOLOGY)
    launcher.start()
    if not launcher.wait_until_ready(timeout=45.0):
        print("[proof] ОТКАЗ стенда: система не готова за 45 с — вердиктов не будет")
        launcher.shutdown()
        otelcol.terminate()
        return 2
    print("[proof] система готова")

    refusing: http.server.HTTPServer | None = None
    try:
        with BackendDriver(port=8765) as drv:
            print(f"[proof] даю хвосту натечь {_SETTLE_SEC} с...")
            time.sleep(_SETTLE_SEC)

            # ---------------------------------------------------------------- #
            # 1. Страж предъявлен: отказ с причиной, и пара на живость оси
            # ---------------------------------------------------------------- #
            self_sub = _subscribe(drv, PROCESS)
            print(f"[proof] подписка на СЕБЯ -> {self_sub!r}")
            refused = self_sub.get("success") is False
            reason = str(self_sub.get("reason") or "")
            results.append(
                _verdict(
                    "страж фреймворка ОТКАЗЫВАЕТ процессу в подписке на себя, с причиной",
                    refused and LOOP_REASON_MARK in reason,
                    f"success={self_sub.get('success')!r}, reason={reason!r}",
                )
            )

            ctl_sub = _subscribe(drv, CONTROL_SUBSCRIBER)
            print(f"[proof] пара — подписка ЧУЖОГО адреса -> {ctl_sub!r}")
            results.append(
                _verdict(
                    "пара: ЧУЖОЙ подписчик на том же процессе принимается (ось жива)",
                    ctl_sub.get("success") is True,
                    f"подписчик {CONTROL_SUBSCRIBER!r}: {ctl_sub!r}. "
                    "Без этой пары отказ выше неотличим от «команда отказывает всегда»",
                )
            )
            _unsubscribe(drv, CONTROL_SUBSCRIBER)

            # ---------------------------------------------------------------- #
            # 2-3. Тихое окно: что доехало до НАСТОЯЩЕГО приёмника
            # ---------------------------------------------------------------- #
            print(f"[proof] тихое окно {_WINDOW_SEC} с (приёмник принимает)...")
            quiet_counters_before = _counters(drv)
            quiet_before = int(quiet_counters_before.get("received", 0) or 0)
            quiet_flushes = _pump_window(drv, _WINDOW_SEC)
            quiet_counters_after = _counters(drv)
            quiet_after = int(quiet_counters_after.get("received", 0) or 0)
            quiet_delta = quiet_after - quiet_before
            # «Тихое» — это утверждение, а не название. Прогон 1 назвал окно тихим,
            # пока приёмник отвечал 404 на КАЖДУЮ отправку: оба окна оказались
            # окнами отказов, и разность их приростов измеряла не петлю, а ничего.
            quiet_exported = int(quiet_counters_after.get("exported", 0) or 0) - int(
                quiet_counters_before.get("exported", 0) or 0
            )
            quiet_failed = int(quiet_counters_after.get("export_failed", 0) or 0) - int(
                quiet_counters_before.get("export_failed", 0) or 0
            )
            print(
                f"[proof] тихое окно: flush {quiet_flushes}, received +{quiet_delta}, "
                f"exported +{quiet_exported}, export_failed +{quiet_failed}"
            )
            results.append(
                _verdict(
                    "тихое окно ДЕЙСТВИТЕЛЬНО тихое: приёмник принимает, отказов нет",
                    quiet_exported > 0 and quiet_failed == 0,
                    f"exported +{quiet_exported}, export_failed +{quiet_failed} за окно. "
                    "Если отказы есть — окно не тихое, и сравнение с окном отказов ниже "
                    "измеряет не петлю (так соврал прогон 1 при приёмнике, отвечавшем 404)",
                )
            )

            # Приёмнику нужно время дописать файл: ждём события, а не таймера.
            deadline = time.monotonic() + 15.0
            records: list[dict] = []
            while time.monotonic() < deadline:
                records, _peek = _records_since(offset)
                if records:
                    break
                time.sleep(0.5)

            by_service: dict[str | None, int] = {}
            for rec in records:
                by_service[rec["service"]] = by_service.get(rec["service"], 0) + 1
            print(f"[proof] у приёмника по service.name: {by_service!r}")

            foreign = sum(count for svc, count in by_service.items() if svc and svc != PROCESS)
            results.append(
                _verdict(
                    "пара: дорога до приёмника ЖИВА — чужие записи доехали",
                    foreign > 0,
                    f"записей не от экспортёра: {foreign} ({by_service!r}). "
                    "Без этого «ноль своих» читался бы на пустом файле",
                )
            )

            own_at_collector = by_service.get(PROCESS, 0)
            own_lines = _own_log_lines(log_dir)
            # Ноль своих записей осмыслен ТОЛЬКО когда дорога жива и свои строки были.
            #
            # Первая редакция судила это утверждение по одному лишь `own_lines` и
            # выдала ДОКАЗАНО на пустом файле приёмника (`by_service == {}`): ноль
            # из нуля. Пара выше при этом честно покраснела — то есть матрица
            # поймала вакуум, а сам вердикт всё равно соврал бы в отчёте.
            own_ok: bool | None = None
            if foreign > 0 and own_lines > 0:
                own_ok = own_at_collector == 0
            results.append(
                _verdict(
                    "записи САМОГО экспортёра у приёмника отсутствуют, при живых своих строках",
                    own_ok,
                    f"service.name={PROCESS!r} у приёмника: {own_at_collector}; "
                    f"собственных строк в журнале: {own_lines}; чужих записей у приёмника: {foreign}"
                    + ("" if own_ok is not None else " — судить не на чем: нужны И живая дорога, И собственные строки"),
                )
            )

            # ---------------------------------------------------------------- #
            # 4. Окно отказов: собственные голоса не кормят исходящий поток
            # ---------------------------------------------------------------- #
            print("[proof] подменяю приёмник на 401 (быстрый отказ) и меряю окно отказов")
            otelcol.terminate()
            try:
                otelcol.wait(timeout=15.0)
            except subprocess.TimeoutExpired:
                otelcol.kill()
            time.sleep(1.0)
            refusing = _start_refusing()

            voices_before = len(_own_voice_lines(log_dir))
            fail_before = int(_counters(drv).get("received", 0) or 0)
            fail_flushes = _pump_window(drv, _WINDOW_SEC)
            fail_after = int(_counters(drv).get("received", 0) or 0)
            voices_after = len(_own_voice_lines(log_dir))

            fail_delta = fail_after - fail_before
            own_voices = voices_after - voices_before
            print(
                f"[proof] окно отказов: flush {fail_flushes}, received +{fail_delta}, "
                f"собственных строк отказа +{own_voices}"
            )
            results.append(
                _verdict(
                    "собственные голоса отказа НЕ кормят исходящий поток",
                    (fail_delta - quiet_delta) < own_voices if own_voices >= 2 else None,
                    f"received: тихое окно +{quiet_delta}, окно отказов +{fail_delta} "
                    f"(разность {fail_delta - quiet_delta}); собственных строк отказа за окно: "
                    f"{own_voices}. Петля вернула бы каждую строку записью, то есть разность "
                    f"была бы не меньше {own_voices}"
                    + ("" if own_voices >= 2 else " — строк отказа меньше двух, ось пуста"),
                )
            )
    finally:
        if refusing is not None:
            refusing.shutdown()
            refusing.server_close()
        if otelcol.poll() is None:
            otelcol.terminate()
        print("[proof] останавливаю систему...")
        launcher.shutdown()

    proven = sum(1 for _n, ok in results if ok is True)
    refuted = [n for n, ok in results if ok is False]
    unknown = [n for n, ok in results if ok is None]
    print(f"\n[proof] ИТОГ: доказано {proven} из {len(results)}")
    for name in refuted:
        print(f"[proof]   ОПРОВЕРГНУТО: {name}")
    for name in unknown:
        print(f"[proof]   НЕ ДОКАЗАНО (отказ измерения): {name}")
    return 1 if refuted else (2 if unknown else 0)


if __name__ == "__main__":
    sys.exit(main())
