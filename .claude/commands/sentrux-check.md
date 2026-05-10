---
description: CI-friendly проверка правил архитектуры (sentrux check, exit 0/1)
---

Запусти CLI-валидатор `sentrux check` — он подходит для CI и pre-commit, выходит с кодом 0 (всё ок) или 1 (есть нарушения).

```bash
sentrux check /Users/twokrai/Project_code/Inspector_bottles
```

(Замени путь на абсолютный путь к корню текущего проекта.)

Покажи пользователю:
- Итоговый exit code и `Quality: NNNN`.
- Список упавших правил (если есть) с файлами-нарушителями.
- Рекомендацию: запустить `/sentrux-rules` для интерактивного разбора, либо поправить точечно.

Если `.sentrux/rules.toml` отсутствует — сообщи и покажи минимальный шаблон (см. `/sentrux-rules`).

$ARGUMENTS
