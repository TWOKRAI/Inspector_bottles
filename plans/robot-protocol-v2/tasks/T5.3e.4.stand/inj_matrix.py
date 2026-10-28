# ruff: noqa: E501
"""Матрица инъекций T5.3e.4: мутация -> прогон robot/tests через machine_gate -> откат.

    PYTHONPATH=<дерево> python inj_matrix.py <дерево> [--check] [--only I3,I6] [--out таблица.md]

Дерево - ОДНОРАЗОВОЕ (мутирует src и откатывает `git checkout --`). `--check` только считает, сколько раз
каждый якорь встречается (должно быть ровно 1), тесты не гоняет. Предсказания лида - в
`plans/robot-protocol-v2/reports/T5.3e.4.injections-predictions.md`; сравнивает лид, не скрипт.
"""

from __future__ import annotations

import argparse
import re
import subprocess  # nosec B404 - прогон pytest через machine_gate
import sys
from pathlib import Path

R = "multiprocess_prototype/frontend/widgets/tabs/services/robot"
CTL = f"{R}/controller.py"
PRES = f"{R}/presenter.py"
PY = "D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.venv/Scripts/python.exe"
SESSION = "inspector-bottles-35"
BASH = "C:/Program Files/Git/bin/bash.exe"  # не "bash": из Python он резолвится в WSL-релей

# (имя, файл, было, стало); \n в строках - переводы строк файла (скрипт подгоняет под CRLF/LF)
MUTATIONS: list[tuple[str, str, str, str]] = [
    ("I1", PRES, '"level": "HARD"', '"level": "HALT"'),
    (
        "I2",
        CTL,
        'if seq is None or self._park_view.get("seq") != seq or self._park_state_seq != seq:',
        "if seq is None:",
    ),
    (
        "I3",
        CTL,
        "            self._park_text = _TXT_PARK_ACCEPTED\n            self._widget.set_status(self._park_text)\n",
        '            self._park_text = _TXT_PARK_ACCEPTED\n            self._widget.set_status("Робот дома, серво выключено.")\n',
    ),
    (
        "I4",
        CTL,
        '            if self._park_text is None:  # итог «Остановить» не затираем\n                self._widget.set_status("Связь',
        '            if True:\n                self._widget.set_status("Связь',
    ),
    (
        "I5",
        CTL,
        '        if rel == "":\n            if not isinstance(value, dict):\n',
        '        if rel == "":\n            return\n            if not isinstance(value, dict):\n',
    ),
    ("I6", CTL, 'elif rel == "seq" and value != view.get("seq"):', "elif False:"),
    ("I7", CTL, "            self._render_park()  # итог мог прийти раньше ответа\n", ""),
    ("I8", CTL, "        self._clear_park_text()\n        labels = {1:", "        labels = {1:"),
    (
        "I9",
        CTL,
        '            self._bindings.bind_fanout(\n                f"{base}.park.**",\n                self._on_park_push,\n                owner=self._widget,\n            )',
        "            pass",
    ),
    (
        "I10",
        CTL,
        "        self._park_state_seq = None\n        device_id = self._device_id\n        self._presenter.park(",
        "        self._park_seq = None\n        device_id = self._device_id\n        self._presenter.park(",
    ),
    (
        "I11",
        CTL,
        '        self._park_text = message or "Основная остановка не принята."',
        '        self._park_seq = None\n        self._park_text = message or "Основная остановка не принята."',
    ),
    (
        "I12",
        CTL,
        '        if self._park_text is None:  # итог «Остановить» не затираем\n            self._widget.set_status("Опрос',
        '        if True:\n            self._widget.set_status("Опрос',
    ),
    ("I13", CTL, '        self._clear_park_text()\n        kind = "абс"', '        kind = "абс"'),
]


def fit(text: str, crlf: bool) -> str:
    return text.replace("\n", "\r\n") if crlf else text


def run_tests(tree: Path) -> tuple[int, list[str], str]:
    gate = (tree / ".git").read_text(encoding="utf-8").strip()  # "gitdir: <abs>/worktrees/<name>"
    common = Path(gate.split("gitdir:", 1)[1].strip()).parent.parent  # <repo>/.git
    script = (common.parent / "scripts" / "machine_gate.sh").as_posix()
    cmd = [
        BASH, script, "light", SESSION, "env", "PYTHONUTF8=1", f"PYTHONPATH={tree.as_posix()}", PY,
        "-m", "pytest", "-q", "--tb=no", "-p", "no:cacheprovider", "-rf", f"{R}/tests",
    ]  # fmt: skip
    proc = subprocess.run(
        cmd, cwd=tree, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600
    )  # nosec B603 B607
    out = proc.stdout + proc.stderr
    failed = re.findall(r"^FAILED\s+\S*?::(\S+?)(?:\s+-|$)", out, flags=re.M)
    m = re.search(r"(\d+) passed", out)
    passed = int(m.group(1)) if m else 0
    return passed, sorted(set(failed)), out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tree", type=Path)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    tree = args.tree.resolve()
    only = {s for s in args.only.split(",") if s}
    rows = ["| # | применилась | passed | failed | упавшие |", "|---|---|---|---|---|"]
    if not args.check:
        passed, failed, out = run_tests(tree)
        rows.append(f"| база | - | {passed} | {len(failed)} | {', '.join(failed) or '-'} |")
        if failed or passed == 0:
            print(out[-2000:])
            print("БАЗА НЕ ЗЕЛЁНАЯ - стоп")
            return 2
    for name, rel, old, new in MUTATIONS:
        if only and name not in only:
            continue
        path = tree / rel
        raw = path.read_bytes().decode("utf-8")
        crlf = "\r\n" in raw
        o, n = fit(old, crlf), fit(new, crlf)
        count = raw.count(o)
        if args.check or count != 1:
            rows.append(
                f"| {name} | {'якорь найден 1 раз' if count == 1 else f'НЕ ПРИМЕНИЛАСЬ (якорь {count} раз)'} | - | - | - |"
            )
            continue
        path.write_bytes(raw.replace(o, n, 1).encode("utf-8"))
        try:
            passed, failed, _ = run_tests(tree)
        finally:
            subprocess.run(["git", "checkout", "--", rel], cwd=tree, check=True)  # nosec B603 B607
        rows.append(f"| {name} | да | {passed} | {len(failed)} | {', '.join(failed) or '-'} |")
    status = subprocess.run(["git", "status", "--short"], cwd=tree, capture_output=True, text=True).stdout.strip()  # nosec B603 B607
    rows.append(f"\ngit status --short после матрицы: {status or 'пусто'}")
    table = "\n".join(rows)
    print(table)
    if args.out:
        args.out.write_text(table + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
