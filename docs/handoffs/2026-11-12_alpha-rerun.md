# Handoff — полоса «Приёмка α», 2026-11-12 (повторная приёмка Task 1.2 + правка скрипта)

Сессия inspector-bottles-9d. Статус из git `main`, не из шапок. Ответы владельцу — по-русски.

## Где что (на момент handoff)

- `main` = слияние Task A (`31510f5c2`) + эта работа после слияния документов; в remote НЕ пушено. Ветка `feat/alpha-hard-split`, worktree `.claude/worktrees/alpha-hard-split` (он же дерево стенда; данные стенда в `data/` вне git).
- Task A (`scripts/alpha_sim`): класс FAIL МЕХАНИЗМ/ТОЧНОСТЬ, каскад `word_line`, `--hard-out`/`--hard-angle-thr`; 233 passed; ревью: sonnet APPROVED (2 раунда), Opus APPROVED (2 раунда); инъекции I1–I31.
- Task 1.2: DONE по механизму (3 из 3), точность открыта; отчёт `docs/reports/2026-11-12_release-1.0_alpha-rerun.md`; результат `plans/release-1.0/tasks/1.2.result.md`.
- Сырые данные трёх прогонов: `data/alpha_rerun/run1…run3` + `RUNS.md` (вне git — при чистке worktree сохранить).
- Архитектурное ревью Opus: `docs/reports/2026-11-12_opus-arch-review.md`; пакет фактов `…arch-evidence.md`. Карта-схема: https://claude.ai/artifact/R3frqTYGxLzm1MuHVMn1vR (приватная).

## Решения владельца (ждут)

1. Вернуть ли окна съёма §2.8 — запись 23 и правка `logic.py` готовы: `plans/release-1.0/lane-tasks/alpha-record-23-draft.md` (НЕ применять без слова). Рекомендация: да; перед возвратом можно 2–3 прогона на других сидах (запас `py` 0,3 мм).
2. Порог «трудного» по углу DS-В2 (рекомендация 5,0°).
3. Вердикт α: рекомендация «пройдена по механизму; точность — ORDER #27, letters-retrain».
4. Из Opus-ревью (чужие полосы): `DatasetEngine` заморозить и перевести GUI + `ml_train` на `LayerSceneGenerator`; место правила «трудного» (DS-1, расходится с `alpha_sim.hard_reasons` в трёх пунктах); циклы фреймворка (sentrux `min_acyclicity` 0,33); контракт `dropped{reason}`; манифест `data/` с sha256 и проверка стенда одной командой.

## Долги этой полосы (не сделано)

- `hard_reasons` — единственная реализация правила «трудного» (`scripts/alpha_sim/logic.py`, пометка `# ponytail: дубль правила DS-1 §6`): заменить импортом после DS-1 1.1c.
- Отложено в Task A: S1 (assert `results`/`shown` в `finish()`), S2 (вынос фейков в `_fakes.py`: hazard-файл импортирует приватные помощники приёмочного), nit-ы (порог 5.0 в трёх местах, `getattr` для флагов).
- `--dump` не сохраняет ответ `system_shutdown` (S9 держится на `out.txt`): поле `replies` пусто — добавить в скрипт.
- Ограничение класса FAIL: потеря одного диска повторяющейся буквы (Е, Р, И) даёт ложный МЕХАНИЗМ-FAIL чужих строк; вердикт в таком прогоне читать по строкам. На стенде не проверено.
- `design.md` §2.7 не описывает park при стопе (второй `SERVO` перед `STOP_REQ`); `design.md` §2.8 `py` расчёт −342,6 против наблюдения −342,3; `defects.md` C-87 всё ещё «открыт» (закрыт `0dad0288a`) — строки правит владелец плана.
- Сохранение кадров: в `letter_robot_sim` нет `frame_saver`; для до-обучения на вырезах — `frame_saver` в рецепте + DS-1 (чужие полосы).

## agentId (персистентные; адрес — agentId)

| Роль | agentId |
|---|---|
| developer Task A (владелец кода и инъекций) | a636434773c3a5509 |
| reviewer sonnet (ветка) | af3d5bca7f0eb558d |
| reviewer Opus (ветка + архитектура) | a2248664ff2abab20 |
| reviewer sonnet (вердикт Task 1.2) | a1b5cd96db4b31a29 |
| исполнитель стенда | a51c4134a46878eb9 |
| tester слепой Task A / сверка сырых | a51947578b6ccf013 / a857be24031b57741 |

Расход developer > 300k токенов: новый исполнитель по `docs/reports/2026-11-12_alpha-hard-split-dev.md` и diff — тот же исполнитель.

## Уроки (для следующей сессии)

- Брифы Agent: линтер требует блоки DESIGN / FILES / REDS / REPORT (≥ 3 строки в DESIGN), иначе `BRIEF-OVERRIDE: <причина>` (слепой tester).
- Трейлеры коммита — отдельные строки одного абзаца (`Why:`, `Layer:`, `Refs:`, `Co-Authored-By:`), не одной строкой.
- Слияние в `main`: `main` checked out в `.claude/worktrees/merge-main` — там ветка-обёртка, `git merge --no-ff -F <файл>`, затем `git checkout main && git merge --ff-only <обёртка>`; не пушить.
- `cd` в команде меняет рабочий каталог сессии: использовать абсолютные пути, возвращаться в worktree.
- Предсказания пишутся и коммитятся ДО прогона; несовпадение — находка (в этой сессии I3 вскрыл дыру тестов, ошибка была в предсказании лида).
- `validate.py` даёт 2 ошибки памяти (теги и индекс BY-MODULE) — есть и на чистом `main`, не от полосы.
