# Release Notes: Google Cloud Translate API v3 Integration

**Release Date:** 2026-02-08
**Version:** PATCH-08 (Complete)
**Feature ID:** task_8_MT_google_cloud_translate

---

## 🎉 What's New

### Google Cloud Translation API v3 Provider

HDLE Premium now supports **Google Cloud Translation API v3** - Google's official, production-grade machine translation service with support for 100+ languages.

**Key Highlights:**
- ✅ **Official Google Cloud API** (not free/unofficial)
- ✅ **Service Account Authentication** - Secure OAuth2 with JSON keys
- ✅ **Budget Guards** - Prevent unexpected costs with usage limits
- ✅ **Usage Tracking** - Real-time monitoring with atomic counters
- ✅ **Encrypted Storage** - AES-256-GCM encryption for credentials
- ✅ **Automatic Retry** - Exponential backoff with jitter for reliability
- ✅ **UI Integration** - Advanced settings in Provider Settings Dialog

---

## 📦 Installation

### Requirements

- **HDLE Premium** installed
- **Schema version 9+** (automatic migration on startup)
- **Google Cloud Account** with billing enabled
- **Service Account JSON key** (see Integration Guide)

### Upgrade Steps

1. **Pull latest code:**
   ```bash
   git pull origin main
   ```

2. **Activate virtual environment:**
   ```bash
   cd J:\Project_Vibe\V_book
   .venv\Scripts\activate
   ```

3. **Run application** (migrations apply automatically):
   ```bash
   python -m app.main
   ```

4. **Verify migration:**
   - Check schema version: Should be **9**
   - Check logs: `M:\V_book\HDLE\logs\hdle.log`
   - Look for: `Current schema version: 9`

---

## 🚀 New Features

### 1. Service Account Authentication

**What it does:**
- Secure authentication using Google Cloud Service Accounts
- No user interaction required (programmatic access)
- JSON key file with RSA private key

**How to use:**
1. Create Service Account in Google Cloud Console
2. Download JSON key file
3. Load into HDLE: Settings → MT Providers → Advanced Settings → Load Service Account JSON

**Security:**
- Encrypted with AES-256-GCM at rest
- Master key stored in Windows Credential Manager
- Tamper detection with authentication tags

**See:** [Integration Guide - Service Account Creation](INTEGRATION_GOOGLE_CLOUD_TRANSLATE.md#service-account-creation)

---

### 2. Budget Guards

**What it does:**
- Enforces usage limits to prevent unexpected costs
- Four levels: per-request, per-minute, per-day, per-month
- Fail-closed mode blocks translations when limit exceeded

**Configuration:**

| Setting | Default | Description |
|---------|---------|-------------|
| Max Chars per Request | 5,000 | Single request limit |
| Max Requests per Minute | 60 | Rate limit (req/min) |
| Max Chars per Day | 100,000 | Daily budget (~$2/day) |
| Max Chars per Month | 1,000,000 | Monthly budget (~$20/month) |

**How to configure:**
- Settings → MT Providers → Advanced Settings → Budget Guards
- Set to **0** for unlimited (not recommended)
- Enable **Fail-Closed** for safety

**See:** [Integration Guide - Budget Limits](INTEGRATION_GOOGLE_CLOUD_TRANSLATE.md#budget-limits-and-alerts)

---

### 3. Usage Tracking

**What it does:**
- Tracks character count and request count in real-time
- Atomic SQL operations prevent race conditions
- Granular tracking: per-minute, per-day, per-month

**Database Schema:**
```sql
CREATE TABLE mt_usage (
    usage_id INTEGER PRIMARY KEY,
    provider_id TEXT NOT NULL,
    period_type TEXT NOT NULL,  -- 'minute', 'day', 'month'
    period_key TEXT NOT NULL,   -- '2026-02-08T15:30', '2026-02-08', '2026-02'
    char_count INTEGER NOT NULL,
    request_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(provider_id, period_type, period_key)
);
```

**How to view:**
- Settings → MT Providers → Advanced Settings → Usage Statistics → Refresh

**See:** [Integration Guide - Usage Tracking](INTEGRATION_GOOGLE_CLOUD_TRANSLATE.md#usage-tracking)

---

### 4. Advanced Settings UI

**What's new in Provider Settings Dialog:**

**Advanced Settings Tab:**
- 📁 **Service Account JSON**: Load/Clear/Preview
- 🔒 **Budget Guards**: Configure all four limit types
- 🔄 **Retry Policy**: Max retries, backoff multiplier, jitter
- 📊 **Usage Statistics**: View current usage, refresh button
- 🧪 **Test Connection**: Verify API access with test translation

**How to access:**
- Settings → MT Providers → Select "Google Cloud Translate (Official v3)" → Advanced Settings tab

**See:** [Integration Guide - Configuration](INTEGRATION_GOOGLE_CLOUD_TRANSLATE.md#hdle-premium-configuration)

---

### 5. Test Connection

**What it does:**
- Verifies Service Account JSON is valid
- Tests API connectivity
- Checks IAM permissions
- Shows test translation with latency

**How to use:**
1. Load Service Account JSON
2. Click **Test Connection** button
3. Wait 1-2 seconds
4. Success: Shows translation "Hello" → target language
5. Failure: Shows error message with details

**Common results:**
- ✅ `Connection Successful` - API working, credentials valid
- ❌ `401 Unauthorized` - Invalid credentials or API not enabled
- ❌ `403 Forbidden` - Service account lacks required role
- ❌ `Network error` - No internet or firewall blocking

---

### 6. Encrypted Credential Storage

**What it does:**
- Stores Service Account JSON encrypted in database
- Uses industry-standard AES-256-GCM
- Master key isolated in OS keyring

**Security Properties:**
- **Confidentiality**: 256-bit AES encryption
- **Integrity**: GCM authentication tag
- **Tamper Detection**: Tag verification on decrypt
- **Key Isolation**: Master key outside database

**Database Table:**
```sql
CREATE TABLE credentials (
    credential_id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    encrypted_value TEXT NOT NULL,  -- Base64(nonce || ciphertext || tag)
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    encryption_version INTEGER NOT NULL DEFAULT 1
);
```

**See:** [Integration Guide - Security](INTEGRATION_GOOGLE_CLOUD_TRANSLATE.md#security-considerations)

---

### 7. Automatic Retry with Backoff

**What it does:**
- Automatically retries failed API calls
- Exponential backoff: 1s, 2s, 4s, 8s, ...
- Jitter randomization prevents thundering herd

**Configuration:**
- **Max Retries**: 3 (default)
- **Initial Delay**: 1 second
- **Backoff Multiplier**: 2.0
- **Jitter**: ±25% randomization

**Retry Logic:**
- 429 Too Many Requests → Retry
- 500 Internal Server Error → Retry
- 503 Service Unavailable → Retry
- Network timeout → Retry
- 401/403 Auth errors → No retry (permanent failure)

---

## 🔧 Technical Changes

### Database Migrations

**Migration 009: MT Usage Tracking** (`app/infra/migrations/009_mt_usage_tracking.sql`)
- Creates `mt_usage` table
- Indexes for efficient lookups
- Updates schema version to 9
- **Fixed**: Correct schema_meta key-value format (commit `f36a30a`)

**Migration 008: Credentials Table** (already applied in v8)
- Creates `credentials` table for encrypted storage
- Triggers for automatic timestamp updates

### New Files

**Provider Implementation:**
- `app/infra/translators/providers/google_cloud_translate_provider.py` (600+ lines)
  - Service Account authentication
  - API v3 client with retry logic
  - Budget guard checks
  - Usage tracking integration

**Configuration:**
- `app/infra/translators/provider_config.py` (+200 lines)
  - Service Account auth mode
  - Credential ID helpers
  - Configuration dataclasses

**Services:**
- `app/services/mt_usage_tracker.py` (230 lines)
  - Atomic usage tracking
  - Budget enforcement
  - Period-based aggregation

**UI:**
- `app/ui/provider_settings_dialog.py` (+400 lines)
  - Advanced Settings tab
  - Service Account JSON upload/preview
  - Budget guard spinboxes
  - Usage statistics display
  - Test connection button

**Tests:**
- `tests/test_google_cloud_translate_provider.py` (16 tests)
- `tests/test_mt_usage_tracker.py` (12 tests)
- `scripts/test_gcp_provider_live.py` (live API tests)
- `scripts/test_app_startup.py` (integration tests)

**Documentation:**
- `docs/INTEGRATION_GOOGLE_CLOUD_TRANSLATE.md` (this guide)
- `docs/PATCH-05-USAGE-TRACKING-COMPLETE.md`
- `docs/PATCH-06-UI-PROVIDER-SETTINGS-COMPLETE.md`
- `docs/PATCH-07-INTEGRATION-COMPLETE.md`

### Modified Files

**Provider Registration:**
- `app/infra/translators/local_providers_setup.py`
  - Added `register_google_cloud_translate()` function

**App Startup:**
- `app/main.py`
  - Registers Google Cloud Translate provider on startup
  - Logs provider registration

**Config Manager:**
- `app/infra/translators/provider_config_manager.py`
  - **Fixed**: Lazy session creation for credential operations (commit `e0535e7`)
  - Removes requirement for explicit CredentialStore in UI

**Batch Translate:**
- `app/ui/dialogs/batch_translate_dialog.py`
  - Added `google_cloud_translate` to force provider dropdown

---

## 📊 Commit History

### PATCH-05: Usage Tracking (commit `6d87b3b`)
- Implemented `MTUsageTracker` service
- Created migration 009 for `mt_usage` table
- 12 unit tests (all passing)
- Atomic SQL operations for concurrent safety

### PATCH-06: UI Integration (commit `1d79679`)
- Extended Provider Settings Dialog with Advanced Settings tab
- Service Account JSON upload/clear/preview
- Budget guard configuration spinboxes
- Usage statistics display with refresh
- Test connection button
- 15 UI tests updated

### PATCH-07: Provider Registration (commit `083d5a8`)
- Registered provider at app startup
- Integration with ProvidersRegistry
- Session management refactor (on-demand sessions)
- Batch translate integration

### Bug Fix: Migration Schema (commit `f36a30a`)
- Fixed migration 009 schema_meta update format
- Changed from `(id, schema_version)` to `(key, value)` format
- Created fresh test database with all migrations
- Added test scripts and batch file

### Bug Fix: CredentialStore Initialization (commit `e0535e7`)
- Removed requirement for explicit CredentialStore in constructor
- Lazy session creation in get/set/delete credential methods
- UI dialogs no longer need to manage database sessions
- Backward compatible with explicit cred_store

### Database Restoration (commit `950c1ab`)
- Restored Hebrew Wikipedia corpus (387k documents)
- Updated schema version from 8 to 9
- Updated run_app_test.bat to use development database

---

## 🐛 Bug Fixes

### Migration Schema Format
**Issue:** Migration 009 used incorrect schema_meta format
**Fixed in:** `f36a30a`
**Details:**
- Was: `UPDATE schema_meta SET schema_version = 9 WHERE id = 1`
- Now: `UPDATE schema_meta SET value = '9' WHERE key = 'schema_version'`
- Root cause: schema_meta uses key-value pairs, not id+version columns

### CredentialStore Initialization
**Issue:** Provider Settings Dialog failed to load Service Account JSON
**Error:** `CredentialStore not initialized. Pass cred_store to ProviderConfigManager constructor.`
**Fixed in:** `e0535e7`
**Details:**
- UI dialogs create ProviderConfigManager without database session
- Modified get/set/delete credential to create temporary sessions
- Backward compatible with explicit cred_store parameter

### Worker Process Hang (task_4_MT_local - previous issue)
**Issue:** Local MT worker hung during startup
**Fixed in:** Previous release
**Details:**
- Inherited logging handlers caused file handle issues
- Clear handlers before configuring worker logging
- Documented in MEMORY.md

---

## 💰 Cost Information

### Pricing

**Google Cloud Translation API v3:**
- **$20 per million characters** translated
- No free tier (charges start immediately)
- Free trial: $300 credits for new accounts (lasts ~15M characters)

### Budget Examples

| Usage | Characters/Month | Cost/Month |
|-------|------------------|------------|
| **Light** | 100,000 | $2 |
| **Medium** | 1,000,000 | $20 |
| **Heavy** | 10,000,000 | $200 |

### Cost Control

**HDLE Budget Guards:**
- Set daily/monthly character limits
- Fail-closed enforcement blocks translation at limit
- Real-time usage tracking

**Google Cloud Budget Alerts:**
- Email notifications at 50%, 90%, 100% of budget
- Configure in GCP Console → Billing → Budgets & alerts

**See:** [Integration Guide - Cost Optimization](INTEGRATION_GOOGLE_CLOUD_TRANSLATE.md#cost-optimization)

---

## ⚠️ Breaking Changes

### None

This release is fully backward compatible.

**Existing users:**
- No changes to existing providers (Google Translate Free, Local MT)
- No changes to existing translations or caches
- No changes to existing settings

**New users:**
- Default behavior unchanged
- Google Cloud Translate requires manual setup (disabled by default)

---

## 🔒 Security Considerations

### Service Account JSON Security

⚠️ **CRITICAL:**
- JSON key file grants **FULL API ACCESS**
- Anyone with file can use your API and incur charges
- **NEVER commit to git or share publicly**

**Safe Storage:**
- ✅ Encrypted external drive
- ✅ Password manager (1Password, Bitwarden, KeePass)
- ✅ Secure folder outside project directory
- ✅ Windows Credential Manager (HDLE uses automatically)

**Unsafe Storage:**
- ❌ Project directory (risk of git commit)
- ❌ Desktop or Downloads folder
- ❌ Cloud storage without encryption
- ❌ Email attachments

### Encryption Details

**Algorithm:** AES-256-GCM (Galois/Counter Mode)

**Properties:**
- 256-bit key size
- Authenticated encryption (confidentiality + integrity)
- 96-bit random nonce per encryption
- 128-bit authentication tag
- NIST approved, FIPS 140-2 compliant

**Key Storage:**
- Master key: Windows Credential Manager (OS-protected)
- Encrypted data: SQLite database (`credentials` table)
- Format: `Base64(nonce || ciphertext || tag)`

**Key Rotation:**
- Service Account: Recommended every 90 days
- Master encryption key: Recommended annually

**See:** [Integration Guide - Security](INTEGRATION_GOOGLE_CLOUD_TRANSLATE.md#security-considerations)

---

## 🧪 Testing

### Test Coverage

**Unit Tests:**
- `tests/test_google_cloud_translate_provider.py` - 16 tests ✅
- `tests/test_mt_usage_tracker.py` - 12 tests ✅
- `tests/test_provider_config.py` - Updated ✅
- `tests/test_provider_settings_dialog.py` - 15 tests ✅

**Integration Tests:**
- `scripts/test_app_startup.py` - Provider registration ✅
- `scripts/test_gcp_provider_live.py` - Live API calls ✅
  - Tested: en→ru, en→he translations
  - Verified: 200-300ms latency
  - Project ID: &lt;your-gcp-project-id&gt;

**Manual Testing:**
- ✅ Service Account JSON upload/clear
- ✅ Test connection with real API
- ✅ Budget guard enforcement
- ✅ Usage tracking display
- ✅ Batch translation (force mode)
- ✅ Hebrew Wikipedia corpus (387k documents)

### Regression Testing

All existing functionality verified:
- ✅ Google Translate (Free) provider still works
- ✅ Local MT (NLLB) provider still works
- ✅ Batch translate with existing providers
- ✅ Dictionary/Terms tab operations
- ✅ Reference corpus queries

---

## 📚 Documentation

### New Documentation

1. **Integration Guide** (`docs/INTEGRATION_GOOGLE_CLOUD_TRANSLATE.md`)
   - Complete setup guide (GCP project, service account, IAM roles)
   - JSON key management and security
   - HDLE configuration steps
   - Budget limits and alerts setup
   - Usage tracking and monitoring
   - Troubleshooting common errors
   - Cost optimization tips
   - Security best practices
   - Migration guide from free provider
   - API reference and glossary

2. **PATCH Documentation**
   - `docs/PATCH-05-USAGE-TRACKING-COMPLETE.md`
   - `docs/PATCH-06-UI-PROVIDER-SETTINGS-COMPLETE.md`
   - `docs/PATCH-07-INTEGRATION-COMPLETE.md`

3. **Release Notes** (this document)

### Updated Documentation

- `README.md` - Added Google Cloud Translate to provider list
- `MEMORY.md` - Documented worker process fix, migration schema fix

---

## 🚦 Known Issues

### None

All known issues resolved in this release.

**Previously Fixed:**
- ✅ Migration 009 schema format (commit `f36a30a`)
- ✅ CredentialStore initialization (commit `e0535e7`)
- ✅ Worker process hang (task_4_MT_local, documented)

---

## 🔮 Future Enhancements

### Planned Features (Not in this release)

1. **Glossary Support**
   - Custom terminology management
   - Upload TMX glossaries to GCP
   - Enforce terminology in translations

2. **Batch Translation API**
   - GCP Batch Translation (async, cheaper)
   - Large document processing
   - Background job management

3. **Language Auto-Detection**
   - Automatic source language detection
   - Skip detection for known languages
   - Confidence scores

4. **Advanced Analytics**
   - Cost per project/corpus
   - Translation quality metrics
   - Provider comparison reports

5. **Multi-Provider Fallback**
   - Primary: Google Cloud Translate
   - Fallback: Google Translate Free
   - On quota exceeded, use fallback

---

## 📞 Support

### Getting Help

**Documentation:**
- [Integration Guide](INTEGRATION_GOOGLE_CLOUD_TRANSLATE.md)
- This release notes document

**Troubleshooting:**
- Check logs: `M:\V_book\HDLE\logs\hdle.log`
- Search for error message in Integration Guide troubleshooting section

**Bug Reports:**
- GitHub Issues: https://github.com/SindromRadioSpb/v_book/issues
- Include: error message, steps to reproduce, log file, schema version

**Community:**
- GitHub Discussions (planned)

---

## 👥 Credits

**Development:**
- Implementation: Claude Sonnet 4.5
- Task specification: task_8.md
- Testing: Manual + automated

**Special Thanks:**
- Google Cloud Platform team for excellent API documentation
- SQLAlchemy team for robust ORM
- PyQt6 team for UI framework

---

## 📄 License

**HDLE Premium** is proprietary software.
**Internal use only** - not for public distribution.

**Google Cloud Translation API:**
- Licensed under Google Cloud Terms of Service
- API pricing: https://cloud.google.com/translate/pricing
- Usage subject to Google Cloud quotas and billing

---

## 🎯 Quick Start

### 5-Minute Setup

1. **Create Google Cloud Project** (2 min)
   - https://console.cloud.google.com/
   - Enable Cloud Translation API
   - Enable billing ($300 free credits)

2. **Create Service Account** (2 min)
   - IAM & Admin → Service Accounts → Create
   - Name: `hdle-translate-sa`
   - Role: **Cloud Translation API User**
   - Create JSON key → Download

3. **Configure HDLE** (1 min)
   - Settings → MT Providers → Google Cloud Translate
   - Advanced Settings → Load Service Account JSON
   - Test Connection → Verify success
   - Rate Limits → Enable provider

**Done!** Start translating with Google Cloud Translate v3 🎉

---

**Release Version:** PATCH-08 (Complete)
**Release Date:** 2026-02-08
**Git Tag:** `v1.0.0-google-cloud-translate`
**Schema Version:** 9
**Commits:** `6d87b3b`, `1d79679`, `083d5a8`, `f36a30a`, `e0535e7`, `950c1ab`
