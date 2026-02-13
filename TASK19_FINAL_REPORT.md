# Task 19: Global TM - Final Report

## Дата: 2026-02-13

## Проблема

После первоначальной реализации Task 19 (3 patches) обнаружена критическая проблема:

**Межпроектное распространение переводов НЕ работало.**

### Воспроизведение

1. Проект 7: лемма "אוסטניטי" имеет перевод "Аустенитный"
2. Проект 6: та же лемма имеет ПУСТОЙ перевод
3. Обе записи tm_entry связаны с одной tm_global (id=2157) с переводом "Аустенитный"

**Ожидалось**: Перевод должен автоматически распространиться на все проекты
**Реально**: Проект 6 остался с пустым переводом

---

## Root Cause Analysis

### Анализ кода

Функция `upsert_and_link()` обновляла `tm_global`, но **НЕ вызывала `propagate_to_entries()`** для синхронизации всех связанных `tm_entry`.

```python
# БЫЛО (неправильно):
def upsert_and_link(self, session, entry):
    g = self.upsert_global(...)
    entry.tm_global_id = g.tm_global_id
    return g  # ❌ Не вызывает propagate_to_entries!
```

### Цепочка проблем

1. Пользователь редактирует перевод в проекте 7 → `on_translation_edited()` вызывается
2. `upsert_and_link()` обновляет `tm_global` с новым переводом ✅
3. `tm_entry` в проекте 7 обновляется ✅
4. **НО**: `tm_entry` в проекте 6 НЕ обновляется ❌
5. Проект 6 остается с пустым переводом ❌

---

## Решение (Hotfix commit 2c24f23)

### 1. Исправление `upsert_and_link()`

**Файл**: `app/services/tm_global_service.py`

```python
# СТАЛО (правильно):
def upsert_and_link(self, session, entry):
    g = self.upsert_global(...)
    entry.tm_global_id = g.tm_global_id

    # CRITICAL FIX: Propagate tm_global changes to ALL linked tm_entries
    session.flush()
    self.propagate_to_entries(
        session=session,
        tm_global_id=g.tm_global_id,
        fields=["translation", "status", "origin", "confidence", "is_noise", "noise_reason"]
    )

    return g  # ✅ Теперь распространяет изменения!
```

### 2. Дополнение `propagate_to_entries()`

Добавлены поля `"origin"` и `"confidence"`:

```python
# БЫЛО:
if "translation" in fields and entry.translation != g.translation:
    entry.translation = g.translation
    changed = True
if "status" in fields and entry.status != g.status:
    entry.status = g.status
    changed = True

# ДОБАВЛЕНО:
if "origin" in fields and entry.origin != g.origin:
    entry.origin = g.origin
    changed = True
if "confidence" in fields and entry.confidence != g.confidence:
    entry.confidence = g.confidence
    changed = True
```

### 3. Скрипт для исправления существующих данных

**Файл**: `scripts/repropagate_tm_global.py`

Одноразовый скрипт для распространения всех существующих `tm_global` на связанные `tm_entry`:

```bash
python scripts/repropagate_tm_global.py --dry-run  # Предпросмотр
python scripts/repropagate_tm_global.py            # Исправление данных
```

**Результат**: Обновлено 13,006 записей tm_entry

---

## Тестирование

### 1. Новые автоматические тесты

**Файл**: `tests/test_task19_propagation.py`

Созданы 3 новых теста для проверки межпроектного распространения:

1. **`test_cross_project_propagation`**: Редактирование в проекте 7 → распространяется на проект 6
2. **`test_edit_propagation`**: Обновление существующего перевода → распространяется на все проекты
3. **`test_no_overwrite_higher_score`**: Перевод с низким score не перезаписывает высокий score

### 2. Результаты тестов

```bash
# Task 19 тесты
python -m pytest tests/test_task19_tm_global.py tests/test_task19_propagation.py -v
```

**✅ Все 13 тестов PASSED (10 оригинальных + 3 новых)**

```bash
# Регрессионные тесты
python -m pytest tests/test_security.py tests/test_task12_fts_nlp.py tests/test_task13_trigger_sync.py -v
```

**✅ Все 50 регрессионных тестов PASSED**

### 3. Ручная проверка

**До исправления**:
```
Project 6: tm_entry.translation = ""  (пусто)
Project 7: tm_entry.translation = "Аустенитный"
tm_global: translation = "Аустенитный"
```

**После repropagate_tm_global.py**:
```
Project 6: tm_entry.translation = "Аустенитный"  ✅
Project 7: tm_entry.translation = "Аустенитный"  ✅
tm_global: translation = "Аустенитный"
```

**Проверка**:
```bash
python scripts/check_lemma.py
cat lemma_check_result.txt
```

---

## Verification Checklist

### ✅ 1. Межпроектное sharing работает

- [x] Редактирование перевода в любом проекте распространяется на все проекты
- [x] Пустые переводы заполняются из tm_global
- [x] Оба проекта показывают одинаковый перевод для одной леммы

### ✅ 2. Детерминированный scoring

- [x] Approved + user_edit beats draft + mt_auto
- [x] Низкий score не перезаписывает высокий score
- [x] Последнее обновление учитывается при равных score

### ✅ 3. Политика шума (noise)

- [x] Глобальный noise = 1 только если ВСЕ записи имеют is_noise = 1
- [x] Если хотя бы один проект считает термин валидным, tm_global.is_noise = 0

### ✅ 4. Идемпотентный backfill

- [x] Backfill можно запускать многократно без ошибок
- [x] Re-propagation script безопасно запускать повторно
- [x] UNIQUE constraint предотвращает дубликаты

### ✅ 5. Обратная совместимость

- [x] tm_entry.translation остается источником для UI
- [x] Старые проекты без tm_global продолжают работать
- [x] Читающий путь (read-path) проверяет tm_global как fallback

---

## Команды для воспроизведения тестов

```bash
# 1. Диагностика состояния БД
python scripts/diagnose_task19.py

# 2. Проверка конкретной леммы
python scripts/check_lemma.py
cat lemma_check_result.txt

# 3. Re-propagation (если нужно исправить данные)
python scripts/repropagate_tm_global.py --dry-run  # Предпросмотр
python scripts/repropagate_tm_global.py            # Исправление

# 4. Автоматические тесты
python -m pytest tests/test_task19_tm_global.py tests/test_task19_propagation.py -v

# 5. Регрессионные тесты
python -m pytest tests/test_security.py tests/test_task12_fts_nlp.py tests/test_task13_trigger_sync.py -v
```

---

## Коммиты

1. **58a026d**: PATCH-03 - read-path fallback + tests + docs
2. **2c24f23**: **HOTFIX** - automatic cross-project propagation
3. **77af916**: docs update with propagation hotfix

---

## Файлы

### Созданные (hotfix)

- `tests/test_task19_propagation.py` - 3 новых теста для propagation
- `scripts/repropagate_tm_global.py` - скрипт исправления данных
- `scripts/diagnose_task19.py` - диагностический инструмент
- `scripts/check_lemma.py` - проверка конкретной леммы

### Модифицированные (hotfix)

- `app/services/tm_global_service.py` - upsert_and_link + propagate_to_entries
- `docs/TASK19_IMPLEMENTATION_SUMMARY.md` - обновлена документация

---

## Статистика

- **Исправлено записей**: 13,006 (все tm_entry в БД)
- **Новых тестов**: 3 (cross-project propagation)
- **Всего тестов Task 19**: 13 (10 + 3)
- **Регрессионных тестов**: 50
- **Все тесты**: ✅ **PASSED (63/63)**

---

## Заключение

### Проблема РЕШЕНА ✅

Межпроектное распространение переводов теперь работает автоматически:

1. ✅ Редактирование перевода в любом проекте → распространяется на все проекты
2. ✅ Детерминированный scoring гарантирует выбор лучшего перевода
3. ✅ Политика шума работает корректно (глобально noise только если все проекты согласны)
4. ✅ Обратная совместимость сохранена
5. ✅ Все тесты проходят (63/63)

### Готово к production использованию

Task 19 (Global TM Canonical Layer) полностью реализован и протестирован.

**Рекомендация**: Можно продолжать работу с уверенностью, что межпроектное sharing переводов работает корректно.
