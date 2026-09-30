# Передача: 1.3h-d (загрузка PNG из браузера) — код готов, ждёт Chrome

**Дата:** 2026-09-30. **Ветка:** `feat/line-sim-layer-editor`, worktree `.claude/worktrees/ls-layer`, HEAD `2569edba`.
**Постановка:** [plans/line-sim-layer-editor/task-1.3h-d-upload.md](../../plans/line-sim-layer-editor/task-1.3h-d-upload.md).
`main` = `79dda66a` (R-4 и 1.3h-a..c уже влиты), ветка впереди на 8 коммитов, от `main` не отстаёт.

## Сделано

- Слепые тестеры (2) до кода — 75 тестов (`c013e4bb`); реализация Sonnet (`961e7e88`); правки лида (`c17a08ea`,
  `cd215f16`, `2569edba`); правка по ревью ит.1 (`7b37281f` RED, `f2d4f292`).
- Инъекции: 18 + J1–J5 + K1–K2, все свойства ловятся (I2 «без предпроверки exists» — эквивалентный мутант, `os.link` ловит то же).
- Живой стенд (curl по маршруту): RGBA → 200 (111 мс), повтор → 409, RGB → 400, `../` → 400, 8.6 МиБ → 413,
  4.6 МиБ → 200 (129 мс), файл в `preset.sprites`, слой строится в `preset.layout`. Тестовые `zz_*.png` удалены.
- Ревью: ит.1 REQUEST_CHANGES (не-PNG до декодеров, зависание `mkstemp` на ACL, PNG-бомба) → ит.2 APPROVE_WITH_NITS,
  ниты закрыты. Отчёт ревьюера — вне репо: `C:\Users\INNOTECH\AppData\Local\Temp\claude\1.3h-d-review\report.md`.
- Радиус `layer_preview + pult_web + device_hub`: 467 passed; `layer_preview` после нитов 131 passed.

## Осталось (по порядку)

1. **Живой Chrome** (пользователь должен написать `@browser`). Стенд — из `ls-layer`, рецепт в
   `apps/line_sim/README.md` (порты 8091/8092/8766/5021 — проверить свободны). Системный диалог выбора файла
   расширение не открывает: подставить файл JS-ом — `new File([bytes], "x.png", {type: "image/png"})` через
   `DataTransfer` в `#presetSpriteFile.files`, затем `dispatchEvent(new Event("change"))`. Проверить: настоящий
   `FileReader` → слой на канве; повтор имени → текст отказа, слоя нет; `document.activeElement` после загрузки —
   канва; Space/Enter после загрузки не жмут кнопку; консоль без ошибок. «Сохранить» НЕ нажимать; загруженные
   файлы потом удалить из `data/line_sim`. Чек-лист и артефакты инструмента — память
   `feedback_node_page_harness_blind_to_browser_defaults.md`.
2. Закрыть 1.3h-d в `plan.md` (строка 144) и влить ветку в `main` (`--no-ff`, сообщение «слияние — …» с `Why:`/`Layer:`/`Refs:`,
   сообщение через `-F <файл>` — `-F -` не работает).
3. R-5 (`plans/queue/defects.md`, строка R-5): (а) выбор держится за имя слоя, (б) номер запроса у «Обновить список»,
   (в) `pytest.mark.timeout` без плагина, (г) загрузка без пресета — слой молча не добавлен, (д) `onerror` не покрыт.
   Разработчик — Sonnet (просьба владельца).
4. Qt (1.2b/1.3) — отдельный чат, ждёт И3.

## Ненадёжное

- Страница проверена только в `page_offline.mjs` (node:vm) — нет фокуса и настоящего `FileReader`.
- FAT32/exFAT для `sprites_dir` не прогонялся (`os.link` там нет → `io_error` на каждую загрузку).
- Worktree ревьюера/тестеров удалены; служебных веток 1.3h-d не осталось.
