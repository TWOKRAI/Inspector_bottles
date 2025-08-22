import os
import random
import numpy as np
from pathlib import Path

from generate_bottle_module import BottleGroup, ImageComposer


class BottleGenerator:
    def __init__(self):
        self.CANVAS_WIDTH = 1920
        self.CANVAS_HEIGHT = 1100
        self.BOTTLE_WIDTH = 288
        self.BOTTLE_HEIGHT = 665
        self.GREEN_BG = (210, 210, 210, 255)
        self.image_dir = Path("Create_bottles\Images")
        
        if not os.path.exists(self.image_dir):
            os.makedirs(self.image_dir)
            print(f"Создана папка {self.image_dir}. Добавьте изображения компонентов бутылки.")
        else:
            print(f"Папка {self.image_dir} существует")
    
        self.conveyor = np.zeros((self.CANVAS_HEIGHT, self.CANVAS_WIDTH, 4), dtype=np.uint8)
        self.conveyor[:] = self.GREEN_BG
        
        # Параметры по умолчанию
        self.params = {
            'fill_level': 0.82,
            'cap_visible': True,
            'ring_visible': True,
            'label_visible': True,
            'label_offset': 0,
            'label_angle': 0,
            'label_vertical_offset': 0,
            'bottle_spacing': 160,
            'n_bottles': 1,
        }
        
        # Конфигурация отклонений для нормального и бракованного режимов
        self.normal_deviations = {
            'fill_level_delta': 0.05,
            'cap_position_delta': 5,
            'ring_position_delta': 5,
            'cap_angle_range': (-3, 3),
            'ring_angle_range': (-3, 3),
            'label_offset_range': (-5, 5),
            'label_angle_range': (-2, 2),
            'label_vertical_offset_range': (-5, 5),
            'cap_missing_prob': 0.1,
            'ring_missing_prob': 0.1
        }
        
        self.defect_deviations = {
            'fill_level_delta': 0.2,
            'cap_position_delta': 20,
            'ring_position_delta': 20,
            'cap_angle_range': (-15, 15),
            'ring_angle_range': (-15, 15),
            'label_offset_range': (-30, 30),
            'label_angle_range': (-15, 15),
            'label_vertical_offset_range': (-30, 30),
            'cap_missing_prob': 0.4,
            'ring_missing_prob': 0.4
        }
        
        # Флаги для включения/отключения конкретных отклонений
        self.active_deviations = {
            'fill_level': True,
            'cap_position': True,
            'ring_position': True,
            'cap_angle': True,
            'ring_angle': True,
            'label_offset': True,
            'label_angle': True,
            'label_vertical_offset': True,
            'cap_missing': True,
            'ring_missing': True
        }
        
        self.bottle_config = {
            "bottle": {
                "file": "bottle3.png",
                "position": (0, 90),
                "angle": 0,
                "scale": 1.0,
                "visible": True,
                "offset": 0,
                "filler_enable": True,
                "filler_level": 0.7,
                "filler_color": (100, 200, 200, 180),
            },
            "cap": {
                "file": "cap2.png",
                "position": (51, 122),
                "angle": 0,
                "scale": 1.0,
                "visible": True,
                "offset": 0
            },
            "ring": {
                "file": "ring2.png",
                "position": (51, 155),
                "angle": 0,
                "scale": 1.0,
                "visible": True,
                "offset": 0
            },
            "label": {
                "file": "eticet2.png",
                "position": (0, 490),
                "angle": 0,
                "scale": 1.0,
                "visible": True, 
                "offset": 0
            }
        }

    def set_deviation_active(self, deviation_name, active):
        """Включает или отключает конкретное отклонение"""
        if deviation_name in self.active_deviations:
            self.active_deviations[deviation_name] = active
        else:
            raise ValueError(f"Неизвестное отклонение: {deviation_name}")

    def generate_image(self, defect_mode=False):
        """Генерирует изображение с текущими параметрами"""
        composer = ImageComposer(self.CANVAS_WIDTH, self.CANVAS_HEIGHT, (0, 0, 0, 0))
        composer.add_layer(self.conveyor, (0, 0))
        
        # Выбираем режим отклонений
        deviations = self.defect_deviations if defect_mode else self.normal_deviations
        
        start_x = 100
        current_x = start_x
        
        for i in range(self.params['n_bottles']):
            config = {k: v.copy() for k, v in self.bottle_config.items()}
            
            # Уровень наполнения
            if self.active_deviations['fill_level']:
                fill_delta = random.uniform(-deviations['fill_level_delta'], deviations['fill_level_delta'])
                config['bottle']['filler_level'] = max(0, min(1, 
                    self.params['fill_level'] + fill_delta
                ))
            else:
                config['bottle']['filler_level'] = self.params['fill_level']
            
            # Крышка
            if self.active_deviations['cap_missing']:
                cap_visible = self.params['cap_visible'] and (random.random() > deviations['cap_missing_prob'])
            else:
                cap_visible = self.params['cap_visible']
            
            config['cap']['visible'] = cap_visible
            
            if cap_visible and self.active_deviations['cap_position']:
                cap_base_x, cap_base_y = config['cap']['position']
                cap_offset_y = random.uniform(-deviations['cap_position_delta'], deviations['cap_position_delta'])
                config['cap']['position'] = (cap_base_x, cap_base_y + cap_offset_y)
            
            if cap_visible and self.active_deviations['cap_angle']:
                config['cap']['angle'] = random.uniform(*deviations['cap_angle_range'])
            
            # Кольцо
            if self.active_deviations['ring_missing']:
                ring_visible = self.params['ring_visible'] and (random.random() > deviations['ring_missing_prob'])
            else:
                ring_visible = self.params['ring_visible']
            
            config['ring']['visible'] = ring_visible
            
            if ring_visible and self.active_deviations['ring_position']:
                ring_base_x, ring_base_y = config['ring']['position']
                ring_offset_y = random.uniform(-deviations['ring_position_delta'], deviations['ring_position_delta'])
                config['ring']['position'] = (ring_base_x, ring_base_y + ring_offset_y)
            
            if ring_visible and self.active_deviations['ring_angle']:
                config['ring']['angle'] = random.uniform(*deviations['ring_angle_range'])
            
            # Этикетка
            config['label']['visible'] = self.params['label_visible']
            
            if self.params['label_visible']:
                if self.active_deviations['label_offset']:
                    config['label']['offset'] = random.randint(*deviations['label_offset_range'])
                
                if self.active_deviations['label_angle']:
                    config['label']['angle'] = random.uniform(*deviations['label_angle_range'])
                
                if self.active_deviations['label_vertical_offset']:
                    base_pos = config['label']['position']
                    vertical_offset = random.randint(*deviations['label_vertical_offset_range'])
                    config['label']['position'] = (base_pos[0], base_pos[1] + vertical_offset)
            
            # Создаем бутылку
            bottle = BottleGroup(self.image_dir, config, position=(80+current_x, 0))
            
            # Добавляем слои
            for img, pos in bottle.get_layers():
                composer.add_layer(img, pos)
            
            current_x += self.BOTTLE_WIDTH + self.params['bottle_spacing']

        return composer.compose()
    
    
from PIL import Image
import cv2
import pygame
import os
from datetime import datetime
from pathlib import Path


class BottleGeneratorApp:
    def __init__(self, generator):
        self.generator = generator
        self.current_image = None
        self.image_type = None 
        
        # Создаем папки для сохранения
        self.good_dir = Path("dataset/good")
        self.bad_dir = Path("dataset/bad")
        self.good_dir.mkdir(parents=True, exist_ok=True)
        self.bad_dir.mkdir(parents=True, exist_ok=True)

        self.cap_crop = [(260, 33), (470, 190)]
        
        # Инициализация pygame
        pygame.init()
        self.screen = pygame.display.set_mode((1300, 1000))  # Увеличили окно
        pygame.display.set_caption("Bottle Generator - Advanced Controls")
        self.font = pygame.font.SysFont('Arial', 16)
        self.title_font = pygame.font.SysFont('Arial', 20, bold=True)
        
        # Параметры управления
        self.sliders = {}
        self.toggles = {}
        self.init_controls()
        
    def init_controls(self):
        """Инициализация элементов управления"""
        y_start = 50
        slider_width = 200
        slider_height = 20
        
        # Слайдеры для параметров
        self.sliders = {
            'fill_level': {'rect': pygame.Rect(30, y_start, slider_width, slider_height), 'value': 0.82, 'min': 0.0, 'max': 1.0, 'label': 'Уровень наполнения'},
            'fill_level_delta': {'rect': pygame.Rect(30, y_start + 40, slider_width, slider_height), 'value': 0.05, 'min': 0.0, 'max': 0.3, 'label': 'Разброс наполнения'},
            'label_offset': {'rect': pygame.Rect(30, y_start + 80, slider_width, slider_height), 'value': 0, 'min': -50, 'max': 50, 'label': 'Смещение этикетки X'},
            'label_vertical_offset': {'rect': pygame.Rect(30, y_start + 120, slider_width, slider_height), 'value': 0, 'min': -50, 'max': 50, 'label': 'Смещение этикетки Y'},
            'label_angle': {'rect': pygame.Rect(30, y_start + 160, slider_width, slider_height), 'value': 0, 'min': -15, 'max': 15, 'label': 'Угол этикетки'},
            'cap_position_delta': {'rect': pygame.Rect(30, y_start + 200, slider_width, slider_height), 'value': 10, 'min': 0, 'max': 30, 'label': 'Смещение крышки'},
            'ring_position_delta': {'rect': pygame.Rect(30, y_start + 240, slider_width, slider_height), 'value': 10, 'min': 0, 'max': 30, 'label': 'Смещение кольца'},
            'bottle_spacing': {'rect': pygame.Rect(30, y_start + 280, slider_width, slider_height), 'value': 160, 'min': 100, 'max': 300, 'label': 'Расстояние между бутылками'},
            'n_bottles': {'rect': pygame.Rect(30, y_start + 320, slider_width, slider_height), 'value': 4, 'min': 1, 'max': 8, 'label': 'Количество бутылок'},
        }
        
        # Переключатели
        self.toggles = {
            'cap_visible': {'rect': pygame.Rect(30, y_start + 360, 20, 20), 'value': True, 'label': 'Видимость крышки'},
            'ring_visible': {'rect': pygame.Rect(30, y_start + 390, 20, 20), 'value': True, 'label': 'Видимость кольца'},
            'label_visible': {'rect': pygame.Rect(30, y_start + 420, 20, 20), 'value': True, 'label': 'Видимость этикетки'},
            'fill_level_enabled': {'rect': pygame.Rect(30, y_start + 450, 20, 20), 'value': True, 'label': 'Случайное наполнение'},
            'cap_position_enabled': {'rect': pygame.Rect(30, y_start + 480, 20, 20), 'value': True, 'label': 'Случайное смещение крышки'},
            'ring_position_enabled': {'rect': pygame.Rect(30, y_start + 510, 20, 20), 'value': True, 'label': 'Случайное смещение кольца'},
        }
        
        # Кнопки
        self.buttons = {
            'generate_good': {'rect': pygame.Rect(30, 550, 200, 40), 'color': (60, 180, 80), 'text': 'Генерировать ХОРОШУЮ'},
            'generate_bad': {'rect': pygame.Rect(30, 600, 200, 40), 'color': (180, 60, 80), 'text': 'Генерировать БРАК'},
            'save_good': {'rect': pygame.Rect(30, 650, 200, 40), 'color': (50, 150, 70), 'text': 'Сохранить как ХОРОШУЮ'},
            'save_bad': {'rect': pygame.Rect(30, 700, 200, 40), 'color': (150, 50, 70), 'text': 'Сохранить как БРАК'},
        }
    
    def update_generator_params(self):
        """Обновляет параметры генератора на основе UI"""
        # Обновляем основные параметры
        for key, slider in self.sliders.items():
            self.generator.params[key] = slider['value']
        
        # Обновляем переключатели видимости
        self.generator.params['cap_visible'] = self.toggles['cap_visible']['value']
        self.generator.params['ring_visible'] = self.toggles['ring_visible']['value']
        self.generator.params['label_visible'] = self.toggles['label_visible']['value']
        
        # Обновляем активные отклонения
        self.generator.set_deviation_active('fill_level', self.toggles['fill_level_enabled']['value'])
        self.generator.set_deviation_active('cap_position', self.toggles['cap_position_enabled']['value'])
        self.generator.set_deviation_active('ring_position', self.toggles['ring_position_enabled']['value'])
    
    def generate_image(self, defect_mode=False):
        """Генерирует изображение с текущими параметрами"""
        self.update_generator_params()
        
        image = self.generator.generate_image(defect_mode=defect_mode)
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2RGBA)
        image = image[self.cap_crop[0][1]:self.cap_crop[1][1], self.cap_crop[0][0]:self.cap_crop[1][0]]
        image = cv2.resize(image, (0,0), fx=0.5, fy=0.5)
        
        return image
    
    def generate_good(self):
        """Генерирует хорошее изображение"""
        self.current_image = self.generate_image(defect_mode=False)
        self.image_type = 'good'
        print("Сгенерирована хорошая бутылка")
        
    def generate_bad(self):
        """Генерирует плохое изображение"""
        self.current_image = self.generate_image(defect_mode=True)
        self.image_type = 'bad'
        print("Сгенерирована бракованная бутылка")
        
    def save_current_image(self, category):
        """Сохраняет текущее изображение в указанную категорию"""
        if self.current_image is None:
            print("Нет изображения для сохранения!")
            return
            
        pil_image = Image.fromarray(self.current_image)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{timestamp}.png"
        
        save_path = self.good_dir / filename if category == 'good' else self.bad_dir / filename
        pil_image.save(save_path)
        print(f"Изображение сохранено как {category}: {save_path}")
    
    def draw_slider(self, slider, mouse_pos):
        """Рисует слайдер"""
        rect = slider['rect']
        value = slider['value']
        min_val, max_val = slider['min'], slider['max']
        
        # Фон слайдера
        pygame.draw.rect(self.screen, (60, 60, 80), rect, border_radius=10)
        
        # Заполненная часть
        fill_width = int((value - min_val) / (max_val - min_val) * rect.width)
        fill_rect = pygame.Rect(rect.x, rect.y, fill_width, rect.height)
        pygame.draw.rect(self.screen, (80, 120, 200), fill_rect, border_radius=10)
        
        # Ползунок
        slider_pos = rect.x + fill_width
        pygame.draw.circle(self.screen, (200, 200, 220), (slider_pos, rect.y + rect.height // 2), 10)
        
        # Текст
        label_text = f"{slider['label']}: {value:.2f}" if isinstance(value, float) else f"{slider['label']}: {value}"
        text_surface = self.font.render(label_text, True, (220, 220, 220))
        self.screen.blit(text_surface, (rect.x, rect.y - 20))
    
    def draw_toggle(self, toggle, mouse_pos):
        """Рисует переключатель"""
        rect = toggle['rect']
        is_hover = rect.collidepoint(mouse_pos)
        
        # Фон переключателя
        bg_color = (80, 80, 100) if is_hover else (60, 60, 80)
        pygame.draw.rect(self.screen, bg_color, rect, border_radius=4)
        
        # Включенное состояние
        if toggle['value']:
            pygame.draw.rect(self.screen, (80, 200, 100), pygame.Rect(rect.x + 2, rect.y + 2, rect.width - 4, rect.height - 4), border_radius=3)
        
        # Текст
        text_surface = self.font.render(toggle['label'], True, (220, 220, 220))
        self.screen.blit(text_surface, (rect.x + 30, rect.y))
    
    def draw_button(self, button, mouse_pos):
        """Рисует кнопку"""
        rect = button['rect']
        is_hover = rect.collidepoint(mouse_pos)
        color = tuple(min(c + 30, 255) for c in button['color']) if is_hover else button['color']
        
        pygame.draw.rect(self.screen, (30, 30, 40), rect.move(2, 2), border_radius=8)
        pygame.draw.rect(self.screen, color, rect, border_radius=8)
        pygame.draw.rect(self.screen, (255, 255, 255, 50), rect, width=1, border_radius=8)
        
        text_surface = self.font.render(button['text'], True, (255, 255, 255))
        text_rect = text_surface.get_rect(center=rect.center)
        self.screen.blit(text_surface, text_rect)
    
    def draw_interface(self):
        """Отрисовывает интерфейс"""
        self.screen.fill((40, 40, 50))
        mouse_pos = pygame.mouse.get_pos()
        
        # Панель управления
        control_panel = pygame.Rect(20, 20, 260, 760)
        pygame.draw.rect(self.screen, (50, 50, 70), control_panel, border_radius=10)
        pygame.draw.rect(self.screen, (70, 70, 90), control_panel, width=1, border_radius=10)
        
        # Заголовок панели управления
        title = self.title_font.render("ПАРАМЕТРЫ ГЕНЕРАЦИИ", True, (255, 255, 255))
        self.screen.blit(title, (control_panel.centerx - title.get_width() // 2, 25))
        
        # Рисуем элементы управления
        for slider in self.sliders.values():
            self.draw_slider(slider, mouse_pos)
        
        for toggle in self.toggles.values():
            self.draw_toggle(toggle, mouse_pos)
        
        for button in self.buttons.values():
            self.draw_button(button, mouse_pos)
        
        # Область предпросмотра
        preview_bg = pygame.Rect(300, 20, 860, 760)
        pygame.draw.rect(self.screen, (30, 30, 40), preview_bg, border_radius=10)
        pygame.draw.rect(self.screen, (60, 60, 80), preview_bg, width=2, border_radius=10)
        
        # Отображение текущего изображения
        if self.current_image is not None:
            try:
                rgb_image = cv2.cvtColor(self.current_image, cv2.COLOR_RGBA2RGB)
                pygame_image = pygame.surfarray.make_surface(rgb_image)
                pygame_image = pygame.transform.rotate(pygame_image, -90)
                pygame_image = pygame.transform.flip(pygame_image, True, False)
                
                scale_factor = min(800 / pygame_image.get_width(), 700 / pygame_image.get_height())
                new_width = int(pygame_image.get_width() * scale_factor)
                new_height = int(pygame_image.get_height() * scale_factor)
                pygame_image = pygame.transform.scale(pygame_image, (new_width, new_height))
                
                img_x = preview_bg.centerx - new_width // 2
                img_y = preview_bg.centery - new_height // 2
                self.screen.blit(pygame_image, (img_x, img_y))
                
                # Статус
                status_text = "ХОРОШАЯ" if self.image_type == 'good' else "✗ БРАК"
                status_color = (60, 180, 80) if self.image_type == 'good' else (180, 60, 80)
                status_surface = self.title_font.render(status_text, True, status_color)
                self.screen.blit(status_surface, (preview_bg.centerx - status_surface.get_width() // 2, preview_bg.bottom - 40))
                
            except Exception as e:
                error_text = f"Ошибка отображения: {str(e)}"
                error_surface = self.font.render(error_text, True, (255, 100, 100))
                self.screen.blit(error_surface, (preview_bg.centerx - error_surface.get_width() // 2, preview_bg.centery))
        
        pygame.display.flip()
    
    def handle_events(self):
        """Обрабатывает события"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            
            elif event.type == pygame.MOUSEBUTTONDOWN:
                mouse_pos = event.pos
                
                # Проверяем клики по слайдерам
                for key, slider in self.sliders.items():
                    if slider['rect'].collidepoint(mouse_pos):
                        self.dragging_slider = key
                        break
                
                # Проверяем клики по переключателям
                for key, toggle in self.toggles.items():
                    if toggle['rect'].collidepoint(mouse_pos):
                        self.toggles[key]['value'] = not toggle['value']
                        self.regenerate_current()
                        break
                
                # Проверяем клики по кнопкам
                for key, button in self.buttons.items():
                    if button['rect'].collidepoint(mouse_pos):
                        if key == 'generate_good':
                            self.generate_good()
                        elif key == 'generate_bad':
                            self.generate_bad()
                        elif key == 'save_good':
                            self.save_current_image('good')
                        elif key == 'save_bad':
                            self.save_current_image('bad')
                        break
            
            elif event.type == pygame.MOUSEBUTTONUP:
                self.dragging_slider = None
            
            elif event.type == pygame.MOUSEMOTION:
                if hasattr(self, 'dragging_slider') and self.dragging_slider:
                    slider = self.sliders[self.dragging_slider]
                    x_pos = max(slider['rect'].x, min(event.pos[0], slider['rect'].x + slider['rect'].width))
                    ratio = (x_pos - slider['rect'].x) / slider['rect'].width
                    new_value = slider['min'] + ratio * (slider['max'] - slider['min'])
                    
                    if slider['label'] in ['Уровень наполнения', 'Разброс наполнения', 'Угол этикетки']:
                        new_value = round(new_value, 2)
                    else:
                        new_value = int(new_value)
                    
                    slider['value'] = new_value
                    self.regenerate_current()
        
        return True
    
    def regenerate_current(self):
        """Перегенерирует текущее изображение с новыми параметрами"""
        if self.current_image is not None:
            if self.image_type == 'good':
                self.generate_good()
            else:
                self.generate_bad()
    
    def run(self):
        """Основной цикл приложения"""
        self.dragging_slider = None
        clock = pygame.time.Clock()
        running = True
        
        while running:
            running = self.handle_events()
            self.draw_interface()
            clock.tick(60)
        
        pygame.quit()

# Использование
if __name__ == "__main__":
    generator = BottleGenerator()
    app = BottleGeneratorApp(generator)
    app.run()