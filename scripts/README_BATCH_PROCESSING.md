# GPU Batch Processing - Quick Guide

## Проблема с оригинальным скриптом

Оригинальный `process_reference_corpus.py` имел архитектурную проблему:
- ❌ Создавал ProcessorRun для КАЖДОГО документа (387k записей в таблице!)
- ❌ Делал множественные commits внутри обработки одного документа
- ❌ Вызывал database lock errors в SQLite

## Решение: Batch-оптимизированный скрипт

Новый `process_reference_corpus_batch.py`:
- ✅ Создает ОДИН ProcessorRun для всего батча
- ✅ Commit только после каждого успешно обработанного документа
- ✅ Нет промежуточных commits внутри обработки
- ✅ Безопасная работа с SQLite
- ✅ Быстрее и эффективнее

## Запуск

### Вариант 1: PowerShell скрипт (рекомендуется)

```powershell
cd J:\Project_Vibe\V_book
.\scripts\run_gpu_processing_batch.ps1
```

**Параметры:**
```powershell
# Кастомные параметры
.\scripts\run_gpu_processing_batch.ps1 `
    -DbPath "M:\V_book\HDLE_Processing\hewiki_gpu_processing.db" `
    -ProjectName "Hebrew Wikipedia Baseline" `
    -UseGPU `
    -BatchSize 100
```

### Вариант 2: Прямой запуск Python

```powershell
cd J:\Project_Vibe\V_book
.\.venv_gpu\Scripts\Activate.ps1

python scripts\process_reference_corpus_batch.py `
    --db-path "M:\V_book\HDLE_Processing\hewiki_gpu_processing.db" `
    --project-name "Hebrew Wikipedia Baseline" `
    --use-gpu `
    --batch-size 100
```

## Мониторинг

### Следить за логом в реальном времени

```powershell
Get-Content M:\V_book\HDLE_Processing\logs\hdle.log -Wait -Tail 50
```

### Проверить прогресс

```powershell
python scripts\verify_reference_corpus.py `
    --db-path "M:\V_book\HDLE_Processing\hewiki_gpu_processing.db" `
    --project-name "Hebrew Wikipedia Baseline"
```

## Остановка и возобновление

### Остановить обработку

```powershell
# Найти процесс Python
Get-Process | Where-Object {$_.ProcessName -eq "python"}

# Остановить (замените PID на реальный)
Stop-Process -Id <PID>
```

### Возобновить обработку

Просто запустите скрипт заново - он автоматически пропустит уже обработанные документы:

```powershell
.\scripts\run_gpu_processing_batch.ps1
```

## Оценка времени

- **С GPU (GTX 1660 Ti):** ~12-18 часов для 387k документов
- **Прогресс:** Логируется каждые 100 документов (batch-size)
- **Скорость:** ~3-6 секунд на документ (зависит от длины)

## После завершения обработки

### Шаг 1: Извлечь термины (~3-5 часов)

```powershell
.\scripts\run_extract_terms.ps1
```

### Шаг 2: Верификация и релиз (~30 минут)

```powershell
.\scripts\run_verify_and_release.ps1
```

## Технические детали

### Что делает batch-скрипт

1. **Создает ОДИН ProcessorRun** для всей сессии обработки
2. **Обрабатывает каждый документ** без создания ProcessorRun
3. **Commit после каждого успешного документа** (не внутри обработки)
4. **Обновляет ProcessorRun** в конце с финальной статистикой

### Разница с оригинальным скриптом

| Аспект | Оригинал | Batch-оптимизированный |
|--------|----------|------------------------|
| ProcessorRun записей | 387k | 1 |
| Commits на документ | 4-5 | 1 |
| Database locks | ❌ Частые | ✅ Редкие |
| Скорость | Медленнее | Быстрее |
| Надежность | ⚠️ Lock errors | ✅ Стабильно |

### ProcessorRun таблица

Оригинальный скрипт создавал запись для каждого документа:
```
run_id | project_id | docs_processed | status
-------|------------|----------------|--------
1      | 1          | 1              | ok
2      | 1          | 1              | ok
3      | 1          | 1              | ok
...    | ...        | ...            | ...
387000 | 1          | 1              | ok
```

Batch-скрипт создает одну запись:
```
run_id | project_id | docs_processed | status
-------|------------|----------------|--------
1      | 1          | 387480         | ok
```

## Troubleshooting

### Database is locked

Если все же возникает эта ошибка:
1. Проверьте, что нет других процессов, использующих БД
2. Удалите WAL/SHM файлы (если процессы завершены):
   ```powershell
   cd M:\V_book\HDLE_Processing
   del hewiki_gpu_processing.db-wal
   del hewiki_gpu_processing.db-shm
   ```

### GPU out of memory

Если GPU память заканчивается:
```powershell
.\scripts\run_gpu_processing_batch.ps1 -BatchSize 50
```

### Проверить GPU

```powershell
python -c "import torch; print('GPU:', torch.cuda.is_available()); print('Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
```

## Лог формат

```
INFO: Progress: 100/387,480 this run (0.0%) | Overall: 100/387,480 (0.0%) | Tokens: 12,345 | Unique lemmas: 3,456
INFO: Progress: 200/387,480 this run (0.1%) | Overall: 200/387,480 (0.1%) | Tokens: 24,567 | Unique lemmas: 6,789
...
```

Где:
- **this run**: Прогресс текущей сессии
- **Overall**: Общий прогресс (включая предыдущие запуски)
- **Tokens**: Общее количество токенов обработано
- **Unique lemmas**: Уникальных лемм найдено
