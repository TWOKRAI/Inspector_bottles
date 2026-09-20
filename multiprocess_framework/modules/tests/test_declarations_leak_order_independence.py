# -*- coding: utf-8 -*-
"""RED (Task 0.1, критерий 1) — гейт фреймворка зелен в ЛЮБОМ порядке сбора модулей.

Независимый приёмочный тест, написанный ДО реализации (`plans/observability-closure/
phase-0-trust-gate.md`, Task 0.1). Источник — Acceptance criteria задачи, не код: реализации
ещё нет (worktree стоит на коммите ДО Task 0.1).

**Что здесь проверяется.** `statistics_module/tests/test_observation_port_hazards.py`
(тест `test_declare_through_the_slot_lands_in_the_shared_catalogue`) вызывает голый
`forget_declarations()` — без `names` и без `kind`. Голый вызов чистит реестр
объявлений ЦЕЛИКОМ, включая пять метрик фреймворка (`cycle_duration_ms`, `effective_hz`,
`fps`, `latency_ms`, `shm`), объявленных при ИМПОРТЕ `process_module/heartbeat/
telemetry.py` и `process_heartbeat.py`. Реестр процессный и наполняется импортом —
повторно объявить стёртое после того, как модуль уже импортирован, некому (см.
докстрока `forget_declarations` в `observability_declarations.py`).

Значит, если `statistics_module/tests` собираются и выполняются РАНЬШЕ
`process_module/tests` в одном процессе pytest, чистка происходит до того, как
`process_module`-тесты успели воспользоваться каталогом, и они начинают падать
пачкой (проверено вручную 2026-08-28 в этом дереве: обратный порядок даёт 21
упавший тест про gated-каталог, прямой — 1 несвязанный таймингом тест). Порядок
аргументов командной строки менять СВОЙСТВО прохождения тестов не должен.

**Дедлайн.** Обе половины гоняются `subprocess.run(..., timeout=...)`, а не голым
`os.system`/пайпом без предела — подвисший прогон хуже отсутствующего (правило
проекта, см. CLAUDE.md `.claude/`).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

# multiprocess_framework/modules/tests/<this file> -> parents[3] = корень репозитория
# (worktree), tests -> modules -> multiprocess_framework -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]

_STATS_DIR = "multiprocess_framework/modules/statistics_module/tests"
_PROCESS_DIR = "multiprocess_framework/modules/process_module/tests"

#: Замер 2026-08-28: единственный тест, что красный НЕЗАВИСИМО от порядка сборки
#: (флейк по времени `overhead < 5.0e-6`, тайминг-бенчмарк facade против прямого
#: вызова). Он не имеет отношения к реестру объявлений — исключён из ОБОИХ
#: прогонов ОДИНАКОВО, чтобы шум таймингов не маскировал и не имитировал
#: свойство, которое тест на самом деле проверяет.
#:
#: **Путь — от ROOTDIR подпроцесса, а не от корня репозитория, и это не педантизм.**
#: `pytest` резолвит `--deselect` по nodeid, а rootdir здесь —
#: `multiprocess_framework/modules/` (там свой конфиг), поэтому настоящий nodeid
#: начинается с `process_module/`. Репо-относительный путь `--deselect` принимает
#: МОЛЧА и не исключает ничего: замер `--collect-only` давал `41 collected` и с
#: флагом, и без него — совпади путь, было бы `40 collected, 1 deselected`.
#: Найдено ревьюером Ф0.5; до того флаг стоял мёртвым, а прогоны выглядели
#: успешными просто потому, что перф-флейк зависит от нагрузки и не всегда стрелял.
_DESELECT_UNRELATED_TIMING_FLAKE = (
    "process_module/tests/test_plugin_stats_road.py"
    "::TestTheCostOfTheHotPath::test_the_facade_adds_little_over_a_direct_call"
)

_SUBPROCESS_TIMEOUT_SEC = 300.0

_SUMMARY_RE = re.compile(r"(\d+) (passed|failed|error|errors)")

#: Строка-сводка pytest узнаётся по ФОРМЕ, а не по положению в выводе: счётчик исходов
#: плюс хвост «in <секунды>s». Второе условие обязательно — без него в сводку попал бы
#: любой абзац, где случайно стоит «N passed».
_SUMMARY_LINE_RE = re.compile(r"\d+ (?:passed|failed|error|errors|skipped|xfailed|xpassed|deselected)\b.*\bin \d")


def _parse_summary(output: str) -> dict[str, int]:
    """Разобрать сводку исходов из вывода подпрогона.

    Ищет ПОСЛЕДНЮЮ строку формы сводки, а не последнюю строку вывода. Разница не
    косметическая — она измерена.

    **Что было и чем это стоило (2026-09-03, задача 2.11).** Прежняя редакция брала
    ``output.strip().splitlines()[-1]``. Корневой гейт дал красный этого теста с
    сообщением «прямой порядок не собрал ни одного пройденного теста ({})» — при том
    что подпрогон честно отработал ``3235 passed, 1 deselected, 1 xfailed``. Причина в
    ОДНОЙ посторонней строке, напечатанной ПОСЛЕ сводки: логгер процесса
    ``hook_leak_probe`` (:mod:`process_module.tests.test_process_hooks_wiring`, строка
    с ``ProcessModule("hook_leak_probe", …)``) при гашении интерпретатора жалуется, что
    канал ``performance_file`` не разрешился. Регулярка по такой строке даёт ``{}``, и
    абсолютный пол теста («ноль наблюдений — тоже результат») срабатывал на СОБСТВЕННОМ
    разборе, а не на предмете. Проверено повтором: на том же коммите второй прогон
    зелёный, на пред-задачном коммите зелёный — то есть тест был флейкозависим от
    порядка гашения чужих потоков, а красный сообщал не о том, о чём написан.

    **Почему именно ПОСЛЕДНЯЯ подходящая, а не первая.** Внутри подпрогона живут тесты,
    которые сами запускают pytest (``test_metric_catalog_order_gate.py``), поэтому в
    середине вывода законно встречается ЧУЖАЯ сводка. Своя всегда последняя — а
    посторонние строки после неё сводкой по форме не являются и в разбор не попадают.
    """
    lines = [ln for ln in output.splitlines() if _SUMMARY_LINE_RE.search(ln)]
    if not lines:
        return {}
    summary: dict[str, int] = {}
    for count, word in _SUMMARY_RE.findall(lines[-1]):
        summary[word] = summary.get(word, 0) + int(count)
    return summary


def _run_order(first: str, second: str) -> tuple[dict[str, int], str]:
    """Гоняет pytest в подпроцессе с заданным порядком директорий-аргументов.

    Возвращает разобранную сводку (``{"passed": N, "failed": M, ...}``) и полный
    вывод — для диагностики при расхождении.
    """
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    # Ребёнок печатает кириллицу, родитель по умолчанию декодирует локалью (cp1251
    # на этой машине) — на первом же русском traceback'е чтение падало
    # `UnicodeDecodeError` в reader-потоке, `proc.stdout` приезжал `None`, и тест
    # умирал `TypeError: unsupported operand +: NoneType and str` вместо того, чтобы
    # сообщить про порядок сборки. Рецепт взят у соседа
    # (`process_module/tests/test_metric_catalog_order_gate.py`), где он уже был.
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        first,
        second,
        "-q",
        "--deselect",
        _DESELECT_UNRELATED_TIMING_FLAKE,
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_SUBPROCESS_TIMEOUT_SEC,
    )
    output = proc.stdout + "\n" + proc.stderr
    return _parse_summary(output), output


def test_statistics_then_process_module_order_matches_the_reverse_order() -> None:
    """Acceptance §1: прямой и обратный порядок аргументов дают одинаковый результат.

    Литерал для сравнения НЕ используем (пример из спеки — "ожидание ~2749 passed" —
    это ориентир, не точное число): свойство, которое проверяется, — совпадение
    двух прогонов ДРУГ С ДРУГОМ, а не с заранее вычисленным числом.
    """
    forward, forward_output = _run_order(_STATS_DIR, _PROCESS_DIR)
    reverse, reverse_output = _run_order(_PROCESS_DIR, _STATS_DIR)

    # АБСОЛЮТНЫЙ ПОЛ — прежде сравнения. Одно лишь `forward == reverse` истинно и
    # тогда, когда оба прогона не собрали НИ ОДНОГО теста: замер ревьюера Ф0.5 —
    # переименуй каталоги, и тест зеленеет на `{} == {}` при «no tests ran» с обеих
    # сторон. Ноль наблюдений выглядел результатом наблюдения. Литерал числа тут
    # по-прежнему не нужен (он ориентир, не контракт), а вот «прогон СОСТОЯЛСЯ и не
    # содержал поломок» — обязан проверяться отдельно от совпадения.
    for имя, сводка, вывод in (("прямой", forward, forward_output), ("обратный", reverse, reverse_output)):
        assert сводка.get("passed", 0) > 0, (
            f"{имя} порядок не собрал ни одного пройденного теста ({сводка}) — сравнивать нечего, "
            f"а совпадение двух пустот прочиталось бы как успех.\n--- хвост ---\n{вывод[-2000:]}"
        )
        for поломка in ("failed", "error", "errors"):
            assert поломка not in сводка, (
                f"{имя} порядок содержит {поломка}={сводка[поломка]} — свойство «оба порядка одинаковы» "
                f"выполнимо и на двух одинаково сломанных прогонах.\n--- хвост ---\n{вывод[-2000:]}"
            )

    assert forward == reverse, (
        "результат прогона зависит от порядка директорий в командной строке:\n"
        f"  statistics_module -> process_module:  {forward}\n"
        f"  process_module -> statistics_module:  {reverse}\n"
        "Ожидаемая причина (Task 0.1, C1): голый forget_declarations() в "
        "test_observation_port_hazards.py чистит реестр объявлений ЦЕЛИКОМ; когда "
        "statistics_module/tests собираются и выполняются раньше process_module/tests, "
        "уже импортированные производители метрик фреймворка не могут переобъявиться "
        "после чистки, и process_module/tests краснеет пачкой тестов про gated-каталог.\n"
        f"--- хвост вывода (прямой порядок) ---\n{forward_output[-2000:]}\n"
        f"--- хвост вывода (обратный порядок) ---\n{reverse_output[-2000:]}"
    )


class TestTheSummaryIsFoundByShapeNotByPosition:
    """Разбор сводки не ломается посторонней строкой после неё — и не выдумывает сводку.

    Четыре быстрых теста без подпроцесса на функцию :func:`_parse_summary`. Заведены
    2026-09-03 (задача 2.11) после того, как ОДНА строка логгера, напечатанная при
    гашении интерпретатора, дала этому файлу красный с сообщением «не собрал ни одного
    пройденного теста» при 3235 честно пройденных. Подробный разбор — в докстринге
    :func:`_parse_summary`.

    Четвёртый тест — КОНТРОЛЬ, и он обязателен: без него починка «искать сводку по
    форме» была бы неотличима от починки «всегда что-нибудь находить», а абсолютный пол
    теста (``passed > 0``) существует именно для случая, когда прогон не состоялся.
    """

    #: Дословная строка, из-за которой красный и случился, — не пересказ.
    STRAY = (
        "[WARNING] [logger_hook_leak_probe] [system] канал 'performance_file' не разрешился "
        "ни в один из существующих (просмотрено 1)"
    )
    REAL = "3235 passed, 1 deselected, 1 xfailed, 2 warnings in 132.60s (0:02:12)"

    def test_a_plain_summary_is_parsed(self) -> None:
        """Обычный случай: сводка и есть последняя строка."""
        assert _parse_summary(f"...\n{self.REAL}\n") == {"passed": 3235}

    def test_a_stray_line_after_the_summary_does_not_hide_it(self) -> None:
        """Предмет починки: посторонняя строка ПОСЛЕ сводки. До правки давало ``{}``."""
        assert _parse_summary(f"...\n{self.REAL}\n\n{self.STRAY}\n") == {"passed": 3235}

    def test_a_nested_summary_earlier_loses_to_the_real_one(self) -> None:
        """Внутри подпрогона есть тесты, сами запускающие pytest — их сводка идёт РАНЬШЕ.

        Своя сводка всегда последняя по форме, поэтому берётся именно она, а не
        первая подходящая.
        """
        nested = "41 passed, 1 deselected in 3.10s"
        parsed = _parse_summary(f"{nested}\n...\n{self.REAL}\n{self.STRAY}\n")
        assert parsed == {"passed": 3235}, parsed

    def test_an_output_without_any_summary_stays_empty(self) -> None:
        """Контроль: прогон, который не состоялся, обязан по-прежнему читаться как пустой.

        Иначе абсолютный пол теста («ноль наблюдений — тоже результат») перестал бы
        срабатывать, и совпадение двух пустот снова прочиталось бы как успех.
        """
        assert _parse_summary(f"ImportError: боом\n{self.STRAY}\n") == {}
