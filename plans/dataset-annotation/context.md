# Контекст плана dataset-annotation: факты по коду и соседи

Часть плана [`plan.md`](plan.md).

## Что есть сегодня (сверено командами 2026-09-26)

| Что | Факт | Команда |
|---|---|---|
| `Services/dataset_gen` | синтетика cut-and-paste, задача «класс + угол», **боксов нет**; 2761 строк без тестов | `find Services/dataset_gen -name '*.py' -not -path '*/tests/*' \| xargs wc -l` |
| `Services/ml_train` | обучение **классификаторов** (torchvision/timm), источники `synthetic`/`exported`/`folder`; 2123 строк | то же; `grep -n folder Services/ml_train/data.py` |
| `Services/ml_inference` | инференс классификации (ONNX Runtime); `TaskType = Literal["classification","detection"]` — детекция объявлена, постобработки нет; 1605 строк | `grep -rn detection Services/ml_inference` → одна строка `model_spec.py:17` |
| Ultralytics | **нет в `pyproject.toml` и нет в `.venv`**; корневой `CLAUDE.md` («Ultralytics YOLO … extras `[ml]`») и `constructor-layers.md:155` («уже в стеке») расходятся с кодом | `grep -n -i ultralytics pyproject.toml` → только комментарий pyright; `.venv/bin/python -c "import ultralytics"` → `ModuleNotFoundError` |
| Кадры брака | **нигде не хранятся.** `inspection_full`: `storage` → `DatabasePlugin` → таблица `detections` (timestamp, frame_id, event_type, data), без картинки; `inspection_result` = `{action, defect_count, total_*, reject_rate}`, без кадра и боксов | `Plugins/io/database/schemas.py:27-46`, `Plugins/control/robot_control/plugin.py:186-192` |
| Сохранение кадров | `frame_saver` пишет поток на диск бэкенда (`data/captures`, по датам), связи с вердиктом нет | `Plugins/io/frame_saver/plugin.py:1-20`, `recipes/color_inspect.yaml:113-130` |
| GUI «Нейронные сети» | 5 файлов, 1718 строк; обучение запускает сам GUI (`QProcess`, конфиг через `QFileDialog`, `RunRegistry` в процессе GUI) — `ml_train_section.py:3-7` | `wc -l …/neural/*.py` |
| `backend_ctl record_*` | пишет ленту **событий** драйвера в JSONL, не кадры — источником снимков не годится | `backend_ctl/recorder.py:1-25` |
| Сокет | входящая строка сервера ≤ 1 048 576 Б, клиента ≤ 16 777 216 Б; JSON-строки | `socket_channel.py:75`, `socket_client.py:184` |
| Крупные грузы по pipe | известный дефект L-6: 0.3–1.2 МБ через pipe 64 КБ | [`transport-single-policy.md`](../transport-single-policy.md) Ф4 |
| Хранение | вердикт: embedded-first, SQLite через `Services/sql` + файлы; `insert_many` построчный, неатомарный | [`storage-stack-embedded-first.md`](../storage-stack-embedded-first.md), [`2026-06-05_sql-insert-many-atomic.md`](../2026-06-05_sql-insert-many-atomic.md) |
| Всегда живой процесс-хозяин команд | образец — `base.yaml`: процесс `devices` с `DeviceHubPlugin`; сам `dataset` — подключаемый фрагмент (`observability_sink.yaml`), не `base.yaml` (`base.yaml:31-36`) | `multiprocess_prototype/backend/topology/base.yaml` |
| HTTP-сервер в плагине | прецедент: `Plugins/sim/mjpeg_sink` на stdlib `http.server` | `Plugins/sim/mjpeg_sink/plugin.py:72` |

## Зависимости

| Сосед | Что нужно этому плану | Какие задачи ждут | Что может начаться раньше |
|---|---|---|---|
| [`plans/gui-constructor/`](../gui-constructor/) (пишется параллельно) | Ф1 даёт контекст виджета на подключение (поле `ctx.connection: str`, каналы на `ctx`; `design-connection-context.md` §3); **канал файлов в контракте резервирует он, реализует этот план** (Task 2.1) | только 2.5b | всё остальное: Ф1, 2.1–2.5a, Ф3, Ф4 |
| [`2026-09-22_gui-service`](../2026-09-22_gui-service/plan.md) | Ф2 (сеть: токен 2.2, поток кадров 2.1) — для разметки с другой машины | разметка по сети (вне объёма) | всё: на одной машине (встроенный GUI или `apps/gui_client` на localhost) работает целиком |
| gui-service 1b.2c | вердикт бэкенда на правку поля доходит до формы | ничего напрямую: ошибки команд датасета виджеты показывают сами | — |
| [`transport-single-policy`](../transport-single-policy.md) Ф4 (L-6) | не нужен — картинки идут HTTP, не pipe; ответы команд ограничены по размеру (Task 1.2, литерал) | — | — |
| [`storage-stack-embedded-first`](../storage-stack-embedded-first.md) / [`sql-insert-many-atomic`](../2026-06-05_sql-insert-many-atomic.md) | `Services/sql`; **`insert_many` не использовать** (построчный коммит) — массовые вставки через `adapter.connection()` одной транзакцией | 1.1, 1.4 | — |
| [`dataset-circle-capture`](../dataset-circle-capture.md) | готовый рецепт захвата кругов (`center_crop`, `frame_saver` в `data/dataset/circles`) — источник для импорта папки (1.4), в будущем — `dataset_capture` вместо `frame_saver` | — | — |
| ревью CTO условие 3 | правило `Services/* ↛ PySide6` кроме `*/gui/*` | владелец — gui-constructor Task 1.0 (контракт-тест); 2.1 от неё зависит | — |

