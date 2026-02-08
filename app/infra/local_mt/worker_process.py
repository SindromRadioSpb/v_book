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
import logging
import multiprocessing
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple, Any
from multiprocessing.connection import Connection

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


@dataclass
class WorkerResult:
    """Translation result from worker."""

    text: str
    source_lang: str
    target_lang: str
    inference_time_ms: float
    request_id: str = ""
    error: Optional[str] = None


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
    # Configure logging in worker process
    logging.basicConfig(
        level=logging.INFO,
        format=f"[Worker-{model_id}] %(asctime)s - %(levelname)s - %(message)s"
    )
    worker_logger = logging.getLogger(__name__)

    try:
        # Load model
        worker_logger.info(f"Loading model: {model_id} ({backend})")
        worker_logger.info(f"Model path: {model_path}")

        if backend == "ctranslate2":
            model = _load_ctranslate2_model(model_path)
        elif backend == "transformers":
            model = _load_transformers_model(model_path, model_id)
        else:
            raise WorkerError(f"Unknown backend: {backend}")

        worker_logger.info(f"Model loaded successfully: {model_id}")

        # Main loop
        while True:
            try:
                # Wait for request
                if not conn.poll(timeout=60):  # 60 second poll timeout
                    continue

                request = conn.recv()

                # Handle request
                if request["type"] == "ping":
                    conn.send({"ok": True, "status": "alive"})

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
                except:
                    break

    except Exception as e:
        worker_logger.error(f"Worker initialization failed: {e}")
        try:
            conn.send({"ok": False, "error": f"Worker init failed: {e}"})
        except:
            pass
    finally:
        conn.close()
        worker_logger.info("Worker process exiting")


# ============================================================================
# Model Loading Functions
# ============================================================================


def _load_ctranslate2_model(model_path: str):
    """Load CTranslate2 model with tokenizer.

    Returns:
        dict: {"translator": ctranslate2.Translator, "tokenizer": AutoTokenizer}
    """
    try:
        import ctranslate2
    except ImportError:
        raise WorkerError("ctranslate2 not installed")

    try:
        from transformers import NllbTokenizer
    except ImportError:
        raise WorkerError("transformers not installed (needed for tokenization)")

    try:
        # Load CTranslate2 translator
        translator = ctranslate2.Translator(model_path, device="cpu")

        # Load tokenizer for proper tokenization/detokenization
        # CTranslate2 models don't include tokenizer files, so we load from HuggingFace
        model_name = Path(model_path).name

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

        # Load tokenizer from HuggingFace (will be cached locally)
        tokenizer = NllbTokenizer.from_pretrained(
            hf_model_id,
            src_lang="eng_Latn",  # Default source language
        )

        return {"translator": translator, "tokenizer": tokenizer}
    except WorkerError:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise WorkerError(f"Failed to load CTranslate2 model: {e}")


def _load_transformers_model(model_path: str, model_id: str):
    """Load Transformers model."""
    try:
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    except ImportError:
        raise WorkerError("transformers not installed")

    try:
        model = AutoModelForSeq2SeqLM.from_pretrained(model_path)
        tokenizer = AutoTokenizer.from_pretrained(model_path)
        return {"model": model, "tokenizer": tokenizer}
    except Exception as e:
        raise WorkerError(f"Failed to load Transformers model: {e}")


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
    except:
        # Fallback: if token conversion fails, use tokens directly
        output_ids = output_tokens

    # Detokenize
    translated_text = tokenizer.decode(output_ids, skip_special_tokens=True)

    return translated_text


def _translate_transformers(
    model_dict: Dict,
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

    # Generate
    outputs = model.generate(
        **inputs,
        forced_bos_token_id=tokenizer.lang_code_to_id[target_lang],
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

        self.process: Optional[multiprocessing.Process] = None
        self.conn: Optional[Connection] = None

        self._start_worker()

    def _start_worker(self):
        """Start worker process."""
        logger.info(f"Starting worker for {self.model_id} ({self.backend})")

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
        # Model loading can take 60-120 seconds on slower systems
        try:
            logger.info(f"Waiting for worker to load model (timeout=120s)...")
            if not self.ping(timeout=120):  # 120 seconds for model loading
                # Check if process is still alive
                if self.process and self.process.is_alive():
                    logger.error(f"Worker process alive but not responding to ping (timeout)")
                else:
                    logger.error(f"Worker process died during startup")
                raise WorkerError("Worker failed to start")
            logger.info(f"Worker ready: {self.model_id}")
        except Exception as e:
            logger.error(f"Worker startup error: {e}")
            self.shutdown()
            raise WorkerError(f"Worker startup failed: {e}")

        logger.info(f"Worker started: {self.model_id}")

    def ping(self, timeout: Optional[float] = None) -> bool:
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
                return response.get("ok", False)
            else:
                logger.warning(f"Worker ping timeout: {self.model_id}")
                return False
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
            self.conn.send({
                "type": "translate",
                "data": {
                    "text": request.text,
                    "source_lang": request.source_lang,
                    "target_lang": request.target_lang,
                    "request_id": request.request_id,
                }
            })

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
            raise WorkerError(f"Worker communication error: {e}")

    def shutdown(self):
        """Shutdown worker process."""
        if self.conn:
            try:
                self.conn.send({"type": "shutdown"})
                if self.conn.poll(timeout=5):
                    self.conn.recv()
            except:
                pass

            try:
                self.conn.close()
            except:
                pass

            self.conn = None

        if self.process and self.process.is_alive():
            self.process.join(timeout=5)
            if self.process.is_alive():
                logger.warning(f"Force terminating worker: {self.model_id}")
                self.process.terminate()
                self.process.join(timeout=2)

        self.process = None

    def __del__(self):
        """Cleanup on deletion."""
        try:
            if hasattr(self, 'process') and hasattr(self, 'conn'):
                self.shutdown()
        except:
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
