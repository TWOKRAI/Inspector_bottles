"""Тесты валидации SettingsProfile (Task 1.2).

Проверяет, что невалидные значения профиля поднимают ValidationError,
а корректные данные создают модель с ожидаемыми значениями.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from multiprocess_prototype.config.settings_profile import SettingsProfile


class TestSettingsProfileValid:
    """Валидные профили — должны создаваться без ошибок."""

    def test_valid_full_profile(self) -> None:
        """Полный валидный профиль создаётся корректно."""
        profile = SettingsProfile.model_validate(
            {
                "camera_count": 4,
                "ring_buffer_size": 5,
                "worker_pool_size": 2,
                "camera_source_type": "webcam",
            }
        )
        assert profile.camera_count == 4
        assert profile.ring_buffer_size == 5
        assert profile.worker_pool_size == 2
        assert profile.camera_source_type == "webcam"

    def test_empty_dict_returns_defaults(self) -> None:
        """Пустой dict → дефолтные значения."""
        profile = SettingsProfile.model_validate({})
        assert profile.camera_count == 1
        assert profile.ring_buffer_size == 3
        assert profile.worker_pool_size == 0
        assert profile.camera_source_type == "simulator"

    def test_all_camera_source_types(self) -> None:
        """Все допустимые типы источника камеры проходят валидацию."""
        for source_type in ("simulator", "webcam", "hikvision", "file"):
            profile = SettingsProfile.model_validate({"camera_source_type": source_type})
            assert profile.camera_source_type == source_type

    def test_camera_count_boundary_min(self) -> None:
        """camera_count = 1 (граничный минимум) — валидно."""
        profile = SettingsProfile.model_validate({"camera_count": 1})
        assert profile.camera_count == 1

    def test_camera_count_boundary_max(self) -> None:
        """camera_count = 16 (граничный максимум) — валидно."""
        profile = SettingsProfile.model_validate({"camera_count": 16})
        assert profile.camera_count == 16

    def test_ring_buffer_size_boundary_min(self) -> None:
        """ring_buffer_size = 2 (граничный минимум) — валидно."""
        profile = SettingsProfile.model_validate({"ring_buffer_size": 2})
        assert profile.ring_buffer_size == 2

    def test_worker_pool_size_zero(self) -> None:
        """worker_pool_size = 0 (отключён) — валидно."""
        profile = SettingsProfile.model_validate({"worker_pool_size": 0})
        assert profile.worker_pool_size == 0


class TestSettingsProfileInvalid:
    """Невалидные значения — должны поднимать ValidationError."""

    def test_camera_count_negative(self) -> None:
        """camera_count: -1 → ValidationError."""
        with pytest.raises(ValidationError):
            SettingsProfile.model_validate({"camera_count": -1})

    def test_camera_count_zero(self) -> None:
        """camera_count: 0 → ValidationError (минимум 1)."""
        with pytest.raises(ValidationError):
            SettingsProfile.model_validate({"camera_count": 0})

    def test_camera_count_exceeds_max(self) -> None:
        """camera_count: 17 → ValidationError (максимум 16)."""
        with pytest.raises(ValidationError):
            SettingsProfile.model_validate({"camera_count": 17})

    def test_ring_buffer_size_zero(self) -> None:
        """ring_buffer_size: 0 → ValidationError (минимум 2)."""
        with pytest.raises(ValidationError):
            SettingsProfile.model_validate({"ring_buffer_size": 0})

    def test_ring_buffer_size_one(self) -> None:
        """ring_buffer_size: 1 → ValidationError (минимум 2 для корректного fan-out)."""
        with pytest.raises(ValidationError):
            SettingsProfile.model_validate({"ring_buffer_size": 1})

    def test_camera_source_type_unknown(self) -> None:
        """camera_source_type: 'unknown' → ValidationError."""
        with pytest.raises(ValidationError):
            SettingsProfile.model_validate({"camera_source_type": "unknown"})

    def test_camera_source_type_empty_string(self) -> None:
        """camera_source_type: '' → ValidationError."""
        with pytest.raises(ValidationError):
            SettingsProfile.model_validate({"camera_source_type": ""})

    def test_worker_pool_size_negative(self) -> None:
        """worker_pool_size: -1 → ValidationError."""
        with pytest.raises(ValidationError):
            SettingsProfile.model_validate({"worker_pool_size": -1})

    def test_worker_pool_size_exceeds_max(self) -> None:
        """worker_pool_size: 9 → ValidationError (максимум 8)."""
        with pytest.raises(ValidationError):
            SettingsProfile.model_validate({"worker_pool_size": 9})
