# -*- coding: utf-8 -*-
"""Живая приёмка 3.4 — предел строки стат-снапшота режет ФАКТИЧЕСКИЕ байты на диске.

Зачем живьём при зелёных тестах. Тесты доказали МЕХАНИКУ формирования строки:
предел соблюдается, потеря названа, ручка читается сборщиком канала. Этот прогон
судит ПРОВОДКУ и ЦЕНУ: доезжает ли ``log_line_max_bytes`` до ``StatsManager``
каждого процесса через сокет, ПМ и раскладку слоёв, и меняется ли при этом
объём, который плоскость реально пишет на диск. Гейт этапа сформулирован в
МиБ/ч на восьми процессах — значит и мерить надо байты файлов, а не длину строки
в памяти.

Метод — два окна одинаковой длины на ОДНОМ стенде:

    окно «до»     предел снят (``log_line_max_bytes=0``) — прежнее поведение;
    окно «после»  предел ``LIMIT_UNDER_TEST`` (512 байт — почему не дефолт, см. константу).

Одинаковая нагрузка, разница только в ручке. Считается прирост байт по всем
``performance.log`` дерева логов (дельта размеров файлов: дописывание в существующий
файл не двигает mtime каталога — урок задачи 3.3), и сравнивается **байт на снапшот**:
число снапшотов в окне плавает вместе с нагрузкой, и голые МиБ/ч приписали бы пределу
чужой эффект (первая редакция прогона так и сделала — 25 снапшотов против 17).

Проверки:

    L1  ручка доезжает: ``config_reload_verified`` по каждому процессу не отдаёт
        отказ, и в окне «после» в файлах появляются строки с голосом потери;
    L2  байты падают: вес снапшота в окне «после» меньше окна «до» — числа в отчёте;
    L3  гейт этапа: фон плоскости в окне «после» ≤ 2 МиБ/ч;
    L4  маркер жив: строки ``metrics snapshot`` продолжают писаться в обоих окнах
        (предел режет тело, а не запись — по маркеру снаружи судят о живости
        статистики, ``probe_b3_shutdown_order_live``);
    L5  ``count`` в заголовке остаётся полным: у усечённых строк число в заголовке
        больше числа метрик, реально уместившихся в тело.

Запуск: ``python -m backend_ctl.probes.probe_3_4_snapshot_line_limit_live``
Стенд одиночный — порт 8765 не терпит двух. Прогон ~9 минут.
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ["BACKEND_CTL"] = "1"

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")

from backend_ctl.harness import BackendHarness  # noqa: E402

RECIPE = PROJECT_ROOT / "multiprocess_prototype" / "recipes" / "webcam_sketch.yaml"

#: Свой каталог логов — дисциплина плана: живой прогон не пишет в общее дерево
#: (П-10: 28 из 34 зондов этого не делают, и их логи ищут не там).
LOG_ROOT = PROJECT_ROOT / "logs_live" / f"3_4_snapshot_line_limit_{int(time.time())}"

#: Длина окна замера, сек. Снапшот идёт раз в ~10 с на процесс: 180 с дают ~18
#: снапшотов на процесс — довольно, чтобы разница не тонула в одном такте.
WINDOW = 180.0

#: Предел, который проверяем. НЕ читается из схемы: замер должен судить конкретное
#: число, а не соглашаться с любым дефолтом, который там окажется завтра.
#:
#: **Почему 512, а не дефолтные 2048.** Первый прогон показал: на ``webcam_sketch``
#: самая длинная строка снапшота — 2042 байта, то есть КОРОЧЕ дефолта. Предел 2048
#: здесь не срабатывает ни разу, и прогон на нём доказывал бы ровно ничего (именно
#: так и вышло: 0 строк с голосом из 17). Замер F1 с его 40–53 КБ снимался на другой
#: нагрузке. Поэтому механизм судится на 512 — числе, при котором срез на этом стенде
#: заведомо происходит; сам дефолт 2048 проверен тестами и расчётом потолка.
LIMIT_UNDER_TEST = 512

#: Дефолт из схемы — не для замера, а чтобы назвать в отчёте, сработал бы он здесь.
SCHEMA_DEFAULT = 2048

SNAPSHOT_RE = re.compile(r"metrics snapshot \(ts=(\d+), count=(\d+)\): (.*)$")
VOICE_RE = re.compile(r"опущено (\d+) из (\d+) метрик, предел (\d+) байт")

FAILURES: List[str] = []


def message_bytes(line: str) -> int:
    """Длина САМОГО сообщения, без префикса логгера.

    Предел ограничивает сообщение, которое канал отдаёт ``LoggerManager``; в файл
    логгер дописывает свой префикс (``#224 2026-08-11 14:49:40,445 [INFO] [devices]
    m.m.statistics_module: ``) — около 75 байт. Сравнение строки ФАЙЛА с пределом
    даёт ложный провал: прогон показал «535 байт при пределе 512», и виноват был
    замер, а не механизм.
    """
    idx = line.find("metrics snapshot")
    return len(line[idx:].encode("utf-8")) if idx >= 0 else 0


def log(msg: str) -> None:
    print(msg, flush=True)


def check(ok: bool, title: str, evidence: str) -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {title}\n         {evidence}")
    if not ok:
        FAILURES.append(f"{title}: {evidence}")


def perf_files() -> List[Path]:
    return sorted(LOG_ROOT.rglob("performance.log"))


def sizes() -> Dict[Path, int]:
    """Размеры всех performance.log. Дельта размеров, а не mtime каталога."""
    return {p: p.stat().st_size for p in perf_files()}


def grown_text(before: Dict[Path, int]) -> str:
    """Текст, ДОПИСАННЫЙ в файлы за окно, — только он и относится к замеру."""
    chunks = []
    for path in perf_files():
        start = before.get(path, 0)
        with open(path, "rb") as fh:
            fh.seek(start)
            chunks.append(fh.read().decode("utf-8", errors="replace"))
    return "".join(chunks)


def processes(drv) -> List[str]:
    """Живые процессы стенда.

    Первая редакция зонда звала ``send_command("ProcessManager", "system.overview")`` —
    команды с таким именем нет, ``_leaf_result`` отдавал пустоту, и список получателей
    выходил ПУСТЫМ. Рассылка ручки тогда не трогала никого, а проверка «ни один процесс
    не отказал» рапортовала PASS по нулю отказов: успех по отсутствию получателя.
    Отсюда обращение к методу драйвера и жёсткий отказ на пустоту (см. ``main``).
    """
    overview = drv.system_overview(timeout=30.0) or {}
    return sorted((overview.get("processes") or {}).keys())


def set_limit(drv, targets: List[str], value: int) -> Tuple[int, List[str]]:
    """Разослать предел по всем процессам. Возвращает (сколько приняли, отказы)."""
    accepted, refused = 0, []
    for name in targets:
        try:
            res = drv.config_reload_verified(
                name,
                observability={"stats": {"log_line_max_bytes": value}},
                settle=1.0,
                timeout=30.0,
            )
        except Exception as exc:  # noqa: BLE001 — отказ обязан быть назван, а не проглочен
            refused.append(f"{name}: {type(exc).__name__} {exc}")
            continue
        verdict = (res or {}).get("verdict")
        if verdict in ("confirmed", "applied", "ok", None):
            accepted += 1
        else:
            refused.append(f"{name}: verdict={verdict}")
    return accepted, refused


def measure(drv, title: str) -> Dict[str, Any]:
    """Прирост байт плоскости за фиксированное окно + разбор дописанных строк."""
    before = sizes()
    time.sleep(WINDOW)
    after = sizes()

    grown = sum(after.get(p, 0) - before.get(p, 0) for p in set(before) | set(after))
    text = grown_text(before)

    lines = [m for m in (SNAPSHOT_RE.search(ln) for ln in text.splitlines()) if m]
    voiced = [ln for ln in text.splitlines() if VOICE_RE.search(ln)]
    longest = max((message_bytes(ln) for ln in text.splitlines() if "metrics snapshot" in ln), default=0)

    mib_per_hour = grown / (1024 * 1024) / (WINDOW / 3600.0)
    # Байт НА СНАПШОТ — то, на что влияет предел. Голые МиБ/ч сравнивать нельзя:
    # число снапшотов в окне плавает вместе с нагрузкой (первый прогон дал 25 против
    # 17 при одинаковом конфиге), и разница темпа выглядела бы эффектом ручки.
    per_snapshot = grown / len(lines) if lines else 0.0
    log(
        f"  {title}: прирост {grown} байт за {WINDOW:.0f} с = {mib_per_hour:.2f} МиБ/ч; "
        f"строк снапшота {len(lines)} ({per_snapshot:.0f} байт на снапшот), "
        f"с голосом потери {len(voiced)}, самая длинная {longest} байт"
    )
    return {
        "bytes": grown,
        "mib_per_hour": mib_per_hour,
        "per_snapshot": per_snapshot,
        "snapshots": len(lines),
        "voiced": len(voiced),
        "longest": longest,
        "matches": lines,
        "files": len(perf_files()),
    }


#: Процесс, чей СТАРТОВЫЙ снапшот и есть тяжёлый случай на этом стенде.
#: Всплеск ``count≈384`` (метрики инициализации) случается ОДНОКРАТНО при подъёме
#: процесса: в шести прошлых прогонах ``logs_live`` эта строка весила 49 314 байт при
#: медиане прогона ~2 КБ. Окна замера открываются после warmup и её не застают — по
#: этой причине первые редакции прогона видели «0 строк с голосом» и делали ложный
#: вывод, что предел на стенде не срабатывает.
BURST_PROCESS = "devices"


def burst_line(drv, limit: int) -> Dict[str, Any]:
    """Стартовый снапшот процесса под заданным пределом — через рестарт.

    Сравнивается ОДНА И ТА ЖЕ запись (метрики инициализации того же процесса) при
    двух значениях ручки, а не два разных окна с плавающей нагрузкой. Это и есть
    честный «до/после»: всё остальное совпадает по построению.
    """
    path = LOG_ROOT / BURST_PROCESS / "performance.log"
    start = path.stat().st_size if path.exists() else 0

    set_limit(drv, [BURST_PROCESS], limit)
    verdict = drv.process_restart_verified(BURST_PROCESS, wait=90.0)
    if not (verdict or {}).get("restarted"):
        return {"error": f"рестарт не подтверждён: {verdict}", "bytes": 0, "count": 0, "voiced": False}

    # Ждём саму запись, а не «сколько-нибудь секунд»: снапшот выходит по такту окна.
    deadline = time.time() + 90.0
    best: Dict[str, Any] = {"bytes": 0, "count": 0, "voiced": False}
    while time.time() < deadline:
        if path.exists():
            with open(path, "rb") as fh:
                fh.seek(start)
                tail = fh.read().decode("utf-8", errors="replace")
            for line in tail.splitlines():
                m = SNAPSHOT_RE.search(line)
                if not m:
                    continue
                nbytes = message_bytes(line)
                if nbytes > best["bytes"]:
                    best = {
                        "bytes": nbytes,
                        "count": int(m.group(2)),
                        "voiced": bool(VOICE_RE.search(line)),
                    }
            if best["count"] >= 100:  # всплеск инициализации пришёл
                break
        time.sleep(3.0)

    log(
        f"  предел {limit}: стартовая строка {best['bytes']} байт при count={best['count']}, "
        f"голос потери {'есть' if best['voiced'] else 'нет'}"
    )
    return best


#: «До» берётся ИЗ АРХИВА, а не из свежего окна, и это названо вслух.
#: В шести прогонах ``logs_live`` (ф8.1 ×2, ф8-ревью, f8.7_verdicts, probe16 ×3) стартовая
#: строка ``devices`` весила 49 314 байт, в ``stage2`` — 53 900. Все они шли тем же
#: харнессом по тому же рецепту, но ДО появления предела, то есть это честное «до»
#: — с той оговоркой, что снято оно не в этом прогоне.
ARCHIVED_BURST_BYTES = 49_314


def l6_startup_burst(drv) -> None:
    """Тяжёлый случай стенда: стартовая запись под дефолтным пределом.

    **Почему здесь ОДНО значение, а не пара.** Первая редакция ставила предел ``0``,
    перезапускала процесс и ждала «жирную» строку для сравнения. Так мерить нельзя:
    ``config.reload`` живёт в памяти процесса, а рестарт поднимает его заново с конфига
    С ДИСКА — установленный ноль исчезает вместе со старым инстансом. Оба замера шли под
    одним и тем же дефолтом и дали идентичные 1972 байта; «экономия 0» была свойством
    метода, а не механизма. Пара с живым нулём требует ДВУХ прогонов стенда с разным
    конфигом на старте — это отдельная работа, здесь она не делается.
    """
    log(f"\n--- L6: стартовый всплеск {BURST_PROCESS} под дефолтом {SCHEMA_DEFAULT} ---")
    burst = burst_line(drv, SCHEMA_DEFAULT)

    if burst.get("error"):
        check(False, "рестарт подтверждён", str(burst["error"]))
        return

    check(
        burst["count"] >= 100,
        "всплеск инициализации пойман (иначе судить нечего)",
        f"count={burst['count']}, строка {burst['bytes']} байт",
    )
    check(
        burst["bytes"] <= SCHEMA_DEFAULT and burst["voiced"],
        "тяжёлая стартовая строка укладывается в дефолт и называет потерю",
        f"{burst['bytes']} байт при пределе {SCHEMA_DEFAULT}, "
        f"голос {'есть' if burst['voiced'] else 'ОТСУТСТВУЕТ'}; "
        f"в архивных прогонах без предела эта же строка весила ~{ARCHIVED_BURST_BYTES} байт "
        f"(экономия ~{ARCHIVED_BURST_BYTES - burst['bytes']} на одной записи — «до» из архива, не из этого прогона)",
    )


def l5_header_count_stays_full(after: Dict[str, Any]) -> None:
    """У усечённой строки заголовок обещает БОЛЬШЕ метрик, чем лежит в теле."""
    log("\n--- L5: count в заголовке — полное число метрик окна ---")
    truncated = [m for m in after["matches"] if VOICE_RE.search(m.group(3))]
    if not truncated:
        check(False, "есть усечённые строки для проверки заголовка", "ни одной строки с голосом потери")
        return

    sample = truncated[0]
    header_count = int(sample.group(2))
    voice = VOICE_RE.search(sample.group(3))
    dropped, total = int(voice.group(1)), int(voice.group(2))
    check(
        header_count == total and dropped > 0,
        "заголовок называет полное число метрик, а не число уместившихся",
        f"count={header_count}, голос: опущено {dropped} из {total}",
    )


def main() -> int:
    log("=" * 78)
    log("Живая приёмка 3.4 — предел строки стат-снапшота, стенд webcam_sketch")
    log(f"каталог логов прогона: {LOG_ROOT}")
    log("=" * 78)

    harness = BackendHarness(recipe=RECIPE, warmup=8.0, log_dir=LOG_ROOT)
    drv = harness.start()
    try:
        targets = processes(drv)
        log(f"\nпроцессов на стенде: {len(targets)} — {', '.join(targets)}")
        if not targets:
            # Без получателей рассылка ручки — не-операция, а все проверки ниже
            # рапортовали бы успех по нулю отказов. Отказ здесь и сразу.
            check(False, "стенд отдал список процессов", "processes пуст — судить нечего, прогон недействителен")
            return 1

        log(f"\n--- окно «до»: предел снят (0), {WINDOW:.0f} с ---")
        accepted_off, refused_off = set_limit(drv, targets, 0)
        log(
            f"  ручку приняли {accepted_off}/{len(targets)} процессов"
            + (f"; отказы: {refused_off}" if refused_off else "")
        )
        before = measure(drv, "окно «до»")

        log(f"\n--- окно «после»: предел {LIMIT_UNDER_TEST} байт, {WINDOW:.0f} с ---")
        accepted_on, refused_on = set_limit(drv, targets, LIMIT_UNDER_TEST)
        log(
            f"  ручку приняли {accepted_on}/{len(targets)} процессов"
            + (f"; отказы: {refused_on}" if refused_on else "")
        )
        after = measure(drv, "окно «после»")

        log("\n--- L1: ручка доезжает до процессов живьём ---")
        check(
            not refused_off and not refused_on,
            "ни один процесс не отказал в применении ручки",
            f"отказов: {len(refused_off) + len(refused_on)}",
        )
        check(
            after["voiced"] > 0,
            "в окне «после» появились строки с голосом потери",
            f"строк с голосом: {after['voiced']} из {after['snapshots']} снапшотов",
        )

        log("\n--- L2: байты падают ---")
        check(
            after["per_snapshot"] < before["per_snapshot"],
            "снапшот в окне «после» весит меньше, чем в окне «до»",
            f"{before['per_snapshot']:.0f} → {after['per_snapshot']:.0f} байт на снапшот "
            f"(фон {before['mib_per_hour']:.2f} → {after['mib_per_hour']:.2f} МиБ/ч при "
            f"{before['snapshots']} и {after['snapshots']} снапшотах — темп плавает, судим нормированное)",
        )
        check(
            after["longest"] <= LIMIT_UNDER_TEST,
            "самая длинная строка окна «после» укладывается в предел",
            f"максимум {after['longest']} байт при пределе {LIMIT_UNDER_TEST} (в окне «до» — {before['longest']})",
        )

        log("\n--- L3: гейт этапа ---")
        check(
            after["mib_per_hour"] <= 2.0,
            "фон плоскости ≤ 2 МиБ/ч",
            f"{after['mib_per_hour']:.2f} МиБ/ч на {len(targets)} процессах, файлов плоскости {after['files']}",
        )
        log(
            f"  [ФАКТ] на этом стенде дефолт {SCHEMA_DEFAULT} байт не срабатывает: самая длинная строка "
            f"окна «до» — {before['longest']} байт. Фон здесь укладывается в гейт и БЕЗ предела "
            f"({before['mib_per_hour']:.2f} МиБ/ч); предел бьёт по тяжёлым процессам замера F1 (40–53 КБ на строку)."
        )

        log("\n--- L4: маркер жив в обоих окнах ---")
        check(
            before["snapshots"] > 0 and after["snapshots"] > 0,
            "строки «metrics snapshot» пишутся и до, и после",
            f"снапшотов: до {before['snapshots']}, после {after['snapshots']}",
        )

        l5_header_count_stays_full(after)
        l6_startup_burst(drv)
    finally:
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
