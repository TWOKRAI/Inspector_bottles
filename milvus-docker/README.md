# Milvus standalone (локально для claude-context)

Образ: **Milvus v2.5.6** + **etcd v3.5.18** (официальный `milvus-standalone-docker-compose.yml` из релиза).

Имеет смысл совмещать с **@zilliz/milvus2-sdk-node ~2.5.x** в claude-context; сервер **2.4.x** с hybrid BM25/sparse часто даёт `sparse_vector` / load errors.

## Старт / стоп

```powershell
Set-Location milvus-docker
docker compose pull
docker compose up -d
docker compose down
```

Порты: **19530** (gRPC), **9091** (метрики/health), MinIO **9000** / **9001**.

## Холодный старт после перезагрузки ПК

Полный порядок, если выключали компьютер и нужно снова поднять цепочку **Docker → Milvus → Ollama → MCP claude-context** (Windows, PowerShell). Пути ниже замените на свой корень репозитория, если он другой.

1. **Docker Desktop** — запустить, дождаться готовности движка (без Milvus MCP не удержит `localhost:19530`).
2. **Ollama** — запустить приложение (сервис в трее). Проверка моделей:
   ```powershell
   ollama list
   ```
   Для MCP нужна модель эмбеддингов (например `bge-m3` или `nomic-embed-text`) — имя должно совпадать с `EMBEDDING_MODEL` / `OLLAMA_MODEL` в настройках MCP.
3. **Milvus (этот compose)** — из каталога `milvus-docker`:
   ```powershell
   Set-Location C:\Users\INNOTECH\Desktop\PROJECT_INNOTECH\Inspector_bottles\milvus-docker
   docker compose up -d
   ```
   При первом запуске после обновления образа можно сначала `docker compose pull`.
4. **Проверка, что standalone жив** — в `docker compose ps` / `docker ps` должен быть **`milvus-standalone`** со статусом **Up** и **healthy**; на хосте слушаются **19530** и **9091**:
   ```powershell
   docker ps -a --filter "name=milvus-standalone" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
   Invoke-WebRequest -Uri http://localhost:9091/healthz -UseBasicParsing
   ```
   Ожидается **StatusCode 200**, содержимое **OK**. Если контейнер **Exited** — `docker logs milvus-standalone`; при ошибке вроде `librdkafka.so.1: file too short` перекачать образ (см. раздел про **input/output error** ниже): `docker compose down`, `docker rmi milvusdb/milvus:v2.5.6`, `docker compose pull standalone`, `docker compose up -d`.
5. **Cursor — MCP claude-context** — перезапустить сервер MCP (или **Reload Window**), чтобы он подключился к Milvus уже после пункта 4.
6. **Индексация** — при необходимости снова вызвать **`index_codebase`** с **абсолютным** путём к репозиторию; после сброса коллекций или смены модели эмбеддингов — с **`force: true`**.
7. **Убедиться, что всё готово** — инструмент **`get_indexing_status`** (статус `completed`, ненулевые файлы/чанки); пробный **`search_code`** по смысловому запросу по тому же пути.

Предупреждение Compose про сеть `milvus exists but was not created for project "milvus-docker"` обычно **не мешает**. Если мешает — настроить сеть как `external: true` в `docker-compose.yml` или удалить неиспользуемую сеть `milvus`, когда к ней не подключены контейнеры.

## Переход с Milvus 2.4 → 2.5 (обязательно)

Метаданные etcd несовместимы между мажорными линиями:

1. `docker compose down`
2. Удалить каталог **`milvus-docker/volumes/`** целиком
3. `docker compose pull` и `docker compose up -d`

## Сброс только коллекций (без смены версии Milvus)

```powershell
.\venv\Scripts\python.exe milvus-docker\drop_hybrid_collections.py
```

`--list-only` — только список имён.

После дропа: перезапуск MCP **claude-context** и `index_codebase` с `force: true`.

## Docker: `input/output error` при `compose up` / pull blob

Сбой **Docker Desktop** или диска (место, WSL2/vhdx, битый layer cache).

1. Перезапустить Docker Desktop (или ПК).
2. Проверить свободное место на диске с данными Docker.
3. При необходимости: **Troubleshoot → Clean / Purge** в Docker Desktop или `docker system prune -a` (удалит неиспользуемые образы).
4. Снова: `docker compose pull` и `docker compose up -d` в `milvus-docker`.
