# -*- coding: utf-8 -*-
"""Живая приёмка задачи 1.6 и гейта этапа 1 — вкладка ищет по живому стору.

Зачем живьём при зелёных тестах. Тесты доказали МЕХАНИКУ: движок находит слово,
панель показывает ответ, отказ отличим от «не нашлось». Здесь судится ПРОВОДКА,
которой нет ни в одном тесте:

* панель в тестах получает стор прямо в конструктор, а в приложении открывает его
  сама — ``open_default_source()`` → ``resolve_default_db_path()`` → env-путь. Этот
  шов не проходит ни один тест, а именно на таких швах трек и находил дефекты;
* открытие стора GUI-процессом происходит на ФАЙЛЕ, в который прямо сейчас пишут
  восемь процессов: миграция auto_vacuum и backfill FTS-индекса впервые встречаются
  с живым писателем. В тестах файл всегда был свой и тихий;
* гейт этапа 1 требует, чтобы INFO-подписка приносила события КАЖДОГО процесса
  стенда, включая оркестратор (1.1/1.2), и чтобы арифметика хвоста сходилась со
  стором.

Проверки:

    S1  INFO-подписка → в хвосте есть записи от каждого процесса, который ответил
        на провокацию (список процессов читается из системы, а не из головы;
        нечитаемый список — это FAIL, а не «ноль процессов»).
    S2  Арифметика: спровоцированные записи с маркером лежат В СТОРЕ, и число
        строк стора за окно выросло не меньше, чем на число доехавших маркеров.
    S3  Панель, открывшая стор ПРОДОВЫМ путём, находит слово из свежей записи.
    S4  Фильтр уровня сужает живую выдачу (пара: до фильтра больше, после — только
        ERROR-маркер).
    S5  Слова, которого нет, панель НЕ выдаёт за пустую историю: таблица пуста,
        а объяснение — про поиск.
    S6  Отказ движка на живом сторе доезжает до метки панели (сломанный запрос).

Запуск: ``python -m backend_ctl.probes.probe_16_tab_search_live``
Стенд одиночный — порт 8765 не терпит двух. Прогон ~2 минуты.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ["BACKEND_CTL"] = "1"

#: Свой каталог логов на прогон: стенд пишет observability.db сюда, и панель
#: обязана найти ТОТ ЖЕ файл сама, через env — это и есть проверяемый шов.
#:
#: Метку времени берём ТОЛЬКО если каталог ещё не назначен. Первая редакция
#: вычисляла её безусловно — и живой прогон дал ПЯТЬ каталогов вместо одного:
#: на Windows дочерние процессы спавнятся переимпортом этого модуля, каждый
#: считал свою метку и перезаписывал env себе. Писатели разъехались по пяти
#: базам, панель открыла шестую и увидела ноль строк. Дефект измерения, а не
#: продукта — но выглядел он в точности как «стор не пишется».
_inherited = os.environ.get("MULTIPROCESS_LOG_DIR")
LOG_DIR = Path(_inherited) if _inherited else PROJECT_ROOT / "logs_live" / f"probe16_{int(time.time())}"
LOG_DIR.mkdir(parents=True, exist_ok=True)
os.environ["MULTIPROCESS_LOG_DIR"] = str(LOG_DIR)

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")

from backend_ctl.harness import BackendHarness  # noqa: E402

RECIPE = PROJECT_ROOT / "multiprocess_prototype" / "recipes" / "webcam_sketch.yaml"

MARKER = "PROBE16-SEARCHABLE-WORD"
ERROR_MARKER = "PROBE16-BROKEN-FRAME"
WARN_MARKER = "PROBE16-SLOW-FRAME"
#: Слово, которого в сторе нет. БЕЗ дефисов и знаков: первая редакция взяла
#: «PROBE16-НЕТ-ТАКОГО-СЛОВА» и получила отказ парсера вместо пустого
#: результата — проверка «не нашлось» судила бы синтаксис, а не поиск.
ABSENT_WORD = "вертолётоносец"

FAILURES: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)


def check(ok: bool, title: str, evidence: str) -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {title}\n         {evidence}")
    if not ok:
        FAILURES.append(f"{title}: {evidence}")


def process_names(drv) -> list[str]:
    """Имена процессов стенда — из живой системы, не из головы.

    Пустой/нечитаемый ответ возвращается КАК пустой список, и вызывающий обязан
    отличить его от «процессов нет»: молчащий детектор не должен выглядеть как
    детектор, показавший ноль.
    """
    overview = drv.system_overview(timeout=30.0) or {}
    for key in ("processes", "process_list", "topology"):
        section = overview.get(key)
        if isinstance(section, dict) and section:
            return sorted(str(k) for k in section)
        if isinstance(section, list) and section:
            names = []
            for item in section:
                if isinstance(item, str):
                    names.append(item)
                elif isinstance(item, dict):
                    name = item.get("name") or item.get("process")
                    if name:
                        names.append(str(name))
            if names:
                return sorted(set(names))
    return []


def provoke(drv, process: str, marker: str, level: str = "INFO") -> bool:
    """Заставить процесс написать запись с опознаваемым маркером. True — команда принята."""
    try:
        res = drv.send_command(
            process,
            "health.report",
            {"message": marker, "level": level, "context": "probe16"},
            timeout=15.0,
        )
        return bool((res or {}).get("success"))
    except Exception as exc:  # noqa: BLE001 — недоступный процесс не должен ронять прогон
        log(f"         (провокация {process} не прошла: {exc})")
        return False


def drain(drv) -> list:
    """Все приехавшие записи БЕЗ клиентского severity-фильтра (иначе судим клиента)."""
    return drv.observability_records(level="DEBUG")


# --------------------------------------------------------------------------


def s1_every_process_reaches_the_subscriber(drv) -> tuple[list[str], int]:
    log("\n--- S1: INFO-подписка → записи от каждого ответившего процесса ---")
    drv.watch_like_gui(tail_level="INFO")
    time.sleep(2.0)
    drain(drv)  # сбросить бутстрап-хвост: считаем только своё окно

    names = process_names(drv)
    check(bool(names), "список процессов стенда прочитан", f"процессы: {names or 'НЕ ПРОЧИТАН'}")
    if not names:
        return [], 0

    accepted: list[str] = []
    for name in names:
        if provoke(drv, name, f"{MARKER} from {name}"):
            accepted.append(name)
    first = accepted[0] if accepted else names[0]
    provoke(drv, first, ERROR_MARKER, level="ERROR")
    # WARNING-маркер нужен S4: ERROR-запись уезжает в плоскость ошибок, и на
    # вкладке «Логи» фильтр ERROR оставлял бы ПУСТОЕ множество — «все
    # оставшиеся суть ERROR» истинно ни на чём. Сужение надо мерить там, где
    # после фильтра что-то остаётся.
    provoke(drv, first, WARN_MARKER, level="WARNING")
    time.sleep(8.0)

    records = drain(drv)
    mine = [r for r in records if MARKER in str(r.get("message", ""))]
    seen = {str(r.get("process", "")) for r in mine}
    missing = [p for p in accepted if p not in seen]

    check(
        bool(accepted),
        "хотя бы один процесс принял провокацию",
        f"приняли: {accepted}, всего процессов: {len(names)}",
    )
    check(
        not missing,
        "записи доехали от КАЖДОГО принявшего процесса",
        f"принявших: {len(accepted)}, увидено в хвосте: {sorted(seen)}, потеряно: {missing}",
    )
    check(
        "ProcessManager" in seen or "ProcessManager" not in accepted,
        "оркестратор среди источников (Н-1/задача 1.1)",
        f"ProcessManager принял провокацию: {'ProcessManager' in accepted}, виден в хвосте: {'ProcessManager' in seen}",
    )
    return accepted, len(mine)


def s2_store_arithmetic(store, before: int, delivered: int) -> None:
    log("\n--- S2: арифметика хвоста и стора ---")
    after = store.count()
    found = store.search(MARKER.split("-")[-1], limit=500) if store.search_available else []
    check(
        after - before >= delivered,
        "стор вырос не меньше, чем доехало в хвост",
        f"строк до={before}, после={after}, дельта={after - before}, доехало в хвост={delivered}",
    )
    check(
        len(found) >= delivered > 0,
        "спровоцированные записи ЛЕЖАТ в сторе (а не только в хвосте)",
        f"найдено поиском по слову: {len(found)}, доехало в хвост: {delivered}",
    )


def s3_s6_panel_on_the_live_store(app_cls, source) -> None:
    from multiprocess_prototype.frontend.widgets.tabs.observability import RecordHistoryPanel

    panel = RecordHistoryPanel(source, "log")

    log("\n--- S3: панель, открывшая стор продовым путём, находит слово ---")
    check(
        panel._edit_search.isEnabled(),
        "поле поиска живое на живом сторе",
        f"enabled={panel._edit_search.isEnabled()}, причина={panel._presenter.search_unavailable_reason}",
    )
    word = MARKER.split("-")[-1]
    panel._edit_search.setText(word)
    panel._edit_search.returnPressed.emit()
    rows = panel._table.rowCount()
    messages = [panel._table.item(r, 4).text() for r in range(rows)]
    check(
        rows > 0 and all(word in m for m in messages),
        "слово из свежей записи найдено через поле панели",
        f"строк: {rows}, пример: {messages[:1]}",
    )

    log("\n--- S4: фильтр уровня сужает живую выдачу (пара, непустая с обеих сторон) ---")
    wide = rows
    panel._edit_search.setText("PROBE16")
    panel._edit_search.returnPressed.emit()
    wide_all = panel._table.rowCount()
    if panel._combo_level is not None:
        panel._combo_level.setCurrentText("WARNING")
    narrow = panel._table.rowCount()
    sev = {panel._table.item(r, 1).text().lower() for r in range(narrow)}
    check(
        0 < narrow < wide_all and sev == {"warning"},
        "WARNING-фильтр сузил выдачу поиска, и остаток непуст",
        f"без фильтра: {wide_all} (слово-только: {wide}), с WARNING: {narrow}, уровни остатка: {sev or '—'}",
    )
    if panel._combo_level is not None:
        panel._combo_level.setCurrentIndex(0)

    log("\n--- S7: кусок живого сообщения, вставленный в поиск, находится ---")
    panel._edit_search.setText(MARKER)
    panel._edit_search.returnPressed.emit()
    found_rows = panel._table.rowCount()
    pasted = panel._table.item(0, 4).text() if found_rows else ""
    panel._edit_search.setText(pasted)
    panel._edit_search.returnPressed.emit()
    check(
        bool(pasted) and panel._table.rowCount() > 0 and panel._presenter.search_error is None,
        "целая строка сообщения (со скобками, дефисами) ищется как есть",
        f"вставлено: {pasted!r} → строк: {panel._table.rowCount()}, ошибка: {panel._presenter.search_error!r}",
    )

    log("\n--- S5: слово, которого нет, — это ответ ПОИСКА, а не пустая история ---")
    panel._edit_search.setText(ABSENT_WORD)
    panel._edit_search.returnPressed.emit()
    hint = panel._lbl_empty.text()
    check(
        panel._table.rowCount() == 0 and "ничего не найдено" in hint,
        "пустой результат объяснён поиском",
        f"строк: {panel._table.rowCount()}, подсказка: {hint[:90]!r}",
    )
    check(
        "observability.history.level" not in hint,
        "подсказка ПУСТОЙ ИСТОРИИ не подменяет ответ поиска",
        f"подсказка: {hint[:90]!r}",
    )

    log("\n--- S6: отказ движка на живом сторе доезжает до метки ---")
    panel._edit_search.setText('"незакрытая кавычка')
    panel._edit_search.returnPressed.emit()
    err = panel._presenter.search_error
    check(
        err is not None and "не понят" in err,
        "сломанный запрос — названный отказ, а не «записей нет»",
        f"search_error={err!r}, подсказка={panel._lbl_empty.text()[:90]!r}",
    )
    panel.deleteLater()


def main() -> int:
    log("=" * 78)
    log("Живая приёмка 1.6 — вкладка ищет по живому стору (стенд webcam_sketch)")
    log(f"каталог прогона: {LOG_DIR}")
    log("=" * 78)

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    harness = BackendHarness(recipe=RECIPE, warmup=8.0)
    drv = harness.start()
    store = None
    try:
        # Стор открывается ПРОДОВЫМ путём панели — на файле, в который прямо
        # сейчас пишут процессы стенда (миграция и backfill встречаются с живым
        # писателем впервые).
        from multiprocess_prototype.frontend.widgets.tabs.observability import open_default_source

        t0 = time.perf_counter()
        store = open_default_source()
        open_ms = (time.perf_counter() - t0) * 1000
        check(
            store is not None,
            "панельный open_default_source() открыл живой стор",
            f"путь={getattr(store, 'db_path', None)}, открытие={open_ms:.1f} мс",
        )
        if store is None:
            return 1
        before = store.count()
        log(f"         строк в сторе до окна: {before}")

        _accepted, delivered = s1_every_process_reaches_the_subscriber(drv)
        time.sleep(3.0)  # дать писателям стора добежать (heartbeat-drain)
        s2_store_arithmetic(store, before, delivered)
        s3_s6_panel_on_the_live_store(app, store)
    finally:
        if store is not None:
            close = getattr(store, "close", None)
            if callable(close):
                close()
        harness.stop()

    log("\n" + "=" * 78)
    if FAILURES:
        log(f"ПРОВАЛЕНО проверок: {len(FAILURES)}")
        for f in FAILURES:
            log(f"  - {f}")
        return 1
    log("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
