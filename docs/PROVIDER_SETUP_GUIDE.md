# MT Provider Setup Guide

**Audience:** End users
**Date:** 2026-02-08
**Version:** 1.2 (P1 Translation Pro + UI Integration)

---

## Overview

HDLE Premium supports multiple **Machine Translation (MT) providers** for automatic translation. This guide shows you how to set up and configure MT providers.

**Available Providers:**
- **DeepL** (recommended for quality)
- **LibreTranslate** (free, open-source)
- **Google Translate** (via Cloud Translation API)
- **Microsoft Translator** (via Azure Cognitive Services)
- **Mock** (for testing, no API key needed)

---

## Quick Start

### 1. Get API Key

Each provider requires an API key (except LibreTranslate and Mock).

#### DeepL
1. Go to https://www.deepl.com/pro-api
2. Create account (free tier: 500,000 chars/month)
3. Copy **API key** from dashboard

#### Google Translate
1. Go to https://cloud.google.com/translate
2. Create Google Cloud project
3. Enable Cloud Translation API
4. Create **API key** in Credentials

#### Microsoft Translator
1. Go to https://azure.microsoft.com/services/cognitive-services/translator/
2. Create Azure account (free tier: 2M chars/month)
3. Create **Translator resource**
4. Copy **API key** from Keys and Endpoint

#### LibreTranslate
- **No API key needed** for public instance (libretranslate.com)
- OR: Self-host LibreTranslate (https://github.com/LibreTranslate/LibreTranslate)

---

### 2. Using Translation in UI

**NEW (2026-02-08):** HDLE Premium now has dedicated UI for translating text!

#### Quick Translation

1. **Open Menu:**
   - Menu: `Tools → Translation → Translate Text...`
   - Keyboard: `Ctrl+Alt+T`

2. **Enter Text:**
   - Select source language (e.g., English)
   - Select target language (e.g., Hebrew)
   - Type or paste text to translate

3. **Click "Translate"**
   - Translation runs in background (UI doesn't freeze)
   - Progress indicator shows while translating
   - Translated text appears in output field

4. **View Metadata:**
   - Provider used: `local_nllb` (Local MT) or `deepl` (Cloud MT)
   - Cache hit: `Yes ✓` (instant) or `No` (fresh translation)
   - Glossary: `Yes ✓` if approved terms applied
   - Latency: Translation time in milliseconds
   - Model: Model ID if using Local MT

5. **Copy Result:**
   - Click "Copy to Clipboard" button
   - Or: Select text and `Ctrl+C`

**Example:**
```
Source (English): "database management system"
Target (Hebrew): "מערכת ניהול מסד נתונים"

Metadata: Provider: local_nllb | Source: mt | Cache Hit: No | Latency: 1234 ms | Model: facebook/nllb-200-distilled-1.3B
```

#### Configure Providers

1. **Open Settings:**
   - Menu: `Tools → Translation → MT Provider Settings...`
   - Keyboard: `Ctrl+Alt+P`

2. **Enable/Disable Providers:**
   - Check/uncheck providers in list
   - Local NLLB: Requires model installation (see below)
   - Cloud providers: Require API keys

3. **Set Provider Chain:**
   - Drag providers to reorder priority
   - Example: `Local NLLB → DeepL → LibreTranslate`
   - First provider tried first, fallback to next on error

4. **Configure Rate Limits:**
   - Requests per minute (default: 60)
   - Local providers: Unlimited (9999)

5. **Save Settings:**
   - Click "Save" or "OK"
   - Settings persist across sessions

---

### 3. Configure in HDLE Premium (Advanced)

#### Option A: Settings UI (RECOMMENDED)

1. **Open Settings**
   - Menu: `Settings → MT Providers`
   - Keyboard: `Ctrl+,` (Settings) → MT Providers tab

2. **Add Provider**
   - Click `Add Provider`
   - Select provider type (DeepL, Google, etc.)
   - Enter API key
   - Click `Test Connection` to verify
   - Click `Save`

3. **Configure Fallback Chain**
   - Drag providers to reorder (first = primary)
   - Example: DeepL → LibreTranslate → Google
   - If DeepL fails, falls back to LibreTranslate automatically

4. **Advanced Settings** (optional)
   - Rate limit: requests per minute (default: 60)
   - Circuit breaker: fail threshold (default: 3)
   - Cache TTL: cache expiration days (default: 7)

#### Option B: Manual Configuration (ADVANCED)

**⚠️ WARNING:** Only for advanced users. Incorrect configuration may expose API keys.

1. **Store API key securely:**
   ```python
   from app.infra.security import CredentialStore

   cred_store = CredentialStore()
   cred_store.store_credential("mt_provider_deepl_api_key", "YOUR_API_KEY_HERE")
   ```

2. **Edit settings file:**
   - Location (Linux): `~/.config/HDLE_Premium/HDLE_Premium.conf`
   - Location (Windows): `%APPDATA%\HDLE_Premium\HDLE_Premium.ini`
   - Location (macOS): `~/Library/Preferences/com.HDLE_Premium.HDLE_Premium.plist`

3. **Add provider configuration:**
   ```ini
   [mt/provider/deepl]
   enabled=true
   requests_per_min=60

   [mt]
   provider_chain=["deepl", "libretranslate"]
   ```

---

## Provider-Specific Setup

### DeepL

**API Key Location:** https://www.deepl.com/account/summary

**API Endpoint:**
- Free tier: `https://api-free.deepl.com/v2/translate`
- Pro tier: `https://api.deepl.com/v2/translate`

**Supported Languages:**
- Source: EN, DE, FR, ES, PT, IT, NL, PL, RU, JA, ZH
- Target: EN, DE, FR, ES, PT, IT, NL, PL, RU, JA, ZH, BG, CS, DA, EL, ET, FI, HU, LT, LV, RO, SK, SL, SV

**Glossary Support:** ✅ Yes (TSV format)

**Rate Limits:**
- Free tier: 500,000 chars/month
- Pro tier: unlimited (pay-as-you-go)

**Configuration:**
```ini
[mt/provider/deepl]
enabled=true
api_key=<stored in CredentialStore>
requests_per_min=60
api_tier=free  # or "pro"
```

---

### LibreTranslate

**Public Instance:** https://libretranslate.com/ (free, no API key)

**Self-Hosted:** https://github.com/LibreTranslate/LibreTranslate

**Supported Languages:**
- 30+ languages (EN, ES, FR, DE, IT, PT, RU, JA, ZH, AR, HI, etc.)
- Full list: https://libretranslate.com/languages

**Glossary Support:** ✅ Yes (JSON format)

**Rate Limits:**
- Public instance: Limited (use sparingly)
- Self-hosted: No limit

**Configuration:**
```ini
[mt/provider/libretranslate]
enabled=true
api_url="https://libretranslate.com/"  # or your self-hosted URL
requests_per_min=30  # Lower for public instance
```

---

### Google Translate

**API Key Location:** Google Cloud Console → Credentials

**API Endpoint:** https://translation.googleapis.com/language/translate/v2

**Supported Languages:**
- 100+ languages
- Full list: https://cloud.google.com/translate/docs/languages

**Glossary Support:** ✅ Yes (via Glossary API, complex setup)

**Rate Limits:**
- Default: 500,000 chars/day
- Configurable in Google Cloud Console

**Pricing:**
- $20 per 1M chars (as of 2026)

**Configuration:**
```ini
[mt/provider/google]
enabled=true
api_key=<stored in CredentialStore>
requests_per_min=60
```

---

### Microsoft Translator

**API Key Location:** Azure Portal → Translator resource → Keys and Endpoint

**API Endpoint:** `https://api.cognitive.microsofttranslator.com/translate?api-version=3.0`

**Supported Languages:**
- 90+ languages
- Full list: https://docs.microsoft.com/azure/cognitive-services/translator/language-support

**Glossary Support:** ✅ Yes (via Custom Translator)

**Rate Limits:**
- Free tier: 2M chars/month
- Standard tier: unlimited (pay-as-you-go)

**Pricing:**
- Free tier: 2M chars/month
- Standard: $10 per 1M chars (as of 2026)

**Configuration:**
```ini
[mt/provider/microsoft]
enabled=true
api_key=<stored in CredentialStore>
requests_per_min=60
api_region="global"  # or specific region (e.g., "westus2")
```

---

## Fallback Chain

**What is a fallback chain?**
- If primary provider fails → automatically tries next provider
- Example: DeepL → LibreTranslate → Google

**When does fallback occur?**
- Network error (timeout, connection failed)
- Rate limit exceeded (429 error)
- Quota exceeded (402, 403 errors)
- Server error (500, 502, 503, 504 errors)
- Invalid API key (401, 403 auth errors)

**Recommended Chains:**

| Use Case | Chain | Rationale |
|----------|-------|-----------|
| **Quality-first** | DeepL → Google → LibreTranslate | Best quality, expensive → free fallback |
| **Cost-aware** | LibreTranslate → DeepL | Free first, paid fallback |
| **Privacy-focused** | LibreTranslate (self-hosted) only | All data stays on your server |
| **High-volume** | Google → Microsoft | Both have high rate limits |

---

## Glossary Integration

**What is a glossary?**
- Custom term list (source → target)
- Ensures consistent translation of domain-specific terms
- Example: "מערכת" → "система" (not "system")

**How to populate glossary:**
1. Approve terms in **Terms** panel (right-click → Approve)
2. Pin translations in **Term Clusters** (right-click → Pin Translation)
3. Import dictionary via **Import** wizard

**Glossary format (per provider):**
- **DeepL:** TSV (tab-separated values)
- **LibreTranslate:** JSON dict `{"source": "target"}`
- **Google:** JSON list `[{"source": "...", "target": "..."}]`
- **Microsoft:** Custom Translator (complex, not yet supported)

**Automatic glossary:**
- HDLE Premium automatically builds glossary from approved terms
- Sends glossary with each translation request
- If provider doesn't support glossary → logs warning (glossary ignored)

---

## Cache Configuration

**What is MT cache?**
- Stores previous translations to avoid redundant API calls
- Saves money and improves speed

**Cache key includes:**
- Source text (normalized)
- Source language + target language
- Provider ID (e.g., "deepl")
- Glossary hash (invalidates cache if glossary changes)
- Provider model version

**Cache TTL (time-to-live):**
- Default: 7 days
- Configurable: `mt/cache_ttl_days`

**Cache metrics:**
- Hit rate target: >80% on second run
- View metrics: Settings → MT Providers → Cache Stats

**Clear cache:**
- Settings → MT Providers → Clear Cache
- Or manually: Delete `mt_cache` table rows

---

## Troubleshooting

### "MT provider failed: AUTH"

**Cause:** Invalid API key

**Solution:**
1. Verify API key in provider dashboard
2. Re-enter API key in Settings → MT Providers
3. Click `Test Connection` to verify

### "MT provider failed: RATE_LIMIT"

**Cause:** Exceeded rate limit (requests per minute)

**Solution:**
1. Lower `requests_per_min` in Settings
2. Or: Upgrade to higher tier (DeepL Pro, Google Standard, etc.)
3. Fallback chain will automatically try next provider

### "MT provider failed: QUOTA"

**Cause:** Exceeded monthly quota (free tier)

**Solution:**
1. Upgrade to paid tier
2. Or: Use free fallback (LibreTranslate)
3. Or: Wait until next month (quota resets)

### "MT provider failed: NETWORK"

**Cause:** Network connection failed or timeout

**Solution:**
1. Check internet connection
2. Check firewall settings (allow outbound HTTPS)
3. Try again later (fallback chain will retry next provider)

### "Circuit breaker OPEN"

**Cause:** Provider failed 3 times in a row → circuit breaker activated

**Solution:**
1. Wait 60 seconds (circuit breaker cooldown)
2. Fix underlying issue (API key, network, quota)
3. Circuit breaker will automatically retry (HALF_OPEN → CLOSED)

### "Cache hit rate < 80%"

**Cause:** Cache not being used effectively

**Solution:**
1. Check if glossary changed (invalidates cache)
2. Check if source text is normalized consistently
3. Check cache TTL (too short → frequent expiration)
4. View cache stats: Settings → MT Providers → Cache Stats

---

## Security and Privacy

### API Key Storage

**Secure storage:**
- API keys encrypted at rest (AES-256-GCM)
- Master key stored in OS keyring (Windows DPAPI, macOS Keychain, Linux Secret Service)
- Never stored in plaintext

**Access control:**
- Only HDLE Premium can decrypt API keys
- User must have OS credentials (login password)

### Data Privacy

**What data is sent to MT providers?**
- Source text (segments to translate)
- Source language + target language
- Glossary (approved terms only)

**What data is NOT sent?**
- Document metadata (title, author, etc.)
- User data (name, email, etc.)
- Full document (only segments that need translation)

**Provider privacy policies:**
- **DeepL:** https://www.deepl.com/privacy
- **Google:** https://cloud.google.com/terms/cloud-privacy-notice
- **Microsoft:** https://privacy.microsoft.com/en-us/privacystatement
- **LibreTranslate:** Self-hosted = full control, public instance = see https://libretranslate.com/

**Recommendations:**
- For sensitive data: Use LibreTranslate (self-hosted)
- For public data: Any provider is fine
- Always review provider privacy policy before use

---

## Local MT Providers (Offline Translation)

### Overview

**What are Local MT Providers?**
- Translation models that run **entirely offline** on your computer
- No API keys, no internet connection, no data sent to third parties
- Free to use (after one-time model download)
- Ideal for sensitive data, high-volume translation, or offline work

**Available Models:**
- **Local NLLB-200** (facebook/nllb-200-distilled-1.3B)
  - 200+ languages
  - 1.3B parameters (distilled model)
  - Backend: CTranslate2 (fast, CPU-optimized)
  - License: CC-BY-NC 4.0 (free for internal use)
  - Model size: ~2.6 GB disk space

**System Requirements:**
- RAM: 4-8 GB free (model loads into memory)
- Disk: 3-5 GB per model (stored on J: drive via junction)
- CPU: Modern multi-core CPU recommended (no GPU required)
- OS: Windows, Linux, macOS

---

### Installation

#### Step 1: Check Disk Space

Local models are stored at `J:\HDLE\models` (Windows) via junction from `%LOCALAPPDATA%\HDLE\models`.

**Verify junction:**
```powershell
# Check if junction exists
Test-Path "$env:LOCALAPPDATA\HDLE\models"

# Check target (should point to J:\HDLE\models)
cmd /c dir "$env:LOCALAPPDATA\HDLE\models" | Select-String "JUNCTION"
```

**Create junction (if needed):**
```powershell
# Create target directory on J: drive
$dst = "J:\HDLE\models"
New-Item -ItemType Directory -Force -Path $dst

# Create junction from C: to J:
$src = Join-Path $env:LOCALAPPDATA "HDLE\models"
cmd /c mklink /J "$src" "$dst"
```

#### Step 2: List Available Models

```bash
python scripts/install_local_mt_model.py --show-models
```

**Output:**
```
Available models:
1. facebook/nllb-200-distilled-1.3B (Backend: ctranslate2)
   - Languages: 200+ (Hebrew, Russian, English, etc.)
   - Size: ~2.6 GB
   - License: CC-BY-NC 4.0
```

#### Step 3: Install Model

**Install NLLB with CTranslate2 backend:**
```bash
python scripts/install_local_mt_model.py \
  --model facebook/nllb-200-distilled-1.3B \
  --backend ctranslate2 \
  --quantization int8
```

**Installation process:**
1. Downloads model from Hugging Face (~2.6 GB)
2. Converts to CTranslate2 format (faster inference)
3. Applies int8 quantization (2x speedup, minimal quality loss)
4. Stores at `J:\HDLE\models\facebook_nllb-200-distilled-1.3B_ctranslate2\`

**Estimated time:**
- Download: 5-15 minutes (depending on internet speed)
- Conversion: 2-5 minutes
- Total: 10-20 minutes

#### Step 4: Verify Installation

```bash
python scripts/install_local_mt_model.py --list
```

**Expected output:**
```
Installed models:
✓ facebook/nllb-200-distilled-1.3B (ctranslate2)
  Path: J:\HDLE\models\facebook_nllb-200-distilled-1.3B_ctranslate2\
  Size: 2.6 GB
  Status: Ready
```

---

### Configuration

#### Enable Local Provider in HDLE Premium

1. **Open Settings**
   - Menu: `Settings → MT Providers`
   - Or: `Ctrl+,` → MT Providers tab

2. **Add Local NLLB Provider**
   - Provider should auto-detect if model installed
   - If not visible: Restart HDLE Premium

3. **Configure Fallback Chain**
   - Drag `Local NLLB` to desired position
   - **Recommended:** Put local provider first (fastest, free)
   - Example chain: `Local NLLB → DeepL → LibreTranslate`

4. **Test Translation**
   - Open a document with Hebrew text
   - Select segment → Request translation
   - Check provider ID in result (should show `local_nllb`)

**Settings Keys (Advanced):**
```ini
[mt/provider/local_nllb]
enabled=true
timeout=30.0  # Worker timeout in seconds
```

---

### How It Works

**Translation Pipeline:**
```
Input text
  ↓
1. Sentence segmentation (split long texts)
  ↓
2. Worker process (model inference via CTranslate2)
  ↓
3. Glossary postprocess (apply approved TM terms)
  ↓
4. Reassemble segments
  ↓
Output translation
```

**Sentence Segmentation:**
- NLLB quality degrades on inputs >512 tokens
- Automatically splits text at sentence boundaries
- Preserves separators (`.`, `!`, `?`, newlines)
- Merges short segments to avoid fragmentation

**Glossary Postprocess:**
- Queries approved terms from Translation Memory (status='approved')
- Replaces MT output with approved translations (exact match)
- Example: MT says "система" → Glossary forces "מערכת" if approved
- Increases consistency and domain accuracy

**Worker Process:**
- Model runs in separate process (no UI blocking)
- Timeout: 30 seconds (configurable)
- IPC via multiprocessing queues (spawn context for Windows)

---

### Performance

**Translation Speed:**
- Short text (1-2 sentences): 0.5-2 seconds
- Medium text (1 paragraph): 2-5 seconds
- Long text (1 page): 5-15 seconds

**Factors affecting speed:**
- CPU cores (more cores = faster)
- Quantization (int8 = 2x faster than float32)
- Text length (longer = more segments)
- RAM availability (swapping = slower)

**Optimization Tips:**
1. Use int8 quantization (minimal quality loss)
2. Close other applications (free up RAM)
3. Keep texts under 1000 words per request
4. Use cache (second translation of same text = instant)

---

### Glossary Integration

**How glossary works with Local MT:**
1. You approve terms in **Terms** panel (right-click → Approve)
2. Local MT translates text using NLLB model
3. **Postprocess:** Replaces MT output with approved terms (exact match)
4. Final translation combines MT + glossary

**Example:**
- Source: "המערכת עובדת טוב" (Hebrew)
- NLLB output: "система работает хорошо" (Russian)
- Approved term: "המערכת" → "система" (exact match)
- Final: "система работает хорошо" (applied glossary term)

**Matching Rules:**
- Exact match only (case-insensitive, whitespace-normalized)
- Project scope: Uses approved terms from current project + global
- Conflict resolution: Higher priority_score wins

**View applied terms:**
- Hover over translation → Shows `applied_terms_count` in metadata
- Logs show: "Applied 3 glossary terms (out of 5 segments)"

---

### Troubleshooting

#### "Model not installed: facebook/nllb-200-distilled-1.3B"

**Cause:** Model files not found at expected path

**Solution:**
1. Verify junction: `Test-Path "$env:LOCALAPPDATA\HDLE\models"`
2. Check target: `ls J:\HDLE\models`
3. Reinstall model: `python scripts/install_local_mt_model.py --model ...`
4. Check logs: `M:\V_book\HDLE\logs\hdle_premium.log`

#### "Worker timeout after 30 seconds"

**Cause:** Model inference taking too long (RAM swapping, CPU overload)

**Solution:**
1. Close other applications (free up RAM)
2. Reduce text length (split into smaller chunks)
3. Increase timeout: Settings → `mt/provider/local_nllb/timeout=60.0`
4. Check RAM usage: Task Manager → Performance → Memory

#### "Translation slower than expected"

**Cause:** Not using int8 quantization, or CPU thermal throttling

**Solution:**
1. Reinstall with int8: `--quantization int8` (2x speedup)
2. Check CPU temperature (thermal throttling = slower)
3. Verify backend: Should use `ctranslate2` (not `transformers`)
4. Check model path: Should be `..._ctranslate2\` not `..._transformers\`

#### "Glossary terms not applied"

**Cause:** Terms not approved, or language pair mismatch

**Solution:**
1. Verify term status: Open Terms panel → Check status='approved'
2. Check language pair: Term must match `src_lang`/`tgt_lang` exactly
3. Verify normalization: Glossary uses lowercase, whitespace-normalized matching
4. Check logs: "Applied X glossary terms" (should show match count)

#### "Worker process crashed"

**Cause:** Out of memory, or corrupted model files

**Solution:**
1. Check RAM: Model needs 4-8 GB free
2. Reinstall model: Delete `J:\HDLE\models\...` and reinstall
3. Check logs: `M:\V_book\HDLE\logs\hdle_premium.log` for error details
4. Report issue with logs attached

---

### Cache Behavior

**Local MT uses same cache as cloud providers:**
- Cache key includes: `text|src_lang|tgt_lang|provider_id|glossary_hash|model_version`
- TTL: 7 days (default)
- Backend isolation: `ctranslate2` and `transformers` use separate cache

**Model version in cache key:**
- Format: `facebook_nllb-200-distilled-1.3B_ctranslate2`
- Includes both model ID and backend
- Different backends → different cache entries (isolated)

**When cache invalidates:**
- Glossary changed (different `glossary_hash`)
- Model changed (different `model_version`)
- Backend changed (e.g., switched from ctranslate2 to transformers)
- TTL expired (default: 7 days)

**View cache stats:**
- Settings → MT Providers → Cache Stats
- Or: Query `mt_cache` table in database

---

### Supported Languages

**NLLB-200 supports 200+ languages, including:**

| Language | ISO Code | NLLB Code |
|----------|----------|-----------|
| Hebrew | `he` | `heb_Hebr` |
| Russian | `ru` | `rus_Cyrl` |
| English | `en` | `eng_Latn` |
| Arabic | `ar` | `arb_Arab` |
| Spanish | `es` | `spa_Latn` |
| French | `fr` | `fra_Latn` |
| German | `de` | `deu_Latn` |
| Chinese (Simplified) | `zh` | `zho_Hans` |
| Japanese | `ja` | `jpn_Jpan` |
| Korean | `ko` | `kor_Hang` |

**Full list:** https://github.com/facebookresearch/flores/tree/main/flores200#languages-in-flores-200

---

### Privacy and Security

**Data Privacy:**
- ✅ **All data stays on your computer** (no network calls)
- ✅ **No telemetry** (model doesn't phone home)
- ✅ **No API keys** (no credentials to manage)
- ✅ **Offline operation** (works without internet after installation)

**Model License:**
- NLLB-200: CC-BY-NC 4.0 (free for internal/research use)
- See `docs/LOCAL_MT_LICENSE_NOTES.md` for full license details

**Use Cases:**
- Translating sensitive documents (legal, medical, financial)
- High-volume translation (no per-character costs)
- Offline work (no internet required)
- Internal company use (no data sharing)

---

### Comparison: Local vs Cloud

| Feature | Local NLLB | DeepL | Google | LibreTranslate |
|---------|------------|-------|--------|----------------|
| **Cost** | Free (after download) | $5.50 per 1M chars | $20 per 1M chars | Free (public) |
| **Privacy** | 100% offline | Cloud (GDPR) | Cloud (privacy policy) | Self-hosted = full control |
| **Speed** | 2-5 sec (medium text) | 1-2 sec | 1-2 sec | 2-4 sec (public) |
| **Quality** | Good | Excellent | Excellent | Good |
| **Languages** | 200+ | 30+ | 100+ | 30+ |
| **Glossary** | ✅ Yes (TM postprocess) | ✅ Yes | ✅ Yes | ✅ Yes |
| **Setup** | One-time install | API key | API key | No key (public) |
| **Internet** | Not needed | Required | Required | Required |

**Recommendation:**
- **Quality-first:** DeepL → Google → Local NLLB
- **Privacy-first:** Local NLLB → LibreTranslate (self-hosted)
- **Cost-aware:** Local NLLB → LibreTranslate (public)
- **Offline:** Local NLLB only

---

## FAQ

**Q: Which provider is best for Hebrew ↔ Russian?**
- **A:** DeepL (best quality), fallback to Google if DeepL unavailable.

**Q: Can I use multiple providers at once?**
- **A:** Yes, configure fallback chain (e.g., DeepL → Google → LibreTranslate). If primary fails, automatically tries next.

**Q: How much does MT cost?**
- **A:** DeepL Free: 500K chars/month (free), DeepL Pro: unlimited ($5.50 per 1M chars). Google: $20 per 1M chars. LibreTranslate: free (self-hosted or public).

**Q: How do I disable MT entirely?**
- **A:** Settings → MT Providers → Disable all providers. Translation will fall back to TM + Dictionary only (no automatic translation).

**Q: Can I self-host all providers?**
- **A:** Only LibreTranslate supports self-hosting. DeepL, Google, Microsoft are cloud-only.

**Q: What if I hit rate limit during import?**
- **A:** Fallback chain automatically tries next provider. Or: Reduce `requests_per_min` in Settings (slower but avoids rate limit).

**Q: How do I know which provider translated a segment?**
- **A:** Hover over translation in Translation Management panel → Shows provider ID (e.g., "deepl", "google") + cache status.

---

## Support

**Issues:**
- GitHub: https://github.com/anthropics/claude-code/issues
- Email: support@hdle-premium.com

**Provider-Specific Support:**
- DeepL: https://support.deepl.com/
- Google: https://cloud.google.com/translate/docs/support
- Microsoft: https://azure.microsoft.com/support/
- LibreTranslate: https://github.com/LibreTranslate/LibreTranslate/issues

---

**Last Updated:** 2026-02-08
**Document Version:** 1.2 (P1 Translation Pro + Local MT + UI Integration)
