# Замер «Компания v3» — трек transport-single-policy, фаза 5 (лид — сессия 19)

Отдельный файл от `pilot-company-v3.md` (layer-render) и `pilot-company-v3-1b2d.md` (gui-service): лиды пишут параллельно.
План: [`plans/transport-single-policy/phase-5.md`](../../plans/transport-single-policy/phase-5.md). Ветка лида — `feat/transport-f5` (worktree `.claude/worktrees/t5-lead`).

## agentId (дозывать по нему, имя после обрыва не резолвится)

| Роль | Имя | agentId | Задача | Контекст |
|---|---|---|---|---|
| debugger | dbg-t55 | `a52f1f37cca20d851` | 5.5, диагноз красных на main (worktree `t55-green`, ветка `fix/t55-green-main`) | — |

## Строки

| подзадача | агент | свежий/дозванный | токены | находки | инъекции живы/мертвы |
|---|---|---|---|---|---|
| 5.5 диагноз (п. 1–4) | debugger | свежий | 172k, 53 вызова, 12 мин | HOL ×2 — код (Windows: `shutdown()` не будит `recv()`); HOL ×1 — тест (Win принимает 2 отправки без блокировки); Path-кодек `\tmp\x`; hot_rebuild пин 38≠37 с 2026-09-06; catalog уже зелёный. П. 5–6 не сделаны — замок стенда | — |
| 5.0 факты | лид | — | — | (а) дверь А; (б) событие не доходит; (д) ветка `:574`; см. `docs/audits/2026-10-02_transport-facts.md` | — |

## Сбои процесса

- `sweep50.py` (5.0(г)) первым запуском упал: нет `if __name__ == "__main__"`, Windows-spawn перезапускал сам скрипт. Потеряно ~2 мин стенда, сирот на порту не осталось.
