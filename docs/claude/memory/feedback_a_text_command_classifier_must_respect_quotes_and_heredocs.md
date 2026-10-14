---
name: feedback-a-text-command-classifier-must-respect-quotes-and-heredocs
description: "Хук, блокирующий команды по тексту (classify в machine_gate.sh), с наивной резкой по ; | && блокировал бы grep -E \"a|pytest\", commit -m \"x; pytest\" и heredoc с pytest у всех сессий — резать только вне кавычек и тел heredoc, а до включения блокирующего хука прогнать его по журналам недели; ложный блок важнее ложного пропуска"
module: [scripts]
mechanism: [hooks, windows-env, dev-tooling]
metadata:
  node_type: memory
  type: feedback
---

Первая редакция `machine_gate.sh classify` резала строку `sed` по `&&`, `||`, `;`, `|`, переводу строки. Слепой tester,
developer и 102 зелёных теста этого не заметили: все таблицы спеки были про «тестовая команда → класс». Ревью
кода прогнало новый хук по журналам сессий за неделю (10 630 Bash-команд, 1 516 со словом-кандидатом): ложные блоки
`grep -n -E "cwd|pytest|subprocess" scripts/run_framework_tests.py`, `git commit -m "fix; pytest -q"`, heredoc с
`pytest -q` в теле — около 10–12 в неделю на все сессии. Хук блокирующий и общий: каждый такой блок мешал бы всем полосам.
После исправления (один `awk` с состоянием кавычек и heredoc) на той же выборке — 0 ложных блоков, 360 настоящих.

**Why:** границу «слово в аргументе или в тексте / команда» текстовым резаком не проведёшь без состояния кавычек и
heredoc; а тесты на «что блокируем» не видят то, что блокировать нельзя. Заодно: `python` → `Git/bin/bash.exe` на
Windows обрезает argv около 8 КБ (классификатор вернул пусто на 8 200 байт), `bash` → `bash` и stdin хука — нет;
длинный текст команды передавать через stdin или файл.

**How to apply:** блокирующему хуку по тексту команды — N-строки в спеке (grep с альтернацией, `commit -m` с `;`,
heredoc, кавычки) и прогон по журналам недели ДО регистрации в `settings.json`; число ложных блоков — в отчёт.
Связано: [[feedback_a_hook_dead_on_windows_by_a_trailing_cr]], [[feedback-bash-from-python-is-wsl-on-windows]].
