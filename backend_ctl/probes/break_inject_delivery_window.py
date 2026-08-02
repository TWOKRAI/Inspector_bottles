# -*- coding: utf-8 -*-
"""Слом-инъекция по вердикту окна доставки (`backend_ctl/protocol.py`).

Заведена корзиной 2.2: независимое ревью нашло, что у `protocol.py` не было НИ
ОДНОЙ инъекции, хотя коммит обещал «каждая правка со своей парой и слом-инъекцией».
Оно же показало цену пропуска — тест, написанный ради пояса `loss_delta < 0`, был
вакуумным: пояс снимался целиком, а тест оставался зелёным, потому что его вход
ловился соседним per-plane признаком.

**Прогноз объявлен ЗДЕСЬ, до прогона** — в ``EXPECTED``, и составлен ПОСЛЕ того,
как написаны все тесты. Расхождение в любую сторону — находка.

Запуск: ``python -m backend_ctl.probes.break_inject_delivery_window``
        ``python -m backend_ctl.probes.break_inject_delivery_window DW-2``
"""

from __future__ import annotations

import re
import shutil
import subprocess  # nosec B404 — dev-утилита: гоняет pytest проекта, как scripts/
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

PROTOCOL = ROOT / "backend_ctl/protocol.py"

TESTS = ["backend_ctl/tests/test_config_reload_verified.py"]


def dw_1(text: str) -> str:
    """Ранняя ветка снова отрицает перезапуск, который сама же видит (находка Ф-4)."""
    return text.replace(
        "            counters_reset=reset,\n            window_sec=_window_seconds(before, after),\n"
        "            by_channel=by_channel,",
        "            counters_reset=False,  # DW-1\n            window_sec=_window_seconds(before, after),\n"
        "            by_channel=by_channel,",
    )


def dw_2(text: str) -> str:
    """Снят пояс: суммарные потери НАЗАД больше не считаются сдвигом базы."""
    return text.replace(
        "    reset = bool(reset_planes) or loss_delta < 0",
        "    reset = bool(reset_planes)  # DW-2",
    )


def dw_3(text: str) -> str:
    """Ранняя ветка снова выдумывает нули вместо честных потерь (находка корзины 2.2)."""
    return text.replace(
        "            losing=(not reset) and loss_delta > 0,",
        "            losing=False,  # DW-3",
    ).replace(
        "            loss_delta=loss_delta,\n            counters_reset=reset,",
        "            loss_delta=0,  # DW-3\n            counters_reset=reset,",
    )


def dw_4(text: str) -> str:
    """Вычет цены опроса больше не признаёт себя недостоверным — уверенная тишина."""
    return text.replace(
        "    cost_exceeds_window = written_delta > 0 and self_cost > written_delta",
        "    cost_exceeds_window = False  # DW-4",
    )


def dw_5(text: str) -> str:
    """Per-plane признак ослеп: судим по сумме, как до C-3-1."""
    guard = "    if not isinstance(before, dict) or not isinstance(after, dict):\n        return out"
    return text.replace(
        f"    out: List[str] = []\n{guard}",
        f"    out: List[str] = []\n    return out  # DW-5\n{guard}",
    )


INJECTIONS = [
    ("DW-1 ранняя ветка отрицает видимый перезапуск", PROTOCOL, dw_1),
    ("DW-2 пояс суммарных потерь снят", PROTOCOL, dw_2),
    ("DW-3 ранняя ветка выдумывает нули потерь", PROTOCOL, dw_3),
    ("DW-4 цена опроса всегда достоверна", PROTOCOL, dw_4),
    ("DW-5 per-plane признак ослеп", PROTOCOL, dw_5),
]

# Прогноз ДО прогона.
EXPECTED: dict[str, set[str]] = {
    "DW-1 ранняя ветка отрицает видимый перезапуск": {
        "test_missing_total_does_not_deny_a_reset_it_can_see",
    },
    "DW-2 пояс суммарных потерь снят": {
        "test_total_losses_going_backwards_is_a_reset_even_without_a_named_plane",
    },
    "DW-3 ранняя ветка выдумывает нули потерь": {
        "test_losses_are_reported_even_without_a_delivery_counter",
    },
    "DW-4 цена опроса всегда достоверна": {
        "test_self_cost_larger_than_the_whole_window_is_not_silence",
    },
    # Пояс переживает: он считается по сумме и от per-plane не зависит — поэтому
    # `test_total_losses_going_backwards` тут выживает, и это заявка, а не догадка.
    "DW-5 per-plane признак ослеп": {
        "test_counters_reset_is_its_own_state",
        "test_partial_reset_of_one_plane_is_not_hidden_by_a_growing_neighbour",
        "test_plane_that_stopped_reporting_is_a_reset",
        "test_loss_counter_going_backwards_in_one_plane_is_detected",
        "test_missing_total_does_not_deny_a_reset_it_can_see",
    },
}


def run_tests() -> tuple[int, set[str]]:
    proc = subprocess.run(  # nosec B603 — аргументы литеральные, внешнего ввода нет
        [str(PY), "-m", "pytest", *TESTS, "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = proc.stdout + proc.stderr
    failed = set(re.findall(r"FAILED [^\s:]+::[^\s:]+::(\w+)", out))
    failed |= set(re.findall(r"FAILED [^\s:]+::(test_\w+)", out))
    if "ERROR collecting" in out:
        failed.add("<ОШИБКА СБОРА — заплата сломала импорт>")
    return proc.returncode, failed


def main(argv: list[str] | None = None) -> int:
    wanted = set(argv or [])
    mismatches = 0
    for title, path, patch in INJECTIONS:
        if wanted and title.split(maxsplit=1)[0] not in wanted:
            continue
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        try:
            original = path.read_text(encoding="utf-8")
            broken = patch(original)
            if broken == original:
                print(f"{title}: ЗАПЛАТА НЕ ПРИМЕНИЛАСЬ — инъекция недействительна")
                mismatches += 1
                continue
            path.write_text(broken, encoding="utf-8")
            _code, failed = run_tests()
        finally:
            shutil.copy2(backup, path)
            backup.unlink(missing_ok=True)
        expected = EXPECTED.get(title, set())
        extra, missing = failed - expected, expected - failed
        if extra or missing:
            mismatches += 1
        print(f"{title}: {'СОВПАЛО' if not extra and not missing else 'РАСХОЖДЕНИЕ'} умерли={len(failed)}", flush=True)
        if missing:
            print(f"    выжили вопреки прогнозу: {sorted(missing)}")
        if extra:
            print(f"    умерли сверх прогноза:   {sorted(extra)}")

    code, failed = run_tests()
    print(f"\nконтроль (без слома): exit={code} умерли={sorted(failed) or 'НИКТО'}")
    print(f"расхождений с прогнозом: {mismatches}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
