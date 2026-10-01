---
date: 2026-10-01
topic: смещение дисков влито; «подпись всегда» влита; план layer-render (универсальный генератор объектов) готов, идёт волна 1
machine: Windows
branch: feat/layer-render (план) → main
---

## Session goal

Прогнать прототип на кадре сима с кириллическим каталогом (хендофф 2026-09-30), по ходу — запросы владельца:
смещение дисков поперёк ленты, дообучение классификатора, общий механизм слоёв для сима и аугментации.

## Done (всё в main eabaf9af, кроме плана layer-render)

- **Замеры прототипа на симе** (letter_robot_sim, 186 с, кириллица А/К/Р/Х): верно 55.9 % (headless) / 44.5 % (GUI) /
  44.5 % (GUI+смещение); ниже 0.5 — 41–54 %; верно среди ответивших 94–96 %. Сеть не ошибается — молчит. fps 24.3, GUI
  конвейер не тормозит. Сырьё: scratchpad сессии 9271acac (может не пережить).
- **sim-lateral-offset** (plans/sim-lateral-offset.md, DONE): `lateral_offset_px: [10,20]`, случайный знак, кадр + паспорт
  + истина робота (`geometry.frame_down_ux/uy`, единичный вектор). Слепой тестер → developer → 23 инъекции → ревью Opus.
  Живой стенд: остаток центра круга −0.15 px медиана.
- **letters-retrain Фаза 0** (plans/letters-retrain/plan.md): 0.2 каталог сима по замеру (буква 0.612 → 0.486·D, штрих 3,
  только DejaVu Sans/Mono — они ОТЛОЖЕННЫЕ шрифты, в обучение не идут; старый — `letters_ink_v2_big`; данные лежат
  ТОЛЬКО в worktree `merge-main/data/line_sim`); 0.3 ml_inference всегда отдаёт топ-1 + `below_threshold`, оранжевая
  пометка «<порог», word_layout не берёт ниже порога и NaN (инъекции 12/12, ревью Opus); 0.1 → передана в layer-render.
- **plans/layer-render** (ветка feat/layer-render, 03d90836 + этот хендофф): «универсальный генератор изображений
  объектов: слои + аугментация» — НЕ генератор букв; фон тоже слои (чёрная заливка + плитка с прозрачными зазорами).
  5 фаз, 17 задач. Ревью плана Opus: CHANGES_REQUESTED → исправлено (2 блокера: побайтное равенство с кадром сима —
  банковское округление `composite`; classes.json). Решения владельца: О-1 holdout_eval на общую формулу кропа (Task 2.4),
  О-2 эффекты сцены из пульта только живьём, О-3 новые пиксели допустимы (старые каталоги — суффикс `_v1`).
  Волны: {1.1 teamlead ∥ 1.2 developer} → {1.3 ∥ 2.1} → {2.2 teamlead} → {2.3 ∥ 2.4}. letters-retrain Фаза 1 стартует после 2.3.
- Память: `project_universal_object_generator.md`, `project_letters_task_scope.md`.

## В работе на момент хендоффа

- Слепые тестеры волны 1 (Sonnet), worktree на 03d90836: Task 1.1 → `.claude/worktrees/lr11-tester` (ветка
  `tests/lr-1.1-blind`), Task 1.2 → `.claude/worktrees/lr12-tester` (`tests/lr-1.2-blind`). Проверить `git log` веток:
  есть коммит `test(...)` — тесты готовы (ожидаются RED); нет — перезапустить тестера с тем же брифом (план, phase-1.md).

## Next step

1. Перенести тесты тестеров в feat/layer-render (`git checkout <sha> -- <файлы>`, коммит `test(...)`).
2. Task 1.1 — teamlead (Opus), Task 1.2 — developer (Sonnet), параллельно, в отдельных worktree; запрет коммитить в main.
3. Инъекции лида по каждому свойству (скрипт-шаблон: `inject_lat.py`/`inject_label.py` из scratchpad — перенести
   идею, файлы могли пропасть) → ревью Opus синхронно → волна 2.

## Data (владелец 2026-10-01: «real_photos — реальные фотки, dataset_gen — там; с остальными можно разобраться»)

| Папка (основное дерево, вне git) | Что | Годится для |
|---|---|---|
| `data/dataset_gen/manual_sprites` | 33 буквы × 4 реальных выреза 128² RGBA + meta.yaml | обучение (на нём училась текущая модель) — НЕ проверка |
| `data/real_photos` | 8 фото: С и А × 4 угла | проверка, но 2 класса из 33 |
| `data/dataset_gen/ru_letters_real` | 18 вырезов С и А (+ _debug) | то же |
| `data/snapshots` | 244 реальных кадра 629×484 / 734×846 с диском, БЕЗ разметки | **единственный путь к честной проверке** — разметить букву+угол |
| `data/backgrounds/belt` | 12 тайлов реальной ленты | фон обучения |
| `data/synthetic`, `data/_smoke`, `data/dataset` | старые эксперименты (Letters, augmented, real_dataset 44) | разобрать / архивировать |
| `data/ml_train/runs` | 4 прогона (июнь) | история |

**Дефект данных:** в `real_photos/C` и `ru_letters_real/sprites/C` класс — ЛАТИНСКАЯ `C` (0x43), модель знает кириллическую
`С` (0x421) → holdout_eval засчитает любой ответ на «С» как ошибку. Переименовать (решение владельца не нужно — это опечатка, но
папки вне git: делать `mv`, не удалять). Также в `synthetic/Letters` — `C` латиница.

## Open (ждут владельца)

1. Разметка `data/snapshots` для честной реальной проверки: полуавтомат (сеть предлагает букву/угол, человек подтверждает)? Сколько уникальных дисков — неизвестно (соседние кадры = один диск).
2. Кто сделал мерж 5a83c232 в main (10:17) — не эта сессия и не сосед.
3. Временная папка `C:/Users/INNOTECH/AppData/Local/Temp/cat_aug_155948` (с прошлой сессии) — удалить руками.
4. Кандидаты вне задач: мерцание выше→ниже→выше порога берёт диск дважды; триггер word_layout не снимается кадром ниже порога; оверлей ml_inference без try для bitmap-шрифта; прототип при активации рецепта переписывает `multiprocess_prototype/app.yaml` (pipeline + теряет отступ) — в worktree merge-main он изменён, откат был запрещён.

## Unreliable

- Сравнение headless/GUI по точности не чистое: сим перезапускался, доля повреждённых плавала 22–28 %.
- Сопоставление «объект ↔ ответ сети» в замерах — по порядку со сдвигом, не по id.
- Каталог сима: только штрих 3 укладывается в допуск — граница допуска на шуме метрики (Х Mono 0.075).
- Оценки бюджета плана layer-render (~7 M токенов) — не замер.

## Environment

- Соседи: `inspector-bottles-b1` ведёт Task 4.7 (transport-single-policy) в `.claude/worktrees/qr-sync`, ветка
  feat/qr-code-reader. Договор: зоны не пересекаются (его — multiprocess_framework/**, Plugins/_shared/fanin, blob_detector,
  backend/assembly, recipes ring/queue; мои — Services/{line_sim,ml_inference,ml_train,dataset_gen,layer_render}, Plugins/sim/**,
  word_layout, center_crop, apps/line_sim). main — только fast-forward из основного дерева, предварительно main → ветка;
  ff из моих веток — без его «ок», но SHA сообщить. Перед functional-прогоном — спросить про его measure, stand.lock.
- Стенд: данные сима/модели — в worktree `merge-main` (detached 97dcfed0, `app.yaml` изменён прототипом). Запуск сима/прототипа
  с GUI: `INSPECTOR_PRESENTATION=$PWD/multiprocess_prototype/frontend/presentation.yaml … python -c "from multiprocess_prototype.main
  import main; main('letter_robot_sim', headless=False)"` (venv-guard `run.py` не пускает из worktree без `.venv`).
  Гашение: `BackendDriver(...).connect()` обязателен перед `system_command`.
- Отработанные worktree этой сессии: lat-off, lat-off-tester, gaps-tester (пустой, контракт отменён), label-tester, retrain — влиты/не нужны.
- main не запушен.

## Addendum — тестеры волны 1 вернулись (после хендоффа)

- **1.1** → `tests/lr-1.1-blind` **30b5d4a2**: 3 файла (`Services/layer_render/tests/test_acceptance_1_1_background_layers.py`,
  `Services/line_sim/tests/test_acceptance_1_1_background_layers_compositor.py`, `Plugins/sim/scene_source/tests/test_background_layers_acceptance_1_1.py`),
  83 RED / 5 GREEN (контроли «без ключа — прежний кадр», sha256 сняты на дереве до задачи). Пины тестера, которых в плане нет —
  СВЕРИТЬ с исполнителем ДО реализации (несовпадение формата = ложный RED): текст ValueError содержит индекс слоя и маркер значения;
  пустой `background_layers: []` в плагине = ValueError; нечитаемый tile выбрасывается, ошибка — одна запись `log_error`, фон чёрный;
  размер в логе `ШxВ` (`tile(<путь>, 7x5, RGBA)`). Замер ≤ 1.3× (шум old-vs-old 1.000–1.009, старый путь ≈ 9.3 мс/кадр 1440×1080).
- **1.2** → `tests/lr-1.2-blind` **a5d898e7**: `Services/line_sim/tests/test_acceptance_layer_render_1_2_gap_alpha.py`, 32 RED / 2 GREEN.
  Пины: `--gap-hue LO,HI` и `--gap-sat-min` — границы включительные; `--rails-px=TOP,BOTTOM` (через `=`); `gap_alpha_mask(tile_rgb)` →
  2D uint8, вход не меняет; альфа бинарная, 4-й канал PNG; ошибка порога — имя флага после `error:` в stderr.
  **Предупреждение тестера:** на РЕАЛЬНОЙ плитке звенья H≈105, S≈20–27, а пикселей с S≥30 всего ≈2 % — «мятный просвет» из плана
  может оказаться тоньше. Исполнитель 1.2 сначала МЕРИТ реальную плитку (`merge-main/data/line_sim/belt_photo_full.png`), потом дефолты;
  реальный тест (единственный на дефолтах) использует придуманные тестером границы доли прозрачных 0..0.5 — может падать не из-за дефекта.

## Addendum 2 — ответы владельца на Open 1–3 (закрыты)

1. **`data/snapshots` НЕ размечать.** Владелец уже вырезал из них реальные диски в `data/dataset_gen/manual_sprites`; их
   подмешивают к синтетике, накладывая ЦЕЛЫЙ диск на фон конвейера (так и должен делать генератор обучения, Фаза 2/letters-retrain Ф1).
   Честная проверка на реальном остаётся узкой: `data/real_photos` (С, А × 4 угла) + отложенные шрифты DejaVu в симе.
2. **Латинская `C` → кириллическая `С` (0x421) переименована** (`mv`, ничего не удалено): `data/real_photos/С`,
   `data/dataset_gen/ru_letters_real/sprites/С` (+ `_debug/С`), `data/synthetic/{Letters,augmented}/С`. Пресеты ссылаются на папки,
   не на имя класса — правок кода не нужно. Старые модели, обученные на латинской `C`, этот класс больше не совпадут — их не трогать.
3. **Мерж 5a83c232** — вероятно, параллельная сессия; владелец отслеживать не будет. Вопрос закрыт; с соседями — договор выше.
