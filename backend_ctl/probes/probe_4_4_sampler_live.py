# -*- coding: utf-8 -*-
"""Живая приёмка 4.4 (С-8) — дроссель повторов показан работающим на живой системе.

Почему живьём, если механизм покрыт тестами. Закон проекта: **названный механизм
— не обязательство**. ``RateSampler`` дважды проходил приёмки со статусом «не
проверено live», а это единственная защита эмитента от шторма при синхронной
записи. Тесты доказывают арифметику дросселя на подставном приёмнике; они не
доказывают ПРОВОДКУ: что ручка ``observability.sampling_*``, поданная живому
процессу по IPC, доезжает до его ``LoggerManager``, что подавление видно
снаружи числом и что ошибки после включения не исчезают.

Что доказывается прогоном (числа — в отчёте, не «стало меньше»):

  4.4-A  шторм при ВЫКЛЮЧЕННОМ дросселе: эмитировано N, подавлено 0, в журнал
         легли все N — база отсчёта, снятая на том же стенде и том же тексте.
  4.4-B  ручка включена НА ЖИВОЙ СИСТЕМЕ (``config.reload`` без рестарта) →
         тот же шторм: прошло ``first_n`` + каждая ``every_mth``-я, остальное
         подавлено. Ожидаемое число считается ДО прогона по правилу дросселя.
  4.4-C  подавление ВИДНО снаружи двумя разными путями, и оба названы:
         счётчик ``records_sampled_out`` у живого процесса
         (``backend_ctl.observability_counters(...).planes["logger"]``) и поле
         ``extra.sampled_skipped`` на пропущенной записи (живой хвост
         ``observability.tail``) — «сколько всего» и «чего именно».
  4.4-D  ERROR не тронут, и это НЕ следствие того, что дроссель вообще не
         работал: в одном и том же прогоне, при потолке, поднятом оператором до
         CRITICAL, шторм WARNING душится, а шторм ERROR проходит целиком.
         Пара маркеров, а не один: вердикт по одному маркеру врёт.

Стенд — свой рецепт (``probe_4_4_sampler_live.yaml``): один процесс, один
плагин-шторм, никаких кадров. Эмитент называет точное число выданных записей,
поэтому подавление считается арифметикой, а не оценивается по объёму файла.

Запуск: ``python -m backend_ctl.probes.probe_4_4_sampler_live``
Логи прогона — ``logs_live/<дата>_4.4_sampler/``, отчёт — ``report.json`` там же.
"""

from __future__ import annotations

import json
import os
import shutil
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

RECIPE = Path(__file__).with_name("probe_4_4_sampler_live.yaml")
TARGET = "storm"
BURST_COMMAND = "log_storm.burst"

#: Порт зонда — свой, чтобы не столкнуться с параллельным стендом.
PORT = 8844

#: Параметры дросселя. Числа НЕ равны дефолтам схемы (0/100/5.0/DEBUG) ни одним
#: разрядом, кроме окна: тест на значениях дефолта проверял бы дефолт, а не ручку.
FIRST_N = 5
EVERY_MTH = 500
BURST_RESET_SEC = 5.0

#: Шторм. Текст ДОСЛОВНО один и тот же на все повторы — ключ дросселя есть
#: «уровень + текст».
N_DEBUG = 2000
N_WARNING = 1000
N_ERROR = 100
TEXT_DEBUG = "[4.4] дословный повтор уровня DEBUG"
TEXT_WARNING = "[4.4] дословный повтор уровня WARNING"
TEXT_ERROR = "[4.4] дословный повтор уровня ERROR"

FAILURES: List[str] = []
CHECKS: List[Dict[str, Any]] = []


def log(msg: str) -> None:
    print(msg, flush=True)


def check(ok: bool, title: str, evidence: str) -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {title}\n         {evidence}")
    CHECKS.append({"ok": bool(ok), "title": title, "evidence": evidence})
    if not ok:
        FAILURES.append(f"{title}: {evidence}")


def expected_passed(total: int, first_n: int, every_mth: int) -> int:
    """Сколько записей ДОЛЖНО пройти по правилу дросселя — считается ДО прогона.

    Ключ свежий (карта пуста, пока дроссель выключен), поэтому счёт идёт с
    первой записи: ``first_n`` проходят всегда, дальше проходит каждая
    ``every_mth``-я после них.
    """
    if total <= first_n:
        return total
    return first_n + (total - first_n) // every_mth


def logger_plane(drv: Any, *, flush: bool = True) -> Dict[str, Any]:
    """Секция ``logger`` счётчиков наблюдаемости живого процесса.

    ``flush=True`` — когерентный снимок: судим по дельте двух замеров, и
    несведённый такт сдвинул бы её на величину, которой в окне не было.
    """
    planes = drv.observability_counters(TARGET, flush=flush, timeout=25.0).planes or {}
    section = planes.get("logger")
    return section if isinstance(section, dict) else {}


def burst(drv: Any, *, count: int, level: str, text: str) -> int:
    """Выдать шторм и вернуть ЧИСЛО эмитированных записей (со слов эмитента)."""
    res = drv.send_command(
        TARGET,
        BURST_COMMAND,
        {"count": count, "level": level, "text": text},
        timeout=120.0,
    )
    payload = res if isinstance(res, dict) else {}
    # Ответ приезжает завёрнутым (result/data) — разворачиваем до секции с emitted.
    for key in ("result", "data", "payload"):
        inner = payload.get(key)
        if isinstance(inner, dict) and "emitted" in inner:
            payload = inner
            break
    emitted = payload.get("emitted")
    if not isinstance(emitted, int):
        raise RuntimeError(f"шторм не подтверждён числом: ответ {res!r}")
    return emitted


def count_in_tree(root: Path, needle: str) -> Tuple[int, Dict[str, int]]:
    """Сколько раз строка встречается в дереве логов и в каком файле.

    Возвращает (максимум по одному файлу, разбивка). Максимум, а не сумма: одна
    запись законно едет в несколько приёмников, и сумма считала бы приёмники, а
    не записи.
    """
    per_file: Dict[str, int] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in (".log", ".jsonl", ".txt"):
            continue
        try:
            text = path.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            continue
        hits = text.count(needle)
        if hits:
            per_file[str(path.relative_to(root))] = hits
    return (max(per_file.values()) if per_file else 0), per_file


def tree_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            try:
                total += path.stat().st_size
            except OSError:
                pass
    return total


def _find_key(node: Any, key: str) -> List[Any]:
    """Все значения ключа на любой глубине dict-дерева.

    Первая редакция зонда искала ``sampled_skipped`` на верхнем уровне ``extra``
    и не находила НИЧЕГО, хотя поле доезжало: display-вид кладёт ``extra``
    записи под ``extra.context`` (паритет живого хвоста с историей из стора).
    Проверка формой доставки — не то свойство, ради которого стоит зонд.
    """
    found: List[Any] = []
    if isinstance(node, dict):
        for name, value in node.items():
            if name == key:
                found.append(value)
            else:
                found.extend(_find_key(value, key))
    elif isinstance(node, list):
        for item in node:
            found.extend(_find_key(item, key))
    return found


def skipped_marks(drv: Any) -> List[int]:
    """Значения ``sampled_skipped`` из живого хвоста наблюдаемости."""
    marks: List[int] = []
    for rec in drv.observability_records(kind="log", level="DEBUG"):
        for value in _find_key(rec, "sampled_skipped"):
            if isinstance(value, int):
                marks.append(value)
    return marks


def brief(res: Dict[str, Any]) -> str:
    return (
        f"verdict={res.get('verdict')!r} checked={(res.get('verified') or {}).get('checked')} "
        f"mismatches={(res.get('verified') or {}).get('mismatches')} "
        f"unverifiable={(res.get('verified') or {}).get('unverifiable')}"
    )


def main() -> int:
    stamp = time.strftime("%Y-%m-%d")
    log_dir = PROJECT_ROOT / "logs_live" / f"{stamp}_4.4_sampler"
    # Каталог прогона чистится ПЕРЕД стартом: счёт идёт вхождениями текста в
    # дереве, и записи прошлого прогона сложились бы с текущими — «прошло 4000
    # из 2000» выглядело бы как дефект механизма, а не как хвост уборки.
    if log_dir.exists():
        shutil.rmtree(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    # Каталог логов задаётся зонду env'ом (сильнее yaml) — правило logs_live/.
    os.environ["INSPECTOR_LOG_DIR"] = str(log_dir)

    report: Dict[str, Any] = {"stand": str(RECIPE), "log_dir": str(log_dir)}
    harness = BackendHarness(recipe=RECIPE, port=PORT, warmup=6.0)
    drv = harness.start()
    try:
        log("\n--- подготовка: DEBUG на живом процессе ---")
        lvl = drv.config_reload_verified(TARGET, observability={"log_level": "DEBUG"}, settle=1.0, timeout=30.0)
        log(f"         {brief(lvl)}")
        check(
            lvl.get("verdict") == "confirmed",
            "подготовка: уровень DEBUG ДЕЙСТВУЕТ (вердикт процесса)",
            f"verified={lvl.get('verified')}",
        )

        # ---------------------------------------------------------------
        # A. Дроссель ВЫКЛЮЧЕН (дефолт поставки: sampling_first_n = 0)
        # ---------------------------------------------------------------
        log("\n--- 4.4-A: шторм при ВЫКЛЮЧЕННОМ дросселе ---")
        before_a = logger_plane(drv)
        bytes_a0 = tree_bytes(log_dir)
        emitted_a = burst(drv, count=N_DEBUG, level="DEBUG", text=TEXT_DEBUG)
        time.sleep(1.0)
        after_a = logger_plane(drv)
        bytes_a1 = tree_bytes(log_dir)
        sampled_a = int(after_a.get("records_sampled_out", 0)) - int(before_a.get("records_sampled_out", 0))
        in_file_a, files_a = count_in_tree(log_dir, TEXT_DEBUG)
        report["A"] = {
            "emitted": emitted_a,
            "sampled_out_delta": sampled_a,
            "in_file": in_file_a,
            "files": files_a,
            "bytes_delta": bytes_a1 - bytes_a0,
        }
        check(
            emitted_a == N_DEBUG,
            "4.4-A: эмитент выдал ровно столько, сколько просили",
            f"emitted={emitted_a} (просили {N_DEBUG})",
        )
        check(
            sampled_a == 0,
            "4.4-A: при выключенном дросселе подавлено НОЛЬ",
            f"records_sampled_out дельта={sampled_a}",
        )
        check(
            in_file_a == emitted_a,
            "4.4-A: в журнал легли ВСЕ записи шторма",
            f"в файле {in_file_a} из {emitted_a}; объём дерева +{bytes_a1 - bytes_a0} Б; файлы={files_a}",
        )

        # ---------------------------------------------------------------
        # B. Ручка включается НА ЖИВОЙ СИСТЕМЕ
        # ---------------------------------------------------------------
        log("\n--- 4.4-B: включение ручки на живой системе ---")
        knob = drv.config_reload_verified(
            TARGET,
            observability={
                "sampling_first_n": FIRST_N,
                "sampling_every_mth": EVERY_MTH,
                "sampling_burst_reset_sec": BURST_RESET_SEC,
            },
            settle=1.0,
            timeout=30.0,
        )
        log(f"         {brief(knob)}")
        report["knob"] = {
            "verdict": knob.get("verdict"),
            "verified": knob.get("verified"),
            "success": knob.get("success"),
        }
        check(
            bool(knob.get("success")),
            "4.4-B: команда смены конфига принята живым процессом",
            f"success={knob.get('success')!r} verdict={knob.get('verdict')!r}",
        )
        # Вердикт — отдельно от «команда не упала»: первый прогон 4.4 отвечал здесь
        # `unverifiable` (ручка подана, подтвердить нечем), и это была находка, а не
        # шум. Readback параметров дросселя заведён ею.
        check(
            knob.get("verdict") == "confirmed",
            "4.4-B: включение дросселя ПОДТВЕРЖДЕНО процессом (не «не проверено»)",
            f"verdict={knob.get('verdict')!r} verified={knob.get('verified')}",
        )

        # Хвост наблюдаемости — ТОТ ЖЕ путь, которым смотрит оператор и GUI.
        # Ставится ПОСЛЕ базового шторма: 2000 записей окна A забили бы кольцо
        # событий и вытеснили то, ради чего хвост и открыт.
        tail = drv.observability_tail(TARGET, level="DEBUG", timeout=25.0)
        log(f"         хвост: success={tail.get('success')} min_level={tail.get('min_level')!r}")
        drv.observability_records(kind="log", level="DEBUG")  # опустошить курсор до шторма

        want_pass = expected_passed(N_DEBUG, FIRST_N, EVERY_MTH)
        before_b = logger_plane(drv)
        bytes_b0 = tree_bytes(log_dir)
        base_file_b = in_file_a
        emitted_b = burst(drv, count=N_DEBUG, level="DEBUG", text=TEXT_DEBUG)
        time.sleep(1.5)
        after_b = logger_plane(drv)
        bytes_b1 = tree_bytes(log_dir)
        sampled_b = int(after_b.get("records_sampled_out", 0)) - int(before_b.get("records_sampled_out", 0))
        in_file_total_b, files_b = count_in_tree(log_dir, TEXT_DEBUG)
        passed_b = in_file_total_b - base_file_b
        marks = skipped_marks(drv)
        report["B"] = {
            "expected_passed": want_pass,
            "emitted": emitted_b,
            "passed_in_file": passed_b,
            "sampled_out_delta": sampled_b,
            "bytes_delta": bytes_b1 - bytes_b0,
            "keys_tracked": after_b.get("sampler_keys_tracked"),
            "keys_saturated": after_b.get("sampler_keys_saturated"),
            "sampled_skipped_marks": marks,
            "files": files_b,
        }
        check(
            passed_b == want_pass,
            "4.4-B: прошло ровно столько, сколько велит правило дросселя",
            f"прошло {passed_b}, ожидалось {want_pass} (first_n={FIRST_N}, every_mth={EVERY_MTH}) из {emitted_b}",
        )
        # Счётчик процесса считает ВЕСЬ процесс, а не мой ключ: при включённом
        # DEBUG рядом душится собственная болтовня стенда. Поэтому подавление
        # МОЕГО шторма считается по журналу (эмитировано − прошло), а разница со
        # счётчиком называется числом, а не списывается на «примерно сошлось».
        mine_b = emitted_b - passed_b
        background_b = sampled_b - mine_b
        report["B"]["mine_suppressed"] = mine_b
        report["B"]["background_suppressed"] = background_b
        check(
            mine_b == emitted_b - want_pass and background_b >= 0,
            "4.4-B: подавлено = эмитировано − прошло (арифметика сходится)",
            f"мой шторм: подавлено {mine_b} из {emitted_b}; счётчик процесса {sampled_b}, "
            f"фон соседних ключей {background_b}",
        )
        check(
            (bytes_b1 - bytes_b0) * 10 < (bytes_a1 - bytes_a0),
            "4.4-B: объём журнала за окно упал более чем на порядок",
            f"было +{bytes_a1 - bytes_a0} Б, стало +{bytes_b1 - bytes_b0} Б",
        )
        check(
            int(after_b.get("sampler_keys_saturated", 0)) == 0,
            "4.4-B: числа получены дросселем, а не проскоком мимо него",
            f"keys_saturated={after_b.get('sampler_keys_saturated')} "
            f"keys_tracked={after_b.get('sampler_keys_tracked')}",
        )
        check(
            bool(marks) and max(marks) == EVERY_MTH - 1,
            "4.4-C: пропущенная запись несёт ЧИСЛО подавленных однокашников",
            f"extra.sampled_skipped из живого хвоста: {marks} (ожидался {EVERY_MTH - 1})",
        )

        # ---------------------------------------------------------------
        # D. Потолок поднят до CRITICAL: WARNING душится, ERROR проходит
        # ---------------------------------------------------------------
        log("\n--- 4.4-D: оператор поднимает потолок до CRITICAL ---")
        # Порог возвращается к WARNING намеренно: DEBUG-болтовня стенда — тот
        # самый фон, из-за которого счётчик процесса не равен подавлению одного
        # ключа. Гашение фона делает арифметику фазы D точной, а не «примерной».
        ceiling = drv.config_reload_verified(
            TARGET,
            observability={
                "log_level": "WARNING",
                "sampling_first_n": FIRST_N,
                "sampling_every_mth": EVERY_MTH,
                "sampling_burst_reset_sec": BURST_RESET_SEC,
                "sampling_max_level": "CRITICAL",
            },
            settle=1.0,
            timeout=30.0,
        )
        log(f"         {brief(ceiling)}")
        report["ceiling"] = {"verdict": ceiling.get("verdict"), "verified": ceiling.get("verified")}
        mism = (ceiling.get("verified") or {}).get("mismatches") or []
        check(
            ceiling.get("verdict") == "failed" and any(item.get("key") == "logger.sampling_max_level" for item in mism),
            "4.4-D: потолок выше ошибок ОТВЕРГНУТ поимённо, а не принят молча",
            f"verdict={ceiling.get('verdict')!r} mismatches={mism}",
        )

        want_pass_warn = expected_passed(N_WARNING, FIRST_N, EVERY_MTH)
        before_w = logger_plane(drv)
        emitted_w = burst(drv, count=N_WARNING, level="WARNING", text=TEXT_WARNING)
        time.sleep(1.0)
        after_w = logger_plane(drv)
        sampled_w = int(after_w.get("records_sampled_out", 0)) - int(before_w.get("records_sampled_out", 0))
        in_file_w, files_w = count_in_tree(log_dir, TEXT_WARNING)
        report["D_warning"] = {
            "emitted": emitted_w,
            "expected_passed": want_pass_warn,
            "passed_in_file": in_file_w,
            "sampled_out_delta": sampled_w,
            "files": files_w,
        }
        check(
            sampled_w == emitted_w - want_pass_warn and in_file_w == want_pass_warn,
            "4.4-D: при потолке CRITICAL шторм WARNING душится (признак жизни дросселя)",
            f"эмитировано {emitted_w}, прошло {in_file_w} (ожидалось {want_pass_warn}), подавлено {sampled_w}",
        )

        before_e = logger_plane(drv)
        emitted_e = burst(drv, count=N_ERROR, level="ERROR", text=TEXT_ERROR)
        time.sleep(1.0)
        after_e = logger_plane(drv)
        sampled_e = int(after_e.get("records_sampled_out", 0)) - int(before_e.get("records_sampled_out", 0))
        in_file_e, files_e = count_in_tree(log_dir, TEXT_ERROR)
        report["D_error"] = {
            "emitted": emitted_e,
            "passed_in_file": in_file_e,
            "sampled_out_delta": sampled_e,
            "files": files_e,
        }
        check(
            sampled_e == 0,
            "4.4-D: ни одна ERROR-запись не подавлена дросселем",
            f"records_sampled_out дельта={sampled_e} при {emitted_e} эмитированных "
            f"(фон погашен порогом WARNING, поэтому число точное)",
        )
        check(
            in_file_e == emitted_e,
            "4.4-D: все ERROR-записи доехали до журнала",
            f"в файле {in_file_e} из {emitted_e}; файлы={files_e}",
        )
    finally:
        try:
            drv.observability_untail(TARGET, timeout=10.0)
        except Exception as exc:  # noqa: BLE001 — стенд всё равно гасится ниже
            log(f"  [WARN] хвост не снят: {exc}")
        try:
            # Ключи снимаются из слоя сессии, а не переприсваиваются прежними
            # значениями: присвоение порвало бы связь с нижним слоем навсегда.
            drv.send_command(
                TARGET,
                "config.reload",
                {
                    "observability_reset": [
                        "sampling_first_n",
                        "sampling_every_mth",
                        "sampling_burst_reset_sec",
                        "sampling_max_level",
                        "log_level",
                    ]
                },
                timeout=25.0,
            )
        except Exception as exc:  # noqa: BLE001
            log(f"  [WARN] ручки не возвращены: {exc}")
        harness.stop()

    report["checks"] = CHECKS
    report["failures"] = FAILURES
    (log_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    log("\n" + "=" * 70)
    log(f"отчёт: {log_dir / 'report.json'}")
    if FAILURES:
        log(f"ПРОВАЛЕНО проверок: {len(FAILURES)} из {len(CHECKS)}")
        for item in FAILURES:
            log(f"  - {item}")
        return 1
    log(f"ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ ({len(CHECKS)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
