Запусти прототип инспекции бутылок.

Выполни из корня репозитория:

```bash
python Inspector_prototype/multiprocess_prototype/main.py
```

Если нужно активировать venv (Git Bash):
```bash
source venv/Scripts/activate
python Inspector_prototype/multiprocess_prototype/main.py
```

При ошибке запуска — покажи трейсбэк и проверь:
1. Активирован ли venv
2. Доступна ли камера (если ошибка OpenCV)
3. Запущены ли зависимые сервисы (Qdrant, если используется)
