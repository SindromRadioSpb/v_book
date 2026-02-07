# MT Provider Setup Guide

**Audience:** End users
**Date:** 2026-02-07
**Version:** 1.0 (P1 Translation Pro)

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

### 2. Configure in HDLE Premium

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

**Last Updated:** 2026-02-07
**Document Version:** 1.0 (P1 Translation Pro)
