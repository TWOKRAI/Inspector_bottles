# Сведение камерных планов в один (2026-11-26)

Дерево `.claude/worktrees/plan-camera-merge`, ветка `docs/camera-plan-merge` от `main` `eaaf82a60`. Не закоммичено.

**Единый план:** `plans/2026-11-26_device-common-base/` (slug прежний, повода менять нет). 56 строк задач:
- Фаза 1, без приборов — 6: C6.1 (бриф переписан), H1 ревью `d89637973`+`989c669e5`, H2 опечатка `plate_*`, H3 пустой `heightForWidth`, H4 `lost_frames` после переподключения, H5 `mvcr_probe` на `None`.
- Фаза 2, день с железом 1.0 — 3: C0.5, C6.3 (М2), H6 обрыв кабеля одной MVS. Фаза 3, окно 4 приборов — 3: H7, C6.3-m3, H8.
- Фаза 3б — 3: C1.3, C1.4, C1.7 (строка 22 очереди: 1.0; вопрос В5). Фаза 4, 2.0 — 8 (1.1-2.2, считыватель и веб-камера).
- Фаза 5, 2.0 — 28 (C*, W2-*; W2-i, W2-j, W2-k BLOCKED). Фаза 6, запись и буфер из gui-frame-path — 5 (GT14, GT8b, GT11, GT12, GT16): **отдельная фаза, срок — вопрос В3.**
- `plans_progress`: total 23, dropped (DEFERRED) 33. Гейт плана: 0 ошибок, WARN старый `tasks/1.1.md` 8,0 KB.

**Сделано (по git, всё в `main`):** camera-device-service — 30 задач (включая 4c, 4.2f-4.2j, которых в списке плана нет; 2.4 разрезана на 2.4a и 2.4b); multicam — 12; gui-frame-path — 13: T1-T10, T13 (`47e977800`; T8c — в `d72bcb8ab`). **Заморожено:** W2-b, W2-b1, W2-t3; qr 2.4, 3.3, 3.4, 5.1. **Снято:** C5.1 (хватает хука `create_port()`). Таблица — `mapping.md`.

**Шапки против git:** camera-device-service — 2.3a, 2.3b, 2.3c, 2.3d, 2.4, 2.4a, 2.4b PENDING, а в `main`; 4c, 4.2f, 4.2g, 4.2i, 4.2j в списке нет. gui-frame-path — «код не тронут», а 13 задач в `main`. multicam — W2-l, m, n, o, q, q2, r имеют брифы без строк; W2-p — без брифа. scope-1.0 — п.14-18 уже сделаны.

**Бриф 6.1 против кода:** старое место `Services/camera_device/tools/` нарушает границу `Services/* -> backend_ctl/*` (`.sentrux/rules.toml:74-77`); новый — `backend_ctl/probes/camera_stand_probe.py`. Добавлены блоки `link`, `identity`, `stream`, `frame_watch` и счётчики потерь; состояние — ключ `state`, не `device_state`.

**Изменённые файлы:** новый план — `plan.md`, `mapping.md`, `amendments.md`, `scope-1.0.md` (заметка сверху), `tasks/C6.1.md`, `tasks/H1-H8.md`, 39 ссылок `tasks/<id>.md`. Закрыты (SUPERSEDED в шапке, текст не тронут): `plans/2026-10-18_camera-device-service/plan.md`, `plans/2026-11-25_multicam-observability/plan.md`, `plans/2026-11-24_gui-frame-path/plan.md`. `plans/qr-code-reader.md` — заметка и 8 строк камерных задач. Ссылки: `plans/queue/ORDER.md` (строки 0, 21, 22, 23, 29, 35; порядок не менял), `plans/code-reader-gui.md`, `plans/code-reader-sdk.md`, `plans/README.md` (ledger). `plans/release-1.0/` ссылок на перенесённые задачи не имеет — не менял.

**ПЛК-часть qr-code-reader (не перенесена):** 0.1 (Modbus, FTP), 1.1, 1.2, 1.3, 1.4, 1.5.

**Вопросы владельцу:**
- В3: запись и буфер (фаза 6) — 1.0 или 2.0? Рекомендую 2.0, а GT14 закоммитить сейчас: код готов, приборы не нужны.
- В4: экран `hold` при объявленной потере связи — показывать «нет связи»? Рекомендую да (W2-c3, 2.0).
- В5: C1.3, C1.4, C1.7 — в очереди 1.0, в 18 задач 1.0 не вошли. Рекомендую 2.0; до ответа — PENDING, очередь не менял.

**Проверки:** `plans_progress.py --queue` rc 0, 50 пунктов; камерные: 1 -> `device-common-base` C6.1 (открыт), 21-24 -> старый план (закрыты: работа сделана), 25 -> C1.3, 26 -> C0.5 (открыты), 34 -> 1.1 (closed: DEFERRED считается закрытым — как и прежняя 3.3), 40 -> qr-code-reader (открыт). `validate.py` через `machine_gate.sh light inspector-bottles-42`: «Ошибок нет! Предупреждений нет!», rc 0.

## Что оставил открытым / ненадёжно

- C1.7: часть про `INSPECTOR_LOG_DIR` могла закрыть `4b8da041c` (C-14) — не сверял.
- 2.3b, 2.4a, 2.4b: коммит задачи в `main`, отдельного коммита слияния не искал (ff). 4.2j: слияния не искал.
- Разбор qr 3.1, 3.2 («заменены рецептами 4.2f-4.2i») — по назначению рецептов, оверлей кода на экране не проверял.
- Брифы фаз 4-6 не сверены с кодом `main`; GT8b, GT11, GT12, GT16, W2-p без брифов.
- Решение в H2 (умолчание поля + WARNING вместо видимой ошибки) принял я; владелец может вернуть.
- Статус «SUPERSEDED -> device-common-base» в ledger — вне его словаря (DRAFT/ACTIVE/DONE/ARCHIVED/FROZEN); `doctor --fix` может переписать.
- Старые `qr-code-reader.md` (95 KB), `ORDER.md` (99 KB), `multicam` `plan.md` (60 KB) выше предела 32 KB — не делил: правка вне задачи.
- Опись OPEN_QUESTIONS и defects собрал помощник (haiku); решающие строки рецептов и плагина я читал сам, тела записей OPEN_QUESTIONS — нет.

## Раунд 2 (ревью плана, CHANGES REQUESTED, 9 пунктов)

Исправлено всё: C6.1 (метрики опросом `introspect.telemetry` -> `levels`, формы ответов, выход 1 при `samples == 0` и пропавшей метрике),
H4 (дефект — возврат из `lost` в `grabbing` мимо `opening`, номера выше прежних), H2 (правка в `recipe.py`, `DisplayDefinition` не трогаем),
H3 (проверка по геометрии, инъекция И1), H5/H8 (stdout JSON-строки), зависимости, хвосты (H9 — F5, H10 — A1, В6 — M2, Р-W2-1…9,
C-109, четыре находки стенда — в `plans/queue/inbox/2026-11-26_camera-plan-merge_1.md`), ссылки в четырёх планах, H1.
План: 58 строк, `status` 0/24 (DEFERRED 34 не считаются), `plan.md` 16,2 KB. `validate` rc 0, `--queue` rc 0.
