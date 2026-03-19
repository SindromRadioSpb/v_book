"""Minimal worker test - NO logging, direct stdout only."""

import multiprocessing
import sys
import time
from pathlib import Path
from multiprocessing.connection import Connection


def worker_func(conn: Connection, model_path: str):
    """Minimal worker - no logging, just stdout."""
    try:
        sys.stdout.write(f"[Worker] PID: {multiprocessing.current_process().pid}\n")
        sys.stdout.flush()

        sys.stdout.write("[Worker] Importing ctranslate2...\n")
        sys.stdout.flush()
        import ctranslate2

        sys.stdout.write("[Worker] Importing NllbTokenizer...\n")
        sys.stdout.flush()
        from transformers import NllbTokenizer

        sys.stdout.write(f"[Worker] Loading translator from: {model_path}\n")
        sys.stdout.flush()

        start = time.perf_counter()
        translator = ctranslate2.Translator(model_path, device="cpu")
        elapsed = time.perf_counter() - start

        sys.stdout.write(f"[Worker] Translator loaded in {elapsed:.2f}s\n")
        sys.stdout.flush()

        sys.stdout.write("[Worker] Loading tokenizer...\n")
        sys.stdout.flush()

        start = time.perf_counter()
        tokenizer = NllbTokenizer.from_pretrained(
            "facebook/nllb-200-distilled-1.3B", src_lang="eng_Latn"
        )
        elapsed = time.perf_counter() - start

        sys.stdout.write(f"[Worker] Tokenizer loaded in {elapsed:.2f}s\n")
        sys.stdout.flush()

        conn.send({"ok": True, "message": "Worker ready"})

        sys.stdout.write("[Worker] Waiting for shutdown...\n")
        sys.stdout.flush()

        # Wait for shutdown
        if conn.poll(timeout=10):
            msg = conn.recv()
            if msg.get("type") == "shutdown":
                sys.stdout.write("[Worker] Shutdown received\n")
                sys.stdout.flush()

    except Exception as e:
        sys.stdout.write(f"[Worker] ERROR: {e}\n")
        sys.stdout.flush()
        import traceback

        traceback.print_exc()
        conn.send({"ok": False, "error": str(e)})


if __name__ == "__main__":
    print("=== MINIMAL WORKER TEST (NO LOGGING) ===")

    model_path = r"C:\Users\Win10_Game_OS\AppData\Local\HDLE\models\facebook_nllb-200-distilled-1.3B_ctranslate2"

    print(f"Model path: {model_path}")
    print(f"Exists: {Path(model_path).exists()}")

    ctx = multiprocessing.get_context("spawn")
    parent_conn, child_conn = multiprocessing.Pipe()

    print("\nStarting worker process...")
    process = ctx.Process(target=worker_func, args=(child_conn, model_path))
    process.start()

    print("Waiting for worker (60s timeout)...")
    if parent_conn.poll(timeout=60):
        response = parent_conn.recv()

        if response.get("ok"):
            print(f"✅ SUCCESS: {response.get('message')}")

            # Shutdown
            print("Sending shutdown...")
            parent_conn.send({"type": "shutdown"})
            process.join(timeout=5)
            print("✅ Worker shut down cleanly")
        else:
            print(f"❌ FAILED: {response.get('error')}")
    else:
        print("❌ TIMEOUT: Worker didn't respond in 60s")
        process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()

    print("\n=== TEST COMPLETE ===")
