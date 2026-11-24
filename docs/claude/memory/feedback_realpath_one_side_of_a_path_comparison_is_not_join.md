---
name: feedback-realpath-one-side-of-a-path-comparison-is-not-join
description: "Сравнение путей: одна сторона realpath, другая join с `/` не равны на Windows (разделители, регистр, 8.3); приводить обе стороны одной цепочкой normcase(normpath(realpath())) (path compare, alpha_sim)"
module: [scripts]
mechanism: [windows-env, test-infra]
metadata:
  type: feedback
---

**Замер 2026-11-23, полоса Т, `scripts/alpha_sim/run_alpha.py`.** Раннер сравнивал `realpath(path)` с
`join(self.tree, script)`: на Windows `C:\a\b.py` против `C:/a/b.py` и разный регистр диска → «скрипт не из дерева».
Правка: `want_path = normcase(normpath(join(tree, script)))` до цикла, слева `normcase(normpath(realpath(path)))`.
Тест подставляет `path.as_posix()` и проверяет это.

**Why:** обе стороны должны пройти одну и ту же нормализацию, иначе равенство зависит от способа записи пути.

**How to apply:** сравнение путей — обе стороны через одну цепочку; пути в командной строке для `shlex.split` отдавать
`as_posix()`, иначе обратная косая съедается. Связано: [[feedback_windows_realpath_returns_extended_prefix_during_concurrent_mkdir]].
