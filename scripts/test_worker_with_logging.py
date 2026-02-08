"""Test worker startup with detailed logging (mimics app behavior)."""
import sys
import logging
from pathlib import Path

if __name__ == '__main__':
    # Setup logging like the app does
    logging.basicConfig(
        level=logging.DEBUG,
        format="[Main] %(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger = logging.getLogger(__name__)

    logger.info("=== TEST WORKER STARTUP (APP-LIKE) ===")
    logger.info(f"Python: {sys.version}")
    logger.info(f"PID: {sys.platform}")

    # Import the worker module
    logger.info("Importing worker module...")
    from app.infra.local_mt.worker_process import LocalMTWorker

    model_path = Path(r"C:\Users\Win10_Game_OS\AppData\Local\HDLE\models\facebook_nllb-200-distilled-1.3B_ctranslate2")

    logger.info(f"Model path: {model_path}")
    logger.info(f"Resolved: {model_path.resolve()}")

    if not model_path.exists():
        logger.error(f"Model not found!")
        sys.exit(1)

    logger.info("Starting worker (this should take < 10s if working correctly)...")
    logger.info("Watch for worker logs prefixed with [Worker-local_nllb]")

    try:
        worker = LocalMTWorker(
            model_path=model_path,
            backend="ctranslate2",
            model_id="local_nllb",
            timeout=30.0,
        )

        logger.info("SUCCESS! Worker started")
        logger.info("Shutting down worker...")
        worker.shutdown()
        logger.info("Worker shut down cleanly")

    except Exception as e:
        logger.error(f"FAILED: {e}", exc_info=True)
        sys.exit(1)

    logger.info("=== TEST COMPLETE ===")
