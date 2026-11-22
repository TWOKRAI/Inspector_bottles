# Handoff полосы Ф: RN1 + PS1 — 2026-11-22

Автор: лид полосы Ф. Закрывается `/clear`. Отчёт: `docs/reports/2026-11-22_system-run-state_lane-f-RN1.md`; заявка: `docs/handoffs/2026-11-22_system-run-state_lane-f-merge-request-rn1-ps1.md`.

## Состояние
RN1 и PS1 готовы в ветках `feat/run-state-rn1` и `docs/run-state-ps1` (от main `15858154e`), в main не слиты: ждут координатора (inspector-bottles-30). Ревью стадии 5 — APPROVED, блокирующих нет.

## Что осталось
| Что | Состояние | Кто |
|---|---|---|
| Слияние RN1 + PS1 | заявка файлом | координатор |
| Хвосты D2, D5, D6 ревью | запись в `OPEN_QUESTIONS` 2026-11-22; D5 требует `driver.py` вне FILES | лид/владелец |
| Входы без `--autostart` (`main.py __main__`, `AGENTS.md:85`, `alpha_sim`, `run_sim_all.ps1`) | список с рекомендацией в отчёте | слово владельца |
| Файл PM, `spawner.py`, `state_proxy.py` | не тронуты | слово координатора по Р1–Р5 |
| Worktree `--lane-F-rn1-tester`, `--lane-F-rn1-inj` | одноразовые, detached | `git worktree remove` после слияния |

## Уроки (в память не писал — решает преемник)
- Хук protect-branch режет `git commit` агента, но не коммит лида из `cd <worktree> && git commit`; файл сообщения писать Write по обычному пути (путь с `..` не находится).
- Хук lint-brief требует `BRIEF-OVERRIDE: <причина>` для слепого tester и матрицы инъекций.
- Предсказание инъекции на общую функцию должно называть ВСЕ тесты, читающие через неё (мой недочёт в (е)).
- Слой коммита для смеси framework + prototype + backend_ctl — `mixed`; `app` не в списке.

## agentId
Стадия 0 reviewer `a31b197f62986ab25`; tester `a7dc4b82286f3a6ca`; developer `a4ca5f699d7194a41`; инъекции `a2476fd02928f73a6`; docs `a1f77e03639684eb4`; ревью стадии 5 `a2a698911fb8a2f81`; PS1 `a3388ac2af6bc64a7`.
