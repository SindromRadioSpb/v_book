"""Worker process for local MT inference.

Architecture:
- Main process spawns worker process with IPC
- Worker loads model once, keeps in memory
- Protocol: {"type": "ping|translate|shutdown", "data": ...}
- Thread-safe: Each worker handles one model

Safety:
- Windows-safe: Uses spawn context (not fork)
- Timeouts: Client-side timeout prevents hangs
- Error handling: Worker never raises uncaught exceptions
"""

import contextlib
import gc
import hashlib
import logging
import multiprocessing
import sys
import time
from dataclasses import dataclass
from multiprocessing.connection import Connection
from pathlib import Path

logger = logging.getLogger(__name__)


# ============================================================================
# Worker Error
# ============================================================================


class WorkerError(Exception):
    """Worker process error."""

    pass


# ============================================================================
# Translation Request/Result
# ============================================================================


@dataclass
class WorkerRequest:
    """Translation request for worker."""

    text: str
    source_lang: str
    target_lang: str
    request_id: str = ""
    sampling_profile_id: str = ""  # PPS PATCH-04: empty = use model-default gen_kwargs


@dataclass
class WorkerResult:
    """Translation result from worker."""

    text: str
    source_lang: str
    target_lang: str
    inference_time_ms: float
    request_id: str = ""
    error: str | None = None


def _cleanup_loaded_model(model_obj: object, backend: str) -> None:
    """Best-effort resource cleanup before worker exit.

    Important for GPU-backed HY-MT models on 8 GB VRAM:
    - drop strong references in the worker process
    - synchronize outstanding CUDA kernels
    - release allocator caches before the process fully exits
    """
    if model_obj is None:
        return

    try:
        import torch
    except Exception:
        torch = None

    try:
        if isinstance(model_obj, dict):
            raw_model = model_obj.get("model")
            tokenizer = model_obj.get("tokenizer")
            model_obj.clear()
            del raw_model
            del tokenizer
        else:
            del model_obj
    except Exception:
        pass

    gc.collect()

    if torch is not None and torch.cuda.is_available():
        with contextlib.suppress(Exception):
            torch.cuda.synchronize()
        with contextlib.suppress(Exception):
            torch.cuda.empty_cache()
        with contextlib.suppress(Exception):
            torch.cuda.ipc_collect()


# ============================================================================
# Worker Process Function
# ============================================================================


def _worker_main(
    conn: Connection,
    model_path: str,
    backend: str,
    model_id: str,
):
    """
    Worker process main loop.

    Args:
        conn: IPC connection to main process
        model_path: Path to model directory
        backend: Backend ("ctranslate2" or "transformers")
        model_id: Model ID (for logging)
    """
    # CRITICAL: Clear inherited logging handlers from main process
    # When using multiprocessing spawn, inherited file handlers don't work
    # in the new process and cause hangs/failures
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Configure fresh logging for worker process
    logging.basicConfig(
        level=logging.DEBUG,  # Changed to DEBUG for detailed logging
        format=f"[Worker-{model_id}] %(asctime)s - %(levelname)s - %(message)s",
        force=True,  # Force reconfiguration even if basicConfig was called before
    )
    worker_logger = logging.getLogger(__name__)

    # DIAGNOSTIC: Log entry point
    worker_logger.info("=== WORKER PROCESS STARTED ===")
    worker_logger.info(f"PID: {multiprocessing.current_process().pid}")

    model = None
    try:
        # Load model
        worker_logger.info(f"Loading model: {model_id} ({backend})")
        worker_logger.info(f"Model path: {model_path}")
        worker_logger.debug("About to call model loading function...")

        try:
            if backend == "ctranslate2":
                worker_logger.debug("Calling _load_ctranslate2_model...")
                model = _load_ctranslate2_model(model_path, worker_logger)
                worker_logger.debug("Returned from _load_ctranslate2_model")
            elif backend == "transformers":
                worker_logger.debug("Calling _load_transformers_model...")
                model = _load_transformers_model(model_path, model_id)
                worker_logger.debug("Returned from _load_transformers_model")
            elif backend == "transformers_causal":
                worker_logger.debug("Calling _load_transformers_causal_model...")
                model = _load_transformers_causal_model(model_path, model_id)
                worker_logger.debug("Returned from _load_transformers_causal_model")
            else:
                raise WorkerError(f"Unknown backend: {backend}")

            worker_logger.info(f"Model loaded successfully: {model_id}")
        except Exception as e:
            worker_logger.error(f"CRITICAL: Model loading failed: {e}", exc_info=True)
            # Send error to parent before dying
            with contextlib.suppress(Exception):
                conn.send({"ok": False, "error": f"Model loading failed: {e}"})
            raise

        # Main loop
        worker_logger.info("=== ENTERING MAIN LOOP ===")
        while True:
            try:
                # Wait for request
                worker_logger.debug("Polling for request (60s timeout)...")
                if not conn.poll(timeout=60):  # 60 second poll timeout
                    worker_logger.debug("Poll timeout, continuing...")
                    continue

                worker_logger.debug("Receiving request...")
                request = conn.recv()
                worker_logger.debug(f"Received request type: {request.get('type', 'UNKNOWN')}")

                # Handle request
                if request["type"] == "ping":
                    worker_logger.debug("Handling ping request...")
                    conn.send({"ok": True, "status": "alive"})
                    worker_logger.debug("Sent ping response")

                elif request["type"] == "translate":
                    # Extract request data
                    req_data = request["data"]
                    req = WorkerRequest(**req_data)

                    # Translate
                    start_time = time.perf_counter()
                    try:
                        if backend == "ctranslate2":
                            translated_text = _translate_ctranslate2(
                                model, req.text, req.source_lang, req.target_lang
                            )
                        elif backend == "transformers_causal":
                            # For causal LM: req.text IS the full prompt (built by provider)
                            translated_text = _translate_transformers_causal(
                                model, req.text, req.sampling_profile_id
                            )
                        else:  # transformers
                            translated_text = _translate_transformers(
                                model, req.text, req.source_lang, req.target_lang
                            )

                        inference_time_ms = (time.perf_counter() - start_time) * 1000

                        result = WorkerResult(
                            text=translated_text,
                            source_lang=req.source_lang,
                            target_lang=req.target_lang,
                            inference_time_ms=inference_time_ms,
                            request_id=req.request_id,
                        )

                        conn.send({"ok": True, "result": result.__dict__})

                    except Exception as e:
                        worker_logger.error(f"Translation error: {e}")
                        result = WorkerResult(
                            text="",
                            source_lang=req.source_lang,
                            target_lang=req.target_lang,
                            inference_time_ms=0,
                            request_id=req.request_id,
                            error=str(e),
                        )
                        conn.send({"ok": False, "result": result.__dict__, "error": str(e)})

                elif request["type"] == "translate_batch":
                    req_items = [WorkerRequest(**item) for item in request["data"]]
                    start_time = time.perf_counter()
                    try:
                        if backend == "transformers_causal":
                            translated_items = _translate_transformers_causal_batch(
                                model, req_items
                            )
                        else:
                            translated_items = []
                            for req in req_items:
                                if backend == "ctranslate2":
                                    translated_items.append(
                                        _translate_ctranslate2(
                                            model, req.text, req.source_lang, req.target_lang
                                        )
                                    )
                                else:
                                    translated_items.append(
                                        _translate_transformers(
                                            model, req.text, req.source_lang, req.target_lang
                                        )
                                    )

                        inference_time_ms = (time.perf_counter() - start_time) * 1000
                        results = [
                            WorkerResult(
                                text=text,
                                source_lang=req.source_lang,
                                target_lang=req.target_lang,
                                inference_time_ms=inference_time_ms / max(len(req_items), 1),
                                request_id=req.request_id,
                            ).__dict__
                            for req, text in zip(req_items, translated_items, strict=False)
                        ]
                        conn.send({"ok": True, "results": results})
                    except Exception as e:
                        worker_logger.error(f"Batch translation error: {e}")
                        conn.send({"ok": False, "error": str(e)})

                elif request["type"] == "shutdown":
                    worker_logger.info("Shutdown requested")
                    conn.send({"ok": True, "status": "shutdown"})
                    break

                else:
                    worker_logger.warning(f"Unknown request type: {request['type']}")
                    conn.send({"ok": False, "error": f"Unknown request type: {request['type']}"})

            except EOFError:
                # Connection closed by main process
                worker_logger.info("Connection closed by main process")
                break
            except Exception as e:
                worker_logger.error(f"Error in worker loop: {e}")
                try:
                    conn.send({"ok": False, "error": str(e)})
                except Exception:
                    break

    except Exception as e:
        worker_logger.error(f"Worker initialization failed: {e}")
        with contextlib.suppress(Exception):
            conn.send({"ok": False, "error": f"Worker init failed: {e}"})
    finally:
        with contextlib.suppress(Exception):
            _cleanup_loaded_model(model, backend)
        conn.close()
        worker_logger.info("Worker process exiting")


# ============================================================================
# Model Loading Functions
# ============================================================================


def _load_ctranslate2_model(model_path: str, logger=None):
    """Load CTranslate2 model with tokenizer.

    Returns:
        dict: {"translator": ctranslate2.Translator, "tokenizer": AutoTokenizer}
    """
    # CRITICAL FIX: Use direct stdout instead of logging to avoid deadlock in spawn context
    import time

    sys.stdout.write("[Worker] _load_ctranslate2_model START\n")
    sys.stdout.write(f"[Worker] model_path: {model_path}\n")
    sys.stdout.flush()

    try:
        sys.stdout.write("[Worker] Importing ctranslate2...\n")
        sys.stdout.flush()
        import ctranslate2

        sys.stdout.write("[Worker] ctranslate2 imported\n")
        sys.stdout.flush()
    except ImportError as e:
        raise WorkerError("ctranslate2 not installed") from e

    try:
        sys.stdout.write("[Worker] Importing NllbTokenizer...\n")
        sys.stdout.flush()
        from transformers import NllbTokenizer

        sys.stdout.write("[Worker] NllbTokenizer imported\n")
        sys.stdout.flush()
    except ImportError as e:
        raise WorkerError("transformers not installed (needed for tokenization)") from e

    try:
        # Load CTranslate2 translator
        sys.stdout.write(f"[Worker] Loading CTranslate2 translator from: {model_path}\n")
        sys.stdout.flush()

        start_time = time.perf_counter()
        translator = ctranslate2.Translator(model_path, device="cpu")
        elapsed = time.perf_counter() - start_time

        sys.stdout.write(f"[Worker] CTranslate2 translator loaded in {elapsed:.2f}s\n")
        sys.stdout.flush()

        # Load tokenizer for proper tokenization/detokenization
        # CTranslate2 models don't include tokenizer files, so we load from HuggingFace
        model_name = Path(model_path).name
        sys.stdout.write(f"[Worker] Model name: {model_name}\n")
        sys.stdout.flush()

        # Infer HuggingFace model ID from path
        # e.g., "facebook_nllb-200-distilled-1.3B_ctranslate2" -> "facebook/nllb-200-distilled-1.3B"
        if "nllb-200-distilled-1.3B" in model_name:
            hf_model_id = "facebook/nllb-200-distilled-1.3B"
        elif "nllb" in model_name.lower():
            hf_model_id = "facebook/nllb-200-distilled-1.3B"  # Default to this
        elif "seamless" in model_name.lower():
            hf_model_id = "facebook/seamless-m4t-v2-large"
        else:
            raise WorkerError(f"Cannot determine HuggingFace model ID for: {model_name}")

        sys.stdout.write(f"[Worker] HuggingFace model ID: {hf_model_id}\n")
        sys.stdout.write("[Worker] Loading tokenizer from HuggingFace...\n")
        sys.stdout.flush()

        # Load tokenizer from HuggingFace (will be cached locally)
        start_time = time.perf_counter()
        tokenizer = NllbTokenizer.from_pretrained(
            hf_model_id,
            src_lang="eng_Latn",  # Default source language
        )
        elapsed = time.perf_counter() - start_time

        sys.stdout.write(f"[Worker] Tokenizer loaded in {elapsed:.2f}s\n")
        sys.stdout.write("[Worker] _load_ctranslate2_model END (SUCCESS)\n")
        sys.stdout.flush()

        return {"translator": translator, "tokenizer": tokenizer}
    except WorkerError:
        raise
    except Exception as e:
        import traceback

        sys.stdout.write(f"[Worker] ERROR in _load_ctranslate2_model: {e}\n")
        sys.stdout.flush()
        traceback.print_exc()
        raise WorkerError(f"Failed to load CTranslate2 model: {e}") from e


def _load_transformers_model(model_path: str, model_id: str):
    """Load Transformers model."""
    try:
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    except ImportError as e:
        raise WorkerError("transformers not installed") from e

    try:
        model = AutoModelForSeq2SeqLM.from_pretrained(model_path)
        tokenizer = AutoTokenizer.from_pretrained(model_path)
        return {"model": model, "tokenizer": tokenizer}
    except Exception as e:
        raise WorkerError(f"Failed to load Transformers model: {e}") from e


def _load_transformers_causal_model(model_path: str, model_id: str) -> dict:
    """Load decoder-only causal LM (e.g. HY-MT1.5-1.8B or HY-MT1.5-7B-GPTQ-Int4).

    GPTQ models (detected via ``"gptq"`` in ``model_id``) are loaded directly
    via ``auto_gptq.AutoGPTQForCausalLM`` to bypass the brittle
    transformers → optimum → auto_gptq version-coupling chain
    (``QuantizeConfig`` API changed in auto_gptq 0.7.x).

    Args:
        model_path: Path to model directory (local files).
        model_id: Model ID for logging and GPTQ detection.

    Returns:
        dict with keys ``"model"``, ``"tokenizer"``, ``"stop_token_ids"``, and ``"is_gptq"``.

    Raises:
        WorkerError: If required packages are missing or loading fails.
    """
    try:
        import torch
        from transformers import AutoTokenizer
    except ImportError as e:
        raise WorkerError("torch/transformers not installed") from e

    try:
        tokenizer = AutoTokenizer.from_pretrained(model_path)

        is_gptq = "gptq" in model_id.lower()

        from transformers import AutoModelForCausalLM

        if is_gptq:
            # Pre-quantized GPTQ model — load via standard transformers path.
            # Requires gptqmodel as the GPTQ backend (auto_gptq 0.7.x lacks
            # hunyuan_v1_dense support and has an incompatible QuantizeConfig
            # API that breaks optimum's quantizer import).
            # With gptqmodel installed, transformers uses it automatically.
            #
            # Windows: triton is unavailable — force torch kernel via GPTQConfig.
            # torch._dynamo must be disabled before model load to prevent
            # inductor from trying to compile with triton during inference.
            import torch as _torch

            _torch._dynamo.config.disable = True  # no triton on Windows

            from transformers import GPTQConfig

            _gptq_config = GPTQConfig(bits=4, backend="torch")
            sys.stdout.write(
                "[Worker] GPTQ model: loading via transformers+gptqmodel (torch backend)\n"
            )
            sys.stdout.flush()
            model = AutoModelForCausalLM.from_pretrained(
                model_path,
                quantization_config=_gptq_config,
                device_map="auto",
            )
            dtype_label = "gptq-int4"
        else:
            dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
            model = AutoModelForCausalLM.from_pretrained(
                model_path,
                dtype=dtype,
                device_map="auto",
            )
            dtype_label = str(dtype).split(".")[-1]

        model.eval()

        device = next(model.parameters()).device
        sys.stdout.write(f"[Worker] {model_id} loaded on {device} ({dtype_label})\n")
        sys.stdout.flush()

        # Pre-compute stop token IDs so generate() doesn't recompute them each call
        stop_token_ids = _hymt_stop_token_ids(tokenizer)
        sys.stdout.write(f"[Worker] HY-MT stop token IDs: {stop_token_ids}\n")
        sys.stdout.flush()

        if is_gptq:
            # TorchQuantLinear (torch backend, no triton) has a first-token latency
            # spike of ~30% due to CUDA kernel scheduling warm-up.  Run a single
            # dummy generation so the first *real* request doesn't absorb this cost
            # inside the user-visible timeout window.
            _warmup_ids = tokenizer("warmup", return_tensors="pt")
            _warmup_ids.pop("token_type_ids", None)
            _warmup_device = next(model.parameters()).device
            _warmup_ids = {k: v.to(_warmup_device) for k, v in _warmup_ids.items()}
            with torch.no_grad():
                model.generate(**_warmup_ids, max_new_tokens=1, do_sample=False)
            sys.stdout.write("[Worker] GPTQ post-load warmup complete\n")
            sys.stdout.flush()

        return {
            "model": model,
            "tokenizer": tokenizer,
            "stop_token_ids": stop_token_ids,
            "is_gptq": is_gptq,
        }
    except WorkerError:
        raise
    except Exception as e:
        raise WorkerError(f"Failed to load causal model: {e}") from e


# ============================================================================
# Translation Functions
# ============================================================================


def _translate_ctranslate2(
    model_dict: dict,
    text: str,
    source_lang: str,
    target_lang: str,
) -> str:
    """Translate text using CTranslate2 with proper tokenization.

    Args:
        model_dict: Dict with "translator" and "tokenizer"
        text: Input text
        source_lang: Source language code (e.g., "eng_Latn")
        target_lang: Target language code (e.g., "heb_Hebr")

    Returns:
        Translated text
    """
    translator = model_dict["translator"]
    tokenizer = model_dict["tokenizer"]

    # Set source language for tokenizer
    tokenizer.src_lang = source_lang

    # Tokenize input text
    # For NLLB, the tokenizer adds language-specific tokens
    inputs = tokenizer(text, return_tensors="pt", padding=False, truncation=True, max_length=512)
    input_ids = inputs["input_ids"][0].tolist()

    # Convert token IDs back to tokens for CTranslate2
    input_tokens = [tokenizer.convert_ids_to_tokens(id) for id in input_ids]

    # Translate with CTranslate2
    # For NLLB, we need to provide target language as prefix
    results = translator.translate_batch(
        [input_tokens],
        target_prefix=[[target_lang]],
        beam_size=1,
        max_decoding_length=512,
    )

    # Get output tokens
    output_tokens = results[0].hypotheses[0]

    # Convert tokens back to IDs for detokenization
    try:
        output_ids = [tokenizer.convert_tokens_to_ids(token) for token in output_tokens]
    except Exception:
        # Fallback: if token conversion fails, use tokens directly
        output_ids = output_tokens

    # Detokenize
    translated_text = tokenizer.decode(output_ids, skip_special_tokens=True)

    return translated_text


# ============================================================================
# PPS PATCH-04: Sampling profiles (local copy — no import from app layer)
# Values MUST match SAMPLING_PROFILES in prompt_policy.py.
# ============================================================================

# Each entry: {temperature, top_k, top_p, repetition_penalty, n_predict}
# temperature=0.0 means greedy by policy intent (not a hardware constraint).
_WORKER_SAMPLING_PROFILES: dict[str, dict] = {
    "hy_mt_precise_sentence": {
        "temperature": 0.7,
        "top_k": 20,
        "top_p": 0.6,
        "repetition_penalty": 1.05,
        "n_predict": 512,
    },
    "hy_mt_precise_short": {
        "temperature": 0.0,  # greedy by policy intent
        "top_k": 0,
        "top_p": 1.0,
        "repetition_penalty": 1.0,
        "n_predict": 32,
    },
    "hy_mt_precise_formatted": {
        "temperature": 0.5,
        "top_k": 10,
        "top_p": 0.5,
        "repetition_penalty": 1.1,
        "n_predict": 512,
    },
}

_WORKER_DEFAULT_SAMPLING_PROFILE_ID = "hy_mt_precise_sentence"


def _resolve_gen_kwargs(
    sampling_profile_id: str,
    force_greedy: bool,
    max_n_predict_cap: int | None,
    stop_ids: list[int],
) -> dict:
    """Build model.generate() kwargs from a sampling profile + model constraints.

    Args:
        sampling_profile_id: Key into _WORKER_SAMPLING_PROFILES.
            Empty string or unknown key → falls back to hy_mt_precise_sentence
            with a WARNING log.
        force_greedy: Hardware constraint (True for 7B-GPTQ on Windows).
            When True, do_sample=False regardless of profile temperature.
            A WARNING is emitted if the profile had temperature > 0.
        max_n_predict_cap: Hard cap on max_new_tokens (None = no cap).
        stop_ids: List of EOS token IDs.

    Returns:
        Dict suitable for model.generate(**kwargs).
    """
    profile = _WORKER_SAMPLING_PROFILES.get(sampling_profile_id)
    if profile is None:
        if sampling_profile_id:
            logger.warning(
                "Unknown sampling_profile_id %r — falling back to %s",
                sampling_profile_id,
                _WORKER_DEFAULT_SAMPLING_PROFILE_ID,
            )
        profile = _WORKER_SAMPLING_PROFILES[_WORKER_DEFAULT_SAMPLING_PROFILE_ID]

    temperature: float = profile["temperature"]
    n_predict: int = profile["n_predict"]

    # Apply model-level token budget cap
    if max_n_predict_cap is not None:
        n_predict = min(n_predict, max_n_predict_cap)

    eos = stop_ids if stop_ids else None

    if force_greedy:
        if temperature > 0.0:
            logger.warning(
                "force_greedy=True overrides sampling intent (temperature=%.2f) "
                "for profile %r — using greedy decoding",
                temperature,
                sampling_profile_id or _WORKER_DEFAULT_SAMPLING_PROFILE_ID,
            )
        return {"max_new_tokens": n_predict, "do_sample": False, "eos_token_id": eos}

    if temperature == 0.0:
        # Profile requests greedy by intent — no hardware constraint involved
        return {"max_new_tokens": n_predict, "do_sample": False, "eos_token_id": eos}

    return {
        "max_new_tokens": n_predict,
        "do_sample": True,
        "top_k": profile["top_k"],
        "top_p": profile["top_p"],
        "temperature": temperature,
        "repetition_penalty": profile["repetition_penalty"],
        "eos_token_id": eos,
    }


# ============================================================================
# HY-MT template constants (verified against PocketPal config)
# ============================================================================

# ---------------------------------------------------------------------------
# HY-MT 1.5 1.8B template tokens  (tencent/HY-MT1.5-1.8B)
# ---------------------------------------------------------------------------
_HYMT_BOS = "<｜hy_begin▁of▁sentence｜>"
_HYMT_SEP = "<｜hy_place▁holder▁no▁3｜>"  # separates system from user turn
_HYMT_USER = "<｜hy_User｜>"
_HYMT_ASSISTANT = "<｜hy_Assistant｜>"
_HYMT_EOS = "<｜hy_end▁of▁sentence｜>"
_HYMT_STOP2 = "<｜hy_place▁holder▁no▁2｜>"

# ---------------------------------------------------------------------------
# HY-MT 1.5 7B-GPTQ template tokens  (tencent/HY-MT1.5-7B-GPTQ-Int4)
# Tokenizer uses a DIFFERENT vocabulary from the 1.8B model.  The 1.8B
# <｜hy_*｜> special tokens do NOT exist in the 7B-GPTQ vocabulary.
# Correct format (from chat_template.jinja shipped with the model):
#   <|startoftext|>{system}<|extra_4|>{user_content}<|extra_0|>
#   → model generates → {translation}<|eos|>
# ---------------------------------------------------------------------------
_HYMT7B_BOS = "<|startoftext|>"  # token 127958 (bos_token)
_HYMT7B_SEP = "<|extra_4|>"  # token 127966, system→user separator
_HYMT7B_USER_END = "<|extra_0|>"  # token 127962, end of user turn
_HYMT7B_EOS = "<|eos|>"  # token 127960 (eos_token)

# ---------------------------------------------------------------------------
# PPS sentinel constants  (must stay in sync with prompt_policy._PPS_*)
# ---------------------------------------------------------------------------
# When LocalHYMTProvider uses PolicyRenderer.render_sentinel_payload(), it
# wraps WorkerRequest.text in this sentinel so the worker can extract:
#   - role_instruction  (Layer 1 — appended to system prompt)
#   - user_content      (Layers 2-5 — task + glossary + source text)
# If the sentinel is absent, the worker falls back to legacy behaviour:
# hardcoded task instruction prepended inside the chat template.
_HYMT_PPS_SENTINEL_START: str = "\x00PPS_PAYLOAD\x00"
_HYMT_PPS_ROLE_SEP: str = "\x00ROLE\x00"

# System prompt: translation engine persona + placeholder rule
# Intentionally does NOT include "Translate from X to Y" — that goes in user turn
_HYMT_SYSTEM_PROMPT = (
    "You are a translation engine specialized in Hebrew-to-Russian translation. "
    "Translate from Hebrew into Russian accurately and naturally. "
    "Preserve meaning, names, numbers, and formatting. "
    "Preserve all placeholder tokens (HDLE_PH_1, HDLE_PH_2, etc.) exactly as-is "
    "without any modification. "
    "Output only the Russian translation without explanations, comments, or extra text."
)

# PPS PATCH-06: 12-char prefix of SHA-256 over system prompt bytes.
# Used in get_model_version() for MT cache key isolation when the prompt changes.
_HYMT_SYSTEM_PROMPT_HASH: str = hashlib.sha256(_HYMT_SYSTEM_PROMPT.encode()).hexdigest()[:12]


def _hymt_stop_token_ids(tokenizer) -> list[int]:
    """Resolve HY-MT stop token IDs from the tokenizer vocabulary.

    Tries both ``convert_tokens_to_ids`` (fast, works when token is in vocab)
    and ``encode`` fallback for single-token strings.  Always includes the
    tokenizer's ``eos_token_id`` if defined.

    Returns:
        Deduplicated list of token IDs to use as ``eos_token_id`` in generate().
    """
    ids: list[int] = []
    unk = getattr(tokenizer, "unk_token_id", None)

    for stop_str in (_HYMT_EOS, _HYMT_STOP2):
        tok_id = tokenizer.convert_tokens_to_ids(stop_str)
        if tok_id is not None and tok_id != unk:
            ids.append(tok_id)
            continue
        # Fallback: encode without special tokens; only use if single token
        encoded = tokenizer.encode(stop_str, add_special_tokens=False)
        if len(encoded) == 1:
            ids.append(encoded[0])

    if tokenizer.eos_token_id is not None:
        ids.append(tokenizer.eos_token_id)

    return list(dict.fromkeys(ids))  # deduplicate, preserve order


def _build_hymt_chat_text(prompt: str, is_gptq: bool) -> str:
    """Build final chat text for HY-MT prompt payload."""
    if prompt.startswith(_HYMT_PPS_SENTINEL_START):
        payload = prompt[len(_HYMT_PPS_SENTINEL_START) :]
        sep_idx = payload.find(_HYMT_PPS_ROLE_SEP)
        if sep_idx == -1:
            role_instruction = ""
            user_content = payload
        else:
            role_instruction = payload[:sep_idx]
            user_content = payload[sep_idx + len(_HYMT_PPS_ROLE_SEP) :]
        role_suffix = ("\n" + role_instruction.strip()) if role_instruction.strip() else ""
        effective_system = _HYMT_SYSTEM_PROMPT + role_suffix
    else:
        effective_system = _HYMT_SYSTEM_PROMPT
        user_content = (
            "Translate the following segment into Russian, "
            f"without additional explanation.\n\n{prompt}"
        )

    if is_gptq:
        return f"{_HYMT7B_BOS}{effective_system}{_HYMT7B_SEP}{user_content}{_HYMT7B_USER_END}"
    return f"{_HYMT_BOS}{effective_system}{_HYMT_SEP}{_HYMT_USER}{user_content}{_HYMT_ASSISTANT}"


def _strip_hymt_generation_result(result: str, is_gptq: bool) -> str:
    result = (result or "").strip()
    if is_gptq:
        if result.endswith(_HYMT7B_EOS):
            result = result[: -len(_HYMT7B_EOS)].strip()
        for boundary in (_HYMT7B_USER_END, _HYMT7B_BOS, "</User>"):
            idx = result.find(boundary)
            if idx != -1:
                result = result[:idx].strip()
                break
        return result

    for stop_str in (_HYMT_EOS, _HYMT_STOP2):
        if result.endswith(stop_str):
            result = result[: -len(stop_str)].strip()
    return result


def _translate_transformers_causal(
    model_dict: dict, prompt: str, sampling_profile_id: str = ""
) -> str:
    """Run HY-MT inference using the vendor-verified template format.

    ``prompt`` (= ``WorkerRequest.text``) carries only the *user content*:
    the placeholder-protected source text, optionally preceded by a
    terminology line built by the provider.  All meta-instructions (role,
    placeholder rule, output format) live in the system prompt inside this
    function so the model never confuses them with text to translate.

    Template (matches PocketPal config):
        <BOS>{system}<SEP><User>Translate … without additional explanation.

        {user_content}<Assistant>

    Stop tokens: ``<｜hy_end▁of▁sentence｜>``, ``<｜hy_place▁holder▁no▁2｜>``

    Args:
        model_dict: Dict with ``"model"``, ``"tokenizer"``, and
            ``"stop_token_ids"`` (pre-computed by ``_load_transformers_causal_model``).
        prompt: User content — source text (+ optional terminology line).
        sampling_profile_id: Key into ``_WORKER_SAMPLING_PROFILES``.
            Empty string uses model-appropriate default via ``_resolve_gen_kwargs``.

    Returns:
        Decoded translation (new tokens only, special tokens stripped).
    """
    import torch

    model = model_dict["model"]
    tokenizer = model_dict["tokenizer"]
    stop_ids = model_dict.get("stop_token_ids") or _hymt_stop_token_ids(tokenizer)
    is_gptq = model_dict.get("is_gptq", False)

    chat_text = _build_hymt_chat_text(prompt, is_gptq)

    # model.device may not exist on all GPTQ wrappers — fall back to parameters()
    try:
        infer_device = model.device
    except AttributeError:
        infer_device = next(model.parameters()).device
    inputs = tokenizer(chat_text, return_tensors="pt").to(infer_device)
    prompt_len = inputs["input_ids"].shape[1]

    # HY-MT generate() rejects token_type_ids — filter it out
    generate_inputs = {k: v for k, v in inputs.items() if k in ("input_ids", "attention_mask")}

    # PPS PATCH-04: resolve gen_kwargs from sampling profile + model constraints.
    # 7B-GPTQ: force_greedy=True (hardware: ~0.6 s/token, no triton on Windows),
    #           max_n_predict_cap=128 (77 s worst case < 120 s timeout).
    # 1.8B:    force_greedy=False, max_n_predict_cap=512.
    gen_kwargs: dict = _resolve_gen_kwargs(
        sampling_profile_id=sampling_profile_id,
        force_greedy=is_gptq,
        max_n_predict_cap=128 if is_gptq else 512,
        stop_ids=stop_ids,
    )

    with torch.no_grad():
        outputs = model.generate(**generate_inputs, **gen_kwargs)

    new_tokens = outputs[0][prompt_len:]
    result = tokenizer.decode(new_tokens, skip_special_tokens=True)
    return _strip_hymt_generation_result(result, is_gptq)


def _translate_transformers_causal_batch(
    model_dict: dict, requests: list[WorkerRequest]
) -> list[str]:
    """Run batched HY-MT inference for a micro-batch of prompts."""
    import torch

    if not requests:
        return []

    if len(requests) == 1:
        return [
            _translate_transformers_causal(
                model_dict,
                requests[0].text,
                requests[0].sampling_profile_id,
            )
        ]

    model = model_dict["model"]
    tokenizer = model_dict["tokenizer"]
    stop_ids = model_dict.get("stop_token_ids") or _hymt_stop_token_ids(tokenizer)
    is_gptq = model_dict.get("is_gptq", False)

    sampling_ids = {req.sampling_profile_id or "" for req in requests}
    if len(sampling_ids) > 1:
        return [
            _translate_transformers_causal(model_dict, req.text, req.sampling_profile_id)
            for req in requests
        ]

    chat_texts = [_build_hymt_chat_text(req.text, is_gptq) for req in requests]

    try:
        infer_device = model.device
    except AttributeError:
        infer_device = next(model.parameters()).device

    original_padding_side = getattr(tokenizer, "padding_side", "right")
    if is_gptq:
        tokenizer.padding_side = "left"
    if getattr(tokenizer, "pad_token_id", None) is None and getattr(tokenizer, "eos_token", None):
        tokenizer.pad_token = tokenizer.eos_token

    try:
        inputs = tokenizer(chat_texts, return_tensors="pt", padding=True).to(infer_device)
        prompt_lens = inputs["attention_mask"].sum(dim=1).tolist()
        generate_inputs = {k: v for k, v in inputs.items() if k in ("input_ids", "attention_mask")}
        gen_kwargs: dict = _resolve_gen_kwargs(
            sampling_profile_id=next(iter(sampling_ids)),
            force_greedy=is_gptq,
            max_n_predict_cap=128 if is_gptq else 512,
            stop_ids=stop_ids,
        )
        with torch.no_grad():
            outputs = model.generate(**generate_inputs, **gen_kwargs)

        results: list[str] = []
        for idx, prompt_len in enumerate(prompt_lens):
            new_tokens = outputs[idx][prompt_len:]
            text = tokenizer.decode(new_tokens, skip_special_tokens=True)
            results.append(_strip_hymt_generation_result(text, is_gptq))
        return results
    finally:
        tokenizer.padding_side = original_padding_side


def _translate_transformers(
    model_dict: dict,
    text: str,
    source_lang: str,
    target_lang: str,
) -> str:
    """Translate text using Transformers."""
    model = model_dict["model"]
    tokenizer = model_dict["tokenizer"]

    # Set source/target languages
    # Note: For NLLB, use forced_bos_token_id for target language
    tokenizer.src_lang = source_lang
    tokenizer.tgt_lang = target_lang

    # Tokenize
    inputs = tokenizer(text, return_tensors="pt")

    # Resolve forced_bos_token_id for target language.
    # transformers 4.x: tokenizer.lang_code_to_id[target_lang]
    # transformers 5.x: lang_code_to_id was removed; use convert_tokens_to_ids()
    lang_to_id = getattr(tokenizer, "lang_code_to_id", None)
    if lang_to_id is not None:
        forced_bos_token_id = lang_to_id[target_lang]
    else:
        forced_bos_token_id = tokenizer.convert_tokens_to_ids(target_lang)

    # Generate
    outputs = model.generate(
        **inputs,
        forced_bos_token_id=forced_bos_token_id,
        max_length=512,
    )

    # Decode
    translated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)

    return translated_text


# ============================================================================
# Worker Client (Main Process)
# ============================================================================


class LocalMTWorker:
    """Client for worker process."""

    def __init__(
        self,
        model_path: Path,
        backend: str,
        model_id: str,
        timeout: float = 30.0,
    ):
        """
        Initialize worker client.

        Args:
            model_path: Path to model directory
            backend: Backend ("ctranslate2" or "transformers")
            model_id: Model ID (for logging)
            timeout: Request timeout in seconds
        """
        self.model_path = model_path
        self.backend = backend
        self.model_id = model_id
        self.timeout = timeout

        self.process: multiprocessing.Process | None = None
        self.conn: Connection | None = None

        self._start_worker()

    def _start_worker(self):
        """Start worker process."""
        import time

        start_time = time.perf_counter()
        logger.info(f"[WORKER] Starting worker for {self.model_id} ({self.backend})")

        # Create IPC connection
        parent_conn, child_conn = multiprocessing.Pipe()

        # Get spawn context (Windows-safe)
        ctx = multiprocessing.get_context("spawn")

        # Start process
        self.process = ctx.Process(
            target=_worker_main,
            args=(child_conn, str(self.model_path), self.backend, self.model_id),
        )
        self.process.start()

        self.conn = parent_conn

        # Wait for worker to be ready (ping)
        # Model loading can take 60-240 seconds on slower systems (1.3GB model)
        try:
            logger.info("Waiting for worker to load model (timeout=240s)...")
            if not self.ping(timeout=240):  # 240 seconds for model loading (increased from 120s)
                # Check if process is still alive
                if self.process and self.process.is_alive():
                    logger.error("Worker process alive but not responding to ping (timeout)")
                else:
                    logger.error("Worker process died during startup")
                raise WorkerError("Worker failed to start")
            elapsed = time.perf_counter() - start_time
            logger.info(f"[WORKER] Worker ready: {self.model_id} ({elapsed:.1f}s)")
        except Exception as e:
            elapsed = time.perf_counter() - start_time
            logger.error(f"[WORKER] Worker startup error: {e} (failed after {elapsed:.1f}s)")
            self.shutdown()
            raise WorkerError(f"Worker startup failed: {e}") from e

        elapsed = time.perf_counter() - start_time
        logger.info(f"[WORKER] Worker started successfully: {self.model_id} ({elapsed:.1f}s)")

    def ping(self, timeout: float | None = None) -> bool:
        """
        Ping worker to check if alive.

        Args:
            timeout: Timeout in seconds

        Returns:
            True if worker alive, False otherwise
        """
        if not self.conn:
            return False

        timeout = timeout if timeout is not None else self.timeout

        try:
            self.conn.send({"type": "ping"})

            if self.conn.poll(timeout=timeout):
                response = self.conn.recv()
                if not response.get("ok", False):
                    # Worker sent error message
                    error_msg = response.get("error", "Unknown error")
                    logger.error(f"Worker ping failed with error: {error_msg}")
                    raise WorkerError(f"Worker initialization failed: {error_msg}")
                return True
            else:
                logger.warning(f"Worker ping timeout: {self.model_id}")
                return False
        except WorkerError:
            raise
        except Exception as e:
            logger.error(f"Worker ping error: {e}")
            return False

    def translate(self, request: WorkerRequest) -> WorkerResult:
        """
        Translate text.

        Args:
            request: Translation request

        Returns:
            Translation result

        Raises:
            WorkerError: If translation fails
        """
        if not self.conn:
            raise WorkerError("Worker not started")

        try:
            # Send request
            self.conn.send(
                {
                    "type": "translate",
                    "data": {
                        "text": request.text,
                        "source_lang": request.source_lang,
                        "target_lang": request.target_lang,
                        "request_id": request.request_id,
                        "sampling_profile_id": request.sampling_profile_id,
                    },
                }
            )

            # Wait for response
            if self.conn.poll(timeout=self.timeout):
                response = self.conn.recv()

                if response.get("ok"):
                    result_data = response["result"]
                    return WorkerResult(**result_data)
                else:
                    error_msg = response.get("error", "Unknown error")
                    raise WorkerError(f"Translation failed: {error_msg}")
            else:
                raise WorkerError(f"Translation timeout ({self.timeout}s)")

        except WorkerError:
            raise
        except Exception as e:
            raise WorkerError(f"Worker communication error: {e}") from e

    def translate_batch(self, requests: list[WorkerRequest]) -> list[WorkerResult]:
        """Translate a micro-batch of requests in a single worker round-trip."""
        if not self.conn:
            raise WorkerError("Worker not started")

        try:
            self.conn.send(
                {
                    "type": "translate_batch",
                    "data": [
                        {
                            "text": req.text,
                            "source_lang": req.source_lang,
                            "target_lang": req.target_lang,
                            "request_id": req.request_id,
                            "sampling_profile_id": req.sampling_profile_id,
                        }
                        for req in requests
                    ],
                }
            )

            if self.conn.poll(timeout=self.timeout):
                response = self.conn.recv()
                if response.get("ok"):
                    return [WorkerResult(**item) for item in response.get("results", [])]
                error_msg = response.get("error", "Unknown error")
                raise WorkerError(f"Batch translation failed: {error_msg}")
            raise WorkerError(f"Batch translation timeout ({self.timeout}s)")
        except WorkerError:
            raise
        except Exception as e:
            raise WorkerError(f"Worker batch communication error: {e}") from e

    def shutdown(self, graceful_timeout: float = 15.0):
        """Shutdown worker process."""
        if self.conn:
            try:
                self.conn.send({"type": "shutdown"})
                if self.conn.poll(timeout=min(graceful_timeout, 5.0)):
                    self.conn.recv()
            except Exception:
                pass

            with contextlib.suppress(Exception):
                self.conn.close()

            self.conn = None

        if self.process and self.process.is_alive():
            self.process.join(timeout=graceful_timeout)
            if self.process.is_alive():
                logger.warning(f"Force terminating worker: {self.model_id}")
                self.process.terminate()
                self.process.join(timeout=2)

        self.process = None

    def __del__(self):
        """Cleanup on deletion."""
        try:
            if hasattr(self, "process") and hasattr(self, "conn"):
                self.shutdown()
        except Exception:
            pass


# ============================================================================
# Helper Functions
# ============================================================================


def start_worker(
    model_path: Path,
    backend: str,
    model_id: str,
    timeout: float = 30.0,
) -> LocalMTWorker:
    """
    Start worker process.

    Args:
        model_path: Path to model directory
        backend: Backend ("ctranslate2" or "transformers")
        model_id: Model ID
        timeout: Request timeout

    Returns:
        Worker client
    """
    return LocalMTWorker(model_path, backend, model_id, timeout)
