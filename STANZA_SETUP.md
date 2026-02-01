# Stanza Setup - Complete ✅

## Что было сделано

### 1. Установка Stanza (выполнено вами)
```powershell
# PyTorch с CUDA 11.8
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# Stanza
pip install -U stanza

# Скачивание Hebrew моделей
python -c "import stanza; stanza.download('he')"
```

✅ Результат:
- PyTorch 2.7.1+cu118 установлен
- Stanza 1.11.0 установлен
- Hebrew модели скачаны в `C:\Users\Win10_Game_OS\stanza_resources`

### 2. Обновление кода приложения

**Обновлено `app/ui/documents_view.py`:**
- ✅ Автоматическая проверка доступности Stanza
- ✅ Автоматическая проверка доступности CUDA
- ✅ Отображение статуса engine в UI
- ✅ Чекбокс "Use GPU for NLP" (если CUDA доступна)
- ✅ Динамическое сообщение подтверждения (Mock vs Stanza)

**Обновлено `app/ui/workers.py`:**
- ✅ Параметр `use_gpu` в ProcessWorker
- ✅ Передача параметра в ProcessService

**Создан `test_stanza_production.py`:**
- ✅ Тест импорта Stanza
- ✅ Тест StanzaEngine
- ✅ Тест ProcessService с Stanza
- ✅ Полная проверка pipeline

---

## Как тестировать

### Тест 1: Проверка Stanza engine
```bash
cd J:\Project_Vibe\V_book
python test_stanza_production.py
```

**Ожидаемый результат:**
```
============================================================
STANZA PRODUCTION TEST
============================================================

✅ Stanza imported successfully
   Stanza version: 1.11.0
   PyTorch version: 2.7.1+cu118
   CUDA available: True
   CUDA device: <your GPU>

============================================================
Testing StanzaEngine
============================================================

✅ StanzaEngine initialized
✅ Processed successfully
   Sentences: 2
   Total tokens: 7

📊 Results:
  Sentence 1: זה טקסט בעברית.
    זה         → lemma=זה         pos=PRON
    טקסט       → lemma=טקסט       pos=NOUN
    ...

============================================================
Testing ProcessService with Stanza
============================================================

✅ Created project: Stanza Test
✅ Got corpus: Main Corpus
✅ Imported document: test_hebrew.txt
🔄 Processing with Stanza engine...
✅ Document processed successfully

📊 Document status: processed
   Sentences: 3
   Tokens: 28
   Unique lemmas: 22

📚 Top 10 lemmas:
   בית ספר         | NOUN   | Freq:   4 | DocFreq: 1
   זה              | PRON   | Freq:   2 | DocFreq: 1
   ...

============================================================
✅ ALL TESTS PASSED - Stanza is working!
============================================================
```

### Тест 2: GUI с Stanza

```bash
cd J:\Project_Vibe\V_book
python -m app.main
```

**Проверка:**

1. **Главное окно → Создать проект**
   - Создайте новый проект "Stanza Test"

2. **Вкладка Documents**
   - Вверху должно быть: `✅ Stanza engine available (GPU: Yes)` (зелёным цветом)
   - Чекбокс `☑ Use GPU for NLP` (отмечен по умолчанию)

3. **Импорт документов**
   - Drag-drop или "Add Files..." для импорта .txt/.docx/.pdf файлов
   - Или используйте тестовый файл из test_data/

4. **Обработка NLP**
   - Выберите документ(ы)
   - Нажмите "Process with NLP"
   - Должно появиться окно подтверждения:
     ```
     Process 1 document(s) with NLP?

     Using Stanza engine (GPU: Yes).
     This will provide accurate lemmatization and POS tagging.
     ```
   - Нажмите "Yes"
   - Наблюдайте за прогресс-баром

5. **Вкладка Dictionary**
   - После обработки перейдите во вкладку Dictionary
   - Увидите таблицу с леммами:
     ```
     Lemma       | POS  | Frequency | Doc Freq | Translation | Status
     -----------------------------------------------------------------
     בית ספר     | NOUN |    15     |    3     |             | auto
     לומד        | VERB |    12     |    2     |             | auto
     ...
     ```
   - Попробуйте фильтры:
     - "Show top": измените количество отображаемых лемм
     - "POS": выберите NOUN, VERB, ADJ и т.д.
     - "Search": введите текст для поиска

---

## Сравнение Mock vs Stanza

### Mock Engine (rule-based)
**Использование:**
- Когда Stanza недоступна (MSYS2, старые системы)
- Для быстрого тестирования pipeline
- Для разработки без GPU

**Точность:**
- ❌ Простые правила (удаление префиксов/суффиксов)
- ❌ Базовое угадывание POS
- ❌ Не подходит для production

**Пример:**
```
Input:  בתי ספר
Mock:   בתי ספר → בתי ספר (POS: NOUN)  [неправильно]
Stanza: בתי ספר → בית ספר (POS: NOUN)  [правильно]
```

### Stanza Engine (ML-based)
**Использование:**
- Production использование
- Когда нужна высокая точность
- Для Hebrew научных текстов

**Точность:**
- ✅ ML модели, тренированные на Hebrew корпусе
- ✅ Правильная лемматизация
- ✅ Точный POS tagging (Universal Dependencies)
- ✅ Морфологический анализ

**Производительность:**
- Первый запуск: 5-10 сек (загрузка моделей)
- CPU: 2-5 сек / 1000 слов
- GPU: 0.5-1 сек / 1000 слов

---

## GPU vs CPU

### Когда использовать GPU?
- ✅ Большие документы (> 10000 слов)
- ✅ Много документов одновременно
- ✅ У вас есть CUDA-совместимая видеокарта

### Когда использовать CPU?
- ✅ Маленькие документы (< 1000 слов)
- ✅ Нет GPU или старая видеокарта
- ✅ Экономия памяти GPU для других задач

**Примечание:** Для Hebrew текстов разница не очень большая (не как для English). CPU обычно достаточно.

---

## Решение проблем

### Stanza не обнаружена в GUI
**Проблема:** UI показывает "⚠️ Stanza not available"

**Решение:**
1. Убедитесь, что используете правильный venv:
   ```bash
   # Должен быть активен J:\Project_Vibe\V_book\.venv
   which python  # должно показать путь к .venv
   ```

2. Проверьте установку:
   ```bash
   python -c "import stanza; print(stanza.__version__)"
   ```

3. Если нет - установите:
   ```bash
   pip install stanza
   python -c "import stanza; stanza.download('he')"
   ```

### GPU не используется
**Проблема:** CUDA available: False

**Решение:**
1. Проверьте PyTorch:
   ```bash
   python -c "import torch; print(torch.cuda.is_available())"
   ```

2. Если False - переустановите PyTorch с CUDA:
   ```bash
   pip uninstall torch torchvision torchaudio
   pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
   ```

3. Проверьте драйверы NVIDIA:
   ```bash
   nvidia-smi  # должно показать GPU
   ```

### Медленная обработка
**Проблема:** Обработка занимает много времени

**Решение:**
1. Включите GPU (если есть)
2. Обрабатывайте документы по одному (не все сразу)
3. Для больших документов (> 100 страниц) ожидайте 1-2 минуты

---

## Что дальше?

После успешного тестирования Stanza переходим к **M4: Live Update**

### M4 задачи:
1. Delta statistics (добавление/удаление документов)
2. Re-processing documents (обновление статистики)
3. Incremental updates (не пересчитывать всё заново)
4. Background tasks (обработка в фоне)

**Estimated time:** 4-5 days
**Priority:** High (needed for production workflow)
