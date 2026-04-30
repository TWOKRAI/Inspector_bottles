"""
Форматеры для визуализации и генерации документации схем.

Базовые форматеры, реализующие интерфейсы IVisualizationFormatter и IDocumentationFormatter.
"""

from typing import Dict, Any, List
from abc import ABC
import json
from datetime import datetime

from ..core.interfaces import IVisualizationFormatter, IDocumentationFormatter


# ============================================================================
# Форматеры визуализации
# ============================================================================

class TextVisualizationFormatter(IVisualizationFormatter):
    """Текстовый форматер визуализации."""
    
    @property
    def format_name(self) -> str:
        return "text"
    
    def format(self, schema_name: str, schema_info: Dict[str, Any]) -> str:
        """Форматировать как текст."""
        lines = [
            f"Схема: {schema_name}",
            "=" * 80,
            ""
        ]
        
        if schema_info.get("docstring"):
            lines.append(f"Описание: {schema_info['docstring']}")
            lines.append("")
        
        lines.append("Поля:")
        lines.append("-" * 80)
        
        for field in schema_info.get("fields", []):
            field_line = f"  {field['name']}"
            
            if "type" in field:
                field_line += f": {field['type']}"
            
            if not field.get("required", True):
                field_line += " (опционально)"
            
            if "default" in field:
                field_line += f" = {field['default']}"
            
            lines.append(field_line)
            
            if "description" in field:
                lines.append(f"    └─ {field['description']}")
        
        return "\n".join(lines)


class JsonVisualizationFormatter(IVisualizationFormatter):
    """JSON форматер визуализации."""
    
    @property
    def format_name(self) -> str:
        return "json"
    
    def format(self, schema_name: str, schema_info: Dict[str, Any]) -> str:
        """Форматировать как JSON."""
        return json.dumps(schema_info, indent=2, ensure_ascii=False)


class HtmlVisualizationFormatter(IVisualizationFormatter):
    """HTML форматер визуализации."""
    
    @property
    def format_name(self) -> str:
        return "html"
    
    def format(self, schema_name: str, schema_info: Dict[str, Any]) -> str:
        """Форматировать как HTML."""
        html = [
            "<!DOCTYPE html>",
            "<html>",
            "<head>",
            f"<title>Схема: {schema_name}</title>",
            "<style>",
            "body { font-family: Arial, sans-serif; margin: 20px; }",
            "h1 { color: #333; }",
            "table { border-collapse: collapse; width: 100%; margin-top: 20px; }",
            "th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }",
            "th { background-color: #4CAF50; color: white; }",
            "tr:nth-child(even) { background-color: #f2f2f2; }",
            ".required { color: red; font-weight: bold; }",
            ".optional { color: blue; }",
            "</style>",
            "</head>",
            "<body>",
            f"<h1>Схема: {schema_name}</h1>"
        ]
        
        if schema_info.get("docstring"):
            html.append(f"<p><strong>Описание:</strong> {schema_info['docstring']}</p>")
        
        html.extend([
            "<table>",
            "<tr>",
            "<th>Поле</th>",
            "<th>Тип</th>",
            "<th>Обязательное</th>",
            "<th>По умолчанию</th>",
            "<th>Описание</th>",
            "</tr>"
        ])
        
        for field in schema_info.get("fields", []):
            required_class = "required" if field.get("required", True) else "optional"
            required_text = "Да" if field.get("required", True) else "Нет"
            
            html.append("<tr>")
            html.append(f"<td><strong>{field['name']}</strong></td>")
            html.append(f"<td>{field.get('type', 'Any')}</td>")
            html.append(f"<td class='{required_class}'>{required_text}</td>")
            html.append(f"<td>{field.get('default', '-')}</td>")
            html.append(f"<td>{field.get('description', '-')}</td>")
            html.append("</tr>")
        
        html.extend([
            "</table>",
            "</body>",
            "</html>"
        ])
        
        return "\n".join(html)


class MermaidVisualizationFormatter(IVisualizationFormatter):
    """Mermaid форматер визуализации."""
    
    @property
    def format_name(self) -> str:
        return "mermaid"
    
    def format(self, schema_name: str, schema_info: Dict[str, Any]) -> str:
        """Форматировать как Mermaid диаграмму."""
        lines = [
            f"classDiagram",
            f"    class {schema_name} {{"
        ]
        
        for field in schema_info.get("fields", []):
            field_type = field.get("type", "Any")
            field_name = field["name"]
            required = "+" if field.get("required", True) else "-"
            
            if "default" in field:
                field_line = f"        {required}{field_name}: {field_type} = {field['default']}"
            else:
                field_line = f"        {required}{field_name}: {field_type}"
            
            lines.append(field_line)
        
        lines.append("    }")
        
        return "\n".join(lines)


# ============================================================================
# Форматеры документации
# ============================================================================

class MarkdownDocumentationFormatter(IDocumentationFormatter):
    """Markdown форматер документации."""
    
    @property
    def format_name(self) -> str:
        return "markdown"
    
    def format_schema(
        self,
        schema_name: str,
        schema_info: Dict[str, Any],
        include_examples: bool = True
    ) -> str:
        """Форматировать схему как Markdown."""
        lines = [
            f"# {schema_name}",
            "",
            f"**Тип:** Схема данных (Pydantic Model)",
            "",
        ]
        
        if schema_info.get("docstring"):
            lines.append("## Описание")
            lines.append("")
            lines.append(schema_info["docstring"])
            lines.append("")
        
        lines.extend([
            "## Поля",
            "",
            "| Поле | Тип | Обязательное | По умолчанию | Описание |",
            "|------|-----|---------------|--------------|----------|"
        ])
        
        for field in schema_info.get("fields", []):
            required = "✅" if field.get("required", True) else "❌"
            default = field.get("default", "-")
            description = field.get("description", "-")
            
            lines.append(
                f"| `{field['name']}` | `{field.get('type', 'Any')}` | {required} | `{default}` | {description} |"
            )
        
        if include_examples:
            lines.extend([
                "",
                "## Пример использования",
                "",
                "```python",
                f"from your_module import {schema_name}",
                "",
                f"# Создание экземпляра с дефолтными значениями",
                f"instance = {schema_name}()",
                "",
                f"# Создание экземпляра с данными",
                f"instance = {schema_name}("
            ])
            
            # Добавляем примеры полей
            example_fields = []
            for field in schema_info.get("fields", [])[:3]:  # Первые 3 поля для примера
                if "default" in field:
                    example_fields.append(f"    {field['name']}={field['default']}")
                else:
                    example_fields.append(f"    {field['name']}=<значение>")
            
            lines.extend(example_fields)
            lines.extend([
                ")",
                "```",
                ""
            ])
        
        return "\n".join(lines)
    
    def format_api_reference(
        self,
        schemas: List[str],
        schema_infos: Dict[str, Dict[str, Any]]
    ) -> str:
        """Форматировать API Reference как Markdown."""
        lines = [
            "# API Reference - Data Schema Module",
            "",
            f"*Сгенерировано: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
            "",
            "## Содержание",
            ""
        ]
        
        # Оглавление
        for schema_name in schemas:
            lines.append(f"- [{schema_name}](#{schema_name.lower()})")
        
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # Документация для каждой схемы
        for schema_name in schemas:
            if schema_name in schema_infos:
                schema_info = schema_infos[schema_name]
                doc = self.format_schema(schema_name, schema_info, include_examples=True)
                lines.append(doc)
                lines.append("")
                lines.append("---")
                lines.append("")
        
        return "\n".join(lines)


class RstDocumentationFormatter(IDocumentationFormatter):
    """reStructuredText форматер документации."""
    
    @property
    def format_name(self) -> str:
        return "rst"
    
    def format_schema(
        self,
        schema_name: str,
        schema_info: Dict[str, Any],
        include_examples: bool = True
    ) -> str:
        """Форматировать схему как reStructuredText."""
        lines = [
            f"{schema_name}",
            "=" * len(schema_name),
            "",
            f"**Тип:** Схема данных (Pydantic Model)",
            "",
        ]
        
        if schema_info.get("docstring"):
            lines.append("Описание")
            lines.append("-" * 10)
            lines.append("")
            lines.append(schema_info["docstring"])
            lines.append("")
        
        lines.extend([
            "Поля",
            "-" * 5,
            "",
        ])
        
        for field in schema_info.get("fields", []):
            lines.append(f"**{field['name']}** (`{field.get('type', 'Any')}`)")
            if "description" in field:
                lines.append(f"  {field['description']}")
            if "default" in field:
                lines.append(f"  По умолчанию: ``{field['default']}``")
            lines.append("")
        
        return "\n".join(lines)
    
    def format_api_reference(
        self,
        schemas: List[str],
        schema_infos: Dict[str, Dict[str, Any]]
    ) -> str:
        """Форматировать API Reference как reStructuredText."""
        lines = [
            "API Reference - Data Schema Module",
            "=" * 50,
            "",
            f"*Сгенерировано: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
            "",
        ]
        
        for schema_name in schemas:
            if schema_name in schema_infos:
                doc = self.format_schema(schema_name, schema_infos[schema_name])
                lines.append(doc)
                lines.append("")
        
        return "\n".join(lines)


class HtmlDocumentationFormatter(IDocumentationFormatter):
    """HTML форматер документации."""
    
    @property
    def format_name(self) -> str:
        return "html"
    
    def format_schema(
        self,
        schema_name: str,
        schema_info: Dict[str, Any],
        include_examples: bool = True
    ) -> str:
        """Форматировать схему как HTML."""
        html = [
            "<!DOCTYPE html>",
            "<html>",
            "<head>",
            f"<title>{schema_name}</title>",
            "<style>",
            "body { font-family: Arial, sans-serif; margin: 20px; }",
            "h1 { color: #333; }",
            "table { border-collapse: collapse; width: 100%; margin-top: 20px; }",
            "th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }",
            "th { background-color: #4CAF50; color: white; }",
            "</style>",
            "</head>",
            "<body>",
            f"<h1>{schema_name}</h1>"
        ]
        
        if schema_info.get("docstring"):
            html.append(f"<p>{schema_info['docstring']}</p>")
        
        html.extend([
            "<table>",
            "<tr><th>Поле</th><th>Тип</th><th>Обязательное</th><th>По умолчанию</th><th>Описание</th></tr>"
        ])
        
        for field in schema_info.get("fields", []):
            required = "Да" if field.get("required", True) else "Нет"
            default = field.get("default", "-")
            description = field.get("description", "-")
            
            html.append(
                f"<tr>"
                f"<td><code>{field['name']}</code></td>"
                f"<td><code>{field.get('type', 'Any')}</code></td>"
                f"<td>{required}</td>"
                f"<td><code>{default}</code></td>"
                f"<td>{description}</td>"
                f"</tr>"
            )
        
        html.extend(["</table>", "</body>", "</html>"])
        return "\n".join(html)
    
    def format_api_reference(
        self,
        schemas: List[str],
        schema_infos: Dict[str, Dict[str, Any]]
    ) -> str:
        """Форматировать API Reference как HTML."""
        html = [
            "<!DOCTYPE html>",
            "<html>",
            "<head>",
            "<title>API Reference - Data Schema Module</title>",
            "<style>",
            "body { font-family: Arial, sans-serif; margin: 20px; }",
            "h1 { color: #333; }",
            "h2 { color: #666; margin-top: 30px; }",
            "table { border-collapse: collapse; width: 100%; margin-top: 20px; }",
            "th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }",
            "th { background-color: #4CAF50; color: white; }",
            "</style>",
            "</head>",
            "<body>",
            "<h1>API Reference - Data Schema Module</h1>",
            f"<p><em>Сгенерировано: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</em></p>",
            "<h2>Содержание</h2>",
            "<ul>"
        ]
        
        for schema_name in schemas:
            html.append(f"<li><a href='#{schema_name.lower()}'>{schema_name}</a></li>")
        
        html.append("</ul>")
        
        for schema_name in schemas:
            if schema_name in schema_infos:
                schema_info = schema_infos[schema_name]
                doc = self.format_schema(schema_name, schema_info, include_examples=True)
                html.append(doc)
        
        html.extend(["</body>", "</html>"])
        return "\n".join(html)

