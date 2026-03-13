# Фикстуры для тестов register_discovery: пакет с классами *Registers и *Data.
from pydantic import BaseModel


class TestRegisters(BaseModel):
    value: int = 0


class TestData(BaseModel):
    """Тестовая дата-модель для проверки discovery по суффиксу Data."""
    name: str = ""


__all__ = ["TestRegisters", "TestData"]
