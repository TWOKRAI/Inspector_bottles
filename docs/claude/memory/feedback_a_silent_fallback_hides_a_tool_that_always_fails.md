---
name: feedback_a_silent_fallback_hides_a_tool_that_always_fails
description: "Молчаливый откат прятал, что системный tar на Windows падал всегда: tar без -f - читает ленту, GNU tar не берёт C:\\ в -C — откат логировать, tar звать как -x -f - с cwd (a silent fallback hid a tool that always failed)"
module: ["scripts/atlas"]
mechanism: [windows-env, error-handling, performance]
metadata:
  type: feedback
---

`codemap.checkout` распаковывал `git archive` через `[tar, "-x", "-C", dir]`, при ненулевом коде — молча
через `tarfile`. На Windows эта форма не работала НИ РАЗУ: bsdtar из System32 без `-f -` открывает ленту
`\\.\tape0` (rc 1), GNU tar из Git не принимает `C:\…` в `-C` (rc 2 «Cannot open»). Откат скрывал это
месяцами: распаковка 3,98 с в `tarfile.extractall` вместо ~1 с (cProfile холодного `card`, Task 1.6g,
2026-10-11). Рабочая форма для обоих — `[tar, "-x", "-f", "-"]` с `cwd=<каталог>` (зонд: rc 0 у обоих).

**Why:** откат без следа превращает «инструмент сломан всегда» в «медленнее, чем могло бы», и это никто
не видит — тесты зелёные, вывод верный.

**How to apply:**
- Любой откат на запасной путь печатает строку в stderr (`atlas: tar failed (rc=<n>), fallback to tarfile`);
  тест держит обе стороны: рабочий путь без отката (запасной путь подменён на исключение) и откат со строкой.
- `tar` на Windows: только `-x -f -` и `cwd`, путь к бинарю — полный из `shutil.which` (голое имя `"tar"`
  берёт System32 `tar.exe` и обходит поддельный `tar.bat` в PATH теста).
- Без `LongPathsEnabled` GNU tar распаковывает за 259 знаков, но чтение даёт `FileNotFoundError` —
  меряй итоговый путь до распаковки (ADR-ATL-003, дополнение 1.6g).

Связано: [[feedback_a_hook_dead_on_windows_by_a_trailing_cr]] (тот же класс: на Windows молча не работает).
