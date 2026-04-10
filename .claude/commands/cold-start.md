Выполни холодный старт всех сервисов для работы с проектом Inspector_bottles.

## Шаги

### 1. Запусти Qdrant (векторная БД для qex)
```bash
docker start qdrant
```
Проверь: `docker ps | grep qdrant` — должен быть `Up`.

### 2. Запусти Ollama (эмбеддинги для qex)
```bash
ollama serve
```
Запускай в отдельном терминале или фоном. Проверь: `ollama list` — должна быть модель `qwen3-embedding:4b`.

### 3. Активируй venv
```bash
source venv/Scripts/activate   # Git Bash (Windows)
# или
uv sync
```

### 4. Проверь qex-индекс
Вызови `/qex-status` — если индекс пустой, запусти `/qex-reindex`.

## Быстрая проверка готовности
```bash
docker ps | grep qdrant    # qdrant Up
ollama list                 # qwen3-embedding:4b присутствует
python -c "import PyQt5"    # venv активен
```
