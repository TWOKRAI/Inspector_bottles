"""Auto-merge predefined-ролей при AuthManager.initialize()."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from Services.auth import (
    AuthConfig,
    AuthManager,
    LockoutPolicy,
    PasswordPolicy,
    Role,
    YamlUserStorage,
)
from Services.auth.predefined_roles import PREDEFINED_ROLES, expected_permissions


@pytest.fixture
def config(tmp_path: Path) -> AuthConfig:
    return AuthConfig(
        users_path=str(tmp_path / "users.yaml"),
        bcrypt_rounds=4,
        password_policy=PasswordPolicy(
            min_length=8,
            require_classes=3,
            bcrypt_rounds_prod=4,
            bcrypt_rounds_test=4,
        ),
        lockout_policy=LockoutPolicy(
            failed_threshold=5,
            reset_after_sec=1800,
            delays_sec=[30, 60, 120, 240, 480],
        ),
    )


@pytest.fixture
def storage(config: AuthConfig) -> YamlUserStorage:
    return YamlUserStorage(config.users_path)


class TestExpectedPermissions:
    def test_admin_contains_all_tabs(self):
        admin = expected_permissions("admin")
        for tab_id in (
            "settings",
            "recipes",
            "processes",
            "services",
            "plugins",
            "pipeline",
            "displays",
        ):
            assert f"tabs.{tab_id}.view" in admin
            assert f"tabs.{tab_id}.edit" in admin

    def test_admin_contains_users_crud(self):
        admin = expected_permissions("admin")
        for name in (
            "users.view",
            "users.create",
            "users.edit",
            "users.delete",
            "users.reset_password",
            "roles.view",
        ):
            assert name in admin

    def test_viewer_view_only(self):
        viewer = expected_permissions("viewer")
        # Все 7 табов в view, никаких .edit
        assert {p for p in viewer if p.endswith(".edit")} == set()
        assert "tabs.recipes.view" in viewer
        assert "tabs.pipeline.view" in viewer

    def test_operator_edit_only_work_tabs(self):
        operator = expected_permissions("operator")
        # operator может edit recipes/processes/pipeline, view остальное
        edits = {p for p in operator if p.endswith(".edit")}
        assert edits == {
            "tabs.recipes.edit",
            "tabs.processes.edit",
            "tabs.pipeline.edit",
        }
        # view на settings/services/plugins/displays (без edit)
        assert "tabs.settings.view" in operator
        assert "tabs.settings.edit" not in operator

    def test_unknown_role_empty(self):
        assert expected_permissions("nope") == frozenset()


class TestAutoMergePredefinedRoles:
    """Поведение AuthManager.initialize() на разных состояниях хранилища."""

    def test_empty_storage_no_op(self, config: AuthConfig):
        """Пустое хранилище — миграция тихо пропускает, ошибок нет."""
        m = AuthManager(config)
        assert m.initialize() is True
        # Хранилище осталось пустым: bootstrap не запускался.
        assert not Path(config.users_path).exists()

    def test_seeded_predefined_with_partial_perms_gets_merged(
        self, storage: YamlUserStorage, config: AuthConfig
    ):
        """Seed: admin с partial-permissions → после initialize() добавляются недостающие."""
        # Эмулируем «старое» состояние, как в реальном users.yaml до PR3
        legacy_admin = Role(
            name="admin",
            level=9,
            permissions=[
                "tabs.recipes.view",
                "tabs.recipes.edit",
                "tabs.settings.view",
                "tabs.settings.edit",
                "tabs.pipeline.view",
                "tabs.pipeline.edit",
                "users.view",
            ],
        )
        storage.save_roles({"admin": legacy_admin})

        m = AuthManager(config)
        m.initialize()

        loaded = storage.load_roles()
        merged = set(loaded["admin"].permissions)

        # Все эталонные permissions admin теперь присутствуют.
        assert expected_permissions("admin").issubset(merged)
        # Старые permissions сохранились (не удалены).
        assert "tabs.recipes.view" in merged

    def test_seeded_custom_role_untouched(
        self, storage: YamlUserStorage, config: AuthConfig
    ):
        """Custom-роли вне списка predefined не затрагиваются миграцией."""
        custom = Role(name="qa_lead", level=4, permissions=["tabs.recipes.view"])
        storage.save_roles({"qa_lead": custom})

        m = AuthManager(config)
        m.initialize()

        loaded = storage.load_roles()
        assert "qa_lead" in loaded
        assert list(loaded["qa_lead"].permissions) == ["tabs.recipes.view"]

    def test_seeded_missing_predefined_role_is_restored(
        self, storage: YamlUserStorage, config: AuthConfig
    ):
        """Если predefined роль удалена — восстанавливается из spec."""
        # Сохраняем только admin (operator/viewer/dev отсутствуют)
        storage.save_roles({"admin": PREDEFINED_ROLES["admin"]})

        m = AuthManager(config)
        m.initialize()

        loaded = storage.load_roles()
        assert {"dev", "admin", "operator", "viewer"}.issubset(loaded.keys())
        assert set(loaded["viewer"].permissions) == set(
            expected_permissions("viewer")
        )

    def test_idempotent(self, storage: YamlUserStorage, config: AuthConfig):
        """Повторный initialize() ничего не меняет (no-op)."""
        storage.save_roles(dict(PREDEFINED_ROLES))

        m1 = AuthManager(config)
        m1.initialize()
        before = storage.load_roles()

        m2 = AuthManager(config)
        m2.initialize()
        after = storage.load_roles()

        # Сериализуемое представление одинаковое
        assert {n: set(r.permissions) for n, r in before.items()} == {
            n: set(r.permissions) for n, r in after.items()
        }
