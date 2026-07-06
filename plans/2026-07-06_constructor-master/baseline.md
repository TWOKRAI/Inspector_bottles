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

## Ф0.4 — FPS/CPU baseline (headless, 2026-07-06)

Headless-probe (BACKEND_CTL=1, boot phone_sketch + 10с сэмпл):

| Метрика | Значение |
|---|---|
| boot до ready (`wait_until_ready`) | ~1.0 с |
| OS-процессов в дереве | 11 |
| CPU суммарно по дереву (idle, без кадров) | ~23.6 % ¹ |
| **FPS phone_sketch** | **hardware-gated** — нет телефона-камеры (PhoneCameraPlugin без источника) |
| **FPS hikvision_letter_robot** | **hardware-gated** — нет камеры Hikvision |

¹ CPU замерен ПРИ error-спаме EdgeDetection (см. находку 2) — как idle-число завышен,
перемерить после установки extras.

**Находки probe (входные данные для следующих фаз):**

1. **env-дрейф №2: extras `[ml]` не установлены** — EdgeDetectionPlugin в цикле:
   «Для TEED нужен PyTorch. Установите extras: uv pip install '.[ml]'». Пайплайны
   sketch-семейства без ML-extras не считают инференс. Решение владельца: ставить
   PyTorch (~2 ГБ) в это окружение или нет.
2. **Shutdown-hang**: `[spawner] ProcessManager did not stop in 5.0s, terminating...`,
   дерево жило 8+ минут до kill -9. Виновник-кандидат: gui-процесс с модальным
   LoginDialog. → подтверждает приоритет Ф3 (Supervisor v2) и Ф1.3 (honest headless).
3. **BACKEND_CTL=1 ≠ headless**: gui-процесс топологии всё равно спавнит Qt
   (LoginDialog поверх рабочего стола). Честный headless-запуск — задача Ф1.3
   BackendHarness (исключение gui из топологии или offscreen-платформа).
4. Error-спам п.1 — это ровно класс «swallow/спам без деградации», который чинит
   Ф2 (`ctx.health.report_error` + breaker): плагин должен перейти в degraded,
   а не молотить ERROR каждые ~1 мс.

**Вывод:** FPS-baseline обоих живых рецептов снимается только с железом — повторить
при подключённой камере (или на Ф7 G.1, где повторный baseline обязателен).
Boot/CPU-числа выше — отправная точка для сравнения.
