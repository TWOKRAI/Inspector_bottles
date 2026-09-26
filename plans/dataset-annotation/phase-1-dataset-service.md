# Phase 1 — Сервис датасета на бэкенде (без GUI)

Часть плана [`plan.md`](plan.md). Цель фазы: датасет существует и управляется **только командами бэкенда** — через
`backend_ctl send_command` уже можно импортировать снимки, разметить, выгрузить YOLO. GUI в фазе нет; стенд не нужен
(unit + `BackendHarness`, `backend_ctl/harness.py:313`).

**Канон каждой задачи фазы:** `tester` до кода в git worktree на пред-коммите, получает только Acceptance этой задачи
(запрещены: `Services/dataset/**` кроме уже слитого предыдущими задачами, дифф, тесты автора) → исполнитель →
break-injection у лида по списку «Инъекции» с предсказанием до прогона → `reviewer` синхронно
(`run_in_background: false`), находки с «вход → наблюдаемый выход». Исполнителю: не коммитить и не пушить без слова
лида; третья неудачная итерация — `ESCALATION -> teamlead` (глубина вложенности агентов до 3, эскалация поднимается
наверх, а не тратится внизу).

## Модель данных (общая для фазы, фиксируется в `Services/dataset/README.md` Task 1.1)

```
data/datasets/<name>/            # <name> ~ ^[a-z0-9_-]{1,40}$, корень — регистр root_dir процесса dataset
  dataset.db                     # SQLite, WAL: images, labels, classes, sources, jobs
  images/ab/<sha256>.<ext>       # по хешу содержимого, НЕИЗМЕНЯЕМЫ после записи (tmp + os.replace)
  thumbs/ab/<sha256>.jpg         # кэш миниатюр, пересобирается (Task 1.3)
  exports/<name>-<N>/            # снимки экспорта (Task 1.1 минимум, Task 4.4 полностью)
```

- `images`: `id` = sha256 байтов файла (hex, 64 символа), `ext`, `width`, `height`, `bytes`, `added_at`.
- `sources`: (`image_id`, `kind` ∈ `import|capture|reject|synthetic|archive`, `ref` — путь/узел/рецепт, `session`,
  `meta_json`). Один снимок может прийти из нескольких источников — строка на каждый.
- `labels`: одна строка на снимок: `image_id`, `rev` (int, ≥ 0), `status` ∈ `unlabeled|labeled|verified|skipped`,
  `image_class_id` (NULL), `boxes_json` — список `{cls, cx, cy, w, h}` в долях [0, 1] (формат YOLO), `updated_at`,
  `updated_by`. «Размечено, объектов нет» = `status=labeled` и пустой список — отличается от `unlabeled`.
- `classes`: `id` (стабильный, не переиспользуется), `name` (уникален в области), `scope` ∈ `box|image`, `color`,
  `hotkey` (1–9 или NULL), `archived`.
- Ревизия непрозрачна для клиента: сравнение на равенство. Ответы — плоские dict, ошибки — `{"success": False,
  "error": <код>, …}`, не исключения.
- Массовые вставки — `adapter.connection()` одной транзакцией. **`BaseRepository.insert_many` не использовать**
  (`Services/sql/core/base_repository.py:80-94` — построчный коммит, план `2026-06-05_sql-insert-many-atomic` не
  выполнен).

---

### Task 1.1 — [VERTICAL SLICE] `DatasetStore` + процесс `dataset` + четыре команды сквозь `backend_ctl`

**Level:** Senior+ · **Assignee:** teamlead · **Module contract:** new-full (`Services/dataset`) · **Layer:** services + prototype
**Handoff:** `developer`(INTERFACE: README + `interfaces.py`) → `tester`(RED) → `teamlead`(GREEN) → `reviewer`

**Goal:** тонкий срез через все слои бэкенда: хранилище → плагин-хозяин команд → процесс в дереве → `backend_ctl`.
Демонстрация: `send_command(dataset, dataset_add_path)` трёх картинок → `dataset_list` → `dataset_save_labels`
одной → `dataset_export_yolo` → на диске YOLO-раскладка, которую читает независимый парсер теста.

**DESIGN:**
- `Services/dataset/` — Qt-free корень: `store.py` (`DatasetStore`: `open(root, name)`, `add_file(path, source)`,
  `list(offset, limit)`, `get(image_id)`, `save_labels(image_id, base_rev, labels, by)`), `schema.py` (схемы
  `SchemaBase` для `Services/sql`), `export_yolo.py` (минимум: всё в `train`, только рамки), `interfaces.py`
  (`IDatasetStore` Protocol), `__init__.py` (реэкспорт, **без импорта `plugin/` и `gui/`**).
- `Services/dataset/plugin/plugin.py` — `DatasetPlugin(ProcessModulePlugin)`, `commands = {"dataset_add_path": …,
  "dataset_list": …, "dataset_get": …, "dataset_save_labels": …, "dataset_export_yolo": …}` по образцу
  `Plugins/hub/device_hub/plugin.py:86-100`; `SQLManager` создаётся в `start()` (после fork, `fork_safe`, как
  `Plugins/io/database/README.md` «Хранилище»); регистры: `root_dir` (дефолт `data/datasets`), `default_dataset`
  (`default`).
- `multiprocess_prototype/backend/topology/base.yaml` — процесс `dataset`, `protected: true`, по образцу `devices`.
- Compare-and-swap: `UPDATE labels SET … , rev = rev + 1 WHERE image_id = :id AND rev = :base_rev`; rowcount 0 →
  `{"success": False, "error": "conflict", "rev": <текущая>}`. Для нового снимка строка `labels` создаётся с
  `rev=0, status=unlabeled` в той же транзакции, что `images`.
- `dataset_add_path(path)` в 1.1 — **один файл или плоская папка, синхронно, ≤ 200 файлов** (иначе
  `{"error": "too_many_use_import"}`); путь обязан лежать под одним из `import_roots` (регистр, дефолт
  `["data"]`), иначе `path_not_allowed`. Долгий импорт — Task 1.4.
- Не трогать: `frontend/**`, хаб (`orchestrator_hooks.py`), `Services/sql/**`.

**FILES (≤ 6 писателю):** 1) `Services/dataset/store.py` 2) `Services/dataset/schema.py` 3) `Services/dataset/export_yolo.py`
4) `Services/dataset/plugin/plugin.py` (+ `registers.py`) 5) `multiprocess_prototype/backend/topology/base.yaml`
6) `Services/dataset/{README,STATUS,DECISIONS}.md` + `interfaces.py`. Тесты — `Services/dataset/tests/`. Снапшоты
`multiprocess_prototype/backend/tests/snapshots/*.build.json` (2 файла) обновляются регенерацией, не руками.

**Acceptance criteria:**
- [ ] `BackendHarness` на рецепте из `recipes/` + `base.yaml`: `send_command("dataset", "dataset_add_path",
      {"path": <tmp с 3 PNG>})` → `{"success": True, "added": 3, "duplicates": 0}`; повтор той же команды →
      `{"added": 0, "duplicates": 3}`; файлов в `images/` — ровно 3 (`find … -type f | wc -l` = 3).
- [ ] `dataset_list {"offset": 0, "limit": 50}` → `total == 3`, у каждого `id` из 64 hex, `status == "unlabeled"`,
      `rev == 0`.
- [ ] `dataset_save_labels {"image_id": X, "base_rev": 0, "boxes": [{"cls": 0, "cx": 0.5, "cy": 0.5, "w": 0.2,
      "h": 0.1}], "status": "labeled"}` → `{"success": True, "rev": 1}`; повтор с `base_rev: 0` →
      `{"success": False, "error": "conflict", "rev": 1}`, строка в БД не изменилась (сравнение `boxes_json` до/после).
- [ ] Рамка вне [0, 1] или `w <= 0` → `{"success": False, "error": "invalid_labels", "errors": [{"path":
      "boxes[0].w", …}]}`, `rev` не изменился.
- [ ] `dataset_export_yolo` → `exports/default-1/data.yaml` с ключами `path`, `train`, `names`; для X файл
      `labels/train/<X>.txt` ровно с одной строкой `0 0.500000 0.500000 0.200000 0.100000`; для двух
      неразмеченных — `.txt` **нет** (unlabeled не экспортируется как негатив); повторный экспорт → `default-2`.
- [ ] `path` вне `import_roots` (литерал `"/etc"`) → `path_not_allowed`, в `images/` ничего не появилось.
- [ ] `grep -rlE "^\s*(from|import)\s+(PySide6|multiprocess_prototype)" Services/dataset --include='*.py'` → пусто;
      `sentrux check .` зелёный (CLI, не MCP).
- [ ] Ответ `dataset_list {"limit": 50}` при 50 снимках — `len(pickle.dumps(reply)) < 16384` (литерал; ответы идут
      через pipe процесса, L-6).

**Hazard-тесты автора (обязательны):** два `save_labels` с одним `base_rev` из двух потоков — ровно один `success`;
падение между записью файла и вставкой строки не оставляет строки без файла (файл пишется первым, `tmp` +
`os.replace`, строка — после; обратный порядок — дефект); `add_file` одного и того же содержимого из двух потоков —
одна строка `images`, две `sources`.

**Инъекции (лид, предсказание до прогона):**
| Сломать | Должны упасть |
|---|---|
| убрать `AND rev = :base_rev` | тест конфликта (tester) + hazard двух потоков (автор) |
| проверка `import_roots` → `return True` | тест `/etc` |
| экспорт пишет `.txt` и для `unlabeled` | тест «для неразмеченных `.txt` нет» |
| порядок: строка, потом файл | hazard «строка без файла» |
| `id` = sha256 имени файла вместо содержимого | тест дубликатов (переименованная копия) |

**Out of scope:** классы (1.2) — в 1.1 `cls` принимается как есть, `names` в `data.yaml` = `["class_0", …]` по
максимальному `cls`; миниатюры и HTTP (1.3); долгий импорт (1.4); сплит (4.3).
**Dependencies:** нет.

---

### Task 1.2 — Классы, статусы, класс снимка, фильтры и страницы

**Level:** Middle+ · **Assignee:** developer · **Module contract:** public-api-change · **Layer:** services
**Handoff:** `tester`(RED) → `developer`(GREEN) → `reviewer`

**Goal:** словарь классов с устойчивыми id и полная модель статусов, на которой стоят браузер (2.3), холст (2.4),
статистика (4.1) и экспорт (4.4).

**DESIGN:**
- Команды: `dataset_classes` (список), `dataset_class_upsert {id?, name, scope, color, hotkey}`,
  `dataset_class_archive {id, reassign_to?}`. Удаления нет — только архив; архив используемого класса без
  `reassign_to` → `class_in_use` с числом снимков. `reassign_to` переписывает `boxes_json`/`image_class_id` одной
  транзакцией и повышает `rev` каждого затронутого снимка (иначе открытый редактор молча затрёт переназначение).
- `hotkey` уникален среди неархивных в области; конфликт → `hotkey_taken`.
- `dataset_save_labels` принимает `image_class_id` и `status`; `cls` рамки обязан быть неархивным классом области
  `box`, `image_class_id` — области `image`.
- `dataset_list {offset, limit ≤ 200, filter: {status?, class_id?, source_kind?, has_boxes?}, order: added|updated}`
  → `{total, items: [{id, status, rev, image_class_id, n_boxes, source_kinds, width, height}]}`; рамки в списке не
  отдаются — только в `dataset_get`.

**FILES:** 1) `Services/dataset/store.py` 2) `Services/dataset/schema.py` 3) `Services/dataset/classes.py` (новый)
4) `Services/dataset/plugin/plugin.py` 5) `Services/dataset/README.md` 6) `Services/dataset/export_yolo.py` (`names`
из классов, индекс = порядок неархивных `box`-классов по `id`, карта `id → индекс` в `data.yaml` комментарием и в
`manifest` 4.4).

**Acceptance criteria:**
- [ ] Создать `scratch`(box, hotkey 1), `chip`(box, hotkey 2), `ok`(image), `defect`(image); повторный `name` в той
      же области → `name_taken`; `hotkey 1` второму box-классу → `hotkey_taken`.
- [ ] Рамка с `cls = <id ok>` → `invalid_labels` (`boxes[0].cls: class scope is image`).
- [ ] Архив `scratch` при 2 снимках с ним без `reassign_to` → `{"error": "class_in_use", "images": 2}`; с
      `reassign_to = chip` → у обоих снимков `cls` = chip, `rev` каждого вырос на 1.
- [ ] 250 снимков: `dataset_list {"limit": 500}` → `invalid_args` (потолок 200); `{"limit": 200}` → 200 элементов и
      `total == 250`; фильтр `{"status": "unlabeled"}` после разметки 10 → `total == 240`.
- [ ] `len(pickle.dumps(dataset_list(limit=200)))` < 49152 (литерал, ниже 64 КБ pipe).
- [ ] Экспорт после архива `scratch`: `names` без `scratch`, индексы сплошные с 0.

**Инъекции:** `reassign_to` без повышения `rev` → тест «rev вырос» падает; снять потолок 200 → тест `invalid_args`;
пропустить проверку области класса → тест `class scope`.

**Out of scope:** цвета/порядок в GUI (2.3/2.4); статистика (4.1).
**Dependencies:** 1.1.

---

### Task 1.3 — Канал «файлы по id»: сервер в процессе `dataset`

**Level:** Senior · **Assignee:** teamlead · **Module contract:** new-lite (`Services/dataset/files_server.py`) · **Layer:** services
**Handoff:** `tester`(RED) → `teamlead`(GREEN) → `reviewer` в режиме **security** (обязательно)

**Goal:** картинка и её миниатюра доходят до клиента, минуя pipe и сокет управления, с тем же поведением на одной
машине и (позже) по сети.

**DESIGN:**
- stdlib `http.server.ThreadingHTTPServer` в потоке-демоне плагина (прецедент `Plugins/sim/mjpeg_sink/plugin.py:72`,
  там же разобрана ловушка пробного bind). Только `GET`.
- URL: `GET /files/dataset/<name>/<id>/<variant>`, `variant ∈ {thumb, full}`. `name` — `^[a-z0-9_-]{1,40}$`, `id` —
  `^[0-9a-f]{64}$`; путь к файлу строится **только** из проверенных `name`/`id` через БД (`images.ext`), строка URL в
  путь не попадает. Всё прочее → 404 без тела с путём.
- `thumb`: JPEG q80, длинная сторона 256 px, создаётся при первом запросе в `thumbs/` (tmp + `os.replace`), дальше
  отдаётся с диска; `full` — исходные байты. `Content-Type` по расширению, `Content-Length`, `Cache-Control:
  max-age=31536000, immutable` (id = хеш содержимого).
- Регистры: `files_bind` (дефолт `127.0.0.1`), `files_port` (дефолт `0` — эфемерный). Фактический адрес публикуется
  в состоянии `dataset.files.endpoint = {"host", "port", "scheme": "http"}` (как `devices.state.*` у `device_hub`).
- **Fail-closed:** `files_bind` не loopback → сервер **не стартует**, в состоянии `dataset.files.error =
  "non_loopback_requires_token"`, громкая строка лога. Токен — вместе с gui-service 2.2 (тот же PSK), не здесь.
- Кнопка остановки процесса закрывает сервер (`shutdown()` + `server_close()` в `stop()`), порт освобождается.

**FILES:** 1) `Services/dataset/files_server.py` 2) `Services/dataset/thumbs.py` 3) `Services/dataset/plugin/plugin.py`
4) `Services/dataset/plugin/registers.py` 5) `Services/dataset/README.md` 6) `Services/dataset/DECISIONS.md`.

**Acceptance criteria:**
- [ ] После старта `state_get dataset.files.endpoint` → `host == "127.0.0.1"`, `port > 0`.
- [ ] `urllib.request.urlopen(.../<id>/full).read()` побайтно равен файлу-источнику; `thumb` — JPEG, `max(w, h) ==
      256` для исходника 1000×500, второй запрос `thumb` не пересоздаёт файл (mtime не изменился).
- [ ] Литералы → 404 и отсутствие чтения вне корня: `/files/dataset/default/../../etc/passwd/full`,
      `/files/dataset/default/%2e%2e%2fetc/full`, `/files/dataset/..%2f/abc/full`, id из 63 символов, `variant=raw`.
- [ ] `files_bind: 0.0.0.0` → порт не слушается (`socket.connect_ex` → отказ), `dataset.files.error ==
      "non_loopback_requires_token"`.
- [ ] 20 параллельных запросов `thumb` к одному новому id — все 200, в `thumbs/` один файл, битых JPEG нет
      (`cv2.imdecode` каждого ответа не `None`).
- [ ] После `stop()` плагина тот же порт можно занять заново в течение 1 с.

**Hazard-тесты автора:** генерация миниатюры, прерванная на середине, не оставляет битый `thumbs/…jpg`; запрос во
время `stop()` не вешает остановку дольше 2 с (вызов в daemon-потоке с дедлайном join — тест не должен зависать).

**Инъекции:** путь из сырой строки URL → хотя бы один литерал обхода отдаёт файл (тест красный); убрать fail-closed →
тест `0.0.0.0`; убрать `tmp + os.replace` у миниатюр → тест параллельных запросов ловит битый JPEG (если не ловит —
тест слабый, это находка).

**Out of scope:** клиент (2.1), токен/TLS (gui-service 2.2), загрузка файлов на сервер.
**Dependencies:** 1.1.

---

### Task 1.4 — Долгие задачи: импорт папки, прогресс, отмена; дедуп; бюджет диска

**Level:** Middle+ · **Assignee:** developer · **Module contract:** public-api-change · **Layer:** services
**Handoff:** `tester`(RED) → `developer`(GREEN) → `reviewer`

**Goal:** импорт тысяч снимков не держит команду и не молчит: шаблон «команда старт → прогресс в состоянии →
отмена» (`constructor-layers.md:171`), одинаковый для импорта, экспорта (4.4) и подсказок (5.2).

**DESIGN:**
- `dataset_import {path, mode, dataset?}` → сразу `{"success": True, "job_id"}`; одна задача на датасет —
  вторая → `{"error": "busy", "job_id": <текущая>}`. `dataset_job_cancel {job_id}`.
- Прогресс: `dataset.jobs.<job_id> = {kind, state: running|done|failed|cancelled, done, total, added, duplicates,
  skipped, error}` в состоянии, не чаще 5 раз в секунду (троттлинг — у писателя, не у подписчика).
- `mode`:
  - `flat` — все картинки рекурсивно, без меток;
  - `class_subfolders` — имя подпапки = класс области `image` (создаётся, если нет);
  - `yolo` — `data.yaml` + `images/**` + `labels/**`: рамки и `names` → классы `box`; снимки с `.txt` → `labeled`,
    без `.txt` → `unlabeled`; сплит не импортируется (он наш, 4.3);
  - `dataset_gen` — выход `export_dataset`/`export_splits` (`images/{класс:03d}/…` + `classes.json`,
    `Services/dataset_gen/README.md`): класс снимка из `classes.json`, источник `synthetic`; угол — в `sources.meta_json`.
- Транзакция на пачку ≤ 200 файлов; отмена проверяется между пачками, уже вставленное остаётся (задача
  `cancelled`, `added` честный).
- Бюджет: регистр `max_disk_mb` (дефолт — открытый вопрос 5 плана); `used` = сумма `images.bytes` + экспорты;
  файл, который не влезает, → `skipped`, задача завершается `failed` с `error: "disk_budget_exceeded"` после первого
  такого. `dataset.usage = {used_mb, max_mb}` в состоянии.

**FILES:** 1) `Services/dataset/jobs.py` (новый) 2) `Services/dataset/importers.py` (новый) 3) `Services/dataset/store.py`
4) `Services/dataset/plugin/plugin.py` 5) `Services/dataset/plugin/registers.py` 6) `Services/dataset/README.md`.

**Acceptance criteria:**
- [ ] Папка 1000 PNG 64×64: `dataset_import mode=flat` отвечает < 200 мс (литерал); `await_condition
      dataset.jobs.<id>.state == "done"` ≤ 60 с; `added == 1000`.
- [ ] `yolo`-папка из экспорта Task 1.1 → те же рамки побайтно после обратного экспорта (круговой тест
      экспорт → импорт в пустой датасет → экспорт; `.txt` совпадают).
- [ ] `class_subfolders` c `good/`, `bad/` → два класса `image`, у каждого снимка `image_class_id` своей папки.
- [ ] Отмена на середине 1000: `state == "cancelled"`, `0 < added < 1000`, `added` == числу строк `images`.
- [ ] `max_disk_mb` меньше объёма папки → `state == "failed"`, `error == "disk_budget_exceeded"`, `used_mb <= max_mb`.
- [ ] Вторая `dataset_import` во время первой → `busy`.
- [ ] Импорт тех же 1000 повторно → `duplicates == 1000`, `added == 0`.

**Инъекции:** отмена не проверяется между пачками → тест отмены; прогресс без троттлинга → тест «не чаще 5/с»
(считает дельты подписки за 2 с, литерал ≤ 12); бюджет считает только новые файлы → тест бюджета на непустом датасете.

**Out of scope:** импорт архива-снимка своего формата (4.4); загрузка с машины клиента (вне плана).
**Dependencies:** 1.2.
