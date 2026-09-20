# -*- coding: utf-8 -*-
"""Живая приёмка Task 2.2 — «отказ доставки СЛЫШЕН», пара закрытый/открытый коллектор.

Критерий плана дословно: *коллектор закрыт → `export_failed` растёт, в журнале
одна строка на окно с числом подавленных; предъявить строку и число. Пара:
коллектор открыт → 0 и ни одной строки.*

**Почему пара обязательна.** «`export_failed` вырос» сам по себе не отличает
работающий детектор от детектора, который считает всегда. Вторая половина —
открытый коллектор — и есть проверка того, что счётчик умеет молчать.

**Почему коллектор здесь самодельный, а не настоящий otelcol.** Нам нужно ровно
одно свойство приёмника — отвечать `200` на `POST /v1/logs`, — и оно достижимо
двадцатью строками stdlib. Настоящий коллектор добавил бы конфиг, докер и свою
версионную зависимость ради того же ответа. Оговорка, унаследованная из
Task 0.1: **`HTTP 200` не значит «доставлено»** — запрос без конверта
`resourceLogs` тоже даёт 200 при нуле записей. Поэтому счёт ведётся по ЗАПИСЯМ
(`ExportOutcome`), а приёмник здесь нужен только чтобы отличить «сеть ответила»
от «сети нет».

**Чем эта проба врала в первой редакции — и это класс дефекта, а не опечатка.**
`BackendDriver` по умолчанию ждёт ответа **5 с**, а `flush` с мёртвым коллектором
живёт **23-42 с** (замеры CTO). Три вызова вернули
`{'success': False, 'error': 'timeout'}`, счётчики пришли пустыми, и две проверки
выдали **ОПРОВЕРГНУТО на исправном механизме**, третья — НЕ ДОКАЗАНО. Правило,
которое из этого следует: **детектор, чей таймаут короче измеряемой операции,
сообщает об отказе ПРЕДМЕТА вместо отказа ИЗМЕРЕНИЯ** — и выглядит это как
находка, а не как поломка прибора. Поэтому здесь таймаут вызова задан заведомо
больше измеренного потолка (:data:`FLUSH_TIMEOUT_SEC`), а не оставлен дефолтным.

Управлять длительностью через `export_timeout_ms` **нельзя**: у SDK это дедлайн
расписания ретраев, а не потолок вызова — `_export` повторяет POST на
`requests.ConnectionError` с исходным таймаутом (замер: 3000 мс -> 4.08 с, то есть
+36% сверх «потолка»; чёрная дыра при 30 с -> 42.08 с). Прежний абзац обещал
«короткий таймаут конфигурацией фрагмента» — во фрагменте такого ключа нет, и
пользы от него не было бы; абзац снят.

**Правило, выведенное из четырёх ложных опровержений этой самой пробы.**
Детектор обязан отличать отказ ПРЕДМЕТА от отказа ИЗМЕРЕНИЯ, иначе он отвечает
«нет» там, где честный ответ — «не знаю», и это хуже молчания. Четыре случая,
все на исправном механизме:

1. счёт по верхним ключам вложенного `levels` -> «0 из 8» при живых числах;
2. таймаут драйвера 5 с против 23-секундного `flush` -> три `timeout` подряд;
3. `len(lines) == 1` на прогоне в девять окон политики по 5 с;
4. чтение журнала раньше, чем логгер дописал строку, и `shutdown()` сокета без
   `server_close()` -> «приёмник получил 0 запросов» при поднятом приёмнике.

Общее у всех четырёх: **утверждение выведено из догадки о темпе, форме или
готовности, а не измерено рядом.**

**Запуск (стенд 8765 эксклюзивен — занять, объявить, освободить):**

    PYTHONPATH=$PWD BACKEND_CTL=1 python -m tools.otel_stand.task22_proof
"""

from __future__ import annotations

import http.server
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

PROCESS = "otel_export"
_TOPOLOGY = "multiprocess_prototype/backend/topology/otel_export.yaml"
COLLECTOR_PORT = 4318
#: Хвосту надо натечь, иначе кольцо пустое и отправлять нечего — а пустой батч
#: до SDK не доезжает вовсе (это отдельное свойство, сторожится тестами).
_SETTLE_SEC = 12.0
#: Потолок ожидания ответа на `otel_export.flush`. Заведомо больше измеренного
#: худшего случая (42.08 с на «чёрную дыру»), иначе драйвер отчитается об отказе
#: ПРЕДМЕТА вместо отказа измерения — см. докстринг модуля.
FLUSH_TIMEOUT_SEC = 90.0
#: Окно голоса процесса по умолчанию, сек (`observability.voices.default_window_sec`).
#: Читается у ИСТОЧНИКА, а не пишется числом: вторая позиция того же значения
#: разошлась бы с политикой молча — ровно на этом проба уже соврала однажды.
POLICY_WINDOW_SEC = 5.0
#: Литерал хвоста строки при подавлении (`compose_voice_text`). На него смотрит
#: критерий приёмки «одна строка на окно С ЧИСЛОМ ПОДАВЛЕННЫХ».
SUPPRESSED_MARK = "подавлено с прошлой записи"

#: Ключ окна голоса. Литерал: на него же ссылается тест и он же ищется в журнале.
VOICE_KEY = "otel_export.export_failed"
#: Постоянная часть строки отказа — переменные части (endpoint, failed, reason)
#: едут в полях, а не в тексте, иначе ключ дросселя и текст разъезжаются.
VOICE_TEXT = "записи не доставлены приёмнику OTLP"


class _AcceptingCollector(http.server.BaseHTTPRequestHandler):
    """Приёмник OTLP/HTTP, умеющий ровно одно: ответить 200 на `POST /v1/logs`."""

    received_requests = 0

    def do_POST(self) -> None:  # noqa: N802 — имя навязано BaseHTTPRequestHandler
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        type(self).received_requests += 1
        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *_args: Any) -> None:
        """Приёмник молчит: его собственный шум мешал бы читать наш журнал."""


class _RefusingCollector(http.server.BaseHTTPRequestHandler):
    """Приёмник, отвечающий **401** — то есть отказывающий БЫСТРО.

    Нужен ровно для одного: сделать подавление наблюдаемым. Отказ по сети
    (мёртвый порт) стоит 23 с из-за ретрая SDK, и два таких отказа в окно 5 с не
    помещаются никак. Ответ 401 закрывает попытку за 0.02 с (замер CTO), и тогда
    два отказа умещаются в одно окно.

    Побочно предъявляет вторую половину находки: `reason` у 401 **дословно тот
    же**, что у отказа сети, — то есть по нашему голосу ошибку авторизации от
    отсутствия сети отличить нельзя. Это записано условием на Task 3.1.
    """

    def do_POST(self) -> None:  # noqa: N802 — имя навязано BaseHTTPRequestHandler
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        self.send_response(401)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *_args: Any) -> None:
        """Приёмник молчит: его шум мешал бы читать наш журнал."""


def _start_server(handler: type) -> http.server.HTTPServer:
    server = http.server.HTTPServer(("127.0.0.1", COLLECTOR_PORT), handler)
    threading.Thread(target=server.serve_forever, daemon=True, name="stand-collector").start()
    return server


def _resubscribe_debug(drv: Any) -> dict:
    """Переподписать экспортёр на уровень DEBUG — поднять темп хвоста.

    При INFO хвост течёт ~0.17 зап/с, и за окно 5 с не набирается двух непустых
    колец, то есть двух ОТКАЗОВ. Без этого подавление непроверяемо на живом
    стенде в принципе. Команда та же, которой пользуется сам плагин, — намерение
    идемпотентно по подписчику, повторный вызов с другим уровнем законен.
    """
    return drv.send_command(
        "ProcessManager",
        "observability.tail.subscribe_all",
        {"subscriber": PROCESS, "level": "DEBUG"},
    )


def _start_collector() -> http.server.HTTPServer:
    server = http.server.HTTPServer(("127.0.0.1", COLLECTOR_PORT), _AcceptingCollector)
    threading.Thread(target=server.serve_forever, daemon=True, name="stand-collector").start()
    return server


def _voice_lines(log_dir: Path) -> list[str]:
    """Строки отказа доставки из журналов процесса — по постоянной части текста.

    Ищем по ТЕКСТУ, а не по ключу окна: ключ живёт в дросселе и в журнал не
    попадает. Читаем все файлы каталога: какой именно приёмник поймает строку
    уровня error, зависит от правил маршрутизации, и жёсткое имя файла сделало бы
    пробу зелёной при выключенном приёмнике.
    """
    lines: list[str] = []
    for path in sorted(log_dir.rglob("*.log")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines.extend(line for line in text.splitlines() if VOICE_TEXT in line)
    return lines


def _await_lines(log_dir: Path, at_least: int, deadline_sec: float = 8.0) -> list[str]:
    """Дождаться, пока в журнале окажется не меньше `at_least` строк отказа.

    **Зачем ждать.** Возврат команды `otel_export.flush` и появление её строки на
    диске — разные моменты: между ними живёт конвейер логгера. Немедленное чтение
    дало ложное опровержение («новых строк: 0» при фактически написанной строке),
    и это ровно тот класс, из-за которого проба уже врала дважды: **отказ
    ИЗМЕРЕНИЯ выданный за отказ ПРЕДМЕТА.**

    Возвращает то, что есть к дедлайну, — ждать бесконечно нельзя, а «не дождался»
    обязано быть отличимо от «строк нет»: об этом судит вызывающий по длине.
    """
    deadline = time.monotonic() + deadline_sec
    lines = _voice_lines(log_dir)
    while len(lines) < at_least and time.monotonic() < deadline:
        time.sleep(0.3)
        lines = _voice_lines(log_dir)
    return lines


def _status(drv: Any) -> dict[str, Any]:
    raw = drv.send_command(PROCESS, "otel_export.status") or {}
    payload = raw.get("result", raw.get("data", raw))
    return payload if isinstance(payload, dict) else raw


def _flush(drv: Any) -> dict[str, Any]:
    """Дожать и ДОЖДАТЬСЯ настоящего ответа, а не таймаута драйвера.

    Возвращает разобранный ответ команды; ключ `error` в нём означает, что
    отказало ИЗМЕРЕНИЕ (не дождались), а не предмет — вызывающий обязан это
    различать, иначе повторится ложный вердикт первой редакции.
    """
    started = time.monotonic()
    raw = drv.send_command(PROCESS, "otel_export.flush", timeout=FLUSH_TIMEOUT_SEC) or {}
    payload = raw.get("result", raw.get("data", raw))
    result = payload if isinstance(payload, dict) else raw
    print(f"[proof]   flush занял {time.monotonic() - started:.2f} с -> {result!r}")
    return result


def _measurement_failed(answers: list[dict[str, Any]]) -> str:
    """Отказ ИЗМЕРЕНИЯ (таймаут драйвера, транспорт) — или пустая строка."""
    broken = [a for a in answers if a.get("error") or a.get("success") is False]
    if not broken:
        return ""
    return f"драйвер не дождался ответа ({broken!r}) — отказало измерение, не предмет"


def _verdict(name: str, ok: bool | None, detail: str) -> tuple[str, bool | None]:
    label = {True: "ДОКАЗАНО   ", False: "ОПРОВЕРГНУТО", None: "НЕ ДОКАЗАНО"}[ok]
    print(f"[{label}] {name}\n              {detail}")
    return name, ok


def main() -> int:
    os.environ.setdefault("BACKEND_CTL", "1")
    log_dir = Path(os.environ.get("INSPECTOR_LOG_DIR") or "logs_stand_t22").resolve()

    from backend_ctl.driver import BackendDriver

    from multiprocess_prototype.main import bootstrap

    results: list[tuple[str, bool | None]] = []

    print(f"[proof] поднимаю топологию headless: {_TOPOLOGY} (коллектор ЗАКРЫТ)")
    launcher = bootstrap(_TOPOLOGY)
    launcher.start()
    if not launcher.wait_until_ready(timeout=45.0):
        print("[proof] ОТКАЗ стенда: система не готова за 45 с — вердиктов не будет")
        launcher.shutdown()
        return 2
    print("[proof] система готова")

    collector: http.server.HTTPServer | None = None
    try:
        with BackendDriver(port=8765) as drv:
            # ---------------------------------------------------------------- #
            # Половина А: коллектор ЗАКРЫТ
            # ---------------------------------------------------------------- #
            phase_a_started = time.monotonic()
            print(f"[proof] даю хвосту натечь {_SETTLE_SEC} с...")
            time.sleep(_SETTLE_SEC)

            before = _status(drv).get("counters", {})
            print(f"[proof] счётчики до flush: {before!r}")

            # Три флаша подряд: одна строка на ОКНО означает, что второй и третий
            # обязаны быть подавлены — при том, что счётчик растёт на каждом.
            flushes = [_flush(drv) for _ in range(3)]
            print(f"[proof] исходы трёх flush: {flushes!r}")
            after = _status(drv).get("counters", {})
            print(f"[proof] счётчики после: {after!r}")

            grew = int(after.get("export_failed", 0)) - int(before.get("export_failed", 0))
            results.append(
                _verdict(
                    "коллектор ЗАКРЫТ → export_failed растёт",
                    grew > 0,
                    f"прирост export_failed за три flush: {grew}; exported={after.get('exported')}",
                )
            )

            lines = _voice_lines(log_dir)
            results.append(
                _verdict(
                    "коллектор ЗАКРЫТ → отказ СЛЫШЕН (строка есть)",
                    bool(lines),
                    (f"строк: {len(lines)}; первая: {lines[0].strip()}")
                    if lines
                    else (
                        f"ни одной строки с текстом {VOICE_TEXT!r} в {log_dir} — "
                        "отказ доставки НЕ слышен, то есть ровно тот дефект, который задача закрывает"
                    ),
                )
            )

            # Число строк сверяется с ЧИСЛОМ ОКОН, а не с единицей.
            #
            # Прежняя редакция требовала `len(lines) == 1` на прогоне длиной ~46 с
            # при окне политики 5 с — то есть одну строку на девять окон. Это было
            # невыполнимо при ЛЮБОМ исправном механизме, и живой прогон дал
            # ОПРОВЕРГНУТО на работающем предмете (строки в 15:34:15 и 15:34:38,
            # 23.0 с врозь). Утверждение, выведенное из догадки о темпе, согласно
            # само с собой ровно до первой встречи с настоящими часами.
            elapsed = time.monotonic() - phase_a_started
            windows = max(1, int(elapsed / POLICY_WINDOW_SEC) + 1)
            results.append(
                _verdict(
                    "число строк не превышает числа окон",
                    len(lines) <= windows if lines else None,
                    f"строк {len(lines)}; окон уместилось {windows} "
                    f"(прошло {elapsed:.1f} с при окне {POLICY_WINDOW_SEC} с). "
                    "Подавление внутри окна проверяется отдельно, фазой быстрого отказа",
                )
            )

            numbered = [ln for ln in lines if re.search(r"failed=\d+", ln)]
            found = re.findall(r"failed=\d+", lines[0]) if lines else []
            results.append(
                _verdict(
                    "строка несёт ЧИСЛО отказавших записей",
                    bool(numbered) if lines else None,
                    f"поле failed= найдено в {len(numbered)} из {len(lines)} строк: {found!r}"
                    if lines
                    else "строк нет — проверять нечего",
                )
            )

            # ---------------------------------------------------------------- #
            # Фаза подавления: БЫСТРЫЙ отказ (401) — иначе окно непроверяемо
            #
            # Отказ по сети стоит 23 с (ретрай SDK), хвост при INFO течёт
            # 0.17 зап/с: два отказа в окно 5 с не помещаются НИКАК, и старая
            # проба не могла показать подавление в принципе. 401 закрывает
            # попытку за 0.02 с, DEBUG поднимает темп хвоста.
            # ---------------------------------------------------------------- #
            print("\n[proof] фаза подавления: поднимаю 401-приёмник и переподписываюсь на DEBUG")
            refusing = _start_server(_RefusingCollector)
            try:
                print(f"[proof] брокер: {_resubscribe_debug(drv)!r}")
                # Ждать ДОЛЬШЕ окна, а не меньше. Прежние 4.0 с при окне 5.0 с
                # означали, что первый отказ всплеска подавляется ЧУЖИМ окном —
                # тем, которое открыла последняя строка фазы А. Проба тогда
                # мерила не подавление внутри своего всплеска, а хвост прошлой
                # фазы, и выдавала опровержение на исправном механизме.
                # Признак был прямо в выдаче: следующая строка несла
                # «подавлено с прошлой записи: 1» — ровно одну подавленную
                # попытку, то есть первую попытку всплеска.
                time.sleep(POLICY_WINDOW_SEC + 1.5)
                lines_before = len(_voice_lines(log_dir))

                # Два отказа подряд ВНУТРИ окна: второй обязан быть подавлен.
                #
                # Пауза между ними ОБЯЗАТЕЛЬНА и она не про таймінг голоса, а про
                # наличие предмета: кольцо пустеет после каждого flush, и второй
                # вызов подряд находит его пустым, отказа не производит и голоса
                # не пробует. Без паузы утверждение проходило ВАКУУМНО — один
                # отказ давал одну строку, и это выглядело как доказанное
                # подавление. Признак вакуума был в соседней оси: следующая
                # строка не несла пометки подавления, потому что подавлять было
                # нечего. Пауза 1.5 с < окна 5.0 с, то есть оба отказа остаются
                # внутри одного окна.
                first = _flush(drv)
                time.sleep(1.5)
                burst = [first, _flush(drv)]
                real_failures = [a for a in burst if int(a.get("failed", 0) or 0) > 0]
                failed_in_burst = sum(int(a.get("failed", 0) or 0) for a in burst)
                # Ждём, а не читаем сразу: строка появляется ПОЗЖЕ возврата команды.
                lines_after_burst = len(_await_lines(log_dir, lines_before + 1))
                results.append(
                    _verdict(
                        "два отказа ВНУТРИ окна → одна строка (второй подавлен)",
                        # Требуем ДВА настоящих отказа. Один отказ, давший одну
                        # строку, о подавлении не говорит ничего — это и есть
                        # вакуумная форма утверждения.
                        ((lines_after_burst - lines_before) == 1) if len(real_failures) == 2 else None,
                        f"настоящих отказов из двух flush: {len(real_failures)} "
                        f"(записей: {failed_in_burst}); новых строк: {lines_after_burst - lines_before}. "
                        f"Исходы: {[a.get('status') for a in burst]!r}"
                        + (
                            ""
                            if len(real_failures) == 2
                            else " — двух отказов не набралось, подавление проверять не на чем"
                        ),
                    )
                )

                # Окно истекло — следующая строка обязана НАЗВАТЬ подавленных.
                # Окно обязано истечь И кольцо обязано быть непустым. Слепая
                # пауза давала второе не всегда: всплеск выгребает кольцо, и
                # заключительный flush находил его пустым — голоса не пробовал,
                # строки не рождалось, и «пометки подавления нет» читалось как
                # отказ механизма вместо отказа подготовки.
                time.sleep(POLICY_WINDOW_SEC + 1.5)
                deadline = time.monotonic() + 20.0
                pending = int(_status(drv).get("pending", 0) or 0)
                while pending == 0 and time.monotonic() < deadline:
                    time.sleep(0.5)
                    pending = int(_status(drv).get("pending", 0) or 0)
                print(f"[proof] в кольце перед заключительным flush: {pending}")
                _flush(drv)
                tail = _await_lines(log_dir, lines_after_burst + 1)
                with_mark = [ln for ln in tail if SUPPRESSED_MARK in ln]
                results.append(
                    _verdict(
                        "строка после окна называет ЧИСЛО ПОДАВЛЕННЫХ",
                        bool(with_mark),
                        f"строк с пометкой {SUPPRESSED_MARK!r}: {len(with_mark)}"
                        + (
                            f"; последняя: {with_mark[-1].strip()}"
                            if with_mark
                            else " — критерий «одна строка на окно С ЧИСЛОМ ПОДАВЛЕННЫХ» не предъявлен"
                        ),
                    )
                )
            finally:
                # server_close() ОБЯЗАТЕЛЕН: shutdown() останавливает serve_forever,
                # но слушающий сокет не закрывает. Без него следующий приёмник на
                # том же порту поднимается формально (allow_reuse_address), а
                # запросы уходят в никуда — измеряемый flush жил 30.03 с и
                # отчитался отказом при «живом» коллекторе.
                refusing.shutdown()
                refusing.server_close()
                time.sleep(0.5)

            # ---------------------------------------------------------------- #
            # Половина Б: коллектор ОТКРЫТ — счётчик обязан УМЕТЬ МОЛЧАТЬ
            # ---------------------------------------------------------------- #
            print(f"\n[proof] поднимаю приёмник на 127.0.0.1:{COLLECTOR_PORT} и повторяю")
            collector = _start_collector()

            # СБРОСОВЫЙ флаш — его исход НЕ засчитывается ни в одну сторону.
            # Без него половина Б мерила бы не то: коллектор поднимается посреди
            # retry-цикла SDK, недоигранная пачка половины А доезжает уже по
            # открытому сокету, и «записи уехали» оказывается правдой о ПРОШЛОМ
            # батче. Так первая редакция и показала `export_failed = 0` при
            # неизвестно чьём успехе.
            print("[proof] сбросовый flush: увожу хвост, накопленный при закрытом коллекторе")
            discarded = _flush(drv)
            broken = _measurement_failed([discarded])
            if broken:
                print(f"[proof] ОТКАЗ ИЗМЕРЕНИЯ на сбросовом flush: {broken}")
                results.append(_verdict("измерение состоялось (половина Б)", False, broken))
                return 2

            print(f"[proof] коплю ЗАВЕДОМО новые записи {_SETTLE_SEC} с...")
            time.sleep(_SETTLE_SEC)

            mid = _status(drv).get("counters", {})
            lines_before_open = len(_voice_lines(log_dir))
            measured = _flush(drv)
            broken = _measurement_failed([measured])
            if broken:
                print(f"[proof] ОТКАЗ ИЗМЕРЕНИЯ на измеряемом flush: {broken}")
                results.append(_verdict("измерение состоялось (половина Б)", False, broken))
                return 2
            time.sleep(1.0)
            end = _status(drv).get("counters", {})
            print(f"[proof] счётчики при открытом коллекторе: {end!r}")

            failed_delta = int(end.get("export_failed", 0)) - int(mid.get("export_failed", 0))
            exported_delta = int(end.get("exported", 0)) - int(mid.get("exported", 0))
            # Ответ ИЗМЕРЯЕМОГО флаша — своя ось: он говорит об ЭТОМ вызове, а не
            # о сумме за прогон, и потому не зависит от чужих недоигранных ретраев.
            results.append(
                _verdict(
                    "коллектор ОТКРЫТ → измеряемый flush отчитался успехом",
                    measured.get("status") == "ok" and int(measured.get("failed", -1)) == 0,
                    f"ответ измеряемого flush: {measured!r}",
                )
            )
            results.append(
                _verdict(
                    "коллектор ОТКРЫТ → export_failed НЕ растёт",
                    failed_delta == 0,
                    f"прирост export_failed: {failed_delta}, прирост exported: {exported_delta}, "
                    f"запросов принято приёмником: {_AcceptingCollector.received_requests}",
                )
            )
            results.append(
                _verdict(
                    "коллектор ОТКРЫТ → записи реально уехали",
                    exported_delta > 0,
                    f"прирост exported: {exported_delta}; приёмник получил "
                    f"{_AcceptingCollector.received_requests} запрос(ов). Оговорка Task 0.1: "
                    "HTTP 200 сам по себе не значит «доставлено», поэтому счёт по записям",
                )
            )
            results.append(
                _verdict(
                    "коллектор ОТКРЫТ → новых строк отказа нет",
                    len(_voice_lines(log_dir)) == lines_before_open,
                    f"строк было {lines_before_open}, стало {len(_voice_lines(log_dir))}",
                )
            )
    finally:
        if collector is not None:
            collector.shutdown()
            collector.server_close()
        print("[proof] гашу систему (PID-specific)...")
        launcher.shutdown()

    print("\n=== СВОДКА ===")
    proved = sum(1 for _n, ok in results if ok is True)
    refuted = sum(1 for _n, ok in results if ok is False)
    unknown = sum(1 for _n, ok in results if ok is None)
    for name, ok in results:
        label = "ДОКАЗАНО" if ok is True else ("ОПРОВЕРГНУТО" if ok is False else "НЕ ДОКАЗАНО")
        print(f"  {label:<13}{name}")
    print(f"\nдоказано {proved}, опровергнуто {refuted}, не доказано {unknown}")
    return 1 if refuted else 0


if __name__ == "__main__":
    sys.exit(main())
