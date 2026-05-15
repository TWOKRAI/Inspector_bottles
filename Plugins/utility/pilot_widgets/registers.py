"""PilotWidgetsRegisters — тестовый стенд формы для всех видов виджетов.

По одному полю на каждый kind из CardsFieldFactory:
    checkbox / slider / spinbox / numeric (float) / combo (literal) /
    color3 / str_short / str_long / path / label (readonly/unsupported).
Плюс одно поле с access_level=5 — для проверки блокировки UI.

Фабрика рисует виджет по FieldMeta.widget; если не указан — по Python-типу.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    FieldRouting,
    SchemaBase,
    register_schema,
)


@register_schema("PilotWidgetsRegistersV1")
class PilotWidgetsRegisters(SchemaBase):
    """Параметры pilot-плагина — стенд для всех видов виджетов фабрики форм."""

    # -------------------------------------------------------------------------
    # 1. checkbox (bool) — основной флаг, гейтит инкремент tick-счётчика
    # -------------------------------------------------------------------------
    enabled: Annotated[
        bool,
        FieldMeta(
            "Enabled",
            info="Если включено — worker инкрементирует tick-счётчик",
            widget="checkbox",
        ),
    ] = False

    # -------------------------------------------------------------------------
    # 2. checkbox (bool) — гейт логирования
    # -------------------------------------------------------------------------
    info: Annotated[
        bool,
        FieldMeta(
            "Info-log",
            info="Если включено — worker логирует каждый tick",
            widget="checkbox",
        ),
    ] = True

    # -------------------------------------------------------------------------
    # 3. slider (int с min/max) — интервал между tick'ами
    # -------------------------------------------------------------------------
    time_value: Annotated[
        int,
        FieldMeta(
            "Период tick",
            info="Время между tick-ами worker'а",
            widget="slider",
            min=1,
            max=60,
            unit="s",
        ),
    ] = 1

    # -------------------------------------------------------------------------
    # 4. spinbox (int без явного диапазона / большой диапазон)
    # -------------------------------------------------------------------------
    counter_max: Annotated[
        int,
        FieldMeta(
            "Лимит счётчика",
            info="Tick-счётчик сбрасывается при достижении (0 — без лимита)",
            widget="spinbox",
            min=0,
            max=1000000,
        ),
    ] = 0

    # -------------------------------------------------------------------------
    # 5. numeric (float) — множитель + decimals + unit
    # -------------------------------------------------------------------------
    multiplier: Annotated[
        float,
        FieldMeta(
            "Множитель tick",
            info="На сколько прибавлять к счётчику за один tick",
            widget="numeric",
            min=0.1,
            max=10.0,
            transfer_k=0.1,
            round_k=2,
            unit="x",
        ),
    ] = 1.0

    # -------------------------------------------------------------------------
    # 6. combo (Literal) — режим работы
    # -------------------------------------------------------------------------
    mode: Annotated[
        Literal["fast", "normal", "slow"],
        FieldMeta(
            "Режим",
            info="Скорость работы: fast=0.5x интервала, normal=1x, slow=2x",
            widget="combo",
        ),
    ] = "normal"

    # -------------------------------------------------------------------------
    # 7. color3 (tuple[int,int,int]) — цвет статуса (RGB 0..255)
    # -------------------------------------------------------------------------
    color: Annotated[
        tuple[int, int, int],
        FieldMeta(
            "Цвет статуса",
            info="RGB-триплет, публикуется в state_proxy для GUI",
            widget="color3",
        ),
    ] = (0, 128, 255)

    # -------------------------------------------------------------------------
    # 8. str_short (короткая строка) — префикс лога
    # -------------------------------------------------------------------------
    label_text: Annotated[
        str,
        FieldMeta(
            "Префикс лога",
            info="Подставляется в [<prefix>] tick #N",
            widget="str",
        ),
    ] = "pilot_widgets"

    # -------------------------------------------------------------------------
    # 9. str_long (длинная строка) — заметки (>120 символов default)
    # -------------------------------------------------------------------------
    notes: Annotated[
        str,
        FieldMeta(
            "Заметки",
            info="Свободный текст; публикуется в state_proxy для проверки text-виджета",
            widget="text",
        ),
    ] = (
        "Это поле тестирует str_long рендер через QPlainTextEdit (read-only, h=60). "
        "Default >120 символов, чтобы фабрика однозначно определила kind=str_long "
        'даже без widget="text". Используется как заметка для оператора.'
    )

    # -------------------------------------------------------------------------
    # 10. path (Path) — путь к файлу
    # -------------------------------------------------------------------------
    data_file: Annotated[
        Path,
        FieldMeta(
            "Файл данных",
            info="Путь к файлу (picker — Phase 10B)",
            widget="path",
        ),
    ] = Path("data/pilot.json")

    # -------------------------------------------------------------------------
    # 11. label (readonly / unsupported) — статус, не редактируется
    # -------------------------------------------------------------------------
    status_info: Annotated[
        str,
        FieldMeta(
            "Статус (readonly)",
            info="Заглушка для проверки label/unsupported builder",
            widget="label",
            readonly=True,
        ),
    ] = "idle"

    # -------------------------------------------------------------------------
    # 12. checkbox с access_level=5 — для smoke-теста блокировки UI
    # -------------------------------------------------------------------------
    admin_only: Annotated[
        bool,
        FieldMeta(
            "Admin-only",
            info="Требуется уровень доступа 5+ — UI должен быть disabled при user_level<5",
            widget="checkbox",
            access_level=5,
        ),
    ] = False

    # -------------------------------------------------------------------------
    # 13. Multi-target smoke — broadcast_flag (fan-out в pilot_a + pilot_b)
    # -------------------------------------------------------------------------
    broadcast_flag: Annotated[
        bool,
        FieldMeta(
            "Broadcast flag",
            info=(
                "Smoke multi-target: при изменении → fan-out в 2 fake процесса (для теста). "
                "pilot_a и pilot_b — фиктивные targets; bridge попытается отправить, "
                "sender выдаст warning о неизвестном target — это ожидаемо."
            ),
            widget="checkbox",
            routing=FieldRouting(channel="control_pilot", process_targets=("pilot_a", "pilot_b")),
        ),
    ] = False
