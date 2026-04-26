# INNOTECH · Silver Industrial — спецификация темы для PySide6

Полное описание всех цветов, градиентов и теней, использованных в `Innotech Theme Preview v2.html`. Передавайте этот файл агенту, который будет повторять тему на PySide6 (QSS + QGraphicsDropShadowEffect).

---

## 1. Палитра (CSS-переменные → константы)

### Фоны / поверхности
| Имя           | HEX        | Назначение                          |
|---------------|------------|-------------------------------------|
| bg-deep       | `#1a1f28`  | Самый тёмный низ окна               |
| bg-mid        | `#2d3440`  | Средний тон фона                    |
| bg-hi         | `#4a5362`  | Светлый верх фона                   |
| bg-hi2        | `#5c6573`  | Пик подсветки металлика             |
| surface-0     | `#3a414e`  | Низ кнопки/панели                   |
| surface-1     | `#5a6370`  | Верх металлика                      |
| surface-2     | `#6e7886`  | Hover                               |
| surface-deep  | `#252a33`  | Inset / углубление                  |

### Серебро
| Имя        | HEX       |
|------------|-----------|
| silver-hi  | `#c8ccd4` |
| silver     | `#9ea6b2` |
| silver-lo  | `#6a7280` |

### Текст
| Имя    | HEX       | Где                                  |
|--------|-----------|--------------------------------------|
| text-0 | `#f2f5fa` | Основной (заголовки, значения)       |
| text-1 | `#c0c7d2` | Вторичный                            |
| text-2 | `#8a93a1` | Caption / mono-метки                 |
| text-3 | `#5e6674` | Disabled / placeholder               |

### Акцент (синий)
| Имя         | HEX       |
|-------------|-----------|
| accent      | `#2b7fff` |
| accent-hi   | `#4a95ff` |
| accent-lo   | `#1f5fcc` |
| accent-deep | `#153f8a` |

### Статусы
| Имя     | HEX       |
|---------|-----------|
| danger  | `#e54863` |
| success | `#2ecc8f` |
| warn    | `#f0a23a` |

### Бордеры (rgba)
| Имя             | Значение                  |
|-----------------|---------------------------|
| border          | `rgba(255,255,255,0.08)`  |
| border-strong   | `rgba(255,255,255,0.14)`  |
| border-dark     | `rgba(0,0,0,0.35)`        |
| border-accent   | `rgba(43,127,255,0.55)`   |

### Радиусы
- `radius`: 12px
- `radius-lg`: 16px

### Шрифты
- UI: Rajdhani (300/400/500/600/700)
- Display: Orbitron (500/600/700/800)
- Mono: JetBrains Mono (400/500)

---

## 2. Глобальные тени (предустановки)

```
shadow-tab    : 0 18px 34px rgba(0,0,0,0.55),
                0 2px 4px rgba(0,0,0,0.35),
                inset 0 1px 0 rgba(255,255,255,0.08)

shadow-panel  : 0 14px 28px rgba(0,0,0,0.45),
                inset 0 1px 0 rgba(255,255,255,0.06),
                inset 0 -1px 0 rgba(0,0,0,0.30)

shadow-btn    : 0 4px 10px rgba(0,0,0,0.40),
                inset 0 1px 0 rgba(255,255,255,0.18),
                inset 0 -1px 0 rgba(0,0,0,0.25)

shadow-accent : 0 10px 22px rgba(43,127,255,0.35),
                inset 0 1px 0 rgba(255,255,255,0.22)
```

> В PySide6 inset-тени имитируются через тонкие линии-границы (`border-top: 1px solid rgba(255,255,255,0.18)` сверху; `border-bottom: 1px solid rgba(0,0,0,0.25)` снизу) или дополнительной обёрткой. Внешние тени — `QGraphicsDropShadowEffect`.

---

## 3. Body / окно приложения (фон главного окна)

**Фон body** — стек из двух radial и одного linear:
```
radial-gradient(1200px 700px at 30% -5%, #6d7786 0%, transparent 55%),
radial-gradient(900px 700px at 105% 115%, #1b1f27 0%, transparent 60%),
linear-gradient(165deg, #4a5362 0%, #343a46 45%, #1e232c 100%)
```
+ оверлей точечной текстуры: `radial-gradient(circle at 1px 1px, rgba(255,255,255,0.5) 1px, transparent 1.5px)` 22×22, opacity 0.06.

**Окно (.window)**
- Фон: `linear-gradient(180deg, #5c6573 0%, #3e4552 45%, #2a303b 100%)`
- Border: `1px solid rgba(255,255,255,0.18)`
- Radius: 14px
- Тень:
  ```
  0 48px 140px rgba(0,0,0,0.75),
  inset 0 1px 0 rgba(255,255,255,0.22),
  inset 0 -2px 0 rgba(0,0,0,0.35),
  0 0 0 1px rgba(0,0,0,0.5)
  ```

---

## 4. Title-bar (.win-titlebar)
- Фон: `linear-gradient(180deg, #6c7684 0%, #4d5663 100%)`
- Border-bottom: `1px solid rgba(0,0,0,0.4)`
- Inset highlight сверху: `inset 0 1px 0 rgba(255,255,255,0.12)`
- Точка-индикатор: `linear-gradient(180deg, #9ea6b2, #5a6370)`, inset highlight `0 1px 0 rgba(255,255,255,0.3)`
- Кнопки —/☐/✕: hover-фон `rgba(255,255,255,0.1)`

---

## 5. App-header (HeaderWidget)
- Фон: `linear-gradient(180deg, #5c6573 0%, #454c5a 55%, #353b47 100%)`
- Border-bottom: `1px solid rgba(0,0,0,0.5)`
- Тени:
  ```
  inset 0 1px 0 rgba(255,255,255,0.18),
  inset 0 -1px 0 rgba(0,0,0,0.35),
  0 8px 16px rgba(0,0,0,0.4)
  ```
- **Голубая подсветка-полоска снизу** (псевдо-элемент 4px):
  `linear-gradient(90deg, transparent 0%, rgba(43,127,255,0.9) 15%, #4a95ff 50%, rgba(43,127,255,0.9) 85%, transparent 100%)`
  с тенью свечения: `0 0 14px rgba(43,127,255,0.6), 0 0 28px rgba(43,127,255,0.35)`

### Логотип-объектив (.logo-mark) — кнопка-камера 84×84, круглая
**Фон (стек двух слоёв):**
1. `radial-gradient(circle at 50% 50%, #1a2030 0%, #11161f 36%, #080b12 52%, #02040a 58%, transparent 59%)` — «колодец»
2. `linear-gradient(155deg, #aab3c2 0%, #8590a1 18%, #5b6473 42%, #3a414e 70%, #1f242d 100%)` — металлический обод

**Тени:**
```
0 10px 22px rgba(0,0,0,0.65),
0 2px 4px rgba(0,0,0,0.45),
inset 0 1px 0 rgba(255,255,255,0.45),
inset 0 -2px 4px rgba(0,0,0,0.7),
0 0 0 1px rgba(0,0,0,0.6)
```

**Кольцо-апертура (::before, 50×50):**
- Conic: `from 30deg, #122b5c 0deg, #3d7de0 60deg, #122b5c 120deg, #3d7de0 180deg, #122b5c 240deg, #3d7de0 300deg, #122b5c 360deg`
- Тени: `0 0 0 2px rgba(0,0,0,0.7), inset 0 2px 5px rgba(0,0,0,0.65), 0 0 14px rgba(43,127,255,0.4)`
- Анимация: `rotate 360deg / 12s linear infinite`

**Стеклянный блик (::after, 30×30):**
- `radial-gradient(circle at 35% 28%, rgba(255,255,255,0.97) 0%, rgba(180,210,255,0.45) 32%, rgba(8,26,60,0.95) 78%)`
- Тень: `0 0 14px rgba(43,127,255,0.75), inset 0 1px 2px rgba(0,0,0,0.65)`

**Pressed-состояние:**
- `transform: scale(0.97); filter: brightness(0.92);`
- Тень меняется на: `0 3px 8px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.18), inset 0 2px 6px rgba(0,0,0,0.65), 0 0 0 1px rgba(0,0,0,0.7)`

### Текст логотипа (.logo-text)
- Цвет: `#4a95ff` (accent-hi)
- text-stroke: `0.5px rgba(120,170,255,0.4)`
- text-shadow:
  ```
  0 1px 0 rgba(0,0,0,0.65),
  0 2px 2px rgba(0,0,0,0.5),
  0 0 22px rgba(43,127,255,0.55),
  0 0 42px rgba(43,127,255,0.25)
  ```

### Status-pill
- Фон: `linear-gradient(180deg, rgba(255,255,255,0.08), rgba(0,0,0,0.15))`
- Border: `1px solid rgba(0,0,0,0.35)`
- Inset: `inset 0 1px 0 rgba(255,255,255,0.12)`
- Точка-статус (свечение):
  - ok: `#2ecc8f` + `box-shadow: 0 0 8px #2ecc8f`
  - warn: `#f0a23a` + `box-shadow: 0 0 8px #f0a23a`
  - off: `#6a7280` (без свечения)

### Msg-strip (центральная строка сообщений) — вдавленная
- Фон: `linear-gradient(180deg, #1a1f28 0%, #252b37 55%, #1e242e 100%)`
- Border: `1px solid rgba(0,0,0,0.65)`
- Тени:
  ```
  inset 0 3px 6px rgba(0,0,0,0.55),
  inset 0 -1px 0 rgba(255,255,255,0.06),
  0 1px 0 rgba(255,255,255,0.14),
  0 6px 14px rgba(0,0,0,0.4)
  ```
- Иконка-точка: `#4a95ff` + `box-shadow: 0 0 10px rgba(43,127,255,0.8), inset 0 0 2px rgba(255,255,255,0.5)`
- Лидирующий текст: `#4a95ff` + `text-shadow: 0 0 10px rgba(43,127,255,0.4)`

### Метрика (.metric)
- Значение: `#4a95ff`, `text-shadow: 0 1px 0 rgba(0,0,0,0.5)`
- Подпись: `#8a93a1`

### Разделитель (.h-div)
- `linear-gradient(180deg, transparent, rgba(0,0,0,0.5), transparent)` шириной 1px
- + `box-shadow: 1px 0 0 rgba(255,255,255,0.08)` (двойная линия)

---

## 6. Image-panel (область видеопотока)
- Фон секции: `linear-gradient(180deg, #2d333e 0%, #252a33 100%)`
- Тень: `0 1px 0 rgba(0,0,0,0.4), 0 -1px 0 rgba(255,255,255,0.04)`

### Image-slot (превью кадра)
- Фон:
  ```
  radial-gradient(ellipse at 50% 0%, rgba(43,127,255,0.06) 0%, transparent 55%),
  linear-gradient(180deg, #14171d 0%, #0a0c10 100%)
  ```
- Border: `1px solid rgba(0,0,0,0.55)`
- Radius: 12px
- Тени:
  ```
  0 14px 28px rgba(0,0,0,0.5),
  inset 0 0 0 1px rgba(255,255,255,0.04),
  inset 0 -1px 0 rgba(255,255,255,0.04)
  ```
- **Голубая подсветка по двум кромкам (left + bottom)** через ::after:
  ```
  inset 2px 0 0 rgba(43,127,255,0.75),
  inset 0 -2px 0 rgba(43,127,255,0.75),
  inset 6px 0 14px -2px rgba(43,127,255,0.45),
  inset 0 -6px 14px -2px rgba(43,127,255,0.45)
  ```

**Slot-label** — `background: rgba(0,0,0,0.55)`, border `rgba(255,255,255,0.1)`, текст `#c0c7d2`.

**Slot-rec (live)** — цвет `#e54863`, точка с тенью `0 0 8px #e54863`, pulse 2s.

**Crosshair-сетка:** линии `rgba(43,127,255,0.12)` 40×40, маска радиальная.

**Bbox:** `border: 1.5px solid #4a95ff; background: rgba(43,127,255,0.05)`.

**Overlay-dot:** `border: 2px solid #2b7fff`, тени `0 0 0 6px rgba(43,127,255,0.1), 0 0 18px rgba(43,127,255,0.35)`.

---

## 7. Tabs (вкладки)
**Контейнер .tabs:**
- Фон: `linear-gradient(180deg, #3b414d 0%, #2f3540 100%)`
- Border-top: `1px solid rgba(0,0,0,0.5)`
- Inset: `inset 0 1px 0 rgba(255,255,255,0.08)`

**Tab-bar:**
- Фон: `linear-gradient(180deg, #2a2f39 0%, #363c48 100%)`
- Border-bottom: `1px solid rgba(0,0,0,0.5)`
- Тень внутрь: `inset 0 -6px 14px rgba(0,0,0,0.35)`

**Tab (обычная):**
- Фон: `linear-gradient(180deg, #4a5161 0%, #363c49 100%)`
- Border: `1px solid rgba(0,0,0,0.4)`, без border-bottom
- Радиус: 12px 12px 0 0
- Цвет текста: `#c0c7d2`
- Тени:
  ```
  0 -6px 14px rgba(0,0,0,0.3),
  inset 0 1px 0 rgba(255,255,255,0.14)
  ```

**Tab :hover:**
- Фон: `linear-gradient(180deg, #5a6272 0%, #434a58 100%)`
- Цвет текста: `#f2f5fa`

**Tab.active:**
- Фон: `linear-gradient(180deg, #6a7284 0%, #4f5768 100%)`
- Цвет текста: `#f2f5fa`
- Тени:
  ```
  0 -8px 20px rgba(0,0,0,0.45),
  inset 0 1px 0 rgba(255,255,255,0.22),
  inset 0 -12px 18px rgba(43,127,255,0.08)
  ```
- Подсветка снизу (::after): `linear-gradient(90deg, transparent, #4a95ff, transparent)`, тень `0 0 12px rgba(43,127,255,0.6)`

**Tab-body:**
- Фон: `linear-gradient(180deg, #3b414d 0%, #333844 100%)`

---

## 8. Groupbox (панели с заголовком)
- Фон: `linear-gradient(180deg, #5a6370 0%, #454c5a 48%, #383e4a 100%)`
- Border: `1px solid rgba(0,0,0,0.45)`
- Radius: 12px
- Тени:
  ```
  0 18px 34px rgba(0,0,0,0.5),
  inset 0 1px 0 rgba(255,255,255,0.22),
  inset 0 -1px 0 rgba(0,0,0,0.35)
  ```

**Заголовок (gb-title):**
- Фон-плашка: `linear-gradient(180deg, #5a6370, #454c5a)`
- Border: `1px solid rgba(0,0,0,0.45)`
- Тени: `inset 0 1px 0 rgba(255,255,255,0.2), 0 2px 6px rgba(0,0,0,0.35)`
- Цвет текста: `#f2f5fa`, акцентная часть `#4a95ff`

---

## 9. Кнопки (.btn)

### Стандартная
- Фон: `linear-gradient(180deg, #6a7284 0%, #4b5261 50%, #3a4150 100%)`
- Border: `1px solid rgba(0,0,0,0.5)`
- Цвет: `#f2f5fa`
- Тени = `shadow-btn`
- text-shadow: `0 1px 0 rgba(0,0,0,0.5)`
- :hover фон: `linear-gradient(180deg, #788092 0%, #566075 50%, #434a5a 100%)`
- :active: `transform: translateY(1px)`, тень `0 2px 6px rgba(0,0,0,0.4), inset 0 1px 0 rgba(0,0,0,0.25)`

### Primary (синяя)
- Фон: `linear-gradient(180deg, #5ea3ff 0%, #2b7fff 50%, #1f5fcc 100%)`
- Border: `1px solid rgba(0,0,0,0.45)`
- Цвет: `#fff`
- Тени = `shadow-accent`
- :hover фон: `linear-gradient(180deg, #7ab3ff 0%, #3d8cff 50%, #2870e0 100%)`

### Danger (красная)
- Фон: `linear-gradient(180deg, #b84050 0%, #8a2d3d 50%, #5f1f28 100%)`
- Цвет: `#fff`
- Border: `1px solid rgba(0,0,0,0.5)`

### Ghost
- Фон: `linear-gradient(180deg, rgba(255,255,255,0.08), rgba(0,0,0,0.15))`
- Цвет: `#c0c7d2`

---

## 10. Combo / Input / Spin

**Combo:**
- Фон: `linear-gradient(180deg, #2e333d 0%, #1e222a 100%)`
- Border: `1px solid rgba(0,0,0,0.55)`, hover → `rgba(43,127,255,0.55)`
- Тени: `inset 0 1px 0 rgba(255,255,255,0.12), inset 0 2px 4px rgba(0,0,0,0.3)`
- Шеврон ▾: `#4a95ff`

**Input:**
- Фон: `linear-gradient(180deg, #1c2028 0%, #262b34 100%)`
- Border: `1px solid rgba(0,0,0,0.55)`
- Тени: `inset 0 2px 4px rgba(0,0,0,0.35), 0 1px 0 rgba(255,255,255,0.08)`
- Focus: border `#2b7fff`, тень `0 0 0 3px rgba(43,127,255,0.2), inset 0 2px 4px rgba(0,0,0,0.35)`

**Spin (числовой):**
- Контейнер как Input
- Кнопки ▲▼: `linear-gradient(180deg, #4a5161, #363c49)`, разделитель `1px rgba(0,0,0,0.5)`, hover-цвет `#4a95ff`

---

## 11. Slider

**Track (5–8px):**
- Фон: `linear-gradient(180deg, #1b1f27, #2a3040)`
- Тени: `inset 0 2px 3px rgba(0,0,0,0.5), 0 1px 0 rgba(255,255,255,0.08)`

**Fill (заполнение):**
- `linear-gradient(90deg, #1f5fcc, #4a95ff)`
- Тень: `0 0 10px rgba(43,127,255,0.45)`

**Thumb (30×30, круглый):**
- Фон: `radial-gradient(circle at 35% 28%, #ffffff 0%, #d7e0ee 30%, #7a8aa5 100%)`
- Border: `1px solid rgba(0,0,0,0.55)`
- Тени:
  ```
  0 5px 12px rgba(0,0,0,0.6),
  inset 0 1px 0 rgba(255,255,255,0.7),
  0 0 0 5px rgba(43,127,255,0.22),
  0 0 16px rgba(43,127,255,0.3)
  ```

**Метки каналов R/G/B:** `R #ff7894 · G #6ae0a8 · B #6aa8ff`
**Значение справа:** `#4a95ff`

---

## 12. Checkbox

**Бокс (16×16):**
- Фон: `linear-gradient(180deg, #1c2028, #262b34)`
- Border: `1px solid rgba(0,0,0,0.55)`
- Тени: `inset 0 1px 2px rgba(0,0,0,0.4), 0 1px 0 rgba(255,255,255,0.1)`

**Checked:**
- Фон: `linear-gradient(180deg, #4a95ff, #1f5fcc)`
- Тени: `0 0 10px rgba(43,127,255,0.45), inset 0 1px 0 rgba(255,255,255,0.3)`
- Галочка: белая

---

## 13. Scrollbar (демонстрация)
**Track (вертикальный, 22px):**
- `linear-gradient(180deg, #1b1f27, #2a3040)`
- Radius 11px
- `inset 0 2px 6px rgba(0,0,0,0.55), 0 1px 0 rgba(255,255,255,0.08)`

**Handle:**
- `linear-gradient(180deg, #9ab0d5, #3d4e74)`
- Radius 8px
- Тени:
  ```
  inset 0 1px 0 rgba(255,255,255,0.4),
  0 3px 8px rgba(0,0,0,0.5),
  0 0 12px rgba(43,127,255,0.25)
  ```

---

## 14. Карточки дизайн-системы (.ds-card)
- Фон: `linear-gradient(180deg, #4c5464 0%, #383e4a 100%)`
- Border: `1px solid rgba(0,0,0,0.4)`
- Radius: 16px
- Тень = `shadow-panel`
- Маркер заголовка: 4×14 прямоугольник `#4a95ff` с `box-shadow: 0 0 8px rgba(43,127,255,0.5)`

---

## 15. Note-блок (info/подсказка)
- Фон: `linear-gradient(180deg, rgba(43,127,255,0.15), rgba(43,127,255,0.05))`
- Border: `1px solid rgba(43,127,255,0.35)`
- Цвет акцента: `#4a95ff`

---

## 16. Code-блок
- Фон: `linear-gradient(180deg, #1c2028, #15181f)`
- Border: `1px solid rgba(0,0,0,0.5)`
- Тень: `inset 0 2px 6px rgba(0,0,0,0.35)`
- Подсветка: keyword `#c5a3ff`, string `#9ecbff`, comment `#8a93a1` italic

---

## 17. Гид по портированию в PySide6 / QSS

**Что переносится 1:1:**
- `qlineargradient`, `qradialgradient`, `qconicalgradient` есть в QSS — углы у `qlineargradient` задаются через `x1,y1,x2,y2` (вместо `180deg` → `x1:0,y1:0,x2:0,y2:1`).
- `border`, `border-radius`, `padding`, цвета — без изменений.
- `rgba(...)` поддерживается.

**Что НЕ работает в QSS и чем заменять:**
- `box-shadow` → `QGraphicsDropShadowEffect` (только одна тень на виджет; для составных используйте обёрточный QFrame).
- `inset`-тени → имитируйте отдельными `border-top`/`border-bottom` 1–2px полупрозрачными rgba; для глубоких inset — двойной QFrame с внутренним градиентом, повторяющим тёмный край.
- `text-shadow` → `QGraphicsDropShadowEffect` на `QLabel`.
- `backdrop-filter`, `mask-image`, `conic-gradient` (для логотипа) → рисуйте `QPainter`-ом в кастомном виджете (paintEvent), либо запекайте в PNG.
- Анимации (`@keyframes lens-spin`, `pulse`) → `QPropertyAnimation` + `QVariantAnimation` на свойстве rotation/opacity.

**Шрифты:** загружайте через `QFontDatabase.addApplicationFont()` (Rajdhani, Orbitron, JetBrains Mono).

**Скругления + тень одновременно:** установите `setAttribute(Qt.WA_TranslucentBackground)` родителю и используйте QFrame с `border-radius` + эффект тени.

---

## 18. Минимальный QSS-скелет (для старта)

```css
QWidget { background: transparent; color: #f2f5fa; font-family: "Rajdhani"; }

QMainWindow {
  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
    stop:0 #5c6573, stop:0.45 #3e4552, stop:1 #2a303b);
}

/* Header */
#HeaderWidget {
  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
    stop:0 #5c6573, stop:0.55 #454c5a, stop:1 #353b47);
  border-bottom: 1px solid rgba(0,0,0,0.5);
}

/* Groupbox */
QGroupBox {
  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
    stop:0 #5a6370, stop:0.48 #454c5a, stop:1 #383e4a);
  border: 1px solid rgba(0,0,0,0.45);
  border-radius: 12px;
  margin-top: 14px;
  padding-top: 18px;
}
QGroupBox::title {
  subcontrol-origin: margin; left: 16px; padding: 2px 12px;
  background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #5a6370, stop:1 #454c5a);
  border: 1px solid rgba(0,0,0,0.45); border-radius: 3px;
  color: #f2f5fa; font-weight: 600; letter-spacing: 2px;
}

/* Buttons */
QPushButton {
  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
    stop:0 #6a7284, stop:0.5 #4b5261, stop:1 #3a4150);
  border: 1px solid rgba(0,0,0,0.5);
  border-radius: 12px; padding: 8px 20px;
  color: #f2f5fa; font-weight: 600; letter-spacing: 1.5px;
}
QPushButton:hover {
  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
    stop:0 #788092, stop:0.5 #566075, stop:1 #434a5a);
}
QPushButton:pressed { padding-top: 9px; padding-bottom: 7px; }
QPushButton[primary="true"] {
  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
    stop:0 #5ea3ff, stop:0.5 #2b7fff, stop:1 #1f5fcc);
  color: white;
}

/* Inputs */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
  background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #1c2028, stop:1 #262b34);
  border: 1px solid rgba(0,0,0,0.55); border-radius: 12px;
  padding: 6px 12px; color: #f2f5fa;
  font-family: "JetBrains Mono";
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
  border: 1px solid #2b7fff;
}

/* Tabs */
QTabBar::tab {
  background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #4a5161, stop:1 #363c49);
  border: 1px solid rgba(0,0,0,0.4); border-bottom: none;
  border-top-left-radius: 12px; border-top-right-radius: 12px;
  padding: 10px 24px; color: #c0c7d2;
  font-weight: 500; letter-spacing: 1.4px;
}
QTabBar::tab:selected {
  background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #6a7284, stop:1 #4f5768);
  color: #f2f5fa;
}

/* Slider */
QSlider::groove:horizontal {
  height: 8px; border-radius: 4px;
  background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #1b1f27, stop:1 #2a3040);
}
QSlider::sub-page:horizontal {
  background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #1f5fcc, stop:1 #4a95ff);
  border-radius: 4px;
}
QSlider::handle:horizontal {
  width: 26px; height: 26px; margin: -10px 0;
  border-radius: 13px; border: 1px solid rgba(0,0,0,0.55);
  background: qradialgradient(cx:0.35, cy:0.28, radius:0.8,
    stop:0 #ffffff, stop:0.3 #d7e0ee, stop:1 #7a8aa5);
}

/* Scrollbar */
QScrollBar:vertical {
  width: 22px; border-radius: 11px;
  background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #1b1f27, stop:1 #2a3040);
}
QScrollBar::handle:vertical {
  background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #9ab0d5, stop:1 #3d4e74);
  border-radius: 8px; min-height: 40px; margin: 3px;
}
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }

/* Checkbox */
QCheckBox::indicator {
  width: 16px; height: 16px; border-radius: 3px;
  background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #1c2028, stop:1 #262b34);
  border: 1px solid rgba(0,0,0,0.55);
}
QCheckBox::indicator:checked {
  background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #4a95ff, stop:1 #1f5fcc);
  image: url(:/icons/check.svg);
}
```

---

## 19. Тени через QGraphicsDropShadowEffect (примеры)

```python
from PySide6.QtWidgets import QGraphicsDropShadowEffect
from PySide6.QtGui import QColor

def panel_shadow():
    eff = QGraphicsDropShadowEffect()
    eff.setBlurRadius(28)
    eff.setOffset(0, 14)
    eff.setColor(QColor(0, 0, 0, 115))   # rgba(0,0,0,0.45)
    return eff

def accent_glow():
    eff = QGraphicsDropShadowEffect()
    eff.setBlurRadius(22)
    eff.setOffset(0, 10)
    eff.setColor(QColor(43, 127, 255, 90))  # accent glow
    return eff

def tab_shadow():
    eff = QGraphicsDropShadowEffect()
    eff.setBlurRadius(34); eff.setOffset(0, 18)
    eff.setColor(QColor(0,0,0,140))
    return eff
```

> Ограничение: один эффект на виджет. Для составных теней (down + glow) используйте обёрточный QFrame со своим эффектом, либо комбинируйте с border-цветами и QSS-градиентами фона.
