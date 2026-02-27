"""
Утилиты для экспорта конфигов из ProcessData.

Позволяет создавать конфиг-чертежи из существующих ProcessData (ДНК → чертеж).
Это полезно для создания конфигов из уже работающих процессов или
для сохранения текущей конфигурации системы.

Пример использования:
    from ...Process_manager_module.builders import export_process_data_to_config
    
    # Экспорт одного процесса
    config = export_process_data_to_config(process_data)
    
    # Экспорт всех процессов из SharedResourcesManager
    all_configs = export_all_processes_to_config(shared_resources)
    
    # Сохранение в YAML файл
    save_config_to_yaml(config, "exported_config.yaml")
"""

import yaml
from typing import Dict, Any, Optional, List
from pathlib import Path
from ...Shared_resources_module import SharedResourcesManager, ProcessData, ProcessDataKeys


def export_process_data_to_config(process_data: ProcessData) -> Dict[str, Any]:
    """
    Экспортирует ProcessData в формат конфигурации процесса.
    
    Создает конфиг-чертеж из существующей ProcessData (ДНК → чертеж).
    
    Args:
        process_data: Экземпляр ProcessData для экспорта
    
    Returns:
        Словарь конфигурации процесса в формате для YAML/ConfigManager
    
    Пример:
        process_data = shared_resources.get_process_data("ChatProcess")
        config = export_process_data_to_config(process_data)
    """
    return process_data.export_to_config()


def export_all_processes_to_config(
    shared_resources: SharedResourcesManager,
    process_names: Optional[List[str]] = None
) -> Dict[str, Dict[str, Any]]:
    """
    Экспортирует все процессы из SharedResourcesManager в формат конфигурации.
    
    Args:
        shared_resources: SharedResourcesManager с зарегистрированными процессами
        process_names: Список имен процессов для экспорта (если None, экспортируются все)
    
    Returns:
        Словарь конфигураций процессов {process_name: config_dict}
    
    Пример:
        all_configs = export_all_processes_to_config(shared_resources)
        # Сохранить в файл
        save_config_to_yaml(all_configs, "all_processes_config.yaml")
    """
    configs = {}
    
    if process_names is None:
        # Получаем все процессы
        all_states = shared_resources.get_all_process_states()
        process_names = list(all_states.keys())
    
    for process_name in process_names:
        process_data = shared_resources.get_process_data(process_name)
        if process_data:
            try:
                config = export_process_data_to_config(process_data)
                configs[process_name] = config
            except Exception as e:
                # Логируем ошибку но продолжаем экспорт других процессов
                print(f"⚠️ Failed to export process '{process_name}': {e}")
    
    return configs


def save_config_to_yaml(
    config: Dict[str, Any],
    file_path: str | Path,
    process_name: Optional[str] = None
) -> bool:
    """
    Сохраняет конфигурацию процесса в YAML файл.
    
    Args:
        config: Словарь конфигурации процесса или словарь конфигураций процессов
        file_path: Путь к файлу для сохранения
        process_name: Имя процесса (если config - конфигурация одного процесса)
    
    Returns:
        True если сохранение успешно
    
    Пример:
        # Сохранение одного процесса
        config = export_process_data_to_config(process_data)
        save_config_to_yaml(config, "chat_process.yaml", "ChatProcess")
        
        # Сохранение всех процессов
        all_configs = export_all_processes_to_config(shared_resources)
        save_config_to_yaml(all_configs, "all_processes.yaml")
    """
    try:
        file_path = Path(file_path)
        
        # Если передан один процесс и указано имя, оборачиваем в формат processes
        if process_name and isinstance(config, dict) and "name" in config:
            yaml_data = {
                "_meta": {
                    "version": "1.0.0",
                    "exported_from": "ProcessData"
                },
                "processes": {
                    process_name: config
                }
            }
        # Если передан словарь процессов, используем формат processes
        elif isinstance(config, dict) and all(isinstance(v, dict) and "name" in v for v in config.values()):
            yaml_data = {
                "_meta": {
                    "version": "1.0.0",
                    "exported_from": "ProcessData"
                },
                "processes": config
            }
        # Иначе сохраняем как есть
        else:
            yaml_data = config
        
        # Сохраняем в файл
        with open(file_path, 'w', encoding='utf-8') as f:
            yaml.dump(yaml_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        
        return True
    
    except Exception as e:
        print(f"❌ Failed to save config to YAML file '{file_path}': {e}")
        return False


def load_config_from_yaml(file_path: str | Path) -> Dict[str, Any]:
    """
    Загружает конфигурацию процессов из YAML файла.
    
    Args:
        file_path: Путь к YAML файлу
    
    Returns:
        Словарь конфигураций процессов
    
    Пример:
        config = load_config_from_yaml("processes.yaml")
    """
    try:
        file_path = Path(file_path)
        
        with open(file_path, 'r', encoding='utf-8') as f:
            yaml_data = yaml.safe_load(f)
        
        # Если формат с processes, возвращаем processes
        if isinstance(yaml_data, dict) and "processes" in yaml_data:
            return yaml_data["processes"]
        
        return yaml_data
    
    except Exception as e:
        raise ValueError(f"Failed to load config from YAML file '{file_path}': {e}")


def export_process_to_yaml(
    process_data: ProcessData,
    file_path: str | Path
) -> bool:
    """
    Экспортирует ProcessData в YAML файл (удобная функция-обертка).
    
    Args:
        process_data: Экземпляр ProcessData для экспорта
        file_path: Путь к файлу для сохранения
    
    Returns:
        True если экспорт успешен
    
    Пример:
        process_data = shared_resources.get_process_data("ChatProcess")
        export_process_to_yaml(process_data, "chat_process.yaml")
    """
    config = export_process_data_to_config(process_data)
    return save_config_to_yaml(config, file_path, process_data.name)


def export_all_processes_to_yaml(
    shared_resources: SharedResourcesManager,
    file_path: str | Path,
    process_names: Optional[List[str]] = None
) -> bool:
    """
    Экспортирует все процессы из SharedResourcesManager в YAML файл.
    
    Args:
        shared_resources: SharedResourcesManager с зарегистрированными процессами
        file_path: Путь к файлу для сохранения
        process_names: Список имен процессов для экспорта (если None, экспортируются все)
    
    Returns:
        True если экспорт успешен
    
    Пример:
        export_all_processes_to_yaml(shared_resources, "all_processes.yaml")
    """
    configs = export_all_processes_to_config(shared_resources, process_names)
    return save_config_to_yaml(configs, file_path)

