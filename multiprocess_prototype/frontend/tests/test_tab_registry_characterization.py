"""Характеризационный тест НАБОРОВ СТРОК табов/permissions/ролей (NEW-D1).

Фиксирует поведение «до» переноса механизма табов в frontend_module
(TabRegistry). Значения захардкожены литералами — тест НЕ выводит их из
тех же источников, которые рефакторятся, а сверяет фактический результат с
эталоном «до». Инвариант «до = после»: после переезда механизма и деривации
permissions/predefined_roles из единого реестра TabSpec эти наборы обязаны
совпасть байт-в-байт.

Референсы: plans/2026-07-06_constructor-master/plan.md (5.10 / NEW-D1),
docs/audits/2026-07-10_module-responsibility-duplication-map.md (D-1/D-4/D-5).
"""

from __future__ import annotations

# Эталон «до» — порядок вкладок приложения (D-1: механизм; D-4: единый список).
_EXPECTED_TAB_IDS: list[str] = [
    "settings",
    "recipes",
    "processes",
    "services",
    "plugins",
    "pipeline",
    "displays",
    "observability",
]

_EXPECTED_TAB_TITLES: list[str] = [
    "Settings",
    "Recipes",
    "Processes",
    "Services",
    "Plugins",
    "Pipeline",
    "Displays",
    "Наблюдаемость",
]

# Полный каталог permissions приложения (D-4: деривация из реестра табов).
_EXPECTED_PERMISSIONS: frozenset[str] = frozenset(
    {
        "tabs.settings.view",
        "tabs.settings.edit",
        "tabs.recipes.view",
        "tabs.recipes.edit",
        "tabs.processes.view",
        "tabs.processes.edit",
        "tabs.services.view",
        "tabs.services.edit",
        "tabs.plugins.view",
        "tabs.plugins.edit",
        "tabs.pipeline.view",
        "tabs.pipeline.edit",
        "tabs.displays.view",
        "tabs.displays.edit",
        "tabs.observability.view",
        "tabs.observability.edit",
        "users.view",
        "users.create",
        "users.edit",
        "users.delete",
        "users.reset_password",
        "roles.view",
        "roles.edit",
        "roles.create",
        "roles.delete",
    }
)

# Predefined роли — эталонные наборы permissions (D-5: деривация из реестра).
_EXPECTED_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "dev": frozenset({"*"}),
    "admin": frozenset(
        {
            "tabs.settings.view",
            "tabs.settings.edit",
            "tabs.recipes.view",
            "tabs.recipes.edit",
            "tabs.processes.view",
            "tabs.processes.edit",
            "tabs.services.view",
            "tabs.services.edit",
            "tabs.plugins.view",
            "tabs.plugins.edit",
            "tabs.pipeline.view",
            "tabs.pipeline.edit",
            "tabs.displays.view",
            "tabs.displays.edit",
            "tabs.observability.view",
            "tabs.observability.edit",
            "users.view",
            "users.create",
            "users.edit",
            "users.delete",
            "users.reset_password",
            "roles.view",
            "roles.edit",
        }
    ),
    "operator": frozenset(
        {
            "tabs.settings.view",
            "tabs.recipes.view",
            "tabs.recipes.edit",
            "tabs.processes.view",
            "tabs.processes.edit",
            "tabs.services.view",
            "tabs.plugins.view",
            "tabs.pipeline.view",
            "tabs.pipeline.edit",
            "tabs.displays.view",
            "tabs.observability.view",
        }
    ),
    "viewer": frozenset(
        {
            "tabs.settings.view",
            "tabs.recipes.view",
            "tabs.processes.view",
            "tabs.services.view",
            "tabs.plugins.view",
            "tabs.pipeline.view",
            "tabs.displays.view",
            "tabs.observability.view",
        }
    ),
}


class TestTabVocabularyCharacterization:
    """Состав/порядок вкладок и view_permission — «до = после»."""

    def test_tab_ids_and_order(self):
        """Порядок tab_id совпадает с эталоном (D-1)."""
        from multiprocess_prototype.frontend.tab_factory import TAB_ORDER

        assert [t["id"] for t in TAB_ORDER] == _EXPECTED_TAB_IDS

    def test_tab_titles_and_order(self):
        """Заголовки вкладок в том же порядке."""
        from multiprocess_prototype.frontend.tab_factory import TAB_ORDER

        assert [t["title"] for t in TAB_ORDER] == _EXPECTED_TAB_TITLES

    def test_view_permission_naming(self):
        """view_permission каждой вкладки = tabs.<id>.view."""
        from multiprocess_prototype.frontend.tab_factory import TAB_ORDER

        for tab in TAB_ORDER:
            assert tab["view_permission"] == f"tabs.{tab['id']}.view"


class TestPermissionsCatalogCharacterization:
    """Полный каталог permissions приложения — «до = после» (D-4)."""

    def test_full_permission_set(self):
        """register_all_permissions даёт ровно эталонный набор из 25 прав."""
        from Services.auth.security import PermissionsRegistry
        from multiprocess_prototype.frontend.permissions import register_all_permissions

        reg = PermissionsRegistry()
        register_all_permissions(reg)
        actual = frozenset(p.name for p in reg.list_all())
        assert actual == _EXPECTED_PERMISSIONS
        assert len(actual) == 25


class TestPredefinedRolesCharacterization:
    """Наборы permissions predefined ролей — «до = после» (D-5)."""

    def test_role_permission_sets(self):
        """dev/admin/operator/viewer имеют эталонные наборы permissions."""
        from Services.auth.predefined_roles import PREDEFINED_ROLES

        for role_name, expected in _EXPECTED_ROLE_PERMISSIONS.items():
            actual = frozenset(PREDEFINED_ROLES[role_name].permissions)
            assert actual == expected, f"Роль {role_name!r}: набор permissions изменился"

    def test_predefined_role_names(self):
        """Состав predefined ролей неизменен."""
        from Services.auth.predefined_roles import PREDEFINED_ROLES

        assert set(PREDEFINED_ROLES.keys()) == {"dev", "admin", "operator", "viewer"}


class TestSingleSourceParity:
    """Единый источник вкладок ↔ производные наборы (D-4/D-5).

    Разделение природы тестов:
    - **литеральные** — операнд сверяется с захардкоженным эталоном «до»
      (`_EXPECTED_*`); это характеризация «до = после».
    - **структурные** — оба операнда деривятся из одного источника; они НЕ
      характеризация, а инвариант деривации (помечены явно ниже).
    - **кросс-слойные** — сравнивают Services-слой с prototype-слоем
      (реальный паритет-guard).
    """

    def test_tabs_registry_is_single_source(self):
        """ЛИТЕРАЛЬНЫЙ: TABS (единый источник) даёт эталонный состав/порядок.

        Порядок вкладок — значимый контракт (`.rules/gui.md`: Settings первым),
        поэтому сверка порядок-чувствительная (list == list с литеральным эталоном).
        """
        from multiprocess_prototype.frontend.tabs_registry import TABS, tab_ids

        assert [spec.id for spec in TABS] == _EXPECTED_TAB_IDS
        assert tab_ids() == _EXPECTED_TAB_IDS  # literal order contract

    def test_permissions_derived_from_tabs_registry(self):
        """СТРУКТУРНЫЙ (не характеризация): каждая вкладка из TABS даёт view+edit.

        Оба операнда из tabs_registry — это инвариант деривации D-4, а не сверка
        с эталоном «до». Литеральный набор из 25 permissions зафиксирован отдельно
        в `TestPermissionsCatalogCharacterization.test_full_permission_set`.
        """
        from Services.auth.security import PermissionsRegistry
        from multiprocess_prototype.frontend.permissions import register_all_permissions
        from multiprocess_prototype.frontend.tabs_registry import tab_ids

        reg = PermissionsRegistry()
        register_all_permissions(reg)
        names = {p.name for p in reg.list_all()}
        for tab_id in tab_ids():
            assert f"tabs.{tab_id}.view" in names
            assert f"tabs.{tab_id}.edit" in names

    def test_predefined_roles_tab_parity(self):
        """КРОСС-СЛОЙНЫЙ (D-5): паритет по множеству Services ↔ prototype.

        Обратный импорт `Services → prototype` запрещён (правило слоёв №9),
        поэтому единый источник (prototype `TABS`) и Services-локальный
        `DEFAULT_TAB_IDS` сверяются здесь, на слое prototype. Сравнение — **по
        множеству**: predefined-роли order-независимы; порядок вкладок — отдельный
        контракт `TABS` (см. `test_tabs_registry_is_single_source`).
        """
        from Services.auth.predefined_roles import DEFAULT_TAB_IDS
        from multiprocess_prototype.frontend.tabs_registry import tab_ids

        assert set(DEFAULT_TAB_IDS) == set(tab_ids()), (
            "Список вкладок Services.auth.predefined_roles.DEFAULT_TAB_IDS разошёлся "
            "с единым источником tabs_registry.TABS — синхронизируйте DEFAULT_TAB_IDS."
        )

    def test_operator_edit_tabs_subset_of_tab_ids(self):
        """КРОСС-СЛОЙНЫЙ (D-5, F1): _OPERATOR_EDIT_TABS ⊆ вкладки.

        Иначе operator получил бы осиротевший `tabs.<id>.edit` без `.view`.
        Проверяем и Services-локальный список, и единый источник prototype.
        """
        from Services.auth.predefined_roles import (
            _OPERATOR_EDIT_TABS,
            DEFAULT_TAB_IDS,
        )
        from multiprocess_prototype.frontend.tabs_registry import tab_ids

        assert set(_OPERATOR_EDIT_TABS) <= set(DEFAULT_TAB_IDS)
        assert set(_OPERATOR_EDIT_TABS) <= set(tab_ids())

    def test_no_edit_permission_without_view(self):
        """СТРУКТУРНЫЙ (F1): в каждой роли нет `tabs.<id>.edit` без `tabs.<id>.view`.

        Инвариант целостности permission-наборов ролей — edit подразумевает view.
        """
        from Services.auth.predefined_roles import PREDEFINED_ROLES

        for role_name, role in PREDEFINED_ROLES.items():
            perms = set(role.permissions)
            if "*" in perms:  # dev — wildcard, инвариант неприменим
                continue
            for perm in perms:
                if perm.startswith("tabs.") and perm.endswith(".edit"):
                    view = perm[: -len(".edit")] + ".view"
                    assert view in perms, f"Роль {role_name!r}: {perm} без соответствующего {view}"

    def test_build_predefined_roles_rejects_orphan_edit(self):
        """F1: build_predefined_roles громко падает на operator_edit_tabs ⊄ tab_ids."""
        import pytest

        from Services.auth.predefined_roles import build_predefined_roles

        with pytest.raises(ValueError, match="operator_edit_tabs"):
            # 'pipeline' убран из tab_ids, но остаётся в operator_edit_tabs
            build_predefined_roles(
                ("settings", "recipes", "processes"),
                operator_edit_tabs=("recipes", "processes", "pipeline"),
            )

    def test_build_predefined_roles_from_tabs_registry_matches(self):
        """КРОСС-СЛОЙНЫЙ (D-5): роли из TABS-ids совпадают с каноническими.

        Слева — деривация из prototype `tab_ids()`, справа — канонические роли
        (построены из Services `DEFAULT_TAB_IDS`); совпадение подтверждает паритет
        не только состава вкладок, но и итоговых permission-наборов ролей.
        """
        from Services.auth.predefined_roles import (
            PREDEFINED_ROLES,
            build_predefined_roles,
        )
        from multiprocess_prototype.frontend.tabs_registry import tab_ids

        derived = build_predefined_roles(tab_ids())
        for role_name in ("dev", "admin", "operator", "viewer"):
            assert set(derived[role_name].permissions) == set(PREDEFINED_ROLES[role_name].permissions), (
                f"Роль {role_name!r}: деривация из TABS-ids разошлась с канонической"
            )
