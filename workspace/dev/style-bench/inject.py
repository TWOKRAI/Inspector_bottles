"""UserPromptSubmit-хук стенда: добавляет напоминание о стиле в контекст хода.

Каждое срабатывание пишет строку в hook_fired.log — run.py по нему доказывает,
что хук действительно сработал в прогоне варианта B.
"""

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    # Имя файла напоминания — аргумент (свой на вариант); по умолчанию вариант B.
    name = sys.argv[1] if len(sys.argv) > 1 else "reminder.md"
    reminder = (HERE / name).read_text(encoding="utf-8").strip()
    with (HERE / "hook_fired.log").open("a", encoding="utf-8") as log:
        log.write(f"{time.time():.3f}\n")
    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": reminder,
        }
    }
    sys.stdout.write(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
