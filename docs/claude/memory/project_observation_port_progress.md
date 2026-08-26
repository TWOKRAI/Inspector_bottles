---
name: project-observation-port-progress
description: observation-port — Ф0–Ф5 закрыты; порт стал единственным писателем чисел, ревью вернуло 3 блокера и все закрыты; ветка feat/observation-port
metadata:
  type: project
---

**Ф0–Ф5 закрыты.** Ветка `feat/observation-port`, 17 коммитов сверх `d1ee1a01`.

## Что построено

- **Ф1–Ф2:** владение = путь, поддерево писателя вместо арбитра; снятие — по писателю.
- **Ф3:** порт наблюдений = четвёртый канонический слот (`observation`), записи `kind=observation`.
- **Ф4:** политика одним glob, пульт порта = пульт логирования, те же L0–L3.
- **Ф5:** порт — ЕДИНСТВЕННЫЙ писатель чисел. `StatsManager` стал ВИДОМ поверх порта
  (пишущие методы форвардят, окна питаются потоком порта через CRM-tap, НЕ через хаб —
  у хаба ёмкость и `drop_oldest`). Род значения маршрутизируется данными одним
  `_route_number` (образец `ErrorManager._level_to_channel`). Слот `"stats"` не тронут:
  13 точек адресации и 57 сайтов вызова не правились.

## Числа, которые стоит помнить

- Дорог записи чисел было **четыре**, а не три: фасад 3/1, прямой `StatsManager` 4/1
  (`drain_adapter`), слот миксина **57/11** (план говорил 42/13 — считал только
  `_record_metric` и пропустил 15 `_record_timing`), `MetricsCollector` 14/2.
- Цена: фасад **2.674–2.850 мкс** сверх прямого вызова, бюджет теста 5.0. Собственная цена
  порта ≈0.93 мкс — этим тестом НЕ охраняется (см. [[feedback-a-delta-benchmark-hides-what-sits-on-both-sides]]).
- Гейт на закрытии: фреймворк **8930 passed / 8 skipped / 1 xfailed**, `statistics_module` 301,
  `process_module` 2423, `data_schema_module` 567, `validate` + `sync` чисто.

## Ревью вернуло фазу — три блокера, все закрыты

`B1` число уходило во 2-ю ступень резолвера и исчезало молча · `B2` `attach_observation_port`
возвращал `True`, не подключив ничего (и `observation_bypasses` читался как идеальный ноль при
мёртвой плоскости) · `B3` доставка шла через `_emit_to_taps`, чей контракт — глушить отказы и
подавлять реентрантность. Каждый перепроверен собственным воспроизведением, не отчётом
исполнителя. Подробности и пары вход→выход — в плане, раздел «ИТОГИ Ф5».

## Хвосты вне фазы

- `ProcessManagerProcess.get_manager` бросает `AttributeError` — вскрыт правкой S2, по существу
  НЕ исправлен, вызывающий защищён `try/except`. Записан в `docs/claude/OPEN_QUESTIONS.md`.
- Тесты фреймворка зависят от порядка: `statistics_module` + `process_module` одним процессом
  pytest дают ~36 красных (старше Ф5 — на `b9bd8345` было 37). Штатный раннер гоняет по одному.
- `scripts/run_framework_tests.py` **выходит с кодом 0 при красных** — читать хвост вывода.
- Флейк `logger_module/tests/test_gate_cost_bench.py` под полной нагрузкой (к Ф5 отношения нет).

Связано: [[feedback-a-guard-that-counts-at-least-once-is-blind]],
[[feedback-unparsed-is-not-absent]], [[feedback-tester-once-per-mechanism-before-the-code]].
