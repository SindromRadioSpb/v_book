# Анализ: Реализация "Hide Noise" и "Mark as Valid/Noise"

**Дата:** 2026-02-12
**Цель:** Изучение существующей реализации для минимизации рисков регрессии

---

## 1. Обзор реализации

### Затронутые компоненты

| Компонент | Файл | Назначение |
|-----------|------|-----------|
| **Dictionary View** | `app/ui/dictionary_view.py` | UI для лемм |
| **Terms View** | `app/ui/terms_view.py` | UI для термов |
| **Lemma Model** | `app/infra/sa_models.py:224-242` | БД модель леммы |
| **TermCluster Model** | `app/infra/sa_models.py:498-544` | БД модель терм-кластера |
| **Term Service** | `app/services/term_extraction_service.py:670-731` | Бизнес-логика фильтрации |

---

## 2. Модели данных

### 2.1. Lemma (Лемма)

```python
class Lemma(Base):
    __tablename__ = "lemma"

    lemma_id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey(...), nullable=False)
    lemma_text = Column(String, nullable=False)
    pos = Column(String)

    # Entity classification (Task 11 - Migration 010)
    entity_class = Column(String)      # WORD_HE, WORD_LATIN, MIXED_ALPHA_NUM, NUMBER, etc.
    is_noise = Column(Integer, default=0)  # 0=not noise, 1=noise
    noise_reason = Column(String)      # NOISE_PUNCT_ONLY, NOISE_SYMBOL_ONLY, etc.
    norm_text = Column(String)         # Normalized form
```

**Значения is_noise:**
- `0` или `NULL` - валидная лемма (не шум)
- `1` - шумовая лемма (noise)

**Примеры entity_class:**
- `WORD_HE` - еврейское слово
- `WORD_LATIN` - латинское слово
- `MIXED_ALPHA_NUM` - смешанный (буквы + цифры)
- `NUMBER` - число
- `PUNCT_ONLY` - только пунктуация
- `SYMBOL_ONLY` - только символы

**Примеры noise_reason:**
- `NOISE_PUNCT_ONLY` - только пунктуация (например, "...")
- `NOISE_SYMBOL_ONLY` - только символы (например, "###")
- `NOISE_NUMBER_ONLY` - только числа (например, "123")

### 2.2. TermCluster (Терм-кластер)

```python
class TermCluster(Base):
    __tablename__ = "term_cluster"

    cluster_id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey(...), nullable=False)

    canonical_key = Column(String, nullable=False)
    representative_he = Column(Text, nullable=False)

    freq_abs = Column(Integer, nullable=False, default=0)
    curation_status = Column(String, nullable=False, default='auto')

    # Entity classification (Task 11 - Migration 010)
    entity_class = Column(String)      # Как у Lemma
    is_noise = Column(Integer, default=0)  # 0=not noise, 1=noise
    noise_reason = Column(String)      # Как у Lemma
    norm_text = Column(String)         # Normalized form
```

**Структура идентична Lemma** - одинаковые поля для классификации.

---

## 3. UI Компоненты

### 3.1. Dictionary View (Леммы)

**Расположение:** `app/ui/dictionary_view.py`

#### A. Hide Noise Checkbox

**Код (строка 80-84):**
```python
self.hide_noise_checkbox = QCheckBox("Hide noise")
self.hide_noise_checkbox.setChecked(True)  # Default: hide noise
self.hide_noise_checkbox.setToolTip("Hide punctuation, numbers, symbols, and other noise")
self.hide_noise_checkbox.stateChanged.connect(self.load_lemmas)
```

**Поведение:**
- По умолчанию **включен** (checked=True)
- Tooltip: "Hide punctuation, numbers, symbols, and other noise"
- При изменении → вызывает `self.load_lemmas()` (перезагрузка данных)

**Фильтрация в load_lemmas() (строка 186-189):**
```python
if self.hide_noise_checkbox.isChecked():
    # Hide noise: is_noise = 0 OR is_noise IS NULL (backward compatibility)
    from sqlalchemy import or_
    stmt = stmt.where(or_(Lemma.is_noise == 0, Lemma.is_noise.is_(None)))
```

**SQL (псевдокод):**
```sql
WHERE (lemma.is_noise = 0 OR lemma.is_noise IS NULL)
```

**Обратная совместимость:**
- `is_noise IS NULL` - для лемм из старых проектов (до Migration 010)
- `is_noise = 0` - для валидных лемм (после Migration 010)

#### B. Context Menu (Правая кнопка мыши)

**Код (строки 404-422):**

**Случай 1: Выделено несколько строк (bulk action)**
```python
if len(selected_rows) > 1:
    mark_valid_bulk_action = QAction(
        f"✓ Mark Selected as Valid ({len(selected_rows)} rows)",
        self
    )
    mark_valid_bulk_action.triggered.connect(
        lambda: self.set_lemmas_noise_status_bulk(False)
    )
    menu.addAction(mark_valid_bulk_action)

    mark_noise_bulk_action = QAction(
        f"✗ Mark Selected as Noise ({len(selected_rows)} rows)",
        self
    )
    mark_noise_bulk_action.triggered.connect(
        lambda: self.set_lemmas_noise_status_bulk(True)
    )
    menu.addAction(mark_noise_bulk_action)
```

**Случай 2: Выделена одна строка**
```python
else:
    current_is_noise = lemma.is_noise == 1 if lemma.is_noise is not None else False

    if current_is_noise:
        # Лемма помечена как noise → предложить "Mark as Valid"
        mark_valid_action = QAction("✓ Mark as Valid (remove from noise)", self)
        mark_valid_action.triggered.connect(
            lambda: self.set_lemma_noise_status(source_row, False)
        )
        menu.addAction(mark_valid_action)
    else:
        # Лемма валидна → предложить "Mark as Noise"
        mark_noise_action = QAction("✗ Mark as Noise", self)
        mark_noise_action.triggered.connect(
            lambda: self.set_lemma_noise_status(source_row, True)
        )
        menu.addAction(mark_noise_action)
```

**Логика:**
- Если `is_noise == 1` → показать "Mark as Valid (remove from noise)"
- Если `is_noise == 0` или `NULL` → показать "Mark as Noise"

#### C. Single Update (Одиночное обновление)

**Метод:** `set_lemma_noise_status(row, is_noise)`
**Код (строки 447-475):**

```python
def set_lemma_noise_status(self, row: int, is_noise: bool):
    """Task 11: Manually override noise status for a lemma."""
    lemma = self.lemma_model.lemmas[row]

    try:
        from sqlalchemy import update
        from app.infra.sa_models import Lemma

        db_service = DBService.get_instance()
        with db_service.get_session() as session:
            # Update is_noise field
            stmt = update(Lemma).where(
                Lemma.lemma_id == lemma.lemma_id
            ).values(
                is_noise=1 if is_noise else 0
            )
            session.execute(stmt)
            session.commit()

            # Update model cache
            lemma.is_noise = 1 if is_noise else 0

            status = "noise" if is_noise else "valid"
            logger.info(f"Marked lemma '{lemma.lemma_text}' as {status}")

            # Reload to apply filter if needed
            if self.hide_noise_checkbox.isChecked():
                self.load_lemmas()

    except Exception as e:
        logger.exception(f"Failed to set noise status for lemma {lemma.lemma_id}")
        show_error(self, "Error", f"Failed to update noise status: {e}")
```

**Логика:**
1. UPDATE Lemma SET is_noise = 1/0 WHERE lemma_id = ?
2. Обновить кеш модели: `lemma.is_noise = 1 if is_noise else 0`
3. Логирование
4. **Если hide_noise_checkbox.isChecked() → reload lemmas**
   - Чтобы шумовая лемма исчезла из списка (если checkbox включен)

**SQL (псевдокод):**
```sql
UPDATE lemma
SET is_noise = 1  -- или 0
WHERE lemma_id = ?
```

#### D. Bulk Update (Массовое обновление)

**Метод:** `set_lemmas_noise_status_bulk(is_noise)`
**Код (строки 480-524):**

```python
def set_lemmas_noise_status_bulk(self, is_noise: bool):
    """Task 11: Bulk operation - update noise status for multiple selected lemmas."""
    selected_rows = self.lemma_table.selectionModel().selectedRows()
    if not selected_rows:
        return

    # Collect lemma IDs
    lemma_ids = []
    for model_index in selected_rows:
        source_row = model_index.row()
        lemma = self.lemma_model.lemmas[source_row]
        lemma_ids.append(lemma.lemma_id)

    try:
        from sqlalchemy import update
        from app.infra.sa_models import Lemma

        db_service = DBService.get_instance()
        with db_service.get_session() as session:
            # Bulk update
            stmt = update(Lemma).where(
                Lemma.lemma_id.in_(lemma_ids)
            ).values(
                is_noise=1 if is_noise else 0
            )
            result = session.execute(stmt)
            session.commit()

            # Update model cache
            for model_index in selected_rows:
                source_row = model_index.row()
                self.lemma_model.lemmas[source_row].is_noise = 1 if is_noise else 0

            status = "noise" if is_noise else "valid"
            logger.info(f"Marked {len(lemma_ids)} lemmas as {status}")

            # Show success message
            QMessageBox.information(
                self,
                "Success",
                f"Marked {len(lemma_ids)} lemmas as {status}"
            )

            # Reload to apply filter if needed
            if self.hide_noise_checkbox.isChecked():
                self.load_lemmas()

    except Exception as e:
        logger.exception(f"Failed to bulk update noise status")
        show_error(self, "Error", f"Failed to bulk update noise status: {e}")
```

**Логика:**
1. Собрать lemma_ids из выделенных строк
2. UPDATE Lemma SET is_noise = 1/0 WHERE lemma_id IN (?, ?, ...)
3. Обновить кеш модели для всех выделенных строк
4. Показать success message: "Marked N lemmas as noise/valid"
5. **Если hide_noise_checkbox.isChecked() → reload lemmas**

**SQL (псевдокод):**
```sql
UPDATE lemma
SET is_noise = 1  -- или 0
WHERE lemma_id IN (1, 2, 3, ...)
```

---

### 3.2. Terms View (Термы)

**Расположение:** `app/ui/terms_view.py`

**Реализация ИДЕНТИЧНА Dictionary View**, но для TermCluster вместо Lemma:

| Компонент | Dictionary View | Terms View |
|-----------|----------------|------------|
| Model | Lemma | TermCluster |
| Checkbox | hide_noise_checkbox (line 80) | hide_noise_checkbox (line 140) |
| Tooltip | "Hide punctuation, numbers, symbols, and other noise" | "Hide numeric, symbolic, and other noisy terms" |
| Filter | `or_(Lemma.is_noise == 0, Lemma.is_noise.is_(None))` | `or_(TermCluster.is_noise == 0, TermCluster.is_noise.is_(None))` |
| Single update | `set_lemma_noise_status(row, is_noise)` | `set_cluster_noise_status(row, is_noise)` |
| Bulk update | `set_lemmas_noise_status_bulk(is_noise)` | `set_clusters_noise_status_bulk(is_noise)` |
| SQL | UPDATE lemma SET is_noise = ... | UPDATE term_cluster SET is_noise = ... |

**Код практически идентичен**, только замена:
- `Lemma` → `TermCluster`
- `lemma_id` → `cluster_id`
- `lemma_text` → `representative_he`
- `self.lemma_model` → `self.terms_model`

---

## 4. Service Layer (Бизнес-логика)

### 4.1. Term Extraction Service

**Метод:** `list_term_clusters()`
**Файл:** `app/services/term_extraction_service.py:670-731`

**Параметр:**
```python
def list_term_clusters(
    session, project_id,
    hide_noise: bool = True,  # Default: скрывать шум
    ...
) -> List[ClusterStats]:
```

**Фильтрация (строка 729-731):**
```python
# Apply noise filter (Task 11: Entity Classification)
if hide_noise:
    # Hide noise: is_noise = 0 OR is_noise IS NULL (backward compatibility)
    stmt = stmt.where(or_(TermCluster.is_noise == 0, TermCluster.is_noise.is_(None)))
```

**SQL (псевдокод):**
```sql
WHERE (term_cluster.is_noise = 0 OR term_cluster.is_noise IS NULL)
```

**Обратная совместимость:**
- Поддерживает старые проекты (is_noise IS NULL)
- Новые проекты (is_noise = 0)

---

## 5. Риски регрессии и митигации

### 5.1. Риск: Потеря данных при bulk update

**Описание:**
Массовое обновление is_noise для сотен/тысяч записей может привести к потере данных при ошибке в середине транзакции.

**Текущая митигация:**
- ✅ Используется транзакция (session.commit())
- ✅ Try-except блок с rollback при ошибке
- ✅ UPDATE одним запросом (не N запросов)

**Дополнительная митигация:**
- ⚠️ Отсутствует подтверждение при bulk update большого количества (>100 rows)
- **Рекомендация:** Добавить предупреждение "You are about to mark N lemmas as noise. Continue?"

### 5.2. Риск: Десинхронизация UI модели и БД

**Описание:**
После UPDATE в БД модель обновляется вручную (`lemma.is_noise = 1`). Если reload не произойдет, UI может показывать устаревшие данные.

**Текущая митигация:**
- ✅ Обновление кеша модели сразу после UPDATE
- ✅ Reload при hide_noise_checkbox.isChecked()

**Риск:**
- ⚠️ Если checkbox НЕ включен, строка остается в таблице, но is_noise уже изменен
- **Сценарий:** User отключил "Hide noise", пометил лемму как noise, затем включил checkbox → лемма НЕ исчезнет до reload

**Текущее поведение:**
- Если checkbox включен → reload происходит → OK
- Если checkbox выключен → строка остается → Приемлемо (пользователь видит все)

**Рекомендация:** Текущее поведение корректно, митигация не требуется.

### 5.3. Риск: Backward compatibility (is_noise IS NULL)

**Описание:**
Старые проекты (до Migration 010) имеют is_noise = NULL. Фильтр должен их показывать как валидные.

**Текущая митигация:**
- ✅ Фильтр: `or_(is_noise == 0, is_noise.is_(None))`
- ✅ Строки с NULL показываются как валидные

**Риск:**
- ⚠️ Если старый проект содержит реально шумовые леммы, но is_noise = NULL, они будут показаны как валидные

**Рекомендация:**
- Запустить migration script для классификации is_noise = NULL → is_noise = 0/1
- Или оставить как есть (пользователь может вручную пометить)

### 5.4. Риск: Performance на больших датасетах

**Описание:**
Bulk update для 10k+ rows может занять несколько секунд и заблокировать UI.

**Текущая митигация:**
- ❌ НЕТ: UPDATE выполняется в main thread (блокирует UI)
- ❌ НЕТ: Нет progress bar для длительных операций

**Рекомендация:**
- Добавить QThread worker для bulk update > 1000 rows
- Показывать progress dialog

### 5.5. Риск: Неправильная интерпретация is_noise в context menu

**Описание:**
Context menu проверяет `lemma.is_noise == 1` для определения, какой пункт показать. Если is_noise = NULL, это трактуется как False (валидный).

**Текущее поведение (строка 413):**
```python
current_is_noise = lemma.is_noise == 1 if lemma.is_noise is not None else False
```

**Логика:**
- `is_noise = 1` → True (noise)
- `is_noise = 0` → False (valid)
- `is_noise = NULL` → False (valid, по умолчанию)

**Митигация:** ✅ Корректно, NULL трактуется как валидный.

### 5.6. Риск: Отсутствие undo для bulk actions

**Описание:**
Bulk update необратим (нет undo). Если пользователь случайно пометил 1000 лемм как noise, восстановить сложно.

**Текущая митигация:**
- ❌ НЕТ: Нет undo functionality
- ✅ Есть: Success message с количеством (можно заметить ошибку)

**Рекомендация:**
- Добавить confirmation dialog для bulk > 100 rows
- Рассмотреть audit log (история изменений is_noise)

### 5.7. Риск: Reload ломает selection

**Описание:**
После `load_lemmas()` выделение (selection) сбрасывается. Если пользователь выделил несколько строк, пометил одну как noise, reload сбросит выделение остальных.

**Текущее поведение:**
- Reload происходит только если hide_noise_checkbox.isChecked()
- При reload выделение теряется

**Рекомендация:**
- Сохранять lemma_ids выделенных строк перед reload
- Восстанавливать selection после reload (если леммы еще в таблице)

---

## 6. Таблица рисков

| # | Риск | Вероятность | Влияние | Текущая митигация | Статус |
|---|------|-------------|---------|-------------------|--------|
| 1 | Потеря данных при bulk update | Низкая | Высокое | Транзакция + try-except | ✅ Покрыто |
| 2 | Десинхронизация UI и БД | Низкая | Среднее | Обновление кеша + reload | ✅ Покрыто |
| 3 | Backward compatibility (NULL) | Низкая | Среднее | `is_noise IS NULL` в фильтре | ✅ Покрыто |
| 4 | Performance (10k+ rows) | Средняя | Среднее | Нет | ⚠️ Требует улучшения |
| 5 | Неправильная интерпретация NULL | Низкая | Низкое | `if is not None else False` | ✅ Покрыто |
| 6 | Отсутствие undo | Средняя | Высокое | Success message | ⚠️ Требует улучшения |
| 7 | Reload ломает selection | Средняя | Низкое | Нет | ⚠️ Требует улучшения |

---

## 7. Рекомендации для минимизации рисков

### Критичные (P0)

1. **Confirmation dialog для bulk > 100 rows**
   ```python
   if len(selected_rows) > 100:
       reply = QMessageBox.question(
           self, 'Confirm Bulk Action',
           f'You are about to mark {len(selected_rows)} lemmas as noise. Continue?',
           QMessageBox.Yes | QMessageBox.No
       )
       if reply == QMessageBox.No:
           return
   ```

2. **Progress dialog для bulk > 1000 rows**
   - Создать QThread worker
   - Показывать progress bar
   - Разрешить cancel

### Важные (P1)

3. **Сохранение selection после reload**
   ```python
   # Before reload
   selected_lemma_ids = [lemma.lemma_id for lemma in selected_lemmas]

   # After reload
   for row, lemma in enumerate(self.lemma_model.lemmas):
       if lemma.lemma_id in selected_lemma_ids:
           self.lemma_table.selectRow(row)
   ```

4. **Audit log для is_noise changes**
   - Создать таблицу `lemma_noise_audit` (lemma_id, old_value, new_value, changed_by, changed_at)
   - Логировать изменения is_noise
   - Позволит восстановить данные при ошибке

### Опциональные (P2)

5. **Batch classification для is_noise = NULL**
   - Запустить migration script для старых проектов
   - Классифицировать по entity_class

6. **Keyboard shortcuts**
   - `V` = Mark as Valid
   - `N` = Mark as Noise
   - `Shift+V/N` = Bulk action

---

## 8. Checklist для тестирования регрессии

### Dictionary View

- [ ] Hide Noise checkbox: включен по умолчанию
- [ ] Hide Noise checkbox: скрывает is_noise = 1
- [ ] Hide Noise checkbox: показывает is_noise = 0 и NULL
- [ ] Context menu (одна строка, valid): показывает "Mark as Noise"
- [ ] Context menu (одна строка, noise): показывает "Mark as Valid"
- [ ] Context menu (несколько строк): показывает bulk actions
- [ ] Mark as Noise (single): UPDATE is_noise = 1
- [ ] Mark as Valid (single): UPDATE is_noise = 0
- [ ] Mark as Noise (bulk): UPDATE is_noise = 1 для всех
- [ ] Mark as Valid (bulk): UPDATE is_noise = 0 для всех
- [ ] После mark as noise (hide_noise ON): лемма исчезает
- [ ] После mark as valid (hide_noise ON): лемма появляется (reload)
- [ ] Success message после bulk action
- [ ] Error message при DB ошибке

### Terms View

- [ ] (Те же тесты, но для TermCluster)

### Performance

- [ ] Bulk update 10 rows: < 1 sec
- [ ] Bulk update 100 rows: < 3 sec
- [ ] Bulk update 1000 rows: < 10 sec
- [ ] Bulk update не блокирует UI (если > 1000 rows)

### Edge Cases

- [ ] is_noise = NULL: показывается как valid
- [ ] is_noise = 0: показывается как valid
- [ ] is_noise = 1: скрывается (если hide_noise ON)
- [ ] Пустой selection: bulk actions недоступны
- [ ] DB error: rollback + error message
- [ ] Reload после bulk: selection сохраняется (если P1 реализовано)

---

## 9. Итоги

**Текущая реализация:**
- ✅ Функционально полная
- ✅ SQL-безопасная (транзакции, try-except)
- ✅ Backward compatible (поддержка NULL)
- ✅ DRY (Dictionary и Terms используют одинаковый паттерн)

**Риски:**
- ⚠️ Performance при bulk > 1000 rows (блокирует UI)
- ⚠️ Отсутствие undo (необратимые изменения)
- ⚠️ Reload ломает selection

**Рекомендации:**
- P0: Confirmation dialog для bulk > 100
- P0: Progress dialog + QThread для bulk > 1000
- P1: Сохранение selection после reload
- P1: Audit log для is_noise changes

**Общая оценка:** Реализация **надежна** для типичных use cases (<100 rows). Требуются улучшения для больших датасетов (1000+ rows).
