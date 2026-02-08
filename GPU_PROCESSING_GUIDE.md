# GPU Processing Guide - Hebrew Wikipedia

## Setup Complete ✅

Ваше GPU-окружение готово:
- ✅ Python 3.13 venv: `.venv_gpu`
- ✅ PyTorch 2.7.1 + CUDA 11.8
- ✅ GPU detected: NVIDIA GeForce RTX 3070
- ✅ Stanza Hebrew model downloaded
- ✅ Working database copy: `M:\V_book\HDLE_Processing\hewiki_gpu_processing.db`

## Database Status

**Source:** `M:\V_book\HDLE\hdle_production_new.db`
- Project: Hebrew Wikipedia Baseline (ID: 1)
- Total documents: 387,639
- Processed: 101 (0.03%) ← **почти не обработано**
- is_general_corpus: 1 ✅

**Working copy:** `M:\V_book\HDLE_Processing\hewiki_gpu_processing.db` (2.4 GB)

---

## Запуск обработки

### Шаг 1: NLP-обработка на GPU (~12-21 часов)

Откройте PowerShell и активируйте GPU venv:

```powershell
cd J:\Project_Vibe\V_book
.\.venv_gpu\Scripts\Activate.ps1
```

**Вариант A: Автоматический запуск (рекомендуется)**

```powershell
.\scripts\run_gpu_processing.ps1
```

**Вариант B: Ручной запуск**

```powershell
python scripts\process_reference_corpus.py `
    --db-path "M:\V_book\HDLE_Processing\hewiki_gpu_processing.db" `
    --project-name "Hebrew Wikipedia Baseline" `
    --use-gpu `
    --batch-size 100
```

**Мониторинг прогресса** (в отдельном терминале):

```powershell
# Создайте лог-директорию, если нужно
mkdir M:\V_book\HDLE_Processing\logs -ErrorAction SilentlyContinue

# Следите за логами
Get-Content M:\V_book\HDLE_Processing\logs\hdle.log -Wait -Tail 50
```

### Шаг 2: Извлечение терминов (~3-5 часов)

После завершения NLP-обработки:

**Вариант A: Автоматический**

```powershell
.\scripts\run_extract_terms.ps1
```

**Вариант B: Ручной**

```powershell
python scripts\extract_reference_terms.py `
    --db-path "M:\V_book\HDLE_Processing\hewiki_gpu_processing.db" `
    --project-name "Hebrew Wikipedia Baseline"
```

### Шаг 3: Проверка и подготовка релиза

После извлечения терминов:

**Вариант A: Автоматический**

```powershell
.\scripts\run_verify_and_release.ps1
```

**Вариант B: Ручной**

```powershell
# Проверка
python scripts\verify_reference_corpus.py `
    --db-path "M:\V_book\HDLE_Processing\hewiki_gpu_processing.db"

# Подготовка релиза (SHA256 + metadata)
python scripts\prepare_release_db.py `
    --db-path "M:\V_book\HDLE_Processing\hewiki_gpu_processing.db" `
    --version (Get-Date -Format "yyyyMMdd")
```

---

## Ожидаемый результат

После завершения всех шагов в `M:\V_book\HDLE_Processing\` будут:

- `hewiki_ref_processed_vYYYYMMDD.db` (2.3-2.5 GB) - финальная база
- `hewiki_ref_processed_vYYYYMMDD.db.sha256` - SHA256 checksum
- `hewiki_ref_processed_vYYYYMMDD.db.json` - Metadata

**Ожидаемые метрики:**
- ✅ 387,639 документов обработано (100%)
- ✅ ~45,000-50,000 лемм
- ✅ ~10,000-15,000 n-грамм
- ✅ Размер: 2.3-2.5 GB

---

## Timeline (RTX 3070)

| Шаг | Время | Примечание |
|-----|-------|-----------|
| 1. NLP Processing | **12-21 часов** | GPU ускорение, можно оставить на ночь |
| 2. Term Extraction | 3-5 часов | CPU-bound, но параллелится |
| 3. Verify + Release | 30 минут | SHA256 расчет ~10 мин |
| **ИТОГО** | **16-27 часов** | Большая часть - автоматически |

---

## Troubleshooting

### GPU Out of Memory

**Симптом:** `CUDA out of memory` error

**Решение:** Уменьшите batch size

```powershell
python scripts\process_reference_corpus.py `
    --db-path "M:\V_book\HDLE_Processing\hewiki_gpu_processing.db" `
    --project-name "Hebrew Wikipedia Baseline" `
    --use-gpu `
    --batch-size 50  # или 25
```

### Медленная обработка (1-2 docs/sec)

**Проверка:** Убедитесь, что Stanza использует GPU

```powershell
python -c "import torch, stanza; nlp = stanza.Pipeline('he', use_gpu=True); print('Using GPU:', next(nlp.processors['tokenize'].model.parameters()).is_cuda)"
```

**Ожидается:** `Using GPU: True`

### Прерванная обработка

**Можно безопасно перезапустить** - скрипт автоматически пропускает уже обработанные документы.

---

## После завершения

1. **Upload to GitHub Release:**

```powershell
# Создайте release
gh release create v1.1.0 `
    --title "HDLE Premium v1.1.0 - Hebrew Wikipedia Reference Corpus" `
    --notes "Includes pre-processed Hebrew Wikipedia Baseline (387,639 documents)" `
    M:\V_book\HDLE_Processing\hewiki_ref_processed_vYYYYMMDD.db
```

2. **Обновите manifest.py:**

Скопируйте MANIFEST ENTRY из вывода `prepare_release_db.py` в файл:
`app/services/reference_setup/manifest.py`

3. **Тестирование:**

Загрузите базу на чистой машине через UI wizard для проверки.

---

## Команды для быстрого запуска

**Полный цикл (оставьте на выходные):**

```powershell
# Шаг 1: NLP (12-21 час)
.\scripts\run_gpu_processing.ps1

# Шаг 2: Terms (3-5 часов)
.\scripts\run_extract_terms.ps1

# Шаг 3: Release (30 мин)
.\scripts\run_verify_and_release.ps1
```

**Проверка статуса в любой момент:**

```powershell
python scripts\verify_reference_corpus.py `
    --db-path "M:\V_book\HDLE_Processing\hewiki_gpu_processing.db"
```

---

## Notes

- Обработка идет на **копии базы** - ваша production база не тронута
- Можно безопасно прерывать и перезапускать
- Логи пишутся в `M:\V_book\HDLE_Processing\logs\hdle.log`
- GPU использование можно мониторить через `nvidia-smi`

---

**Created:** 2026-02-07
**GPU:** NVIDIA GeForce RTX 3070
**Status:** ✅ Ready to run
