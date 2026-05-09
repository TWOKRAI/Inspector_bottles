# -*- coding: utf-8 -*-
"""Тесты SDK errors: SdkError, check_sdk_error, error_description."""
from __future__ import annotations

import pytest

from hikvision_camera_module_2.sdk.errors import (
    SdkError,
    check_sdk_error,
    error_description,
    MV_OK,
    MV_E_HANDLE,
    MV_E_PARAMETER,
    MV_E_NODATA,
)


class TestSdkError:
    """Тесты создания и атрибутов SdkError."""

    def test_sdk_error_creation(self):
        """SdkError хранит код, операцию и описание."""
        err = SdkError(MV_E_HANDLE, "open_device")

        assert err.code == MV_E_HANDLE
        assert err.operation == "open_device"
        assert err.description == "Неверный или отсутствующий handle"
        # Строковое представление содержит hex-код
        assert "0x80000000" in str(err)
        assert "open_device" in str(err)

    def test_sdk_error_is_exception(self):
        """SdkError наследует Exception."""
        err = SdkError(MV_E_PARAMETER, "set_param")
        assert isinstance(err, Exception)


class TestCheckSdkError:
    """Тесты утилиты check_sdk_error."""

    def test_check_sdk_error_ok(self):
        """MV_OK (0) не бросает исключение."""
        # Не должно выбросить ничего
        check_sdk_error(MV_OK, "any_operation")

    def test_check_sdk_error_raises(self):
        """Ненулевой код бросает SdkError."""
        with pytest.raises(SdkError) as exc_info:
            check_sdk_error(MV_E_NODATA, "get_frame")

        assert exc_info.value.code == MV_E_NODATA
        assert exc_info.value.operation == "get_frame"

    def test_check_sdk_error_raises_unknown_code(self):
        """Неизвестный ненулевой код тоже бросает SdkError."""
        unknown_code = 0xDEADBEEF
        with pytest.raises(SdkError) as exc_info:
            check_sdk_error(unknown_code, "unknown_op")

        assert exc_info.value.code == unknown_code


class TestErrorDescription:
    """Тесты функции error_description."""

    def test_error_description_known(self):
        """Известные коды возвращают описание на русском."""
        desc = error_description(MV_E_HANDLE)
        assert desc == "Неверный или отсутствующий handle"

        desc2 = error_description(MV_E_PARAMETER)
        assert desc2 == "Неверный параметр"

    def test_error_description_ok(self):
        """MV_OK тоже имеет описание."""
        desc = error_description(MV_OK)
        assert desc == "Успех"

    def test_error_description_unknown(self):
        """Неизвестный код возвращает generic-строку с hex."""
        desc = error_description(0x99999999)
        assert "Неизвестный код ошибки" in desc
        assert "0x99999999" in desc.lower()
