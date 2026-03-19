"""Diagnostic script for worker crash investigation.

Tests CTranslate2 model loading in different contexts:
1. Simple standalone load
2. Multiprocessing spawn context
3. With logging (like app does)

Usage:
    python scripts/diagnose_worker_crash.py
"""

import logging
import sys
import time
from pathlib import Path

print("\n" + "=" * 80)
print("WORKER CRASH DIAGNOSTIC")
print("=" * 80)

# Test 1: Simple standalone load
print("\n[TEST 1] Simple standalone load (no multiprocessing)...")
try:
    import ctranslate2
    from transformers import NllbTokenizer

    model_path = Path(
        r"C:\Users\Win10_Game_OS\AppData\Local\HDLE\models\facebook_nllb-200-distilled-1.3B_ctranslate2"
    )

    if not model_path.exists():
        print(f"  [ERROR] Model not found: {model_path}")
        print(f"  Resolved to: {model_path.resolve()}")
        sys.exit(1)

    print(f"  Model path: {model_path}")
    print(f"  Resolved: {model_path.resolve()}")

    # Load translator
    print("  Loading CTranslate2 translator...")
    start = time.time()
    translator = ctranslate2.Translator(str(model_path), device="cpu", compute_type="int8")
    load_time = time.time() - start
    print(f"  [OK] Translator loaded in {load_time:.1f}s")

    # Load tokenizer
    print("  Loading tokenizer...")
    start = time.time()
    tokenizer = NllbTokenizer.from_pretrained(
        "facebook/nllb-200-distilled-1.3B", src_lang="eng_Latn"
    )
    tok_time = time.time() - start
    print(f"  [OK] Tokenizer loaded in {tok_time:.1f}s")

    # Test translation
    print("  Testing translation...")
    text = "Hello world"
    inputs = tokenizer(text, return_tensors="pt", padding=False, truncation=True)
    input_ids = inputs["input_ids"][0].tolist()

    results = translator.translate_batch(
        [input_ids],
        target_prefix=[tokenizer.lang_code_to_id["rus_Cyrl"]],
        beam_size=1,
        max_decoding_length=512,
    )

    output_ids = results[0].hypotheses[0]
    translated = tokenizer.decode(output_ids, skip_special_tokens=True)
    print(f"  [OK] Translation: '{text}' → '{translated}'")

    print(f"\n  [TEST 1 PASSED] Total time: {load_time + tok_time:.1f}s")

except Exception as e:
    print(f"\n  [TEST 1 FAILED] {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)

# Test 2: Multiprocessing spawn context
print("\n[TEST 2] Multiprocessing spawn context...")
try:
    import multiprocessing
    from multiprocessing.connection import Connection

    def worker_func(conn: Connection, model_path: str):
        """Worker function (runs in separate process)."""
        # Clear inherited logging handlers (CRITICAL for spawn)
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        # Configure fresh logging
        logging.basicConfig(level=logging.INFO, format="[Worker] %(message)s", force=True)

        try:
            import ctranslate2
            from transformers import NllbTokenizer

            logging.info(f"Loading model from: {model_path}")
            start = time.time()

            translator = ctranslate2.Translator(model_path, device="cpu", compute_type="int8")
            load_time = time.time() - start

            logging.info(f"Model loaded in {load_time:.1f}s")

            tokenizer = NllbTokenizer.from_pretrained(
                "facebook/nllb-200-distilled-1.3B", src_lang="eng_Latn"
            )

            # Send success
            conn.send({"ok": True, "load_time": load_time})

        except Exception as e:
            logging.error(f"Worker error: {e}")
            import traceback

            traceback.print_exc()
            conn.send({"ok": False, "error": str(e)})

    # Spawn worker
    ctx = multiprocessing.get_context("spawn")
    parent_conn, child_conn = multiprocessing.Pipe()

    model_path = str(
        Path(
            r"C:\Users\Win10_Game_OS\AppData\Local\HDLE\models\facebook_nllb-200-distilled-1.3B_ctranslate2"
        )
    )

    process = ctx.Process(target=worker_func, args=(child_conn, model_path))
    process.start()

    print("  Waiting for worker (timeout: 300s)...")

    if parent_conn.poll(timeout=300):
        response = parent_conn.recv()
        process.join(timeout=10)

        if response.get("ok"):
            print(f"  [OK] Worker loaded model in {response['load_time']:.1f}s")
            print(f"\n  [TEST 2 PASSED]")
        else:
            print(f"  [TEST 2 FAILED] Worker error: {response.get('error')}")
            sys.exit(1)
    else:
        print(f"  [TEST 2 FAILED] Worker timeout")
        process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
        sys.exit(1)

except Exception as e:
    print(f"\n  [TEST 2 FAILED] {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)

# Test 3: Memory check
print("\n[TEST 3] Memory check...")
try:
    import psutil

    mem = psutil.virtual_memory()
    print(f"  Total RAM: {mem.total / (1024**3):.1f} GB")
    print(f"  Available: {mem.available / (1024**3):.1f} GB")
    print(f"  Used: {mem.percent}%")

    if mem.available / (1024**3) < 3:
        print(f"  [WARNING] Low memory! Need at least 3GB for model loading")
    else:
        print(f"  [OK] Sufficient memory")

    print(f"\n  [TEST 3 PASSED]")

except Exception as e:
    print(f"\n  [TEST 3 FAILED] {e}")

# Summary
print("\n" + "=" * 80)
print("DIAGNOSTIC COMPLETE")
print("=" * 80)
print("\nIf all tests passed:")
print("  → Model loads correctly")
print("  → Multiprocessing works")
print("  → Issue may be in app-specific code (logging, imports, etc.)")
print("\nIf test failed:")
print("  → Check error message above")
print("  → Possible causes: corrupted model, missing deps, low memory")
print("\n")
