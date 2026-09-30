# Передача: 1.3h-d и «кадр как у камеры» влиты в main, дальше R-5

**Дата:** 2026-09-30. **main:** `c5168660` (не запушен). Сессия-лид: Opus; код писал Sonnet (`developer`), по просьбе владельца.

## Сделано

- **1.3h-d** (загрузка PNG из браузера) — живой Chrome пройден (настоящий `FileReader`, отказы повтора и не-PNG,
  фокус на канве, Space/Enter не жмут кнопки), влит `c2a3b876`. План `plans/line-sim-layer-editor/plan.md` — DONE.
- **line-sim-belt-look** ([plan](../../plans/line-sim-belt-look/plan.md)) — влит `c5168660`:
  - 1.1 `make_seamless_texture`: период по NCC градиента (реальное фото 205 px); резерв k·P только с `--force-period`
    (в авторежиме ломал `test_hazards_3_6::test_h6`; дрейф света фото 16–22 % неотличим от виньетки).
  - 1.2 `make_font_letters`: `--ink-rgb/--grain-sigma/--seed/--edge-blur-px/--disk-from-photo`.
  - 1.3 стенд: пресет `letters_layered.yaml` на `letters_ink` + `letters_ink_disk.png`, `color_rgb` снят; плитка 410x484.
- Данные вне git (в worktree `ls-look`, `data/line_sim/`): `belt_photo_full.png`, `belt_tile.png`, `letters_ink/`,
  `letters_ink_disk.png`. Свежему дереву их нужно скопировать или пересобрать командами из
  `apps/line_sim/pipeline.yaml` и `Services/line_sim/presets/README.md` (фото ленты — `data/backgrounds/belt`).

## Дальше (по порядку)

1. **R-5** (`plans/queue/defects.md`, строка R-5), разработчик — Sonnet: (а) выбор слоя держится за имя —
   переименование + «Отмена» переносит выбор; (б) номер запроса у «Обновить список»; (в) `pytest.mark.timeout` без
   плагина в acceptance `pult_web`; (г) загрузка PNG без загруженного пресета — слой молча не добавлен;
   (д) `FileReader.onerror` не покрыт (`page_offline.mjs` не умеет `error`). Поток: слепой тестер в worktree до кода →
   developer → инъекции лида → reviewer синхронно → живой Chrome (`@browser`), см. память
   `feedback_node_page_harness_blind_to_browser_defaults.md`.
2. Прогон самого прототипа на `letter_robot_sim.yaml` против нового кадра сима (детектор + ML-классификатор).
   Пока проверен только прокси тракта на numpy: 1 круг r 143–158 на диске, 0 ложных из 11.
3. Решения владельца: боевой TTF этикетки (DejaVu тоньше реальной буквы); шум/свет камеры (п.4 плана, вне плана).

## Протокол стенда (договор с соседней сессией)

Перед подъёмом стенда — файл `D:\PROJECT_INNOTECH\Inspector_vision\stand.lock` (вне репо): есть — занято;
нет — создать строкой «сессия, время, что поднято», сообщить соседям; погасил — удалить и сообщить.
Гасить сим: `backend_ctl` `system_command {'cmd': 'system.shutdown'}` на порт 8766 (ключ `shutdown` не существует;
MCP `backend-ctl` смотрит на 8765 прототипа — для сима драйвер из python).

## Ненадёжное

- Фото-диск на 2 % меньше реального (294 px вместо 300): отступ альфы 3 px под размытие σ=1.
- Прокси детектора — не сам прототип; ML-классификатор на новом кадре не проверялся.
- Worktrees `look-t11/t12/d11/d12`, `ls-look` и их ветки влиты, но не удалены (в тестерских лежат незакоммиченные
  отчёты `docs/reviews/…`). Отчёты ревьюеров вне репо: `C:/Users/INNOTECH/AppData/Local/Temp/claude/look-1.{1,2}-review/`.
