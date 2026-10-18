# Передача: полоса К · W1a закрыта — к стенду MVS 2026-10-19 (Task 0.5)

Автор: лидер полосы К (Opus 5.5), сессия `inspector-bottles-53`. Заменяет `2026-10-18_camera-w1a.md` (та — до правки текста задач).

## 1. Состояние

| Что | Значение |
|---|---|
| Ветка | `feat/camera-device-service`, HEAD `9a6f12ff8` + коммит этой передачи; **в `main` не слита** — слово владельца |
| Worktree | `.claude/worktrees/camera-w1a` (основной полосы); `camera-w1a-02`, `camera-w1a-03` — отработали, их коммиты перенесены `cherry-pick` (можно удалить: `git worktree remove`) |
| План | ACTIVE, ledger `3/42`, `contract.lock` обновлён амендментом №1 |
| Ревью плана | р.1 CHANGES -> р.2 CHANGES -> р.3 `cto` APPROVED (`docs/reviews/2026-10-18_camera-plan-review.md`) |
| Ревью волны | р.1 CHANGES (3 blocker) -> р.2 **APPROVED** (`docs/reviews/2026-10-18_camera-w1a-wave-review.md`) |
| Отчёты задач | `docs/reports/2026-10-18_camera-device-service_0.2.md`, `_0.3.md`, `_0.4.md` |
| Метрики пилота | `plans/2026-10-18_camera-device-service/amendments.md` §3 |
| Чек-лист 0.5 | `plans/2026-10-18_camera-device-service/checklist-0.5.md` |

## 2. Коммиты кода W1a

| Коммит | Что |
|---|---|
| `8dbef380b` | 0.3 — 11 обёрток MVS, `MVCC_ENUMENTRY`/`MVCC_INTVALUE_EX`, `AM_*`/`IFT_*`, `EXCEPTION_CALLBACK` |
| `0c92beea7` | 0.2 — цветной кадр, рецепт после `open` (`fps` -> `AcquisitionFrameRate`, `ExposureAuto`/`GainAuto` Off), `param_errors` |
| `dacd33b33` | 0.4 — зонд `Services/hikvision_camera/tools/mvs_probe.py` + строка G6 |
| `08dee5d9b`, `11634a669`, `5c33101d0` | правки ревью волны р.1 (пп. 1, 2, 4, 7 / 9 / 3) |

## 3. Завтра (2026-10-19), по порядку

1. Слово владельца на слияние -> `merge: …` в `main` (+ `Why:`/`Layer:`/`Refs:`, сообщение из файла; хук требует оформленный `/code-review` — `feedback_git_main_merge_hook_traps`). Без слияния стенд 0.5 не поднять: `frontend/run.py` ищет `.venv` в корне дерева.
2. Окно `heavy` у координатора `inspector-bottles-a9`; MVS в сети; IDMVS закрыт ~10 с.
3. `checklist-0.5.md` шаги 1–9: зонд (перечисление -> `--dump` до -> H1/H2/H5 с `--write --orig` -> `--dump` после, diff пуст) -> стенд `hikvision_inspect` через `backend_ctl`. Сбор чисел — `junior` (haiku); вывод — Opus `reviewer` (W4 по плану).
4. Не нажимать Ctrl+C в `--experiment h2 --mode split` (ревью волны р.2, замечание a).
5. Результаты: JSON дерева -> `Services/camera_device/testing/recordings/mvs_<модель>.json` (только файл, без кода — решение лидера), «Факты MVS» -> `tasks/0.5.result.md`, отчёт -> `docs/reports/2026-10-19_camera-device-service_0.5.md`, строка координатору.
6. По желанию (light): `VirtualCamTool` (`C:\Program Files (x86)\IDMVSSTD\Applications\Win32\VirtualCamTool`) — запустить и посмотреть, даёт ли зонд `devices>0`. Сегодня без него `devices=0`.

## 4. Правила полосы (координатор и владелец, 2026-10-18)

- Лид координирует, не исполняет: Haiku — механика и числа, Sonnet — исполнители, Opus — ревью волны, Fable — 3-я итерация. В брифе — конкретные FILES.
- Расход агента ~400–500k — решает лид (свежий агент с файлом отчёта и диффом, или узкая проверка); сигналов координатору нет.
- После каждой задачи — `docs/reports/<дата>_<plan-slug>_<task>.md` (≤ ~15 строк) и строка координатору `ОТЧЁТ: … — <путь> · решение нужно: да|нет`.
- Бриф исполнителя — `plans_ledger.py brief` в файл; хук `lint-brief` пропускает строку `BRIEF-OVERRIDE: <причина>` со ссылкой на файл.
- Один писатель на дерево: правки параллельно — в отдельных worktree, затем `cherry-pick`.

## 5. Агенты (agentId годны только в этой сессии — после `/clear` звать свежих с файлом отчёта)

| Роль | agentId | Модель | Токены |
|---|---|---|---|
| reviewer — ревью плана р.2 | `a5841e3f88eb29182` | opus | 211k |
| cto — 3-я итерация ревью плана | `aae1208635436996f` | fable | 124k |
| developer 0.2 (+ правка п. 9) | `a49b57b87b4765f99` | sonnet | 115k |
| developer 0.3 (+ правка п. 3) | `ae3f2bc8200e9908d` | sonnet | 140k |
| developer 0.4 (+ правки пп. 1, 2, 4, 7) | `a43222c83d08f921f` | sonnet | 215k |
| developer — черновик чек-листа 0.5 | `a58fc5a29b21ca88f` | sonnet | 78k |
| reviewer — ревью волны р.1 + р.2 | `a27bf912d3a891b79` | opus | 209k |
| **итого** | | Opus 420k · Fable 124k · Sonnet 548k · Haiku 0 | ~1,09M |

## 6. Что открыто / ненадёжно

- Ничего не проверено на камере: раскладки и вызовы проверены на фейке уровня C у ревьюера, не на DLL с открытой камерой.
- Ctrl+C в `split` (замечание a): одна строка `session.cancel.set()` перед `finish()` — не внесена, код после APPROVED не правился.
- Отложено на 4.2a: каналы по битам формата (упакованные Mono12 дают мусор), одно правило для `None` в рецепте.
- Ветка GigE (`GevSCPSPacketSize`) тестом не покрыта.
- `MV_CC_GetIntValue` — экспорт без прототипа в заголовке.
- G6 `Services/code_reader/tools/thread_split_probe.py:210` — дефект C-8 координатора, не наш.
- Урок-кандидат (индекс памяти > 8 КБ, не записан): agentId другой сессии не дозывается (`2026-10-18_camera-w1a.md` §8).
