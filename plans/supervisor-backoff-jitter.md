# supervisor-backoff-jitter (В5 · NEW-6a)

**Ветка:** `feat/supervisor-backoff-jitter`
**Refs:** `plans/current-path/plan.md` (В5 NEW-6), `plans/2026-07-06_constructor-master/plan.md`
**Слой:** framework
**Статус:** реализовано (первый инкремент NEW-6; стратегии/группы/эскалация — NEW-6b далее)

## Цель

Экспоненциальный backoff + jitter для авто-рестарта процессов. Сейчас backoff
фиксированный (`policy.backoff_sec`) — при crash-loop это N рестартов подряд с
одинаковой паузой. Экспонента гасит шторм (пауза растёт), jitter размазывает
одновременный рестарт группы (thundering herd). Аддитивно, дефолт = прежнее поведение.

## Сделано

- `RestartPolicy` (+ поля, все с backward-safe дефолтами):
  `backoff_mode: "fixed"(деф)|"exponential"`, `backoff_max_sec=60.0`, `backoff_jitter=0.0`.
- `ProcessMonitor._compute_backoff(policy, attempt, rand=None)` — чистый staticmethod:
  fixed → `backoff_sec`; exponential → `min(backoff_sec*2**(attempt-1), backoff_max_sec)`;
  jitter → множитель `[1-j, 1+j]` (r∈[0,1), инъекция `rand` для детерминизма тестов).
- Подключён в `_try_auto_restart` (`backoff = self._compute_backoff(policy, attempt)`),
  где `attempt = count+1` (счётчик рестартов в окне). Питает pending/recovery-дедлайны
  и событие `restarting`.
- Проброс из рецепта: `_resolve_policy` уже делает `RestartPolicy(**rp)` — новые ключи
  доходят, старые dict'ы работают с дефолтами.

## Acceptance

- [x] fixed (деф) — const `backoff_sec` для любой попытки (backward-compat).
- [x] exponential — `2,4,8,16,…` с потолком `backoff_max_sec`.
- [x] jitter — в `[base·(1-j), base·(1+j)]`, ≥0, clamp `j>1→1`, r=0.5 → без изменения.
- [x] legacy restart_policy-dict без новых полей → дефолты (fixed), поведение прежнее.
- [x] Тесты: `test_backoff.py` (16) + `test_process_monitor.py` зелёные (88 passed).
- [ ] Профильный framework-suite зелёный; Fable-ревью.

## Out of scope (→ NEW-6b)

- `strategy` (rest_for_one/one_for_all) + именованные группы супервизии (OTP-модель:
  упорядоченный состав + стратегия; порядок rest_for_one из `depends_on`, когда не задан).
- Эскалация give-up на уровень группы.
- NEW-7 alerting поверх supervisor-событий.
