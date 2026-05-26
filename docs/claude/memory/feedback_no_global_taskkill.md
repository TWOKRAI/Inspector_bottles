---
name: feedback-no-global-taskkill
description: Запрещено убивать процессы по имени образа (taskkill /IM python.exe, pkill python) — это убьёт сторонние процессы на машине. Только TaskStop или kill по конкретному PID.
metadata:
  type: feedback
---

Не используй массовые kill-команды по имени образа: `taskkill /F /IM python.exe`, `taskkill /F /IM node.exe`, `pkill python`, `killall python`, `pkill -f run.py` (последний по pattern — тоже зло, может схватить чужое).

**Why:** user работает на shared dev-машине с другими процессами Python (другие агенты, тестовые runner'ы, GUI прот пользователя, IDE-плагины с встроенным venv). Massacre по имени образа убьёт всё подряд. Зафиксировано 2026-05-26: reviewer Phase 5 убил `python.exe` после smoke прота — security warning от harness.

**How to apply:**
1. Если запустил процесс через **Bash `run_in_background=true`** — останавливай через **`TaskStop` с task_id**, который вернул `Bash`. Это убивает только конкретный спавн.
2. Если процесс запустил пользователь / другой агент — **не трогай**. Если нужно — спроси.
3. Если знаешь PID — `taskkill /F /PID <pid>` или `kill <pid>` допустимы.
4. **Никогда** — `/IM`, `/F /IM`, `pkill <name>`, `killall <name>`, `pkill -f <pattern>` без явного разрешения пользователя.
5. На Windows для собственного Bash-launched процесса: TaskStop в первую очередь; если не помогает (редко) — задай PID через `Get-Process | Where-Object {...}` и kill по pid.

Связано: skill `verify` (запуск прота для проверки) — даже там завершение через TaskStop, не taskkill.
