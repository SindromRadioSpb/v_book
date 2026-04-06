"""Local HY-MT 7B GPTQ provider (Tencent Hunyuan 7B Int4 quantized).

This is a thin subclass of LocalHYMTProvider that overrides only the
model identity properties.  All translation logic (placeholder protection,
glossary postprocess, prompt construction) is inherited unchanged.

Prerequisites:
    - Model installed via: python scripts/install_local_mt_model.py
          --model HY-MT1.5-7B-GPTQ-Int4 --backend transformers_causal
    - auto-gptq >= 0.6.0 installed:  pip install auto-gptq>=0.6.0
      (or: pip install optimum[gptq])

VRAM budget: ~3.5–4 GB (Int4 quant) — fits RTX 3070 8 GB alongside NLLB.
Enabled: ``enabled_by_default=False`` — must be explicitly activated.
         Never initialised automatically at startup to avoid VRAM collision
         with the default 1.8B provider.
"""

from sqlalchemy.orm import Session

from app.infra.translators.providers.local_hymt_provider import LocalHYMTProvider

MODEL_ID = "tencent/HY-MT1.5-7B-GPTQ-Int4"
BACKEND = "transformers_causal"


class LocalHYMT7BGPTQProvider(LocalHYMTProvider):
    """Local HY-MT 1.5 (7B GPTQ Int4) translation provider.

    Inherits all translation, placeholder, and glossary logic from
    LocalHYMTProvider.  Only model identity is overridden.
    """

    def __init__(
        self,
        model_id: str = MODEL_ID,
        backend: str = BACKEND,
        db_session: Session | None = None,
        project_id: int | None = None,
        timeout: float = 120.0,
    ):
        """Initialise LocalHYMT7BGPTQProvider.

        Args:
            model_id: HuggingFace model ID (default: tencent/HY-MT1.5-7B-GPTQ-Int4).
            backend: Must be "transformers_causal".
            db_session: Optional DB session for glossary postprocessing.
            project_id: Optional project ID for TM scope.
            timeout: Worker request timeout in seconds (7B is slower than 1.8B).
        """
        super().__init__(
            model_id=model_id,
            backend=backend,
            db_session=db_session,
            project_id=project_id,
            timeout=timeout,
        )

    @property
    def provider_id(self) -> str:
        return "local_hymt_7b_gptq"

    @property
    def display_name(self) -> str:
        return "Local HY-MT 1.5 7B GPTQ (Offline, Experimental)"
