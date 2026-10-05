# Транспорт, фаза 5 — хендофф лида №2 (2026-10-03, вечер)

Продолжение `docs/handoffs/2026-10-03_transport-f5-lead.md`. **Цель следующего захода — закрыть Task 5.4** (замер на
`multi_camera.yaml`), затем решить слияние сделанной части фазы 5 в main.

## Состояние
- Ветка `feat/transport-f5`, worktree `.claude/worktrees/t5-lead`, HEAD `d1dc783a6`. main влит до `4ce905efa`
  (слияние `9e9cec47c`); **main ушёл вперёд на 24 коммита** (до `8b0eeac41`: commit-mechanism Task 1.1 — хук
  session-log снят с pre-commit). Перед следующими коммитами влить main:
  `merge: main (8b0eeac41) в feat/transport-f5 — <зачем>` + Why/Layer/Refs. До вливания хук ещё дописывает
  `docs/sessions/2026-10-03.md` в каждый коммит — это штатно; если журнал в `git status` как `MM` — проверить до коммита.
- Сделано в фазе 5 и **не в main**: 5.2 (`236ec9e5b`), 5.3 (`0eb42340a`), 5.6 (`fd906e4ee`), 5.9a, код 5.4 (`d06155efd`).
  В main: 5.5, 5.5c (`68a8ba279`).
- Task 5.5d — **SUPERSEDED** (`d1dc783a6`) планом `plans/2026-10-03_lifecycle-owner-scope/` (ветка
  `feat/lifecycle-owner-scope`, первый приоритет очереди). Ветка `fix/t55d-qt-gc` (worktree `t55d-impl`) **не вливается**;
  полезное из неё (страж `batch-drain-*`, `unwire` в writethrough-тесте, `close` в тесте 3.3) переезжает в Ф1 того плана.
  Worktree `t55d-impl` можно снять после подтверждения владельца (`git worktree remove`, не `rm -rf`).

## Task 5.4 — что осталось
Код: `d06155efd` (preroll: `SourceProducer.produce()` стартует по событию готовности потребителей, PM взводит событие).
Открыт один пункт acceptance (`phase-5.md`, Task 5.4):
- [ ] **`multi_camera.yaml` — то же, обе камеры** (`multiprocess_prototype/backend/topology/multi_camera.yaml`;
  условие «после 5.9a» выполнено). Критерий как у `stand.yaml`: 3 прогона; `s0` — кумулятивный снимок через 10 с после
  ready; `queue_data_evicted` в `s0` = 0 у всех процессов; `frame_stale_drops` в `s0` = 0 под `every`, под `latest` —
  число в отчёте.
- Инструмент: `scripts/stand_gate` (Task 5.6), прогон `--runs 3`; прошлые прогоны и формат —
  `docs/reviews/2026-10-03_phase5-stand-w2.md`, `reports/stand*`. Повтор `stand_gate --runs 3` (дренаж) — тем же окном.
- Открытый вопрос владельцу в критерии `stand.yaml`: предложение лида по `frame_stale_drops` storage под `latest`
  (5–9 за 10 с) — ждёт решения, не блокирует замер.
- Перед стендом: машина общая — спросить/проверить соседей (`ListAgents`), не держать два бэкенда сразу
  (PID-реестр и SHM-cleanup конфликтуют), никакого глобального `taskkill` — только `TaskStop` или PID.
- В том же окне стенда (из прошлого хендоффа, волна 4): зонд доли `plugin_ms` в цикле для 5.8a; сверка источника
  `cycle_median` для 5.8s; предусловие 5.11 по коду.
- После замера: строка 5.4 в «Порядке выполнения» → `[DONE <дата> — <sha>]`, отчёт стенда в `docs/reviews/`,
  `plans_progress.py --check --root .`.

## Дальше по фазе 5
| Задача | Статус | Замечание |
|---|---|---|
| 5.8s профиль `throughput` | PENDING | скрипт стенд-гейта — можно в любое окно |
| 5.8a storage, сброс в потоке | PENDING | **предложено владельцу (не подтверждено):** ждать Ф0 lifecycle-owner-scope и строить поток сразу на `IScope.spawn` / `Stoppable`, иначе это ещё один самописный поток под миграцию Ф4 |
| 5.8b пул исполнителя | PENDING (после 5.8s) | то же — пул = адаптер Ф4 lifecycle |
| 5.11 слоты потерь в карточке | PENDING | то же — виджет сразу на `attach_qt` / `Subscribers` |
| 5.12 гейт готовности к линии | PENDING (после 5.8a) | — |
| 4.8, 5.7, 5.9, 1.1, 1.2, 1.4, 3.1 | DEFERRED | по своим условиям |
Спеки 5.8 и 5.11 — ред. 3 (`task-5.8.md`, `task-5.11.md`), spec-review пройден.

**Слияние фазы 5 в main:** после 5.4 — сделанную часть (5.2, 5.3, 5.4, 5.6, 5.9a) влить, чтобы ветка не гнила.
Гейт `run_framework_tests` до Ф5 lifecycle-плана падает ~1 из 4 аварийно (`Fatal Python error: Aborted`, причина
известна) — повтор с записью в отчёт, не молча. Слияние — по слову владельца, формат `merge: суть` + Why/Layer/Refs,
SHA соседям.

## Связи
- **lifecycle-owner-scope** — первый приоритет, ведёт другая сессия (хендофф
  `docs/handoffs/2026-10-03_lifecycle-owner-scope-start.md` в ветке `feat/lifecycle-owner-scope`).
  `lifecycle-stop-ownership` Ф2 («перемерить 20 стопов после L-6») по тексту разблокирована фазой 4 транспорта — запуск
  после Ф1 lifecycle-плана (предложено владельцу, в очередь не внесено).
- Соседи по машине: f0 (layer-render), commit-mechanism (inspector-bottles-7d), plans-progress. Перед стендом и
  тяжёлыми прогонами — сообщить.

## agentId этой сессии (для повторного вызова через SendMessage)
| Роль | agentId | Чем закончил |
|---|---|---|
| reviewer 5.5c | `a9bbef824420a9ba9` | 5.5c влита |
| spec-reviewer волны 4 (5.8, 5.11) | `a67d3aff359a6d129` | спеки ред. 3 |
| investigator аварийного завершения | `a2c4d8f8325048042` | диагноз (OPEN_QUESTIONS §5.5c п.8) |
| tester 5.5d | `a5f9d901ce6dcd59b` | 5.5d SUPERSEDED |
| reviewer 5.5d | `aa4ed797125259a38` | итерации исчерпаны, 5.5d SUPERSEDED |
| CTO архитектуры lifecycle (3 раунда) | `a0493f81705fa59f1` | контекст >230k — для новых вердиктов звать свежего |
| reviewer архитектуры lifecycle (2 раунда) | `a1c0053f723d2c332` | лимит итераций исчерпан |

## Не забыть
- Решения владельца 2026-10-03 этой сессии: один механизм жизненного цикла у всех; план lifecycle — первым в очереди;
  промт и хендофф новой сессии lifecycle — сделаны. Записаны: память `project_universal_lifecycle_decision.md`
  (обе копии), `plans/queue/ORDER.md` §0 (ветка lifecycle).
- Вопрос CTO на приёмке фазы 5 «прод-риск сборки Qt-мусора на чужом потоке в GUI» — ушёл в lifecycle-план (Ф2/Ф5).
