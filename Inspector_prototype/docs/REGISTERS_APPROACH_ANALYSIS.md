# Анализ подходов к регистрам и полям. Итоговое решение

Документ фиксирует сравнение подходов, оценку в баллах и **одно рекомендуемое эффективное решение** для полей и регистров (Pydantic v2).

---

## 1. Два основных подхода

### Подход A: «Поле = примитив + json_schema_extra»

- Регистр — Pydantic-модель с полями вида `dp: float = field_from_schema(1.4, description='...', min=0.1, max=20, ...)`.
- Метаданные лежат в `json_schema_extra` каждого `Field`; при необходимости из них собирается meta через `from_pydantic_field(FieldInfo)`.
- Схема по умолчанию задаётся словарём (`DEFAULT_FIELD_SCHEMA`), фабрика `FieldSchema(schema)(default_value, **overrides)` возвращает `Field(...)`.

### Подход B: «Поле = объект (value + метаданные)»

- Поле — отдельная Pydantic-модель с атрибутами `value`, `default`, `description`, `info`, `min`/`max`, i18n, `routing` и т.д.
- Регистр — модель, у которой атрибуты суть такие объекты: `dp: DpField = Field(default_factory=DpField)`.
- Для рецептов/очередей используется явный контракт: `values_dict()` (плоский dict) и `model_validate_from_values_update(data)`.

---

## 2. Оценка в баллах

| Критерий | Подход A (field_from_schema) | Подход B (поле = объект) |
|----------|------------------------------|---------------------------|
| **Один источник истины** | 4/10 — дефолт и метадата дублируются в вызове; meta восстанавливается из FieldInfo | 9/10 — значение и метадата в одном классе поля |
| **Читаемость** | 5/10 — много повторяющихся kwargs, зависимость от «крюка» FieldSchema | 9/10 — класс поля с явными атрибутами, наследование между полями |
| **Типизация (Pydantic v2)** | 6/10 — типы есть, но метадата в json_schema_extra, не типобезопасна | 9/10 — всё в моделях, явные типы value/default |
| **Переиспользование** | 5/10 — копипаста параметров, наследование полей неочевидно | 9/10 — MinDistField(DpField) или MinDistField(NumericField), переопределение одного параметра |
| **Сериализация** | 7/10 — model_dump() плоский «по факту»; контракт неявный | 9/10 — явные values_dict() / model_validate_from_values_update() |
| **Расширяемость** | 6/10 — флаги вроде required_after_create нужно прокидывать вручную | 9/10 — флаги и методы в BaseField |
| **Итого** | **5.5/10** | **9.0/10** |

**Вывод:** для новой и рефакторинговой разработки целесообразно опираться на **подход B**.

---

## 3. Варианты внутри подхода B

### 3.1 Иерархия полей: DpField(BaseField) vs DpField(NumericField)

| Вариант | Плюсы | Минусы | Оценка |
|---------|--------|--------|--------|
| **DpField(BaseField)** | Один уровень наследования, все поля «равны» | В каждом числовом поле дублируются transfer_k, round_k, clamp/round_value | 6/10 |
| **DpField(NumericField)** | Нет дублирования числовой логики; NumericField даёт clamp, round_value, transfer_k, round_k | Два уровня: BaseField → NumericField → DpField | 9/10 |

**Рекомендация:** числовые поля (dp, minDist, param1, …) наследовать от **NumericField**; поля без min/max/round (строка, bool только с описанием) — от **BaseField**.

### 3.2 Базовый класс регистра: два класса vs один контейнер

| Вариант | Описание | Оценка |
|---------|----------|--------|
| Каждый регистр: `class DrawRegisters(RegisterMixin, BaseModel)` | Явно видно оба предка | 7/10 |
| Один базовый класс: `class RegisterBase(RegisterMixin, BaseModel)`; регистры: `class DrawRegisters(RegisterBase)` | Меньше повторений, один раз задан порядок наследования и семантика «регистр» | 9/10 |

**Рекомендация:** ввести **RegisterBase** в data_schema_module и наследовать от него все модели регистров.

### 3.3 Размещение BaseField и NumericField

| Вариант | Где BaseField / NumericField | Оценка |
|---------|-----------------------------|--------|
| Оба в App (field_registers) | Специфика приложения в одном месте | 5/10 — дублирование при нескольких приложениях/модулях |
| Оба в data_schema_module/fields | Общая основа для любых регистров; App только конкретные DpField, MinDistField, … | 9/10 |
| BaseField в App, NumericField в модуле | Несогласованно, NumericField тогда зависит от «чужого» BaseField | 4/10 |

**Рекомендация:** **BaseField** и **NumericField** держать в **data_schema_module/fields**; в App — только конкретные классы полей (DpField, MinDistField, …) и сами регистры (DrawRegisters, …).

---

## 4. Итоговое эффективное решение (одно целевое)

Опираться на **подход B** и зафиксировать следующее.

### 4.1 Структура в data_schema_module (ядро)

- **fields/base_field.py** — `BaseField`: value, default, description, info, i18n, min/max, routing, required_after_create, методы to_metadata_dict(), validate_value(), get_description(), get_info().
- **fields/numeric_field.py** — `NumericField(BaseField)`: transfer_k, round_k, clamp(), round_value(), переопределение validate_value под числа.
- **fields/register_mixin.py** — `RegisterMixin`: values_dict(), model_validate_from_values_update(), get_field_meta_model(), get_field_metadata(), get_field_description(), validate_field_value(), can_modify_field(), get_fields_for_access_level().
- **fields/register_base.py** (новый) — `RegisterBase(RegisterMixin, BaseModel)`: единая база для всех моделей регистров.

Экспорт из модуля: BaseField, NumericField, RegisterMixin, RegisterBase.

### 4.2 Структура в App (field_registers)

- Конкретные поля — классы от **NumericField** (или от BaseField для нечисловых): DpField(NumericField), MinDistField(NumericField), Param1Field(NumericField), … При необходимости переиспользования описаний: MinDistField(DpField) с переопределением value/description.
- Регистры — от **RegisterBase**: `class DrawRegisters(RegisterBase)` с полями вида `dp: DpField = Field(default_factory=DpField)` и т.д.

### 4.3 Контракт сериализации

- Рецепты и очереди: только плоский словарь значений.
- Экспорт: `register.values_dict()` → `{name: value, ...}`.
- Импорт: `register.model_validate_from_values_update(data)` (in-place).
- RegistersContainer: для каждого регистра при наличии methods values_dict / model_validate_from_values_update использовать их, иначе — model_dump / model_validate.

### 4.4 Сводная таблица

| Элемент | Расположение | Наследование |
|---------|--------------|--------------|
| BaseField | data_schema_module/fields | — |
| NumericField | data_schema_module/fields | BaseField |
| RegisterMixin | data_schema_module/fields | — |
| RegisterBase | data_schema_module/fields | RegisterMixin, BaseModel |
| DpField, MinDistField, … | App/field_registers | NumericField (или BaseField для нечисловых) |
| DrawRegisters, ConveyorRegisters, … | App/field_registers | RegisterBase |

---

## 5. К чему прийти: одно решение

- **Подход:** поле = объект с value + метаданными (подход B).
- **Базовые типы полей:** BaseField и NumericField в data_schema_module/fields; в App — только конкретные поля (DpField, MinDistField, …), по возможности от NumericField.
- **Базовый класс регистров:** один класс RegisterBase = RegisterMixin + BaseModel в data_schema_module; все регистры наследуют RegisterBase.
- **Сериализация:** явный контракт values_dict() и model_validate_from_values_update(); контейнер и рецепты/очереди работают только с плоским словарём значений.

Это даёт один понятный, эффективный и расширяемый способ описывать регистры и поля без дублирования и без смешивания ответственности между модулем и приложением.
