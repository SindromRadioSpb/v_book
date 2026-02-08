# Worker Process Startup Fix (2026-02-08)

## Problem

Worker process for Local MT (NLLB model) was dying during startup when launched from the PyQt application, but worked perfectly in standalone diagnostic scripts.

**Symptoms**:
- Worker ping timeout after 120 seconds
- "Worker process died during startup" error
- Batch translate dialog showed "Translating rows..." with infinite waiting
- Standalone test script worked perfectly (loaded model in ~25 seconds)

## Root Cause

**Logging handler inheritance across multiprocessing**

When using `multiprocessing.spawn` (Windows default), the worker process:
1. Creates a new Python interpreter
2. Inherits the root logger configuration from the main process
3. The inherited handlers (RotatingFileHandler, StreamHandler) have file handles that don't exist in the new process
4. When the worker tries to log, it attempts to write to non-existent file handles
5. This causes the worker to hang or crash during startup

## Solution

Clear inherited logging handlers in the worker process before configuring fresh logging.

**File**: `app/infra/local_mt/worker_process.py`

**Change**:
```python
def _worker_main(conn, model_path, backend, model_id):
    # CRITICAL: Clear inherited logging handlers from main process
    # When using multiprocessing spawn, inherited file handlers don't work
    # in the new process and cause hangs/failures
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Configure fresh logging for worker process
    logging.basicConfig(
        level=logging.INFO,
        format=f"[Worker-{model_id}] %(asctime)s - %(levelname)s - %(message)s",
        force=True,  # Force reconfiguration
    )
```

## Verification

Standalone test (`scripts/test_worker_startup.py`) now shows:
```
[STEP 2] Starting worker process...
  [OK] Worker started successfully!

[STEP 3] Testing worker ping...
  [OK] Worker is alive and responding!

[STEP 4] Testing translation...
  Input: hello
  Output: Привет!
  Latency: 761.0ms

SUCCESS: Worker is functioning correctly
```

Worker loads model in ~25 seconds (normal for NLLB-200-distilled-1.3B).

## Testing Checklist

Test batch translation in the application:

1. **Start application**: `python -m app.main --db-path "J:\Project_Vibe\V_book\hdle_premium.db"`
2. **Go to Dictionary tab**
3. **Check MT settings**: Tools → MT Provider Settings → Enable "local_nllb"
4. **Select lemmas** without Russian translation
5. **Click "Translate Selected..."**
6. **Expected**:
   - Dialog shows "Starting worker..." (20-30 seconds)
   - Then "Translating rows..." with progress
   - Translations appear in Russian column
7. **Repeat for Terms tab**

## Lessons Learned

1. **Multiprocessing + Logging**: Always clear inherited handlers when spawning worker processes
2. **Testing isolation**: Standalone scripts may work while application fails due to environmental differences
3. **Diagnostic approach**: Compare working vs failing environments to identify inherited state issues
4. **Windows spawn context**: Be aware that spawn creates a NEW interpreter, not a fork, so inherited state can cause issues

## Related Files

- `app/infra/local_mt/worker_process.py` - Worker process implementation
- `app/infra/util/logging.py` - Main application logging setup
- `scripts/test_worker_startup.py` - Diagnostic test for worker
- `app/infra/translators/providers/local_nllb_provider.py` - Provider that creates workers
