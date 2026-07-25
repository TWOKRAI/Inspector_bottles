"""
RestartPolicy — политика автоматического перезапуска процессов.

Используется ProcessMonitor для принятия решения о рестарте
упавших (crashed) или зависших (unresponsive) процессов.
"""

from __future__ import annotations

from typing import Literal

from ...data_schema_module import SchemaBase


class RestartPolicy(SchemaBase):
    """Политика авто-рестарта процессов.

    Attributes:
        enabled: Включён ли авто-рестарт
        max_retries: Максимальное число попыток рестарта В ОКНЕ window_sec
        backoff_sec: Базовая задержка перед рестартом (секунды). При
            ``backoff_mode="exponential"`` — задержка ПЕРВОЙ попытки, дальше растёт.
        backoff_mode: ``"fixed"`` (по умолчанию, прежнее поведение — постоянный
            ``backoff_sec``) или ``"exponential"`` (``backoff_sec * 2**(attempt-1)``,
            ограничено ``backoff_max_sec``). Экспонента гасит crash-loop-шторм:
            частые падения → быстро растущая пауза (NEW-6a).
        backoff_max_sec: Потолок задержки для ``exponential`` (секунды). Защита от
            ухода паузы в бесконечность при большом числе попыток.
        backoff_jitter: Доля случайного разброса задержки, ``0.0..1.0``. Итоговая
            задержка = base * (1 ± uniform(0, jitter)). ``0`` → без джиттера (прежнее
            детерминированное поведение). Джиттер размазывает одновременный рестарт
            группы процессов (thundering herd), NEW-6a.
        window_sec: Окно стабильности (секунды) для подсчёта попыток. Метки
            рестартов старше ``now - window_sec`` протухают и не считаются —
            это защищает от вечной flap-петли (пожизненный счётчик сдавался
            навсегда), одновременно давая процессу «отдышаться». ``0`` →
            пожизненный счётчик как раньше (метки не протухают).
        restart_on_crash: Рестартовать при crashed (exitcode != 0)
        restart_on_unresponsive: Рестартовать при отсутствии heartbeat
        restart_on_health_failed: Рестартовать живой (heartbeating) процесс, который
            САМ выставил ``health.status=failed`` (тихо-мёртвый: liveness ОК, но
            плагин/breaker объявил фатальный отказ). H4 (Ф4-добор). Срабатывает
            только при включённом env-флаге ``FW_HEALTH_RESTART`` (default off) —
            liveness-рестарт (crash/unresponsive) от этого флага не зависит.

    ВНИМАНИЕ (exponential + окно give-up, NEW-6a → уточняется в NEW-6b): счётчик
    попыток (``max_retries``/``window_sec``) считает метки рестартов В ОКНЕ, а сама
    exponential-пауза РАСХОДУЕТ это окно. Если ``backoff_max_sec`` сопоставим с
    ``window_sec / max_retries``, растущая пауза даёт старым меткам протухнуть быстрее,
    чем счётчик дойдёт до ``max_retries`` → ``gave_up``/FAILED может НЕ наступить
    (вечный throttled crash-loop без терминального события). Дефолты
    ``backoff_max_sec=60 == window_sec=60`` с ``max_retries=3`` (2/4/8с) безопасны, но
    при ``exponential`` держите ``backoff_max_sec`` СУЩЕСТВЕННО меньше
    ``window_sec / max_retries``. Полное решение (экспонента от consecutive-failure
    счётчика, сбрасываемого только по recovered) — NEW-6b.
    """

    # Raw-дефолт enabled=False — безопасный «нейтральный» для прямого
    # RestartPolicy() в тестах/минимальных конфигах. В проде композиция ставит
    # enabled=True per-process через FW_AUTORESTART (авто-рестарт-всех, Ф4) —
    # см. process_manager_process._resolve_policy. Т.е. дефолт off, прод on.
    enabled: bool = False
    max_retries: int = 3
    backoff_sec: float = 2.0
    # Literal (не str): опечатка в рецепте ("exponentail") → ValidationError →
    # _resolve_policy падает на глобальную политику с WARNING, а НЕ молча в fixed
    # (класс «проглоченный сбой» — оператор думал бы, что шторм гасится).
    backoff_mode: Literal["fixed", "exponential"] = "fixed"
    backoff_max_sec: float = 60.0
    backoff_jitter: float = 0.0  # доля 0.0..1.0
    window_sec: float = 60.0
    restart_on_crash: bool = True
    restart_on_unresponsive: bool = True
    restart_on_health_failed: bool = True
