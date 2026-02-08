# Как остановить старый процесс и запустить новый

## Шаг 1: Остановить старый процесс

### В PowerShell (где запущен процесс):

Нажмите **Ctrl+C** несколько раз

### Или найдите и убейте процесс:

```powershell
# Найти все процессы Python
Get-Process python | Format-Table Id, ProcessName, StartTime, Path -AutoSize

# Остановить процесс (замените <PID> на реальный ID)
Stop-Process -Id <PID>
```

## Шаг 2: Очистить WAL файлы (опционально)

После остановки процесса:

```powershell
cd M:\V_book\HDLE_Processing
del hewiki_gpu_processing.db-wal
del hewiki_gpu_processing.db-shm
```

**Важно:** Делайте это ТОЛЬКО после полной остановки процесса!

## Шаг 3: Запустить новый batch-скрипт

```powershell
cd J:\Project_Vibe\V_book
.\scripts\run_gpu_processing_batch.ps1
```

Или прямо через Python:

```powershell
cd J:\Project_Vibe\V_book
.\.venv_gpu\Scripts\Activate.ps1

python scripts\process_reference_corpus_batch.py `
    --db-path "M:\V_book\HDLE_Processing\hewiki_gpu_processing.db" `
    --project-name "Hebrew Wikipedia Baseline" `
    --use-gpu `
    --batch-size 100
```

## Прогресс продолжится автоматически!

Новый скрипт автоматически пропустит уже обработанные документы (~199 уже готово) и продолжит с документа 200+.

## Преимущества нового скрипта:

- ✅ **Одна запись ProcessorRun** вместо 387,000
- ✅ **Меньше database locks**
- ✅ **Быстрее** (меньше commits)
- ✅ **Та же статистика** и прогресс
