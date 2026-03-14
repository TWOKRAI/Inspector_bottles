"""
ProcessData как контейнер для множества ДНК компонентов.

ProcessData хранит в себе множество ComponentDNA, образуя полную картину системы.
"""

from typing import Dict, Any, Optional, List
from ..models.dna import ComponentDNA
from ..factory.dna_factory import DNAFactory


class ProcessDataContainer:
    """
    Контейнер для хранения множества ДНК компонентов в ProcessData.
    
    ProcessData.custom['component_dnas'] = {
        'component_type': {
            'component_name': ComponentDNA,
            ...
        },
        ...
    }
    """
    
    DNA_KEY = 'component_dnas'  # Ключ в ProcessData.custom
    
    def __init__(self, process_data: Any):
        """
        Инициализация контейнера.
        
        Args:
            process_data: Экземпляр ProcessData
        """
        self.process_data = process_data
        self._ensure_structure()
    
    def _ensure_structure(self):
        """Обеспечить наличие структуры в ProcessData."""
        if not hasattr(self.process_data, 'custom'):
            self.process_data.custom = {}
        
        if self.DNA_KEY not in self.process_data.custom:
            self.process_data.custom[self.DNA_KEY] = {}
    
    def register_dna(self, dna: ComponentDNA) -> bool:
        """
        Зарегистрировать ДНК компонента в ProcessData.
        
        Args:
            dna: ComponentDNA компонента
            
        Returns:
            True если регистрация успешна
        """
        self._ensure_structure()
        
        dnas = self.process_data.custom[self.DNA_KEY]
        component_type = dna.component_type.value
        
        if component_type not in dnas:
            dnas[component_type] = {}
        
        # Сохраняем как dict для сериализации
        dnas[component_type][dna.name] = dna.model_dump()
        
        # Обновляем timestamp ProcessData
        if hasattr(self.process_data, 'update_timestamp'):
            self.process_data.update_timestamp()
        
        return True
    
    def get_dna(
        self,
        component_name: str,
        component_type: Optional[str] = None
    ) -> Optional[ComponentDNA]:
        """
        Получить ДНК компонента из ProcessData.
        
        Args:
            component_name: Имя компонента
            component_type: Тип компонента (опционально, для поиска)
            
        Returns:
            ComponentDNA или None
        """
        self._ensure_structure()
        
        dnas = self.process_data.custom.get(self.DNA_KEY, {})
        
        if component_type:
            # Поиск по типу
            if component_type in dnas and component_name in dnas[component_type]:
                dna_data = dnas[component_type][component_name]
                return ComponentDNA(**dna_data)
        else:
            # Поиск по всем типам
            for type_dnas in dnas.values():
                if component_name in type_dnas:
                    dna_data = type_dnas[component_name]
                    return ComponentDNA(**dna_data)
        
        return None
    
    def list_dnas(
        self,
        component_type: Optional[str] = None
    ) -> List[ComponentDNA]:
        """
        Получить список всех ДНК компонентов.
        
        Args:
            component_type: Фильтр по типу компонента
            
        Returns:
            Список ComponentDNA
        """
        self._ensure_structure()
        
        dnas = self.process_data.custom.get(self.DNA_KEY, {})
        result = []
        
        if component_type:
            if component_type in dnas:
                for dna_data in dnas[component_type].values():
                    result.append(ComponentDNA(**dna_data))
        else:
            for type_dnas in dnas.values():
                for dna_data in type_dnas.values():
                    result.append(ComponentDNA(**dna_data))
        
        return result
    
    def get_component_tree(
        self,
        root_component_name: str,
        root_component_type: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Получить дерево компонентов начиная с корневого.
        
        Args:
            root_component_name: Имя корневого компонента
            root_component_type: Тип корневого компонента
            
        Returns:
            Дерево компонентов или None
        """
        root_dna = self.get_dna(root_component_name, root_component_type)
        if not root_dna:
            return None
        
        # Получаем все ДНК для построения дерева
        all_dnas = {}
        for dna in self.list_dnas():
            all_dnas[dna.name] = dna
        
        return DNAFactory.get_component_tree(root_dna, all_dnas)
    
    def get_storage_map(self) -> Dict[str, Any]:
        """
        Получить карту хранилища всех компонентов.
        
        Returns:
            Словарь с информацией о том, где хранится каждый компонент
        """
        result = {}
        
        for dna in self.list_dnas():
            component_id = f"{dna.component_class}:{dna.name}"
            result[component_id] = DNAFactory.get_storage_info(dna)
        
        return result
    
    def clone_component(
        self,
        source_name: str,
        new_name: str,
        source_type: Optional[str] = None,
        **overrides
    ) -> Optional[ComponentDNA]:
        """
        Клонировать компонент с изменениями.
        
        Args:
            source_name: Имя исходного компонента
            new_name: Новое имя компонента
            source_type: Тип исходного компонента
            **overrides: Переопределения полей
            
        Returns:
            Новая ComponentDNA или None
        """
        source_dna = self.get_dna(source_name, source_type)
        if not source_dna:
            return None
        
        new_dna = DNAFactory.clone_component(source_dna, new_name, **overrides)
        self.register_dna(new_dna)
        
        return new_dna
    
    def remove_dna(
        self,
        component_name: str,
        component_type: Optional[str] = None
    ) -> bool:
        """
        Удалить ДНК компонента из ProcessData.
        
        Args:
            component_name: Имя компонента
            component_type: Тип компонента
            
        Returns:
            True если удаление успешно
        """
        self._ensure_structure()
        
        dnas = self.process_data.custom.get(self.DNA_KEY, {})
        
        if component_type:
            if component_type in dnas and component_name in dnas[component_type]:
                del dnas[component_type][component_name]
                if hasattr(self.process_data, 'update_timestamp'):
                    self.process_data.update_timestamp()
                return True
        else:
            for type_dnas in dnas.values():
                if component_name in type_dnas:
                    del type_dnas[component_name]
                    if hasattr(self.process_data, 'update_timestamp'):
                        self.process_data.update_timestamp()
                    return True
        
        return False
    
    def clear(self, component_type: Optional[str] = None):
        """
        Очистить все ДНК компонентов.
        
        Args:
            component_type: Очистить только указанный тип
        """
        self._ensure_structure()
        
        dnas = self.process_data.custom.get(self.DNA_KEY, {})
        
        if component_type:
            if component_type in dnas:
                dnas[component_type].clear()
        else:
            dnas.clear()
        
        if hasattr(self.process_data, 'update_timestamp'):
            self.process_data.update_timestamp()

