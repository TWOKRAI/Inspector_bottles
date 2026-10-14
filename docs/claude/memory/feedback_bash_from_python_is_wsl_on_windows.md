---
name: feedback-bash-from-python-is-wsl-on-windows
description: "subprocess.run(['bash', ...]) из Python на Windows запускает WSL-заглушку System32\\bash.exe, а не Git Bash — гейт машины и любой .sh из скрипта матрицы падают кодом 1 без прогона; звать C:/Program Files/Git/bin/bash.exe"
module: [scripts]
mechanism: [windows-env, dev-tooling, break-injection]
metadata:
  node_type: memory
  type: feedback
  modified: 2026-10-13
---

Ловушка: в Git Bash `bash` — это Git Bash, но процесс Python ищет `bash` по PATH Windows и находит
`C:\Windows\System32\bash.exe` (WSL). Без установленного дистрибутива он падает сразу.

Замер (T3.5b, 2026-10-13): скрипт матрицы звал `machine_gate.sh` через `subprocess.run(["bash", GATE, ...])` →
все 13 прогонов `code 1`, вывод `WSL (10 - Relay) ERROR: CreateProcessCommon:875: execvpe(/bin/bash) failed`,
тестов 0. Строки `MATCH` у «ожидаемо выживших» инъекций при этом выглядели как успех: пустой список падений
совпал с пустым прогнозом. С `"C:/Program Files/Git/bin/bash.exe"` тот же вызов → `0 gate-ok`, матрица прошла.

Вторая ловушка того же скрипта: `dict(**os.environ, PYTHONUTF8="1")` → `TypeError`, если переменная уже есть
в окружении; писать `dict(os.environ, PYTHONUTF8="1")`.

**Why:** сбой запуска маскируется под результат: у пустого прогноза «совпадение» при нуле прогонов
(см. [[feedback_injection_zero_may_mean_the_guards_were_not_collected]]).

**How to apply:** скрипт, который из Python зовёт `.sh` (гейт, стенд), — полный путь к Git Bash; база матрицы
обязана дать код 0 и число passed, иначе стоп до первой инъекции. Связано: [[feedback_zero_observations_looks_like_a_result]].
