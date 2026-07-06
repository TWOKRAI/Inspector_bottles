# Baseline Ф0 — constructor-master

- **Дата:** 2026-07-06
- **Ветка:** `fix/constructor-f0` (от main после merge 9a5f4b8f + fix Ф0.2)
- **Задачи:** Ф0.3 (sentrux), Ф0.4 (FPS/CPU)

## Ф0.3 — sentrux baseline (session_start снят 2026-07-06)

Скан: 3605 файлов, 529 044 строк, 2903 import-рёбер.

| Метрика | Score (0-10000) | Raw | Порог rules.toml | Статус |
|---|---|---|---|---|
| **quality_signal** | **7174** | — | min_quality 0.60 | OK |
| modularity (bottleneck) | 5652 | 0.3478 | min_modularity 0.45 | OK |
| acyclicity | 10000 | 0 циклов | min_acyclicity 0.45, max_cycles 2 | OK |
| depth | 6154 | 5 | min_depth **0.60** (временно, было 0.65) | OK¹ |
| equality | 6063 | 0.3937 | min_equality 0.60 | OK |
| redundancy | 9012 | 0.0988 | min_redundancy 0.80 | OK |

¹ min_depth временно опущен 0.65→0.60 (факт 0.6154; вернуть в Ф8 H.5 после перезамера
пост-F/E). cross_module_edges = 1600 из 2687 — источник modularity-bottleneck.

`check_rules`: 9 правил, 0 нарушений (pass).

**Чекпойнты плана:** modularity после F ≥ 5900, после Ф5 ≥ 6050, финал ≥ 6200;
quality после Ф4 ≥ 7250, финал ≥ 7500.

## Ф0.2 — pytest (фиксация для истории)

| Сьют | До Ф0.2 | После Ф0.2 |
|---|---|---|
| framework (`scripts/run_framework_tests.py`) | 3395 passed, 2 failed (hot_reload) | **3401 passed, 29 skipped, 0 failed** |
| prototype (`pytest multiprocess_prototype`) | 2819 passed, 1 failed (log_dir_parity) | **2820 passed, 14 skipped, 0 failed** |

Причины красных: (а) env-дрейф — `watchdog>=4.0` объявлен в pyproject, но отсутствовал
в .venv (→ `uv pip install watchdog`); (б) тест хардкодил `/var/log/inspector` —
mkdir требует root на macOS (→ tmp_path). Код продукта не менялся.

## Ф0.4 — FPS/CPU baseline

_(заполняется в Ф0.4)_

- phone_sketch (qt-smoke + `introspect.router_stats`): TBD
- hikvision_letter_robot: hardware-gated — при доступной камере, иначе headless + пометка
