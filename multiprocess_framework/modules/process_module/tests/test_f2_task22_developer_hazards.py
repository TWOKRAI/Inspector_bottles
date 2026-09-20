# -*- coding: utf-8 -*-
"""Ф2, задача 2.2 — авторские сторожа ВНУТРЕННИХ опасностей реализации.

Независимый тестер (``test_f2_task22_schema_wiring.py``) доказал КОНТРАКТ — эти
пять свойств родились из чтения СОБСТВЕННОЙ реализации и защищают места, которые
только автор и видит: где новый защитный код может тихо сломаться при следующей
правке рядом, а не то, что задача обещала оператору.

1. Гейт ``errors.enabled=False`` не оживает от ``errors.channels`` — до правки
   ``if cfg.errors.channels: error["channels"] = ...`` не смотрел на пустоту
   ``error`` и дописывал ключ в СНЯТЫЙ словарь, оживляя ``ErrorManager`` через
   заднюю дверь.
2. ``resolve_history_store_settings`` не роняет подъём стора на мусорной секции
   (мусор МЕНЯЕТ РОД защиты по сравнению с ``resolve_history_policy`` — та
   разбирает поля вручную, эта валидирует всю секцию Pydantic'ом целиком, и
   мусор в ЛЮБОМ поле секции способен уронить ВСЕ шесть, если try/except не
   держит).
3. Третья точка дороги ``commands.log_success`` не падает на менеджере без
   ``set_log_success_enabled`` — духless-проверка (``callable``), а не
   предположение о типе.
4. ``IDENTITY_SECTION_KEYS`` с ЧЕТЫРЬМЯ элементами (было три) не скрещивает
   секции: запрос, тронувший только ``history``, не порождает фантомных путей
   ``events.*``/``flight.*``/``voices.*`` в ``expected`` и не завышает ``checked``.
5. Три новых параметра ``observability_effective`` (``command``,
   ``session_ttl_sec``, ``history``) — строго opt-in: вызывающий, не знающий о
   них (старый код), получает ответ БЕЗ новых ключей, а не с ``None``-мусором.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from multiprocess_framework.modules.process_module.configs.observability_config import (
    ObservabilityConfig,
    expand_observability,
)
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    observability_effective,
    observability_verified,
)
from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    resolve_history_store_settings,
)

from .test_observation_policy_review_f4 import _wired


# =========================================================================== #
# H1 — гейт errors.enabled не оживает от errors.channels
# =========================================================================== #
class TestErrorsChannelsDoesNotResurrectTheGate:
    def test_channels_override_alongside_a_disabled_plane_keeps_the_dict_empty(self) -> None:
        cfg = ObservabilityConfig.model_validate(
            {"errors": {"enabled": False, "channels": {"errors_file": {"enabled": False}}}}
        )

        expanded = expand_observability(cfg)

        assert expanded["error"] == {}, (
            f"errors.channels оживил СНЯТЫЙ гейт: {expanded['error']!r} — "
            "`_create_error_manager` увидел бы непустой словарь и создал ErrorManager вопреки enabled=False"
        )

    def test_control_channels_override_alongside_an_enabled_plane_still_lands(self) -> None:
        """Пара-контроль: гейт не должен ГАСИТЬ каналы у ВКЛЮЧЁННОЙ плоскости —
        без неё первый тест проходил бы и у поломки, которая просто убрала ветку
        ``errors.channels`` целиком."""
        cfg = ObservabilityConfig.model_validate(
            {"errors": {"enabled": True, "channels": {"errors_file": {"enabled": False}}}}
        )

        expanded = expand_observability(cfg)

        assert expanded["error"]["channels"] == {"errors_file": {"enabled": False}}, expanded["error"]


# =========================================================================== #
# H2 — resolve_history_store_settings не роняет подъём на мусоре
# =========================================================================== #
class _StoreSettingsSvc:
    """Минимальный процесс для ``process_observability_layers`` (тот же контракт,
    что ``test_observability_history_policy.py::_Svc``, независимо здесь: ДРУГОЙ
    механизм — валидация схемой целиком, а не по-полевой разбор — не должен
    наследовать чужой тестовый двойник молча."""

    def __init__(self, history: Any) -> None:
        self.name = "hist_settings_svc"
        self.warnings: list = []
        self._history = history

    def get_config(self, key: str, default: Any = None) -> Any:
        if key == "observability_app":
            return {"history": self._history}
        return default

    def _log_warning(self, message: str, module: str | None = None) -> None:
        self.warnings.append(str(message))

    def _log_info(self, *a: Any, **k: Any) -> None: ...
    def _log_debug(self, *a: Any, **k: Any) -> None: ...


class TestResolveHistoryStoreSettingsToleratesGarbage:
    def test_a_bad_level_next_to_enabled_does_not_crash_and_falls_back(self) -> None:
        """``level`` мусорный, но `enabled`/`db_path` в секции ЗАДАНЫ валидными —
        целиковая Pydantic-валидация видит ОДНО невалидное поле секции и обязана
        упасть на дефолты ВСЕЙ секции (по докстрингу функции), а не поднять
        исключение наружу."""
        svc = _StoreSettingsSvc({"level": "ГРОМКО-НЕВЕРНО", "enabled": False, "db_path": "custom.db"})

        settings = resolve_history_store_settings(svc)

        assert settings == {"enabled": True, "db_path": ""}, settings
        assert any("history" in w for w in svc.warnings), "мусор прошёл молча"

    def test_a_non_dict_section_does_not_crash(self) -> None:
        svc = _StoreSettingsSvc("не словарь")

        settings = resolve_history_store_settings(svc)

        assert settings == {"enabled": True, "db_path": ""}, settings

    def test_a_clean_section_is_read_verbatim(self) -> None:
        """Контроль: чистая секция не проваливается на дефолт — иначе первые два
        теста прошли бы и у версии, которая ВСЕГДА возвращает дефолт."""
        svc = _StoreSettingsSvc({"enabled": False, "db_path": "custom.db"})

        settings = resolve_history_store_settings(svc)

        assert settings == {"enabled": False, "db_path": "custom.db"}, settings


# =========================================================================== #
# H3 — третья точка дороги commands.log_success не падает на менеджере без сеттера
# =========================================================================== #
class TestCommandApplicationIsDuckTypedNotAssumed:
    def test_reload_with_a_command_manager_lacking_the_setter_does_not_raise(self, tmp_path: Path) -> None:
        """``_wired`` даёт ``_FakeCommandManager`` БЕЗ ``set_log_success_enabled`` —
        ровно тот случай, которым духless-проверка (``callable``) обязана
        поглотиться молча, а не бросить ``AttributeError`` из-под пересборки."""
        _, handlers = _wired(tmp_path)

        res = handlers["config.reload"]({"observability": {"commands": {"log_success": True}}})

        assert res["success"] is True, res


# =========================================================================== #
# H4 — четыре IDENTITY_SECTION_KEYS не скрещиваются
# =========================================================================== #
class TestIdentitySectionsDoNotCrossContaminate:
    def test_requesting_only_history_does_not_leak_phantom_paths_for_the_others(self) -> None:
        request = {"history": {"level": "WARNING"}}
        effective: Dict[str, Any] = {"history": {"level": "WARNING", "max_rows": 200_000}}

        verified = observability_verified(request, effective)

        assert verified["checked"] == 1, verified
        assert verified["mismatches"] == [], verified
        # Ни один путь events./flight./voices. не имеет права появиться в
        # unverifiable ИЗ-ЗА identity-веток: секции не запрошены — их вовсе не
        # должно быть ни в expected, ни, следовательно, нигде в вердикте.
        leaked = [p for p in verified["unverifiable"] if p.split(".", 1)[0] in ("events", "flight", "voices")]
        assert leaked == [], f"identity-ветки скрестились: {leaked}"


# =========================================================================== #
# H5 — три новых параметра observability_effective строго opt-in
# =========================================================================== #
class TestNewEffectiveParamsAreOptIn:
    def test_omitting_the_three_new_kwargs_omits_the_three_new_keys(self) -> None:
        out = observability_effective()

        assert "command" not in out, out
        assert "session_ttl_sec" not in out, out
        assert "history" not in out, out

    def test_passing_them_adds_exactly_those_keys(self) -> None:
        class _Cmd:
            _log_success_enabled = True

        out = observability_effective(command=_Cmd(), session_ttl_sec=42.0, history={"level": "WARNING"})

        assert out["command"] == {"log_success": True}, out
        assert out["session_ttl_sec"] == 42.0, out
        assert out["history"] == {"level": "WARNING"}, out
