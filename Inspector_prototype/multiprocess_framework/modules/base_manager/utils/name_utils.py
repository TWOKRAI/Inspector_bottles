"""
Утилиты для работы с именами адаптеров.

Внутренние функции, используемые внутри модуля.
"""

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


def get_adapter_name_from_class(class_name: str) -> str:
    """
    Определить имя адаптера из имени класса (автоматическое определение).
    
    **Простая логика для базовых случаев.** 
    Для сложных имен классов рекомендуется указывать имя явно в attach_adapter().
    
    Примеры:
        CommandAdapter -> "command"
        ProcessIntegrationAdapter -> "process_integration"
        HTTPClientAdapter -> "httpclient" (простая логика, для точности укажите имя явно)
        XMLParserAdapter -> "xmlparser"
    
    Args:
        class_name: Имя класса адаптера
        
    Returns:
        Имя адаптера в snake_case без суффикса "Adapter"
        
    Note:
        Для сложных случаев (аббревиатуры, длинные имена) рекомендуется 
        указывать имя явно: attach_adapter(adapter, name="rest_api_client")
    """
    # Убираем суффикс "Adapter" если есть
    if class_name.endswith("Adapter"):
        class_name = class_name[:-7]
    
    # Простая конвертация PascalCase в snake_case
    # Не разделяем последовательности заглавных букв (HTTP -> http, а не h_t_t_p)
    # Разделяем только переходы от строчных к заглавным
    
    # Вставляем _ перед заглавными буквами, которые следуют за строчными
    # HTTPClient -> HTTPClient (не разделяем, т.к. нет строчных перед)
    # ProcessIntegration -> Process_Integration (разделяем, т.к. есть строчные)
    name = re.sub(r'([a-z\d])([A-Z])', r'\1_\2', class_name)
    
    # Конвертируем в нижний регистр
    # HTTPClient -> httpclient (последовательности заглавных остаются вместе)
    name = name.lower()
    
    # Убираем двойные подчеркивания если появились
    name = re.sub(r'__+', '_', name)
    
    return name

