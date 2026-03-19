## План: Translation Management Panel — Premium UX Overhaul

### Контекст

Панель Translation Management (Ctrl+Shift+T) сейчас показывает только первые 100 записей без возможности перейти дальше, без фильтрации по нескольким проектам, без управления размером страницы, без сортировки колонок и без экспорта. При росте датасетов до сотен тысяч записей панели нужны полноценная серверная пагинация, сортировка, мультипроектный фильтр и экспорт в Excel, чтобы соответствовать стандартам премиум-приложения.

### Текущее состояние (ключевые разрывы)

* Жёстко задано limit=100, offset=0 — UI-пагинации нет, несмотря на поддержку в бэкенде
* Область видимости только одного проекта — combo “Project/Global/All”, нет мультивыбора
* Нет сортировки колонок — setSortingEnabled(False), только ORDER BY updated_at DESC
* Нет экспорта — ExportService и openpyxl существуют, но не подключены к TM-панели
* Нет управления размером страницы — нельзя менять количество строк на экране
* Нет сохранения фильтров — настройки не сохраняются между сессиями

---

## Фичи к реализации (7 изменений)

### Feature 1: Классическая панель пагинации

**UI:** Панель навигации под таблицей:
`« ‹  Page [1] of 50  › »     Showing 1–100 of 5,000     Page size: [100 ▾]`

* Кнопки First/Prev/Next/Last (отключаются на границах)
* Ввод номера страницы (QSpinBox, ввод для прыжка)
* Выбор размера страницы: QComboBox со значениями [25, 50, 100, 250, 500]
* Лейбл диапазона: `"Showing 1–100 of 5,000"`
* Клавиатура: Ctrl+Left/Right для prev/next страницы

**Отслеживание состояния:**

* `self.current_page = 1`
* `self.page_size = 100` (загружать из SettingsService `tm_panel/page_size`)
* `self.total_count = 0` (из `model.total_count`)

**Файл:** `app/ui/translation_management_panel.py`

---

### Feature 2: Мультипроектный фильтр (попап с чекбоксами)

**UI:** Заменить текущий combo “Scope” на:

* QPushButton `"Projects: All ▾"` — открывает попап-диалог
* Диалог содержит: QListWidget с чекбоксами для каждого проекта + кнопки `"Select All"` / `"Clear All"`
* Текст кнопки обновляется по выбору: `"Projects: 2 of 5 selected"`
* Включить `"Global (no project)"` как отдельный чекбокс

**Backend:** Добавить параметр фильтра `project_ids: List[int]` в `search_tm_entries()` и `count_tm_entries()`

* При выборе нескольких проектов: `TMEntry.project_id.in_(project_ids)`
* Если отмечен “Global”: добавить `TMEntry.project_id.is_(None)` через OR
* Если выбраны все: фильтр по проектам не применять (то же, что “All”)

**Файлы:**

* `app/ui/translation_management_panel.py` — новый диалог + кнопка
* `app/services/translation_admin_service.py` — логика мультипроектного фильтра

---

### Feature 3: Серверная сортировка по колонкам

**UI:** Включить кликабельные заголовки колонок с индикаторами сортировки (▲/▼)

* Клик по заголовку → сортировка ASC; второй клик → сортировка DESC; третий клик → убрать сортировку (вернуться к дефолту)
* Сортировка по умолчанию: `updated_at DESC`
* Только одна колонка сортировки (без multi-sort)

**Backend:** Добавить параметры `sort_column` и `sort_direction` в:

* `search_tm_entries(session, filters, limit, offset, sort_column, sort_direction)`
* Пробросить через `TMSearchWorker`

**Маппинг UI → DB:**

| UI Column   | DB Column   |
| ----------- | ----------- |
| ID          | tm_id       |
| Kind        | kind        |
| Source      | src_text    |
| Translation | translation |
| Status      | status      |
| Scope       | project_id  |
| Origin      | origin      |
| Source Ref  | source_ref  |
| Updated     | updated_at  |

**Файлы:**

* `app/ui/translation_management_panel.py` — включить сортировку, ловить клики по заголовкам
* `app/services/translation_admin_service.py` — добавить параметры сортировки в запрос
* `app/ui/workers.py` — пробросить параметры сортировки через `TMSearchWorker`

---

### Feature 4: Экспорт в Excel

**UI:** Кнопка `"Export Excel"` в action bar

* Экспортирует текущий отфильтрованный результат (все страницы, не только текущую)
* Показывает QFileDialog для пути сохранения
* Progress dialog во время экспорта (для больших датасетов)
* Экспорт выполняется в фоне через QThread

**Формат экспорта (openpyxl, по паттернам существующего ExportService):**

* Лист `"Translation Memory"`
* Заголовки: `ID, Kind, Source, Translation, Status, Project, Origin, Source Ref, Updated`
* Оформленные заголовки (жирный шрифт, закрепить верхнюю строку)
* Авто-ширина колонок
* Атомарная запись (temp + rename)

**Реализация:** Добавить метод `export_tm_filtered_xlsx()` в `ExportService`

* Принимает тот же `filters dict`, что и `search_tm_entries`, но БЕЗ limit/offset (экспорт всего совпадающего)
* Переиспользовать существующие openpyxl-паттерны из `export_xlsx()`

**Файлы:**

* `app/ui/translation_management_panel.py` — кнопка экспорта + обработчик
* `app/services/export_service.py` — новый метод `export_tm_filtered_xlsx()`
* `app/ui/workers.py` — новый `TMExportWorker` (или переиспользовать паттерн `ExportWorker`)

---

### Feature 5: Сохранение настроек (Settings Persistence)

Сохранять и восстанавливать пользовательские предпочтения через существующий `SettingsService`:

| Setting Key             | Type  | Default      | Что сохраняем                     |
| ----------------------- | ----- | ------------ | --------------------------------- |
| tm_panel/page_size      | int   | 100          | Строк на странице                 |
| tm_panel/sort_column    | str   | "updated_at" | Последняя колонка сортировки      |
| tm_panel/sort_direction | str   | "desc"       | Последнее направление сортировки  |
| tm_panel/header_state   | bytes | —            | Ширины колонок (существующий API) |

**Файл:** `app/ui/translation_management_panel.py` — загрузка в `__init__`, сохранение при изменениях

---

### Feature 6: Заменить Scope combo на мультипроектный UI

Текущий combo “Scope” (Project/Global/All) заменяется новым мультипроектным фильтром (Feature 2). Удалить старый `scope_combo`, чтобы не путать пользователя.

**Файл:** `app/ui/translation_management_panel.py`

---

### Feature 7: Улучшенная строка статуса

Заменить простой лейбл `"Results: N"` на богатую строку статуса:

`Showing 1–100 of 5,000 entries | Page 1 of 50 | Filters active: kind=lemma, status=approved`

**Файл:** `app/ui/translation_management_panel.py`

---

## Файлы к изменению (6 файлов + 1 новый)

1. `app/services/translation_admin_service.py`

* `search_tm_entries()`: добавить `sort_column`, `sort_direction`, `project_ids`
* `count_tm_entries()`: добавить `project_ids` (зеркалить логику фильтра)
* Валидировать `sort_column` по allowlist, чтобы предотвратить SQL injection
* Добавить OR-логику для мультипроектного + global фильтра

2. `app/ui/workers.py` — `TMSearchWorker`

* Принимать `sort_column`, `sort_direction` в конструкторе
* Пробрасывать в `admin_service.search_tm_entries()`
* Новый `TMExportWorker(QThread)` для Excel-экспорта

3. `app/ui/translation_management_panel.py` (МАСШТАБНАЯ переработка UI-layout)

* Удалить старый Scope combo
* Добавить кнопку мультипроектного фильтра + `ProjectSelectDialog`
* Добавить пагинационную панель (First/Prev/Page/Next/Last + селектор page size)
* Включить серверную сортировку через сигнал клика по заголовку
* Добавить кнопку Export Excel
* Добавить сохранение настроек (load/save page_size, sort, header state)
* Обновить формат status bar
* Вести: `current_page, page_size, sort_column, sort_direction, selected_project_ids`

4. `app/ui/models_qt.py` — `TranslationManagementTableModel`

* Структурные изменения не нужны (модель уже работает с серверными данными)
* `total_count` уже отслеживается

5. `app/services/export_service.py`

* Новый метод: `export_tm_filtered_xlsx(session, file_path, filters, sort_column, sort_direction)`
* Стримить данные чанками (batch SELECT с offset) для больших датасетов
* Использовать openpyxl со стилями (существующие паттерны)

6. `app/infra/settings.py`

* Изменения не нужны (существующий API достаточен)

7. **NEW:** `tests/test_tm_panel_ux.py`

* Тест серверной сортировки (ASC/DESC для каждой колонки)
* Тест мультипроектного фильтра (один, несколько, global, all)
* Тест математики пагинации (число страниц, offset, граничные условия)
* Тест экспорта с фильтрами
* Тест сохранения настроек

---

## Детальная реализация

### Pagination State Machine

```python
# В TranslationManagementPanel.__init__:
self.current_page = 1
self.page_size = settings.get_int("tm_panel/page_size", 100)
self.total_count = 0
self.sort_column = settings.get_string("tm_panel/sort_column", "updated_at")
self.sort_direction = settings.get_string("tm_panel/sort_direction", "desc")
self.selected_project_ids = None  # None = все проекты

# Вычисляемое:
@property
def total_pages(self):
    return max(1, (self.total_count + self.page_size - 1) // self.page_size)

@property
def current_offset(self):
    return (self.current_page - 1) * self.page_size
```

### Обновлённый flow perform_search()

```python
def perform_search(self):
    # Сбор фильтров (существующая логика) + добавить project_ids
    filters = self.build_filters()
    if self.selected_project_ids is not None:
        filters["project_ids"] = self.selected_project_ids

    # Создать worker с пагинацией + параметрами сортировки
    self.worker = TMSearchWorker(
        filters=filters,
        limit=self.page_size,
        offset=self.current_offset,
        sort_column=self.sort_column,
        sort_direction=self.sort_direction,
    )
    # ... connect signals, start
```

### Серверная сортировка — защита от SQL injection

```python
# В translation_admin_service.py:
SORT_COLUMNS = {
    "tm_id": TMEntry.tm_id,
    "kind": TMEntry.kind,
    "src_text": TMEntry.src_text,
    "translation": TMEntry.translation,
    "status": TMEntry.status,
    "project_id": TMEntry.project_id,
    "origin": TMEntry.origin,
    "source_ref": TMEntry.source_ref,
    "updated_at": TMEntry.updated_at,
}

def search_tm_entries(self, session, filters=None, limit=100, offset=0,
                      sort_column="updated_at", sort_direction="desc"):
    # Валидировать sort column (предотвращение инъекций)
    column = SORT_COLUMNS.get(sort_column, TMEntry.updated_at)
    if sort_direction == "asc":
        stmt = stmt.order_by(column.asc())
    else:
        stmt = stmt.order_by(column.desc())
```

### Мультипроектный фильтр — Backend

```python
# В translation_admin_service.py search_tm_entries():
if "project_ids" in filters and filters["project_ids"] is not None:
    project_ids = filters["project_ids"]
    include_global = None in project_ids or -1 in project_ids
    real_ids = [pid for pid in project_ids if pid is not None and pid != -1]

    conditions = []
    if real_ids:
        conditions.append(TMEntry.project_id.in_(real_ids))
    if include_global:
        conditions.append(TMEntry.project_id.is_(None))

    if conditions:
        stmt = stmt.where(or_(*conditions))
```

### ProjectSelectDialog

```python
class ProjectSelectDialog(QDialog):
    """Попап-диалог с чекбоксами проектов."""
    def __init__(self, projects, selected_ids, parent=None):
        # QListWidget с чекбоксами
        # Кнопки "Select All" / "Clear All"
        # Пункт "Global (no project)" с id=-1
        # Кнопки OK / Cancel
```

### Excel Export Worker

```python
class TMExportWorker(QThread):
    progress = pyqtSignal(str)         # Статусное сообщение
    export_complete = pyqtSignal(int)  # Кол-во строк
    error = pyqtSignal(str)

    def __init__(self, file_path, filters, sort_column, sort_direction):
        # ...

    def run(self):
        # Использовать ExportService.export_tm_filtered_xlsx()
        # Чанками: доставать по 1000 строк за раз, писать на лист
```

---

## Снижение рисков (Risk Mitigations)

1. SQL injection в сортировке: валидировать `sort_column` по allowlist DB-колонок
2. Память при большом экспорте: стримить чанками по 1000 строк, не держать всё в RAM
3. Off-by-one в пагинации: unit-тесты граничных условий (страница 1, последняя, пустой результат)
4. Десинхрон состояния фильтра: при любом изменении фильтров сбрасывать на страницу 1
5. Взаимодействие sort + pagination: сначала сортировка, потом пагинация (ORDER BY до LIMIT/OFFSET)
6. Мультипроектный фильтр без выбранных: трактовать как “показывать ничего” (0 результатов), не как “показать всё”
7. Конкурирующие поисковые запросы: отменять предыдущий worker перед стартом нового (существующий паттерн)
8. Отмена экспорта: поддержать cancel во время долгого экспорта
9. Регрессия inline edit: убедиться, что редактирование колонки Translation работает при включённой сортировке
10. Регрессия bulk actions: убедиться, что Approve/Reject/Deprecate работает с пагинацией
11. Header click vs sort: использовать `sectionClicked` у horizontal header, не `table.clicked`

---

## Производительность (Performance Considerations)

* Текстовый поиск `LIKE '%text%'`: уже медленный на больших датасетах. В этой итерации не меняем (FTS5 для TM — отдельная фича).
* Сортировка по неиндексированным колонкам: `origin`, `source_ref`, `translation` не индексированы. На 100k+ строк может быть медленно. Пока допустимо; индексы можно добавить позже.
* Экспорт всех строк: для 500k записей экспорт может занимать 10–30 секунд. Фоновый worker + progress dialog это покрывают.
* COUNT-запрос: выполняется отдельно от SELECT. Для сложных фильтров удваивает время запросов. Допустимый компромисс ради точной пагинации.

---

## План верификации (Verification Plan)

### Автотесты (`tests/test_tm_panel_ux.py`)

1. Математика пагинации: `page_count(0)`, `page_count(1)`, `page_count(100)`, `page_count(101)`, `page_count(999)`
2. Offset: `page=1→0`, `page=2→100`, `page=50→4900`
3. Валидация sort column: валидные принимаются, невалидные отклоняются (fallback на default)
4. SQL мультипроектного фильтра: один проект, несколько, global, смешанный
5. Экспорт пишет валидный xlsx: openpyxl открывает результат

### Проверка синтаксиса

```bash
python -c "from app.services.translation_admin_service import TranslationAdminService; print('OK')"
python -c "from app.ui.translation_management_panel import TranslationManagementPanel; print('OK')"
python -c "from app.services.export_service import ExportService; print('OK')"
```

### Ручное тестирование

1. Открыть TM panel → убедиться, что пагинация видна и счётчики корректны
2. Нажать Next/Last → данные меняются, счётчик страницы обновляется
3. Изменить page size → сброс на page 1, корректное число строк
4. Клик по заголовку → индикатор сортировки, данные пересортированы
5. Нажать “Projects…” → попап со всеми проектами
6. Выбрать 2 проекта → фильтр применён, результаты обновились
7. Нажать “Export Excel” → диалог файла, экспорт завершается, файл открывается в Excel
8. Закрыть и снова открыть панель → page size и sort восстановлены
9. Пустые результаты → “No results”, кнопки отключены
10. Bulk Approve с пагинацией → работает для выделения на текущей странице

---

● Отлично! План утверждён. Это существенное улучшение с 7 фичами. Дай мне создать задачи, чтобы отслеживать реализацию:

● Отлично! 8 задач создано. Начну с бэкенд-слоя сервисов (Task #8), потому что это фундамент для всего остального.

----
Переведи:
 Excellent progress! I've successfully completed the first 5 tasks for the Translation Management Panel UX overhaul:

  ✅ Completed:    s           e  o                          l
  1. Task #8: Added server-side sorting and multi-project filter to TranslationAdminService backend
  2. Task #9: Updated TMSearchWorker to pass sort parameters through
  3. Task #10: Created ProjectSelectDialog with checkboxes and replaced the Scope combo with a multi-project filter button
  4. Task #11: Added full pagination bar with First/Prev/Next/Last buttons, page number input, page size selector (25/50/100/250/500), and Ctrl+Left/Right keyboard shortcuts
  5. Task #12: Enabled server-side column sorting with clickable headers showing ▲/▼ indicators

  Current State:
  The Translation Management panel now supports:                                                                                                                                                                                                                                 - Multi-project filtering (select any combination of projects + global entries)
  - Full pagination navigation for large datasets (100k+ entries)                                                                                                                                                                                                                - Server-side sorting by clicking column headers (cycles: ASC → DESC → default)
  - Adjustable page size (25-500 rows)
  - Keyboard shortcuts (Ctrl+Left/Right for pagination, Enter for editing)

  Remaining Tasks:
  - Task #13: Settings persistence (save user preferences)
  - Task #14: Excel export functionality
  - Task #15: Comprehensive tests

  Moving to Task #13 now to add settings persistence so user preferences are preserved across sessions.

✻ Cogitated for 14m 54s

  8 tasks (5 done, 3 open)                                                                                                                                                                                                                                                       □ Add settings persistence to TranslationManagementPanel
  □ Add Excel export to ExportService and panel                                                                                                                                                                                                                                  □ Create tests for TM panel UX improvements
  √ Add server-side sort and multi-project to TranslationAdminService
  √ Update TMSearchWorker with sort params
  √ Add ProjectSelectDialog to TranslationManagementPanel
  √ Add pagination bar to TranslationManagementPanel
  √ Enable server-side sorting in TranslationManagementPanel
