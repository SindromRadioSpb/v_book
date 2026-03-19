"""Local NLLB provider using CTranslate2 worker process.

This provider runs NLLB translation locally using the installed model.
It integrates:
- Worker process for model inference (PATCH-03)
- Text segmentation for long inputs (PATCH-04)
- Glossary postprocessing with TM (PATCH-05)

Language Support: 200+ languages via NLLB-200

Architecture:
1. Initialize worker process with model
2. Segment long texts (>512 tokens)
3. Translate segments via worker
4. Apply glossary postprocess (replace MT with approved TM terms)
5. Reassemble translated segments
6. Return result with metadata
"""

import logging
import time

from sqlalchemy.orm import Session

from app.infra.local_mt import LocalMTWorker, WorkerError, WorkerRequest, start_worker
from app.infra.translators.base_provider import (
    BaseProvider,
    TranslationErrorKind,
    TranslationRequest,
    TranslationResult,
)
from app.services.local_models import ModelResourceManager
from app.services.local_mt import (
    apply_glossary,
    reassemble_text,
    segment_text,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Language Code Mapping
# ============================================================================

# Map ISO 639-1 codes to NLLB language codes
# Format: ISO_639_1 → NLLB_CODE (language_Script)
ISO_TO_NLLB = {
    # Hebrew
    "he": "heb_Hebr",
    "iw": "heb_Hebr",  # Alternative code for Hebrew
    # English
    "en": "eng_Latn",
    # Russian
    "ru": "rus_Cyrl",
    # Arabic
    "ar": "arb_Arab",
    # Spanish
    "es": "spa_Latn",
    # French
    "fr": "fra_Latn",
    # German
    "de": "deu_Latn",
    # Italian
    "it": "ita_Latn",
    # Portuguese
    "pt": "por_Latn",
    # Chinese (Simplified)
    "zh": "zho_Hans",
    "zh-CN": "zho_Hans",
    # Chinese (Traditional)
    "zh-TW": "zho_Hant",
    # Japanese
    "ja": "jpn_Jpan",
    # Korean
    "ko": "kor_Hang",
    # Turkish
    "tr": "tur_Latn",
    # Polish
    "pl": "pol_Latn",
    # Dutch
    "nl": "nld_Latn",
    # Swedish
    "sv": "swe_Latn",
    # Norwegian
    "no": "nob_Latn",
    # Danish
    "da": "dan_Latn",
    # Finnish
    "fi": "fin_Latn",
    # Greek
    "el": "ell_Grek",
    # Czech
    "cs": "ces_Latn",
    # Romanian
    "ro": "ron_Latn",
    # Hungarian
    "hu": "hun_Latn",
    # Ukrainian
    "uk": "ukr_Cyrl",
    # Bulgarian
    "bg": "bul_Cyrl",
    # Croatian
    "hr": "hrv_Latn",
    # Serbian
    "sr": "srp_Cyrl",
    # Slovak
    "sk": "slk_Latn",
    # Lithuanian
    "lt": "lit_Latn",
    # Latvian
    "lv": "lvs_Latn",
    # Estonian
    "et": "est_Latn",
    # Slovenian
    "sl": "slv_Latn",
}


def map_iso_to_nllb(iso_code: str) -> str | None:
    """
    Map ISO 639-1 code to NLLB language code.

    Args:
        iso_code: ISO 639-1 code (e.g., "he", "en", "ru", "zh-CN")

    Returns:
        NLLB code (e.g., "heb_Hebr") or None if not supported
    """
    # Normalize: lowercase first part, uppercase after hyphen
    # e.g., "zh-cn" → "zh-CN", "ZH-TW" → "zh-TW"
    if "-" in iso_code:
        parts = iso_code.split("-")
        normalized = f"{parts[0].lower()}-{parts[1].upper()}"
    else:
        normalized = iso_code.lower()

    return ISO_TO_NLLB.get(normalized)


# ============================================================================
# LocalNLLBProvider
# ============================================================================


class LocalNLLBProvider(BaseProvider):
    """
    Local NLLB-200 translation provider.

    Uses CTranslate2 worker process for inference with:
    - Sentence segmentation for long texts
    - Glossary postprocessing with approved TM terms
    - Offline operation (no API calls)
    """

    def __init__(
        self,
        model_id: str = "facebook/nllb-200-distilled-1.3B",
        backend: str = "ctranslate2",
        db_session: Session | None = None,
        project_id: int | None = None,
        timeout: float = 30.0,
    ):
        """
        Initialize LocalNLLBProvider.

        Args:
            model_id: Model ID (default: facebook/nllb-200-distilled-1.3B)
            backend: Backend (default: ctranslate2)
            db_session: Optional database session for glossary postprocessing
            project_id: Optional project ID for TM scope
            timeout: Worker timeout in seconds (default: 30.0)
        """
        self.model_id = model_id
        self.backend = backend
        self.db_session = db_session
        self.project_id = project_id
        self.timeout = timeout

        self.worker: LocalMTWorker | None = None
        self._model_manager = ModelResourceManager()

        # Initialize worker
        self._init_worker()

    def _init_worker(self):
        """Initialize worker process."""
        # Check if model installed
        is_installed, reason = self._model_manager.is_installed(self.model_id, self.backend)

        if not is_installed:
            logger.error(f"Model not installed: {self.model_id} ({self.backend}). Reason: {reason}")
            raise RuntimeError(
                f"Model not installed: {self.model_id}. "
                f"Install with: python scripts/install_local_mt_model.py --model nllb-200-distilled-1.3B"
            )

        # Get model path
        model_path = self._model_manager.model_dir(self.model_id, self.backend)

        # Start worker
        try:
            self.worker = start_worker(
                model_path=model_path,
                backend=self.backend,
                model_id=self.model_id,
                timeout=self.timeout,
            )
            logger.info(f"LocalNLLBProvider initialized with model: {self.model_id}")
        except WorkerError as e:
            logger.error(f"Failed to start worker: {e}")
            raise RuntimeError(f"Failed to start worker: {e}")

    @property
    def provider_id(self) -> str:
        return "local_nllb"

    @property
    def display_name(self) -> str:
        return "Local NLLB-200 (Offline)"

    @property
    def supports_glossary(self) -> bool:
        """Glossary support via TM postprocessing."""
        return True

    @property
    def supports_batch(self) -> bool:
        return False

    def get_model_version(self) -> str:
        """
        Return model version for cache key.

        Format: {model_id}_{backend}
        Example: facebook_nllb-200-distilled-1.3B_ctranslate2

        This ensures different backends (ctranslate2 vs transformers)
        use separate cache entries.
        """
        # Include both model_id and backend for cache isolation
        model_id_normalized = self.model_id.replace("/", "_")
        return f"{model_id_normalized}_{self.backend}"

    def healthcheck(self) -> bool:
        """Check if worker is alive."""
        if not self.worker:
            return False

        try:
            return self.worker.ping(timeout=5.0)
        except Exception as e:
            logger.warning(f"Healthcheck failed: {e}")
            return False

    def translate(self, request: TranslationRequest) -> TranslationResult:
        """
        Translate text using local NLLB model.

        Process:
        1. Map ISO codes to NLLB codes
        2. Segment text (for long inputs)
        3. Translate segments via worker
        4. Apply glossary postprocess (if DB available)
        5. Reassemble translated segments
        6. Return result with metadata

        Args:
            request: TranslationRequest with source text and parameters

        Returns:
            TranslationResult (never raises exceptions)
        """
        start_time = time.time()

        # Validate worker
        if not self.worker:
            return TranslationResult(
                provider_id=self.provider_id,
                error_kind=TranslationErrorKind.SERVER,
                error_message="Worker not initialized",
                latency_ms=0,
            )

        # Map language codes
        src_nllb = map_iso_to_nllb(request.source_lang)
        tgt_nllb = map_iso_to_nllb(request.target_lang)

        if not src_nllb or not tgt_nllb:
            unsupported_lang = request.source_lang if not src_nllb else request.target_lang
            return TranslationResult(
                provider_id=self.provider_id,
                error_kind=TranslationErrorKind.UNSUPPORTED,
                error_message=f"Unsupported language: {unsupported_lang}",
                latency_ms=int((time.time() - start_time) * 1000),
            )

        # Handle empty text early
        if not request.source_text or not request.source_text.strip():
            return TranslationResult(
                translated_text="",
                provider_id=self.provider_id,
                latency_ms=int((time.time() - start_time) * 1000),
                meta={"segment_count": 0},
            )

        # Segment text
        try:
            segments = segment_text(request.source_text)

            if not segments:
                # Empty text after segmentation
                return TranslationResult(
                    translated_text="",
                    provider_id=self.provider_id,
                    latency_ms=int((time.time() - start_time) * 1000),
                    meta={"segment_count": 0},
                )

        except Exception as e:
            logger.error(f"Segmentation error: {e}")
            return TranslationResult(
                provider_id=self.provider_id,
                error_kind=TranslationErrorKind.INVALID_REQUEST,
                error_message=f"Segmentation failed: {e}",
                latency_ms=int((time.time() - start_time) * 1000),
            )

        # Translate segments
        mt_translations = []
        total_inference_time_ms = 0.0

        for segment in segments:
            try:
                worker_request = WorkerRequest(
                    text=segment.text,
                    source_lang=src_nllb,
                    target_lang=tgt_nllb,
                    request_id=request.trace_id,
                )

                result = self.worker.translate(worker_request)

                if result.error:
                    logger.error(f"Worker translation error: {result.error}")
                    return TranslationResult(
                        provider_id=self.provider_id,
                        error_kind=TranslationErrorKind.SERVER,
                        error_message=f"Translation failed: {result.error}",
                        latency_ms=int((time.time() - start_time) * 1000),
                    )

                mt_translations.append(result.text)
                total_inference_time_ms += result.inference_time_ms

            except WorkerError as e:
                logger.error(f"Worker error: {e}")
                return TranslationResult(
                    provider_id=self.provider_id,
                    error_kind=TranslationErrorKind.SERVER,
                    error_message=f"Worker error: {e}",
                    latency_ms=int((time.time() - start_time) * 1000),
                )
            except Exception as e:
                logger.error(f"Unexpected error during translation: {e}")
                return TranslationResult(
                    provider_id=self.provider_id,
                    error_kind=TranslationErrorKind.UNKNOWN,
                    error_message=f"Unexpected error: {e}",
                    latency_ms=int((time.time() - start_time) * 1000),
                )

        # Apply glossary postprocess (if DB available)
        applied_terms_count = 0
        used_glossary = False

        if self.db_session:
            try:
                # Extract source segments
                source_segments = [seg.text for seg in segments]

                # Apply glossary
                postprocess_result = apply_glossary(
                    self.db_session,
                    source_segments=source_segments,
                    target_segments=mt_translations,
                    src_lang=src_nllb,
                    tgt_lang=tgt_nllb,
                    project_id=self.project_id,
                )

                # Use postprocessed translations
                mt_translations = postprocess_result.translations
                applied_terms_count = postprocess_result.match_count
                used_glossary = applied_terms_count > 0

                if used_glossary:
                    logger.debug(
                        f"Applied {applied_terms_count} glossary terms "
                        f"(out of {len(segments)} segments)"
                    )

            except Exception as e:
                logger.warning(f"Glossary postprocess failed: {e} (continuing with MT output)")
                # Continue with MT translations (don't fail the request)

        # Reassemble translated segments
        try:
            final_translation = reassemble_text(segments, mt_translations)
        except Exception as e:
            logger.error(f"Reassembly error: {e}")
            return TranslationResult(
                provider_id=self.provider_id,
                error_kind=TranslationErrorKind.UNKNOWN,
                error_message=f"Reassembly failed: {e}",
                latency_ms=int((time.time() - start_time) * 1000),
            )

        # Calculate total latency
        latency_ms = int((time.time() - start_time) * 1000)

        # Return success result
        return TranslationResult(
            translated_text=final_translation,
            provider_id=self.provider_id,
            used_glossary=used_glossary,
            cache_hit=False,
            latency_ms=latency_ms,
            meta={
                "segment_count": len(segments),
                "inference_time_ms": total_inference_time_ms,
                "applied_terms_count": applied_terms_count,
                "model_id": self.model_id,
                "backend": self.backend,
            },
        )

    def shutdown(self):
        """Shutdown worker process."""
        if self.worker:
            try:
                self.worker.shutdown()
                logger.info("LocalNLLBProvider worker shut down")
            except Exception as e:
                logger.warning(f"Error shutting down worker: {e}")
            finally:
                self.worker = None

    def __del__(self):
        """Cleanup on deletion."""
        try:
            if hasattr(self, "worker") and self.worker:
                self.shutdown()
        except:
            pass
