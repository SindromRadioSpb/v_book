"""SPIKE-2: HY-MT Validation Script.

Standalone validation — НЕ зависит от HDLE codebase.
Проверяет 5 категорий / capabilities HY-MT до реализации провайдера:
  1. Basic he→ru translation + latency
  2. Terminology injection
  3. Placeholder / tag preservation (MANDATORY feature)
  4. Mixed-language handling
  5. Contextual translation

Inference path: tokenizer.apply_chat_template() — официальный vendor path HY-MT.
Raw tokenization НЕ используется (может давать нестабильный/деградированный вывод).

Usage (PowerShell):
    python scripts\\spike_hymt_validation.py `
        --model-id tencent/HY-MT1.5-1.8B `
        --device cuda `
        --dtype bfloat16 `
        --output-report docs\\SPIKE_HY-MT_results.md

    # Быстрый smoke (первые 5 кейсов):
    python scripts\\spike_hymt_validation.py --max-cases 5 ...

Requirements:
    pip install "transformers==4.56.0" torch accelerate
"""

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Force UTF-8 output on Windows console (Hebrew + Cyrillic)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ============================================================================
# HY-MT Prompt Builder
# ============================================================================

LANG_NAMES = {
    "he": "Russian",   # target language name for he→ru prompts
    "ru": "Russian",
    "en": "English",
}

TARGET_LANG_NAME = "Russian"  # pilot: he → ru


def build_basic_prompt(source_text: str) -> str:
    """Basic translation prompt (no extras)."""
    return (
        f"Translate the following segment into {TARGET_LANG_NAME}, "
        f"without additional explanation.\n\n"
        f"{source_text}"
    )


def build_terminology_prompt(source_text: str, term_pairs: list[tuple[str, str]]) -> str:
    """Translation prompt with terminology injection."""
    terms_block = "\n".join(
        f"{src} → {tgt}" for src, tgt in term_pairs
    )
    return (
        f"Translate the following segment into {TARGET_LANG_NAME}, "
        f"without additional explanation.\n\n"
        f"Use the following term translations:\n"
        f"{terms_block}\n\n"
        f"{source_text}"
    )


def build_placeholder_prompt(source_text: str) -> str:
    """Translation prompt with placeholder protection instruction."""
    return (
        f"Translate the following segment into {TARGET_LANG_NAME}, "
        f"without additional explanation. "
        f"Preserve all tokens that look like HDLE_PH_N (where N is a number) "
        f"exactly as they appear — do not translate or modify them.\n\n"
        f"{source_text}"
    )


def build_context_prompt(source_text: str, context: str) -> str:
    """Translation prompt with document context."""
    return (
        f"Translate the following segment into {TARGET_LANG_NAME}, "
        f"without additional explanation.\n\n"
        f"Document context: {context}\n\n"
        f"{source_text}"
    )


# ============================================================================
# Placeholder Protector
# ============================================================================

_PH_PATTERNS = [
    # {name}, {0}, {variable_name}
    (re.compile(r"\{[a-zA-Z0-9_]+\}"), "brace"),
    # %s, %d, %1$s
    (re.compile(r"%(?:\d+\$)?[sdif%]"), "printf"),
    # <TagName>, </TagName>, <Tag attr="..."/>
    (re.compile(r"<[^>]+>"), "xml_tag"),
    # [[placeholder]]
    (re.compile(r"\[\[[^\]]+\]\]"), "double_bracket"),
]


@dataclass
class ProtectedText:
    protected: str           # text with HDLE_PH_N substituted
    mapping: dict[str, str]  # {"HDLE_PH_1": original_value}


# Unicode directional marks inserted by RTL/LTR mixing (Hebrew context).
# These are invisible but break substring matching.
_DIR_MARKS = re.compile(
    r"[\u200b\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d\u202e"
    r"\u2066\u2067\u2068\u2069\ufeff]"
)


def _normalize_for_restore(text: str) -> str:
    """Strip Unicode directional/invisible marks that break substring search."""
    return _DIR_MARKS.sub("", text)


def protect_placeholders(text: str) -> ProtectedText:
    """Replace all placeholder patterns with ASCII-safe tokens.

    Token format: HDLE_PH_N (no quotes, no XML brackets — immune to RTL marks
    and quote-style changes by causal LLM tokenizers).
    """
    mapping: dict[str, str] = {}
    counter = [0]
    result = text

    def replace_match(m: re.Match, kind: str) -> str:
        counter[0] += 1
        token = f"HDLE_PH_{counter[0]}"
        mapping[token] = m.group(0)
        return token

    for pattern, kind in _PH_PATTERNS:
        result = pattern.sub(lambda m, k=kind: replace_match(m, k), result)

    return ProtectedText(protected=result, mapping=mapping)


def restore_placeholders(translated: str, mapping: dict[str, str]) -> tuple[str, list[str]]:
    """Restore original placeholders. Returns (restored_text, missing_tokens).

    Normalizes Unicode directional marks before searching — these are inserted
    by the model in Hebrew/RTL context and break naive substring matching.
    """
    # Normalize for matching (strip invisible dir marks)
    normalized = _normalize_for_restore(translated)

    result = normalized
    missing = []
    for token, original in mapping.items():
        norm_token = _normalize_for_restore(token)
        if norm_token in result:
            result = result.replace(norm_token, original)
        else:
            missing.append(token)
    return result, missing


# ============================================================================
# Test Cases
# ============================================================================

@dataclass
class TestCase:
    id: str
    category: str
    source: str
    prompt_fn: object          # callable → str
    prompt_kwargs: dict = field(default_factory=dict)
    expected_contains: list[str] = field(default_factory=list)  # русские слова/термины
    expected_placeholders: list[str] = field(default_factory=list)  # должны сохраниться


TEST_CASES = [
    # ── Basic Translation ────────────────────────────────────────────────────
    TestCase(
        id="basic_01",
        category="basic",
        source="שלום עולם",
        prompt_fn=build_basic_prompt,
        expected_contains=["мир", "привет", "здравствуй"],
    ),
    TestCase(
        id="basic_02",
        category="basic",
        source="הספרייה הלאומית של ישראל",
        prompt_fn=build_basic_prompt,
        expected_contains=["национальн", "библиотек", "израил"],
    ),
    TestCase(
        id="basic_03",
        category="basic",
        source="מערכת ניהול מסדי נתונים יחסיים",
        prompt_fn=build_basic_prompt,
        expected_contains=["систем", "баз", "данн"],
    ),
    TestCase(
        id="basic_04",
        category="basic",
        source="הוראות שימוש במוצר זה חייבות להיקרא לפני ההפעלה",
        prompt_fn=build_basic_prompt,
        expected_contains=["инструкц", "использован", "перед"],
    ),
    TestCase(
        id="basic_05",
        category="basic",
        source="לחץ על הכפתור כדי להמשיך",
        prompt_fn=build_basic_prompt,
        expected_contains=["нажмите", "кнопку", "продолжить"],
    ),

    # ── Terminology Injection ────────────────────────────────────────────────
    TestCase(
        id="term_01",
        category="terminology",
        source="מאגר הנתונים אינו פעיל",
        prompt_fn=build_terminology_prompt,
        prompt_kwargs={"term_pairs": [("מאגר נתונים", "база данных")]},
        expected_contains=["база данных"],
    ),
    TestCase(
        id="term_02",
        category="terminology",
        source="יש לפתוח את תפריט ההגדרות",
        prompt_fn=build_terminology_prompt,
        prompt_kwargs={"term_pairs": [("הגדרות", "настройки"), ("תפריט", "меню")]},
        expected_contains=["меню", "настройки"],
    ),
    TestCase(
        id="term_03",
        category="terminology",
        source="מנהל הרשת אחראי על אבטחת המידע",
        prompt_fn=build_terminology_prompt,
        prompt_kwargs={"term_pairs": [
            ("מנהל הרשת", "сетевой администратор"),
            ("אבטחת מידע", "информационная безопасность"),
        ]},
        expected_contains=["сетевой администратор", "информационная безопасность"],
    ),
    TestCase(
        id="term_04",
        category="terminology",
        source="קובץ הקוד מכיל שגיאת תחביר",
        prompt_fn=build_terminology_prompt,
        prompt_kwargs={"term_pairs": [
            ("קובץ קוד", "исходный файл"),
            ("שגיאת תחביר", "синтаксическая ошибка"),
        ]},
        # Accept inflected forms: "синтаксическ" covers ошибка/ошибки/ошибок
        expected_contains=["синтаксическ"],
    ),

    # ── Placeholder / Tag Preservation (MANDATORY) ──────────────────────────
    TestCase(
        id="placeholder_01",
        category="placeholder",
        source="שלום, {name}! ברוך הבא.",
        prompt_fn=build_placeholder_prompt,
        expected_contains=["Привет", "Добро пожаловать"],
        expected_placeholders=["{name}"],
    ),
    TestCase(
        id="placeholder_02",
        category="placeholder",
        source="לחץ על <כפתור>המשך</כפתור> כדי להמשיך",
        prompt_fn=build_placeholder_prompt,
        expected_contains=["Нажмите", "продолжить"],
        expected_placeholders=["<כפתור>", "</כפתור>"],
    ),
    TestCase(
        id="placeholder_03",
        category="placeholder",
        source="נותרו %d פריטים ב-%s",
        prompt_fn=build_placeholder_prompt,
        expected_contains=["остал"],
        expected_placeholders=["%d", "%s"],
    ),
    TestCase(
        id="placeholder_04",
        category="placeholder",
        source="הקובץ {filename} נשמר ב-{path}",
        prompt_fn=build_placeholder_prompt,
        expected_contains=["файл", "сохранён"],
        expected_placeholders=["{filename}", "{path}"],
    ),
    TestCase(
        id="placeholder_05",
        category="placeholder",
        source="שגיאה: <error code=\"404\">דף לא נמצא</error>",
        prompt_fn=build_placeholder_prompt,
        expected_contains=["Ошибка", "не найдена"],
        expected_placeholders=["<error code=\"404\">", "</error>"],
    ),

    # ── Mixed Language ───────────────────────────────────────────────────────
    TestCase(
        id="mixed_01",
        category="mixed_language",
        source="אנחנו משתמשים ב-database לאחסון נתונים",
        prompt_fn=build_basic_prompt,
        expected_contains=["database", "данн"],  # "database" may be preserved
    ),
    TestCase(
        id="mixed_02",
        category="mixed_language",
        source="יש להריץ את ה-script לאחר ה-deployment",
        prompt_fn=build_basic_prompt,
        # Model may translate or preserve — check for coherent Russian output
        expected_contains=["запуск", "скрипт", "script", "развёрт", "разверт", "deployment"],
    ),
    TestCase(
        id="mixed_03",
        category="mixed_language",
        source="הגדרת ה-API key בקובץ ה-config",
        prompt_fn=build_basic_prompt,
        expected_contains=["API", "config"],
    ),

    # ── Contextual Translation ───────────────────────────────────────────────
    TestCase(
        id="context_01",
        category="contextual",
        source="הפעל אותו",
        prompt_fn=build_context_prompt,
        prompt_kwargs={"context": "Technical documentation for server deployment"},
        expected_contains=["Запустите", "Включите", "Активируйте"],
    ),
    TestCase(
        id="context_02",
        category="contextual",
        source="לחץ עליו",
        prompt_fn=build_context_prompt,
        prompt_kwargs={"context": "User interface instructions for a button"},
        expected_contains=["Нажмите"],
    ),
]


# ============================================================================
# Model Runner
# ============================================================================


def load_model(model_id: str, device: str, dtype: str):
    """Load HY-MT model."""
    print(f"\n[Model] Loading {model_id} (device={device}, dtype={dtype})...")
    start = time.perf_counter()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    # Resolve dtype
    dtype_map = {
        "bfloat16": torch.bfloat16,
        "float16": torch.float16,
        "float32": torch.float32,
    }
    torch_dtype = dtype_map.get(dtype, torch.bfloat16)

    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        dtype=torch_dtype,
        device_map=device if device == "auto" else None,
        trust_remote_code=True,
    )

    if device not in ("auto",):
        model = model.to(device)

    elapsed = time.perf_counter() - start
    print(f"[Model] Loaded in {elapsed:.1f}s")

    # Print VRAM usage if CUDA
    if device == "cuda" or (device == "auto" and model.device.type == "cuda"):
        import torch
        allocated = torch.cuda.memory_allocated() / 1024**3
        reserved = torch.cuda.memory_reserved() / 1024**3
        print(f"[Model] VRAM: {allocated:.2f}GB allocated, {reserved:.2f}GB reserved")

    return model, tokenizer, elapsed


def run_inference(model, tokenizer, prompt: str) -> tuple[str, float]:
    """Run HY-MT inference via official vendor path (apply_chat_template).

    Uses tokenizer.apply_chat_template() per HY-MT model card.
    Falls back to raw tokenization if chat template not available.
    Returns (translated_text, inference_time_s).
    """
    import torch

    # ── Official HY-MT vendor path ─────────────────────────────────────────
    messages = [{"role": "user", "content": prompt}]

    chat_template_available = (
        hasattr(tokenizer, "apply_chat_template")
        and tokenizer.chat_template is not None
    )

    if chat_template_available:
        chat_text = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = tokenizer(chat_text, return_tensors="pt").to(model.device)
    else:
        # Fallback: raw prompt (exploratory only — results may differ)
        print("  [WARNING] Chat template not available — using raw tokenization (sub-optimal)")
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

    prompt_len = inputs["input_ids"].shape[1]

    # HY-MT generate() does not accept token_type_ids — filter to safe keys only
    generate_inputs = {
        k: v for k, v in inputs.items()
        if k in ("input_ids", "attention_mask")
    }

    start = time.perf_counter()
    with torch.no_grad():
        outputs = model.generate(
            **generate_inputs,
            max_new_tokens=512,
            do_sample=True,
            top_k=20,
            top_p=0.6,
            temperature=0.7,
            repetition_penalty=1.05,
            pad_token_id=tokenizer.eos_token_id,
        )
    elapsed = time.perf_counter() - start

    new_tokens = outputs[0][prompt_len:]
    result = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
    return result, elapsed


# ============================================================================
# Test Runner
# ============================================================================


@dataclass
class TestResult:
    case_id: str
    category: str
    source: str
    prompt: str
    translation: str
    latency_s: float
    expected_found: list[str]
    expected_missing: list[str]
    placeholders_ok: bool
    placeholders_missing: list[str]
    hallucination_detected: bool
    passed: bool
    notes: str = ""


HALLUCINATION_PATTERNS = [
    # English explanatory drift
    re.compile(r"\bI (see|understand|notice|will|can)\b", re.I),
    re.compile(r"\bTranslation:\b", re.I),
    re.compile(r"\bNote:\b", re.I),
    re.compile(r"\bSure,?\b", re.I),
    re.compile(r"\bHere is the translation\b", re.I),
    re.compile(r"\bCertainly\b", re.I),
    re.compile(r"\bOf course\b", re.I),
    re.compile(r"\bAs requested\b", re.I),
    # Russian explanatory drift
    re.compile(r"Перевод\s*:", re.I),
    re.compile(r"Вот\s+(перевод|результат)", re.I),
    re.compile(r"Конечно[,!]", re.I),
    re.compile(r"Пожалуйста[,!]", re.I),
    re.compile(r"Я\s+(вижу|понимаю|перевожу|могу)", re.I),
    re.compile(r"Примечание\s*:", re.I),
    re.compile(r"Примечание:", re.I),
]

# NOTE: Russian drift detection still requires visual inspection of the report.
# Automated patterns cover common cases but are NOT exhaustive.


def detect_hallucination(text: str) -> bool:
    return any(p.search(text) for p in HALLUCINATION_PATTERNS)


def run_test_case(
    case: TestCase,
    model,
    tokenizer,
) -> TestResult:
    # Build prompt
    if case.prompt_kwargs:
        prompt = case.prompt_fn(case.source, **case.prompt_kwargs)
    else:
        prompt = case.prompt_fn(case.source)

    # For placeholder cases: protect first, embed protected text in prompt
    has_placeholders = bool(case.expected_placeholders)
    protected = None
    if has_placeholders:
        protected = protect_placeholders(case.source)
        # Rebuild prompt with protected text
        if case.prompt_kwargs:
            prompt = case.prompt_fn(protected.protected, **case.prompt_kwargs)
        else:
            prompt = case.prompt_fn(protected.protected)

    # Inference
    translation, latency = run_inference(model, tokenizer, prompt)

    # Restore placeholders if applicable
    if has_placeholders and protected:
        translation, ph_missing = restore_placeholders(translation, protected.mapping)
        # Check which expected placeholders are present in final output
        ph_results_missing = [
            ph for ph in case.expected_placeholders
            if ph not in translation
        ]
        placeholders_ok = len(ph_results_missing) == 0
    else:
        ph_missing = []
        ph_results_missing = []
        placeholders_ok = True

    # Check expected_contains (case-insensitive, partial match)
    translation_lower = translation.lower()
    expected_found = [e for e in case.expected_contains if e.lower() in translation_lower]
    expected_missing = [e for e in case.expected_contains if e.lower() not in translation_lower]

    hallucination = detect_hallucination(translation)

    # Determine pass/fail
    # Placeholder cases: MUST preserve all placeholders
    if has_placeholders:
        passed = placeholders_ok and not hallucination
    else:
        # Basic/terminology/mixed: at least 1 expected term found
        passed = len(expected_found) >= 1 and not hallucination

    return TestResult(
        case_id=case.id,
        category=case.category,
        source=case.source,
        prompt=prompt,
        translation=translation,
        latency_s=latency,
        expected_found=expected_found,
        expected_missing=expected_missing,
        placeholders_ok=placeholders_ok,
        placeholders_missing=ph_results_missing,
        hallucination_detected=hallucination,
        passed=passed,
    )


# ============================================================================
# Report Generator
# ============================================================================


def generate_report(
    results: list[TestResult],
    model_id: str,
    device: str,
    dtype: str,
    model_load_time: float,
) -> str:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed

    latencies = [r.latency_s for r in results]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    max_latency = max(latencies) if latencies else 0
    min_latency = min(latencies) if latencies else 0

    by_category: dict[str, list[TestResult]] = {}
    for r in results:
        by_category.setdefault(r.category, []).append(r)

    lines = [
        "# SPIKE-2: HY-MT Validation Results",
        "",
        f"> Model: `{model_id}` | Device: `{device}` | Dtype: `{dtype}`",
        f"> Model load time: **{model_load_time:.1f}s**",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total tests | {total} |",
        f"| Passed | {passed} ({'✅' if passed == total else '⚠️'}) |",
        f"| Failed | {failed} ({'✅' if failed == 0 else '❌'}) |",
        f"| Avg latency | {avg_latency:.2f}s |",
        f"| Min latency | {min_latency:.2f}s |",
        f"| Max latency | {max_latency:.2f}s |",
        "",
    ]

    # GO/NO-GO verdict
    avg_ok = avg_latency < 5.0
    pass_rate = passed / total if total > 0 else 0
    quality_ok = pass_rate >= 0.75

    placeholder_results = [r for r in results if r.category == "placeholder"]
    ph_all_ok = all(r.placeholders_ok for r in placeholder_results)
    hallucinations = sum(1 for r in results if r.hallucination_detected)
    hall_ok = hallucinations / total < 0.1 if total > 0 else True

    verdict_ok = avg_ok and quality_ok and ph_all_ok and hall_ok
    verdict = "## ✅ GO" if verdict_ok else "## ⚠️ GO WITH ISSUES" if pass_rate >= 0.5 else "## ❌ NO-GO"

    lines += [
        verdict,
        "",
        f"| Criterion | Target | Actual | Status |",
        f"|-----------|--------|--------|--------|",
        f"| Avg latency | < 5.0s | {avg_latency:.2f}s | {'✅' if avg_ok else '❌'} |",
        f"| Pass rate | ≥ 75% | {pass_rate*100:.0f}% | {'✅' if quality_ok else '❌'} |",
        f"| Placeholder preservation | 100% | {'100%' if ph_all_ok else 'FAILED'} | {'✅' if ph_all_ok else '❌'} |",
        f"| Hallucination rate | < 10% | {hallucinations}/{total} | {'✅' if hall_ok else '❌'} |",
        "",
    ]

    # By category
    lines.append("## Results by Category")
    lines.append("")

    for category, cat_results in by_category.items():
        cat_passed = sum(1 for r in cat_results if r.passed)
        lines.append(f"### {category.title()} ({cat_passed}/{len(cat_results)} passed)")
        lines.append("")
        lines.append("| ID | Source | Translation | Latency | Expected | Status |")
        lines.append("|----|--------|------------|---------|----------|--------|")

        for r in cat_results:
            src_short = r.source[:40] + "..." if len(r.source) > 40 else r.source
            tr_short = r.translation[:60] + "..." if len(r.translation) > 60 else r.translation
            found = ", ".join(r.expected_found) or "-"
            status = "✅" if r.passed else "❌"
            if r.hallucination_detected:
                status += " HALLUCINATION"
            if not r.placeholders_ok:
                status += f" PH_MISSING:{r.placeholders_missing}"
            lines.append(f"| {r.case_id} | {src_short} | {tr_short} | {r.latency_s:.2f}s | {found} | {status} |")

        lines.append("")

    # Full translations
    lines.append("## Full Translations")
    lines.append("")
    for r in results:
        lines.append(f"### {r.case_id} [{r.category}] — {'✅ PASS' if r.passed else '❌ FAIL'}")
        lines.append(f"**Source**: `{r.source}`")
        lines.append(f"**Translation**: {r.translation}")
        lines.append(f"**Latency**: {r.latency_s:.2f}s")
        if r.expected_missing:
            lines.append(f"**Expected (missing)**: {r.expected_missing}")
        if not r.placeholders_ok:
            lines.append(f"**⚠️ Placeholders missing**: {r.placeholders_missing}")
        if r.hallucination_detected:
            lines.append("**⚠️ HALLUCINATION DETECTED**")
        lines.append("")

    # Architecture notes
    lines += [
        "## Architecture Notes",
        "",
        "### Worker design decision",
        "Provider builds full prompt → `WorkerRequest.text` = prompt → worker does tokenize/generate/decode.",
        "`WorkerRequest` protocol unchanged.",
        "",
        "### `worker_process.py` changes required",
        "```python",
        '# New backend: "transformers_causal"',
        "# New functions: _load_transformers_causal_model(), _translate_transformers_causal()",
        "# Existing NLLB branches unchanged",
        "```",
        "",
        "### placeholder protection",
        "**MANDATORY, not optional.** Every `LocalHYMTProvider.translate()` call must:",
        "1. `protect_placeholders(source_text)` → protected text + mapping",
        "2. Build prompt with protected text",
        "3. Inference",
        "4. `restore_placeholders(translation, mapping)` + validate missing",
        "",
        "### terminology_mode",
        "Default: `both` (prompt injection + `apply_glossary()` postprocess). Hardcoded, not a user toggle.",
        "",
    ]

    return "\n".join(lines)


# ============================================================================
# Main
# ============================================================================


def parse_args():
    parser = argparse.ArgumentParser(description="SPIKE-2: HY-MT Validation")
    parser.add_argument("--model-id", default="tencent/HY-MT1.5-1.8B")
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu", "auto"])
    parser.add_argument("--dtype", default="bfloat16",
                        choices=["bfloat16", "float16", "float32"])
    parser.add_argument("--output-report", default=None,
                        help="Path to save markdown report")
    parser.add_argument("--max-cases", type=int, default=None,
                        help="Limit number of test cases (for quick smoke)")
    return parser.parse_args()


def main():
    args = parse_args()

    print("=" * 60)
    print("SPIKE-2: HY-MT Validation")
    print(f"  Model: {args.model_id}")
    print(f"  Device: {args.device}")
    print(f"  Dtype: {args.dtype}")
    print("=" * 60)

    # Validate torch + cuda
    try:
        import torch
        if args.device == "cuda" and not torch.cuda.is_available():
            print("WARNING: CUDA not available, falling back to CPU")
            args.device = "cpu"
        if args.device == "cuda":
            print(f"  CUDA: {torch.cuda.get_device_name(0)}")
            total_vram = torch.cuda.get_device_properties(0).total_memory / 1024**3
            print(f"  VRAM: {total_vram:.1f}GB total")
    except ImportError:
        print("ERROR: torch not installed. Run: pip install torch")
        sys.exit(1)

    # Load model
    try:
        model, tokenizer, load_time = load_model(args.model_id, args.device, args.dtype)
    except Exception as e:
        print(f"\nERROR: Failed to load model: {e}")
        print("\nTo download the model:")
        print(f"  python -c \"from huggingface_hub import snapshot_download; "
              f"snapshot_download('{args.model_id}')\"")
        sys.exit(1)

    # Select test cases
    cases = TEST_CASES
    if args.max_cases:
        cases = cases[:args.max_cases]

    print(f"\nRunning {len(cases)} test cases...")
    print("-" * 60)

    results = []
    for i, case in enumerate(cases, 1):
        print(f"[{i:2d}/{len(cases)}] {case.id} ({case.category}): {case.source[:40]}...")
        try:
            result = run_test_case(case, model, tokenizer)
            status = "✅" if result.passed else "❌"
            ph_note = " ⚠️PH" if not result.placeholders_ok else ""
            hall_note = " ⚠️HALL" if result.hallucination_detected else ""
            print(f"       {status}{ph_note}{hall_note} {result.latency_s:.2f}s → {result.translation[:60]}")
            results.append(result)
        except Exception as e:
            print(f"       ERROR: {e}")
            results.append(TestResult(
                case_id=case.id,
                category=case.category,
                source=case.source,
                prompt="",
                translation=f"[ERROR: {e}]",
                latency_s=0,
                expected_found=[],
                expected_missing=case.expected_contains,
                placeholders_ok=False,
                placeholders_missing=case.expected_placeholders,
                hallucination_detected=False,
                passed=False,
                notes=str(e),
            ))

    # Generate report
    report = generate_report(results, args.model_id, args.device, args.dtype, load_time)

    # Save report
    if args.output_report:
        output_path = Path(args.output_report)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
        print(f"\nReport saved: {output_path}")

    # Print summary to console
    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    latencies = [r.latency_s for r in results]
    avg_lat = sum(latencies) / len(latencies) if latencies else 0
    print(f"RESULTS: {passed}/{total} passed | avg latency: {avg_lat:.2f}s")

    # Collect metrics for strict GO/NO-GO
    ph_results = [r for r in results if r.category == "placeholder"]
    ph_ok = all(r.placeholders_ok for r in ph_results) if ph_results else True
    hallucinations = sum(1 for r in results if r.hallucination_detected)

    if ph_results:
        print(f"PLACEHOLDER PRESERVATION: {'✅ OK' if ph_ok else '❌ FAILED'}")

    # Strict GO/NO-GO: ALL four criteria must pass
    pass_rate = passed / total if total > 0 else 0
    latency_ok = avg_lat < 5.0
    quality_ok = pass_rate >= 0.75
    hall_rate = hallucinations / total if total > 0 else 0
    hall_ok = hall_rate < 0.10

    criterion_results = [
        ("latency < 5.0s", latency_ok, f"{avg_lat:.2f}s"),
        ("pass rate >= 75%", quality_ok, f"{pass_rate*100:.0f}%"),
        ("placeholder 100%", ph_ok if ph_results else True, "N/A" if not ph_results else ("OK" if ph_ok else "FAILED")),
        ("hallucination < 10%", hall_ok, f"{hall_rate*100:.0f}%"),
    ]

    print("\nGO/NO-GO criteria:")
    all_go = True
    for name, ok, value in criterion_results:
        mark = "✅" if ok else "❌"
        print(f"  {mark} {name}: {value}")
        if not ok:
            all_go = False

    verdict = "✅ GO" if all_go else "❌ NO-GO (see criteria above)"
    print(f"\nVERDICT: {verdict}")
    print("=" * 60)

    # Exit code 0 only if ALL criteria pass
    return 0 if all_go else 1


if __name__ == "__main__":
    sys.exit(main())
