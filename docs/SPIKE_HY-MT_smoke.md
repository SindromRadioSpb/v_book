# SPIKE-2: HY-MT Validation Results

> Model: `tencent/HY-MT1.5-1.8B` | Device: `cuda` | Dtype: `bfloat16`
> Model load time: **5.4s**

## Summary

| Metric | Value |
|--------|-------|
| Total tests | 5 |
| Passed | 5 (✅) |
| Failed | 0 (✅) |
| Avg latency | 1.27s |
| Min latency | 0.87s |
| Max latency | 2.15s |

## ✅ GO

| Criterion | Target | Actual | Status |
|-----------|--------|--------|--------|
| Avg latency | < 5.0s | 1.27s | ✅ |
| Pass rate | ≥ 75% | 100% | ✅ |
| Placeholder preservation | 100% | 100% | ✅ |
| Hallucination rate | < 10% | 0/5 | ✅ |

## Results by Category

### Basic (5/5 passed)

| ID | Source | Translation | Latency | Expected | Status |
|----|--------|------------|---------|----------|--------|
| basic_01 | שלום עולם | Шалом, всем миру! | 1.30s | мир | ✅ |
| basic_02 | הספרייה הלאומית של ישראל | Национальная библиотека Израиля | 0.87s | национальн, библиотек, израил | ✅ |
| basic_03 | מערכת ניהול מסדי נתונים יחסיים | Система управления относительными базами данных | 1.03s | систем, баз, данн | ✅ |
| basic_04 | הוראות שימוש במוצר זה חייבות להיקרא לפני... | Инструкции по использованию данного продукта необходимо проч... | 2.15s | инструкц, использован, перед | ✅ |
| basic_05 | לחץ על הכפתור כדי להמשיך | Нажмите на кнопку, чтобы продолжить. | 1.02s | нажмите, кнопку, продолжить | ✅ |

## Full Translations

### basic_01 [basic] — ✅ PASS
**Source**: `שלום עולם`
**Translation**: Шалом, всем миру!
**Latency**: 1.30s
**Expected (missing)**: ['привет', 'здравствуй']

### basic_02 [basic] — ✅ PASS
**Source**: `הספרייה הלאומית של ישראל`
**Translation**: Национальная библиотека Израиля
**Latency**: 0.87s

### basic_03 [basic] — ✅ PASS
**Source**: `מערכת ניהול מסדי נתונים יחסיים`
**Translation**: Система управления относительными базами данных
**Latency**: 1.03s

### basic_04 [basic] — ✅ PASS
**Source**: `הוראות שימוש במוצר זה חייבות להיקרא לפני ההפעלה`
**Translation**: Инструкции по использованию данного продукта необходимо прочитать перед началом его эксплуатации.
**Latency**: 2.15s

### basic_05 [basic] — ✅ PASS
**Source**: `לחץ על הכפתור כדי להמשיך`
**Translation**: Нажмите на кнопку, чтобы продолжить.
**Latency**: 1.02s

## Architecture Notes

### Worker design decision
Provider builds full prompt → `WorkerRequest.text` = prompt → worker does tokenize/generate/decode.
`WorkerRequest` protocol unchanged.

### `worker_process.py` changes required
```python
# New backend: "transformers_causal"
# New functions: _load_transformers_causal_model(), _translate_transformers_causal()
# Existing NLLB branches unchanged
```

### placeholder protection
**MANDATORY, not optional.** Every `LocalHYMTProvider.translate()` call must:
1. `protect_placeholders(source_text)` → protected text + mapping
2. Build prompt with protected text
3. Inference
4. `restore_placeholders(translation, mapping)` + validate missing

### terminology_mode
Default: `both` (prompt injection + `apply_glossary()` postprocess). Hardcoded, not a user toggle.
