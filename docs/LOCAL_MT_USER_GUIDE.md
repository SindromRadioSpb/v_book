# Local MT User Guide - NLLB Model Translation

> **⚠️ DEPRECATED - This document is outdated (early development phase)**
>
> **For current documentation, see:**
> - **User Guide:** `docs/PROVIDER_SETUP_GUIDE.md` → "Local MT Providers" section
> - **License Notes:** `docs/LOCAL_MT_LICENSE_NOTES.md`
> - **Implementation Plan:** `docs/P1_TRANSLATION_PRO_PLAN.md` → "task_4_MT_local" section
>
> **Status Update (2026-02-08):**
> - ✅ All features mentioned below are now COMPLETE (PATCH-00 through PATCH-09)
> - ✅ LocalNLLBProvider fully integrated into provider chain
> - ✅ Sentence segmentation working
> - ✅ Glossary postprocess working
> - ✅ MT cache keying with model version isolation
> - ✅ Full UI integration

---

## 📋 Текущее состояние (2026-02-07) [OUTDATED]

### ✅ Что работает:
1. **Модель установлена:** `J:\HDLE\models\facebook_nllb-200-distilled-1.3B_ctranslate2`
2. **Проверка модели:** `python scripts/install_local_mt_model.py --list`
3. **Worker process:** Инфраструктура для запуска инференса
4. **Provider Settings UI:** Настройки провайдеров (пока без Local NLLB)

### ❌ Что НЕ работает:
1. **Перевод через UI:** LocalNLLBProvider ещё не создан
2. **Интеграция в цепочку:** Провайдер не добавлен в registry
3. **Сегментация предложений:** Длинные тексты могут работать плохо
4. **Постобработка терминологии:** Применение утверждённых терминов

---

## 🧪 Тестирование модели (без UI)

### Вариант 1: Через тестовый скрипт

```bash
python scripts/test_nllb_model.py
```

**Что делает скрипт:**
1. Проверяет установку модели
2. Запускает worker process
3. Выполняет 5 тестовых переводов:
   - English → Hebrew ("Hello world")
   - Hebrew → English ("שלום עולם")
   - English → Russian ("Hello world")
   - Hebrew → Russian ("שלום עולם")
   - Technical term ("database management system")
4. Показывает время инференса
5. Корректно завершает worker

**Ожидаемый результат:**
```
============================================================
NLLB Model Translation Test
============================================================

1. Checking if model installed...
   ✅ Model installed: J:\HDLE\models\facebook_nllb-200-distilled-1.3B_ctranslate2

2. Starting worker process...
   ✅ Worker started successfully

3. Running translation tests...

   Test 1/5: English → Hebrew
   Source: Hello world
   ✅ Translation: שלום עולם
      Inference time: 234.56 ms

   Test 2/5: Hebrew → English
   Source: שלום עולם
   ✅ Translation: Hello world
      Inference time: 198.32 ms

   ...

4. Shutting down worker...
   ✅ Worker shut down successfully

============================================================
✅ Test completed successfully!
============================================================
```

### Вариант 2: Через Python REPL (интерактивный режим)

```python
from pathlib import Path
from app.infra.local_mt import start_worker, WorkerRequest
from app.services.local_models import ModelResourceManager

# 1. Проверка модели
manager = ModelResourceManager()
model_path = manager.model_dir("facebook/nllb-200-distilled-1.3B", "ctranslate2")
print(f"Model path: {model_path}")

# 2. Запуск worker
worker = start_worker(
    model_path=model_path,
    backend="ctranslate2",
    model_id="facebook/nllb-200-distilled-1.3B",
    timeout=30.0,
)

# 3. Перевод English → Hebrew
request = WorkerRequest(
    text="Hello world",
    source_lang="eng_Latn",
    target_lang="heb_Hebr",
)
result = worker.translate(request)
print(f"Translation: {result.text}")
print(f"Time: {result.inference_time_ms:.2f} ms")

# 4. Перевод Hebrew → Russian
request2 = WorkerRequest(
    text="שלום עולם",
    source_lang="heb_Hebr",
    target_lang="rus_Cyrl",
)
result2 = worker.translate(request2)
print(f"Translation: {result2.text}")

# 5. Завершение
worker.shutdown()
```

---

## 🚀 Интеграция в UI (Roadmap)

### Что нужно сделать для работы переводов через UI:

#### PATCH-04: Sentence Segmentation (2-3 дня)
**Зачем:** NLLB работает плохо на длинных текстах (>512 токенов)
**Что делает:** Разбивает длинный текст на предложения, переводит каждое отдельно, собирает обратно

**Файлы:**
- `app/services/local_mt/segmentation.py`
- `tests/test_local_mt_segmentation.py`

**Пример:**
```python
Input: "שלום עולם! זה טסט. עוד משפט?"
Segments: ["שלום עולם!", "זה טסט.", "עוד משפט?"]
# Translate each → Reassemble with separators
Output: "Hello world! This is a test. Another sentence?"
```

---

#### PATCH-05: Glossary Postprocess (2 дня)
**Зачем:** NLLB не поддерживает глоссарий нативно
**Что делает:** После перевода заменяет термины на утверждённые из tm_entry

**Пример:**
```python
# Translation from NLLB
translated = "система управления базами данных"

# Approved terms from tm_entry
glossary = [
    {"source": "database", "target": "מסד נתונים"},
    {"source": "management system", "target": "מערכת ניהול"},
]

# Postprocess
final = apply_glossary(translated, glossary)
# Result: "מערכת ניהול מסד נתונים" (with approved terms)
```

---

#### PATCH-06: LocalNLLBProvider (3-4 дня)
**Главный компонент!** Провайдер для интеграции в систему переводов.

**Файлы:**
- `app/infra/translators/providers/local_nllb_provider.py`
- `tests/test_local_nllb_provider.py`

**Интерфейс:**
```python
class LocalNLLBProvider(BaseProvider):
    @property
    def provider_id(self) -> str:
        return "local_nllb"

    @property
    def display_name(self) -> str:
        return "Local NLLB (Offline)"

    @property
    def supports_glossary(self) -> bool:
        return True  # Via postprocessing

    def translate(self, request: TranslationRequest) -> TranslationResult:
        # 1. Check model installed
        # 2. Start worker if not running
        # 3. Segment text (PATCH-04)
        # 4. Translate via worker
        # 5. Apply glossary (PATCH-05)
        # 6. Return result
        pass

    def healthcheck(self) -> bool:
        # Check if model installed
        pass
```

---

#### PATCH-08: Provider Chain Integration (1 день)
**Зачем:** Добавить Local NLLB в цепочку провайдеров
**Что делает:** Регистрирует провайдер и ставит в начало цепочки

**Изменения:**
```python
# app/infra/translators/providers_registry.py
from app.infra.translators.providers.local_nllb_provider import LocalNLLBProvider

def register_providers():
    registry = ProvidersRegistry()

    # Register local providers first (highest priority)
    registry.register(LocalNLLBProvider())

    # Then external providers
    registry.register(DeepLProvider())
    registry.register(MicrosoftProvider())
    ...
```

**Provider chain order:**
```json
["local_nllb", "deepl", "microsoft", "libretranslate"]
```

---

## 📊 Ожидаемые коды языков (NLLB-200)

### Поддерживаемые языки в проекте:

| Язык         | Код NLLB       | Примечание                     |
|--------------|----------------|--------------------------------|
| Иврит        | `heb_Hebr`     | Hebrew script                  |
| Английский   | `eng_Latn`     | Latin script                   |
| Русский      | `rus_Cyrl`     | Cyrillic script                |
| Французский  | `fra_Latn`     | Latin script                   |
| Немецкий     | `deu_Latn`     | Latin script                   |
| Испанский    | `spa_Latn`     | Latin script                   |
| Итальянский  | `ita_Latn`     | Latin script                   |

**Формат:** `{язык}_{письменность}`

### Как узнать код языка:
```python
# Mapping существующих кодов в NLLB
LANGUAGE_CODES = {
    "he": "heb_Hebr",  # Hebrew
    "en": "eng_Latn",  # English
    "ru": "rus_Cyrl",  # Russian
    "fr": "fra_Latn",  # French
    "de": "deu_Latn",  # German
}
```

---

## 🎯 Варианты действий

### Вариант А: Быстрая интеграция (3-4 часа)
**Цель:** Минимальная версия для тестирования в UI

**Шаги:**
1. Создать упрощённый LocalNLLBProvider (без сегментации и глоссария)
2. Зарегистрировать в ProvidersRegistry
3. Протестировать через UI Translation Management Panel

**Плюсы:**
- Быстро увидите результат в UI
- Можно тестировать перевод лемм/терминов

**Минусы:**
- Без сегментации (плохо на длинных текстах)
- Без постобработки терминологии
- Упрощённая версия

---

### Вариант Б: Полная интеграция (5-7 дней)
**Цель:** Правильная реализация с качеством

**Шаги:**
1. PATCH-04: Sentence segmentation (2 дня)
2. PATCH-05: Glossary postprocess (2 дня)
3. PATCH-06: LocalNLLBProvider (3 дня)
4. PATCH-08: Provider chain integration (1 день)

**Плюсы:**
- Качественный перевод
- Работа с длинными текстами
- Применение утверждённой терминологии
- Production-ready

**Минусы:**
- Дольше

---

## 💡 Рекомендации

### Для тестирования модели прямо сейчас:
```bash
# 1. Запустить тестовый скрипт
python scripts/test_nllb_model.py

# 2. Проверить список моделей
python scripts/install_local_mt_model.py --list

# 3. Проверить установку
python scripts/install_local_mt_model.py --verify nllb-200-distilled-1.3B --backend ctranslate2
```

### Для перевода лемм/терминов через UI:
**Сейчас:** ❌ Не работает (нужен LocalNLLBProvider)

**Решение:**
1. **Быстро (Вариант А):** Создать минимальный провайдер за 3-4 часа
2. **Правильно (Вариант Б):** Последовательно PATCH-04 → PATCH-05 → PATCH-06 → PATCH-08

---

## 🔍 Проверка работоспособности модели

### Диагностика:
```bash
# 1. Проверка файлов модели
dir J:\HDLE\models\facebook_nllb-200-distilled-1.3B_ctranslate2
# Должны быть: model.bin, shared_vocabulary.json, config.json, manifest.json

# 2. Проверка манифеста
python -c "import json; print(json.load(open(r'J:\HDLE\models\facebook_nllb-200-distilled-1.3B_ctranslate2\manifest.json')))"

# 3. Тест worker process
python scripts/test_nllb_model.py
```

### Возможные проблемы:

**1. Worker fails to start: "ctranslate2 not installed"**
```bash
# Решение: Установить ctranslate2
pip install ctranslate2
```

**2. Worker fails to start: "Unable to open file 'model.bin'"**
```bash
# Решение: Проверить путь и права доступа
dir J:\HDLE\models\facebook_nllb-200-distilled-1.3B_ctranslate2\model.bin
```

**3. Translation timeout**
```bash
# Решение: Увеличить timeout
worker = start_worker(..., timeout=60.0)  # 60 секунд
```

---

## 📞 Поддержка

Если возникли проблемы:
1. Запустить `python scripts/test_nllb_model.py`
2. Проверить логи worker process
3. Убедиться, что модель установлена корректно
4. Проверить, что ctranslate2 установлен: `python -c "import ctranslate2; print(ctranslate2.__version__)"`

---

**Статус:** Модель установлена ✅, но UI интеграция ещё не завершена ❌
**Next Step:** Выбрать Вариант А (быстро) или Вариант Б (правильно)
