"""Simple diagnostic: test model loading in spawn context."""

import logging
import multiprocessing
import time
from pathlib import Path
from multiprocessing.connection import Connection


def worker_func(conn: Connection, model_path: str):
    """Worker function."""
    # Clear inherited handlers
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)

    logging.basicConfig(level=logging.INFO, format="[Worker] %(message)s", force=True)

    try:
        logging.info("Worker started")
        import ctranslate2

        logging.info(f"Loading model: {model_path}")
        start = time.time()

        translator = ctranslate2.Translator(model_path, device="cpu", compute_type="int8")
        load_time = time.time() - start

        logging.info(f"Model loaded in {load_time:.1f}s")
        conn.send({"ok": True, "time": load_time})

    except Exception as e:
        logging.error(f"Worker failed: {e}", exc_info=True)
        conn.send({"ok": False, "error": str(e)})


if __name__ == "__main__":
    print("Testing model load in multiprocessing spawn context...")

    model_path = str(
        Path(
            r"C:\Users\Win10_Game_OS\AppData\Local\HDLE\models\facebook_nllb-200-distilled-1.3B_ctranslate2"
        )
    )

    ctx = multiprocessing.get_context("spawn")
    parent_conn, child_conn = multiprocessing.Pipe()

    process = ctx.Process(target=worker_func, args=(child_conn, model_path))
    process.start()

    print("Waiting for worker (300s timeout)...")

    if parent_conn.poll(timeout=300):
        response = parent_conn.recv()
        process.join(timeout=10)

        if response.get("ok"):
            print(f"[SUCCESS] Worker loaded model in {response['time']:.1f}s")
        else:
            print(f"[FAILED] Worker error: {response.get('error')}")
    else:
        print("[FAILED] Worker timeout")
        process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
