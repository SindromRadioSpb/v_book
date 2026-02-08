# Worker Startup Fix - Root Cause Analysis

## Problem

Dictionary batch translate hung at 240s timeout with "Worker process died during startup" error.

## Root Cause

**Multiprocessing spawn context on Windows requires proper module-level code guards.**

When using `multiprocessing` with `spawn` context (Windows default), Python:
1. Starts a fresh Python interpreter for the worker process
2. **Re-imports the main module** to access the target function
3. **Executes all module-level code** during import

If the main module has code that spawns workers at module level (not guarded by `if __name__ == '__main__'`), it creates an **infinite recursive spawn loop**:

```python
# BAD - causes infinite loop
from app.infra.local_mt.worker_process import LocalMTWorker

model_path = Path("...")
worker = LocalMTWorker(...)  # ❌ Spawns worker, which re-imports this module,
                              #    which spawns another worker, etc.
```

```python
# GOOD - safe from spawn loop
if __name__ == '__main__':
    from app.infra.local_mt.worker_process import LocalMTWorker

    model_path = Path("...")
    worker = LocalMTWorker(...)  # ✅ Only runs in main process
```

## Symptoms

- Worker timeout after 240s
- "Worker process died during startup" error
- No worker logs (worker never reaches main loop)
- In diagnostic: RuntimeError about "bootstrapping phase"

## Solution

### 1. Test Scripts: Add `if __name__ == '__main__'` Guards

All scripts that spawn workers must guard initialization code:

```python
if __name__ == '__main__':
    # All worker initialization code here
    worker = LocalMTWorker(...)
```

**Fixed Files:**
- `scripts/test_worker_with_logging.py` - Added guard around entire main logic
- `scripts/diagnose_worker_simple.py` - Already had guard

### 2. App Code: Already Correct

The app (`app/main.py`) already has proper guards:

```python
def main():
    # All initialization in function
    ...

if __name__ == "__main__":
    sys.exit(main())
```

Providers are initialized lazily on first use (not at module level), so no spawn loop occurs.

### 3. Worker Process: Logging Handler Cleanup

The worker process already clears inherited logging handlers (lines 84-96 in `worker_process.py`):

```python
# CRITICAL: Clear inherited logging handlers from main process
root_logger = logging.getLogger()
for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)

# Configure fresh logging for worker process
logging.basicConfig(
    level=logging.DEBUG,
    format=f"[Worker-{model_id}] %(asctime)s - %(levelname)s - %(message)s",
    force=True,
)
```

This prevents file handle issues in spawned processes.

## Verification

After fixing the test script guard:

```bash
$ python scripts/test_worker_with_logging.py
[Worker-local_nllb] CTranslate2 translator loaded in 1.73s
[Worker-local_nllb] Tokenizer loaded in 3.85s
[Main] Worker started successfully: local_nllb (10.6s)
[Main] SUCCESS! Worker started
```

**Performance:**
- **Translator load:** 1.73s
- **Tokenizer load:** 3.85s (includes HuggingFace network checks)
- **Total:** 10.6s

## Key Lessons

1. **Always use `if __name__ == '__main__'` guards** for any code that spawns processes
2. **Multiprocessing spawn re-imports modules** - module-level side effects run twice
3. **Clear inherited logging handlers** in worker processes to avoid file handle issues
4. **Test in isolation** - create minimal reproduction scripts to isolate issues

## References

- Python multiprocessing docs: https://docs.python.org/3/library/multiprocessing.html#the-spawn-and-forkserver-start-methods
- Section: "Safe importing of main module"

## Related Files

- `app/infra/local_mt/worker_process.py` - Worker implementation
- `app/infra/translators/providers/local_nllb_provider.py` - Provider that starts workers
- `app/infra/translators/local_providers_setup.py` - Provider initialization (lazy)
- `app/main.py` - App entry point (already has proper guards)
- `scripts/test_worker_with_logging.py` - Test script (fixed)
- `scripts/diagnose_worker_simple.py` - Diagnostic script (correct)
