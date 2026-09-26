# Phase 4 — Качество и экспорт

Часть плана [`plan.md`](plan.md). Цель фазы: владелец видит, достаточно ли данных и сбалансированы ли классы,
проходит разметку второй раз и выгружает воспроизводимый снимок датасета для облачного обучения.

**Канон:** как в Ф1. Стенд не нужен (кроме ручной проверки панелей в собранном GUI).

---

### Task 4.1 — Статистика датасета

**Level:** Middle · **Assignee:** developer · **Module contract:** impl-only · **Layer:** services
**Handoff:** `tester`(RED) → `developer`(GREEN) → `reviewer`

**DESIGN:**
- `dataset_stats {dataset?}` → `{images, by_status: {…}, by_source: {…}, box_classes: [{id, name, images, boxes}],
  image_classes: [{id, name, images}], empty_labeled, boxes_per_image: {min, median, max}, usage: {used_mb, max_mb}}`.
  Считается SQL-запросами по индексу, без чтения картинок.
- Сводка `dataset.stats` в состоянии — после каждого сохранения/импорта, не чаще раза в 2 с (троттлинг у писателя).
- Панель `Services/dataset/gui/stats_panel.py`: таблица классов с полосой доли, предупреждение, если у класса < 50
  снимков или доля < 5 % (пороги — аргументы, дефолты названы здесь).

**FILES:** 1) `Services/dataset/stats.py` 2) `Services/dataset/plugin/plugin.py` 3) `Services/dataset/gui/stats_panel.py`
4) тесты.

**Acceptance criteria:**
- [ ] Датасет-фикстура (10 снимков: 3 unlabeled, 4 labeled c рамками `scratch`×5 и `chip`×2, 2 labeled пустых,
      1 verified): `by_status == {"unlabeled": 3, "labeled": 6, "verified": 1, "skipped": 0}`,
      `empty_labeled == 2`, `scratch.boxes == 5`, `chip.images` — литерал из фикстуры.
- [ ] `dataset_stats` на 10 000 снимков < 300 мс (литерал; синтетические строки, без файлов).
- [ ] 50 сохранений за 1 с → дельт `dataset.stats` в состоянии ≤ 1 за каждые 2 с.
- [ ] Панель: класс с 10 снимками при пороге 50 подсвечен предупреждением.

**Инъекции:** считать `labeled` пустые как `unlabeled` → тест `empty_labeled`; снять троттлинг → тест дельт.
**Dependencies:** 1.2.

---

### Task 4.2 — Режим проверки

**Level:** Middle · **Assignee:** developer · **Module contract:** impl-only · **Layer:** services
**Handoff:** `tester`(RED) → `developer`(GREEN) → `reviewer`

**DESIGN:**
- В рабочем месте (2.4) переключатель «Проверка»: навигация только по `status=labeled` (фильтр браузера), клавиша
  `V` — `verified` + следующий, `R` — вернуть в `unlabeled` с заметкой (поле `note` в `labels`, одна строка);
  правка рамки в режиме проверки снимает `verified` → `labeled` (проверено то, что видел проверяющий).
- `updated_by` — имя сессии оператора, если auth на бэкенде есть (gui-service 1b.4), иначе `"local"`. Разделять
  «разметчик» и «проверяющий» по правам — вне объёма.
- Экспорт (4.4) получает опцию `only_verified`.

**FILES:** 1) `Services/dataset/gui/workbench.py` 2) `Services/dataset/store.py` (`note`) 3) `Services/dataset/schema.py`
4) тесты.

**Acceptance criteria:**
- [ ] 5 размеченных: режим проверки, `V`×5 → все `verified`, каждый со своим `rev + 1`.
- [ ] Правка рамки у `verified` → после сохранения `status == "labeled"`.
- [ ] `R` с заметкой → `status == "unlabeled"`, `note` сохранена, снимок виден в фильтре «не размечено».

**Инъекции:** правка не снимает `verified` → тест правки.
**Dependencies:** 2.4.

---

### Task 4.3 — Детерминированный сплит

**Level:** Middle+ · **Assignee:** developer · **Module contract:** impl-only · **Layer:** services
**Handoff:** `tester`(RED) → `developer`(GREEN) → `reviewer`

**DESIGN:**
- `split_of(group_key, seed, ratios) -> "train"|"val"|"test"`: `u = int(sha256(f"{seed}:{group_key}".encode()).hexdigest()[:8], 16) / 16**8`,
  пороги по накопленным долям. Чистая функция, без состояния.
- `group_key` = `sources.session` захвата, если есть (кадры одной сессии = одна группа — соседние кадры одного
  изделия не разъезжаются по train и val), иначе `image_id`. Для импорта — имя подпапки первого уровня опцией
  `group_by_folder` (дефолт `false`).
- Сплит **не хранится** в индексе: вычисляется при экспорте и фиксируется в `manifest.json` снимка (4.4).
  Параметры по умолчанию: `seed=0`, `ratios={"train": 0.8, "val": 0.2, "test": 0.0}` — регистр процесса.
- Оговорка в README: группы крупные → доли по снимкам отклоняются от номинала; отклонение показывается в отчёте
  экспорта, не выравнивается.

**FILES:** 1) `Services/dataset/split.py` 2) `Services/dataset/README.md` 3) тесты.

**Acceptance criteria:**
- [ ] `split_of("abc", 0, {"train": .8, "val": .2})` — одно и то же значение в двух процессах Python
      (`PYTHONHASHSEED` разный) — литерал, записанный тестом.
- [ ] 10 000 id с `ratios 0.8/0.2`: доля train в [0.78, 0.82].
- [ ] Добавить ещё 1 000 id → ни один из первых 10 000 не сменил сплит.
- [ ] Две сессии по 50 кадров → все кадры сессии в одном сплите.
- [ ] Смена `seed` → меняется назначение ≥ 10 % id (сплит действительно зависит от seed).

**Инъекции:** `hash()` вместо sha256 → тест двух процессов; сплит по порядку добавления (`i % 5`) → тест «добавить
1000»; игнорировать `session` → тест сессий.
**Dependencies:** 1.2.

---

### Task 4.4 — Экспорт-снимок для облака и обратный импорт архива

**Level:** Senior · **Assignee:** teamlead · **Module contract:** public-api-change · **Layer:** services
**Handoff:** `tester`(RED) → `teamlead`(GREEN) → `reviewer`

**Goal:** один zip, который владелец загружает в облачный сервис обучения, и который можно воспроизвести и вернуть на
другую машину (перенос Orin ↔ ПК без сетевой фазы gui-service).

**DESIGN:**
- `dataset_export {format: yolo_detect|classify|both, only_verified?, include_sources?: [...], seed?, ratios?, zip?:
  true}` — долгая задача по шаблону 1.4 (`dataset.jobs.<id>`), результат в `exports/<name>-<N>/` + `<name>-<N>.zip`.
- `yolo_detect`: `images/{train,val,test}/<id>.<ext>`, `labels/{train,val,test}/<id>.txt` (строки `idx cx cy w h`,
  6 знаков), `data.yaml` (`path: .`, `train`, `val`, `test`, `names` словарём `{idx: name}`); `labeled` без рамок →
  пустой `.txt` (негатив), `unlabeled`/`skipped` не экспортируются.
- `classify`: `{train,val,test}/<class_name>/<id>.<ext>` по `image_class_id` (раскладка ImageFolder; Ultralytics
  classify и torchvision читают её — **по общим знаниям, не проверено в сессии**). `ml_train` source `folder` читает
  один корень и делит сам (`Services/ml_train/data.py:288-292`) — наш val он проигнорирует; это ограничение
  `ml_train`, не править (открытый вопрос 2 плана).
- `manifest.json`: версия формата, датасет, время, `seed`, `ratios`, карта `class_id → idx`, список `{id, sha256,
  split, rev}`, счётчики, отклонение долей (4.3). Картинки копируются **hardlink'ом**, где ФС позволяет, иначе копией;
  в zip — байты.
- Бюджет: экспорт, не влезающий в `max_disk_mb`, отказывает до начала (`disk_budget_exceeded`, оценка по сумме
  `images.bytes`).
- Обратный импорт: `dataset_import mode=archive` (1.4) принимает свой zip: снимки по хешу, метки — только для
  снимков, у которых локально `unlabeled`; иначе локальные остаются, счётчик `label_conflicts` в итоге задачи.

**FILES:** 1) `Services/dataset/export.py` (заменяет минимальный `export_yolo.py` 1.1) 2) `Services/dataset/importers.py`
(`archive`) 3) `Services/dataset/plugin/plugin.py` 4) `Services/dataset/README.md` 5) `Services/dataset/DECISIONS.md`
6) тесты.

**Acceptance criteria:**
- [ ] Фикстура 4.1 → `yolo_detect`: число `.txt` = 7 (4 с рамками + 2 пустых + 1 verified), пустых `.txt` ровно 2,
      `unlabeled` в экспорте нет; каждая строка `.txt` разбирается независимым парсером теста в 5 чисел, координаты
      в [0, 1].
- [ ] Два экспорта с одинаковыми параметрами на неизменном датасете → `manifest.json` равны без поля времени; списки
      файлов в zip равны.
- [ ] `only_verified: true` → в экспорте 1 снимок.
- [ ] Круговой тест: экспорт → `dataset_import mode=archive` в пустой датасет → экспорт → `.txt` и `names` совпадают
      побайтно.
- [ ] Импорт архива в датасет, где один снимок уже размечен иначе → локальные рамки не тронуты, `label_conflicts == 1`.
- [ ] `classify`: снимки класса `defect` лежат в `train/defect/` или `val/defect/` согласно `manifest.json`.
- [ ] Опционально, вне CI: `yolo check`/`YOLO(...).train(epochs=1)` в **отдельном одноразовом venv** с Ultralytics
      принимает `data.yaml` — результат командой и выводом в отчёт; в зависимости проекта Ultralytics не добавляется.

**Инъекции:** экспортировать `unlabeled` пустыми `.txt` → тест «unlabeled нет» (ложные негативы — самый дорогой
дефект датасета); `names` списком по порядку создания классов вместо карты → круговой тест после архива класса;
архив затирает локальные метки → тест `label_conflicts`.

**Out of scope:** COCO; загрузка в облако; сжатие/ресайз при экспорте (облако делает само).
**Dependencies:** 4.3, 1.4.
