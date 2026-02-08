# Google Cloud Translate API v3 Integration Guide

## Overview

This guide covers the integration of **Google Cloud Translation API v3** (Official API) into HDLE Premium. This is a production-grade, high-quality machine translation service with support for 100+ languages.

**Key Features:**
- Official Google Cloud API (not free/unofficial)
- Advanced v3 API with glossary support
- Service Account authentication (secure)
- Budget guards and usage tracking
- Automatic retry with exponential backoff
- Encrypted credential storage

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Google Cloud Project Setup](#google-cloud-project-setup)
3. [Service Account Creation](#service-account-creation)
4. [IAM Roles and Permissions](#iam-roles-and-permissions)
5. [JSON Key Management](#json-key-management)
6. [HDLE Premium Configuration](#hdle-premium-configuration)
7. [Budget Limits and Alerts](#budget-limits-and-alerts)
8. [Usage Tracking](#usage-tracking)
9. [Troubleshooting](#troubleshooting)
10. [Cost Optimization](#cost-optimization)

---

## Prerequisites

Before you begin, you need:

1. **Google Cloud Account** (Gmail account)
2. **Active GCP Project** with billing enabled
3. **Credit Card** for billing (Google provides $300 free trial)
4. **HDLE Premium** installed (schema version 9+)

**Estimated Setup Time:** 15-20 minutes

---

## Google Cloud Project Setup

### Step 1: Create or Select a Project

1. Go to **Google Cloud Console**: https://console.cloud.google.com/
2. Click **Select a project** → **NEW PROJECT**
3. Enter project details:
   - **Project name**: `HDLE Translation` (or any name)
   - **Organization**: (optional, leave as No organization)
   - **Location**: No organization
4. Click **CREATE**
5. Wait for project creation (10-15 seconds)
6. **Note your Project ID** (e.g., `hdle-translate-123456`)

### Step 2: Enable Billing

1. Go to **Billing** → **Link a billing account**
2. If you don't have a billing account:
   - Click **CREATE BILLING ACCOUNT**
   - Enter credit card details
   - Accept terms
   - **Note**: Google provides $300 free trial credits
3. Link the billing account to your project

### Step 3: Enable Cloud Translation API

1. Go to **APIs & Services** → **Library**
2. Search for **"Cloud Translation API"**
3. Click on **Cloud Translation API** (NOT "Google Cloud Translation")
4. Click **ENABLE**
5. Wait for API activation (5-10 seconds)

**Verification:**
- Go to **APIs & Services** → **Enabled APIs & services**
- You should see **Cloud Translation API** in the list

---

## Service Account Creation

Service Accounts provide secure, programmatic access to Google Cloud APIs without user interaction.

### Step 1: Create Service Account

1. Go to **IAM & Admin** → **Service Accounts**
2. Click **+ CREATE SERVICE ACCOUNT**
3. Enter service account details:
   - **Service account name**: `hdle-translate-sa`
   - **Service account ID**: `hdle-translate-sa` (auto-filled)
   - **Description**: `Service Account for HDLE Premium Translation`
4. Click **CREATE AND CONTINUE**

### Step 2: Grant Roles

On the **Grant this service account access to project** screen:

1. Click **Select a role**
2. Choose **Cloud Translation API User**
   - **Role**: `roles/cloudtranslate.user`
   - **Description**: Can use Cloud Translation API
3. Click **CONTINUE**

### Step 3: Grant User Access (Optional)

Skip this step unless you need to grant other users access to this service account.

Click **DONE**

**Verification:**
- Service account created: `hdle-translate-sa@<project-id>.iam.gserviceaccount.com`

---

## IAM Roles and Permissions

### Required Role: Cloud Translation API User

**Role Name**: `roles/cloudtranslate.user`

**Permissions Included:**
- `cloudtranslate.operations.get` - Check operation status
- `cloudtranslate.operations.list` - List operations
- `cloudtranslate.operations.wait` - Wait for operation completion
- `resourcemanager.projects.get` - Get project metadata

**What It Allows:**
- ✅ Translate text using Cloud Translation API v3
- ✅ Detect source language
- ✅ List supported languages
- ❌ Create glossaries (requires Admin role)
- ❌ Modify billing settings
- ❌ Manage other service accounts

### Alternative: Cloud Translation API Admin (NOT Recommended)

**Role Name**: `roles/cloudtranslate.admin`

**Additional Permissions:**
- Glossary management (create, update, delete)
- Batch translation jobs

**Why Not Recommended:**
- More permissions than needed (principle of least privilege)
- Higher security risk if JSON key compromised
- HDLE Premium doesn't use glossaries yet

**Use Cloud Translation API User** unless you specifically need glossary features.

---

## JSON Key Management

### Step 1: Create JSON Key

1. Go to **IAM & Admin** → **Service Accounts**
2. Find your service account: `hdle-translate-sa@...`
3. Click on the service account name
4. Go to **KEYS** tab
5. Click **ADD KEY** → **Create new key**
6. Select **JSON** format
7. Click **CREATE**

**Result:**
- A JSON file downloads automatically: `<project-id>-<random>.json`
- Example: `hdle-translate-123456-a1b2c3d4e5f6.json`

⚠️ **CRITICAL SECURITY WARNING:**
- This JSON file contains **FULL ACCESS** to your Translation API
- Anyone with this file can use your API and incur charges
- **NEVER commit this file to git/version control**
- **NEVER share this file publicly**
- **Store it securely** (see next section)

### Step 2: Secure Storage

**Recommended Storage Locations:**

✅ **GOOD:**
- Encrypted external drive (BitLocker, VeraCrypt)
- Password manager (1Password, Bitwarden, KeePass)
- Secure folder outside project directory
- Windows Credential Manager (HDLE uses this automatically)

❌ **BAD:**
- Project directory (risk of git commit)
- Desktop or Downloads folder
- Cloud storage (Google Drive, Dropbox) without encryption
- Email attachments

**Example Secure Path:**
```
C:\SecureKeys\google_cloud\hdle-translate-sa.json
J:\Credentials\hdle-translate-sa.json  (external drive)
```

### Step 3: Verify JSON Structure

Open the JSON file in a text editor and verify it contains:

```json
{
  "type": "service_account",
  "project_id": "hdle-translate-123456",
  "private_key_id": "a1b2c3d4...",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...",
  "client_email": "hdle-translate-sa@hdle-translate-123456.iam.gserviceaccount.com",
  "client_id": "123456789...",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/..."
}
```

**Required Fields:**
- `project_id` - Your GCP project ID
- `private_key` - RSA private key (starts with `-----BEGIN PRIVATE KEY-----`)
- `client_email` - Service account email

### Step 4: Rotation Policy (Recommended)

For production use, rotate keys regularly:

1. **Every 90 days**: Create new key, update HDLE, delete old key
2. **On suspected compromise**: Immediately delete old key, create new one
3. **On team changes**: Rotate when employees leave

**How to Rotate:**
1. Create new key (Step 1 above)
2. Load new key into HDLE (see Configuration section)
3. Test translation works
4. Delete old key from GCP console

---

## HDLE Premium Configuration

### Step 1: Launch Application

```batch
cd J:\Project_Vibe\V_book
.venv\Scripts\activate
python -m app.main
```

Or use the batch file:
```batch
run_app_test.bat
```

### Step 2: Open Provider Settings

1. Menu: **Settings** → **MT Provider Settings**
2. Select **Google Cloud Translate (Official v3)** from the list
3. Click on the **Advanced Settings** tab

### Step 3: Load Service Account JSON

1. Click **Load Service Account JSON** button
2. Navigate to your JSON file location
3. Select the JSON file (e.g., `hdle-translate-sa.json`)
4. Click **Open**

**What Happens:**
- JSON file is validated (checks for `project_id`, `private_key`)
- Contents are encrypted with AES-256-GCM
- Master key stored in Windows Credential Manager
- Encrypted data saved to database (`credentials` table)
- Original file remains unchanged (not moved or deleted)

**Success Indicators:**
- Preview shows: `✓ Service Account configured (project: <your-project-id>)`
- Preview text color: Green

**Error Messages:**
- ❌ `Invalid JSON` - File is not valid JSON
- ❌ `Missing 'project_id' field` - Wrong JSON structure
- ❌ `Failed to load` - File read error (check permissions)

### Step 4: Test Connection

1. Click **Test Connection** button (requires Service Account loaded)
2. Wait for API call (1-2 seconds)
3. **Success**: Dialog shows test translation:
   ```
   Connection Successful
   Test translation: "Hello" → "Привет"
   Latency: 250ms
   ```
4. **Failure**: Dialog shows error message with details

**Common Test Errors:**
- `401 Unauthorized` - Invalid credentials or API not enabled
- `403 Forbidden` - Service account lacks `cloudtranslate.user` role
- `Network error` - No internet connection or firewall blocking
- `Quota exceeded` - Free tier limit reached (unlikely on first test)

### Step 5: Configure Budget Guards (Optional)

Budget guards prevent unexpected API costs by enforcing usage limits.

**Budget Guard Settings:**

1. **Max Chars per Request** (default: 5000)
   - Single translation request limit
   - Prevents accidental large requests
   - Google limit: 30,000 characters/request
   - **Recommended**: 5000 (safe default)

2. **Max Requests per Minute** (default: 60)
   - Rate limit (requests/minute)
   - Prevents API quota exhaustion
   - Google default quota: 300 requests/minute
   - **Recommended**: 60 (conservative)

3. **Max Chars per Day** (default: 100,000)
   - Daily budget guard
   - Prevents daily overspending
   - Example: 100k chars ≈ $2/day at $20/million chars
   - **Recommended**: Set based on budget

4. **Max Chars per Month** (default: 1,000,000)
   - Monthly budget guard
   - Prevents monthly overspending
   - Example: 1M chars ≈ $20/month
   - **Recommended**: Set based on budget

**Special Values:**
- **0** = Unlimited (no enforcement)
- **1+** = Enforced limit

**Fail-Closed Enforcement:**
- ☑ **Enabled**: Blocks translation if budget exceeded (SAFE)
- ☐ **Disabled**: Logs warning but allows translation (RISKY)

**Recommendation**: Enable fail-closed for production use.

### Step 6: Enable Provider

1. Go to **Rate Limits** tab
2. Check **☑ Enable MT provider**
3. Click **OK** to save

**Verification:**
- Provider enabled in provider list
- Available in batch translate dialog (Force Provider dropdown)

---

## Budget Limits and Alerts

### Google Cloud Budget Alerts

Set up billing alerts in GCP to monitor costs:

#### Step 1: Create Budget

1. Go to **Billing** → **Budgets & alerts**
2. Click **CREATE BUDGET**
3. **Budget name**: `HDLE Translation Budget`
4. **Projects**: Select your project
5. **Services**: Select **Cloud Translation API**
6. **Amount**:
   - **Budget type**: Specified amount
   - **Target amount**: $50/month (adjust based on needs)

#### Step 2: Configure Alerts

Set threshold alerts to notify before overspending:

1. **Alert thresholds**:
   - 50% ($25)
   - 90% ($45)
   - 100% ($50)
2. **Email notifications**: Enter your email
3. Click **FINISH**

**Result:**
- Email alerts sent at 50%, 90%, 100% of budget
- No automatic charge blocking (manual monitoring required)

### HDLE Premium Budget Guards

HDLE enforces limits automatically:

**Example Budget Setup:**

| Limit | Value | Cost Estimate |
|-------|-------|---------------|
| Max Chars/Request | 5,000 | Single request cap |
| Max Requests/Min | 60 | 3,600 req/hour max |
| Max Chars/Day | 100,000 | ~$2/day @ $20/M chars |
| Max Chars/Month | 1,000,000 | ~$20/month |

**Cost Calculation:**
- Google Cloud Translation pricing: **$20 per million characters**
- Example: Translate 500,000 chars/month = $10/month

**Free Tier:**
- Google offers **$300 free credits** for new accounts
- No ongoing free tier for Translation API v3
- All usage after free credits is billed

### Monitoring Usage

Track usage in HDLE Premium:

1. **Settings** → **MT Provider Settings** → **Advanced Settings**
2. Click **Refresh** button in Usage Statistics section
3. View current usage:
   - **Today**: Characters and requests today
   - **This Month**: Characters and requests this month
4. Compare against budget limits

**Export Usage Data:**
- Usage stored in database table: `mt_usage`
- Query manually: `SELECT * FROM mt_usage WHERE provider_id = 'google_cloud_translate'`

---

## Usage Tracking

### Database Schema

HDLE tracks usage in the `mt_usage` table:

```sql
CREATE TABLE mt_usage (
    usage_id INTEGER PRIMARY KEY,
    provider_id TEXT NOT NULL,           -- 'google_cloud_translate'
    period_type TEXT NOT NULL,           -- 'minute', 'day', 'month'
    period_key TEXT NOT NULL,            -- '2026-02-08T15:30', '2026-02-08', '2026-02'
    char_count INTEGER NOT NULL,         -- Total characters
    request_count INTEGER NOT NULL,      -- Total requests
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(provider_id, period_type, period_key)
);
```

### Query Examples

**Today's usage:**
```sql
SELECT
    SUM(char_count) as total_chars,
    SUM(request_count) as total_requests
FROM mt_usage
WHERE provider_id = 'google_cloud_translate'
    AND period_type = 'day'
    AND period_key = date('now');
```

**Monthly usage:**
```sql
SELECT
    period_key as month,
    SUM(char_count) as total_chars,
    SUM(request_count) as total_requests
FROM mt_usage
WHERE provider_id = 'google_cloud_translate'
    AND period_type = 'month'
GROUP BY period_key
ORDER BY period_key DESC
LIMIT 12;
```

### Atomic Updates

Usage tracking uses atomic SQL operations:

```sql
-- Increment counters atomically (no race conditions)
INSERT INTO mt_usage (provider_id, period_type, period_key, char_count, request_count)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT(provider_id, period_type, period_key) DO UPDATE SET
    char_count = char_count + excluded.char_count,
    request_count = request_count + excluded.request_count,
    updated_at = datetime('now');
```

**Benefits:**
- No race conditions in concurrent batch translate
- Accurate counting even with parallel requests
- Real-time budget enforcement

---

## Troubleshooting

### Common Errors

#### 1. "Failed to load Service Account JSON: Invalid JSON"

**Cause:** File is not valid JSON or corrupted

**Solution:**
1. Open file in text editor
2. Verify JSON structure (see [JSON Key Management](#json-key-management))
3. Re-download from GCP if corrupted

---

#### 2. "401 Unauthorized"

**Cause:** Invalid credentials or API not enabled

**Solution:**
1. Verify Cloud Translation API is enabled:
   - GCP Console → APIs & Services → Enabled APIs
2. Check service account still exists:
   - IAM & Admin → Service Accounts
3. Verify JSON key not deleted:
   - Service Account → Keys tab
4. Re-download JSON key if needed

---

#### 3. "403 Forbidden: Permission denied"

**Cause:** Service account lacks required role

**Solution:**
1. Go to **IAM & Admin** → **IAM**
2. Find service account: `hdle-translate-sa@...`
3. Click **Edit principal** (pencil icon)
4. Verify role: **Cloud Translation API User** (`roles/cloudtranslate.user`)
5. If missing, add role:
   - **ADD ANOTHER ROLE** → Cloud Translation API User → **SAVE**

---

#### 4. "429 Too Many Requests: Quota exceeded"

**Cause:** Exceeded Google Cloud quota

**Solution:**
1. Check quota in GCP Console:
   - **IAM & Admin** → **Quotas & System Limits**
   - Filter: `Cloud Translation API`
2. Default quota: 300 requests/minute, 60 requests/minute/user
3. Request quota increase if needed:
   - Click quota → **EDIT QUOTAS** → Request increase

---

#### 5. "Budget limit exceeded"

**Cause:** HDLE budget guard triggered

**Solution:**
1. Check usage: **Settings** → **MT Providers** → **Advanced Settings** → **Refresh**
2. Compare usage against limits
3. Options:
   - **Wait**: Usage resets at period boundary (minute/day/month)
   - **Increase limits**: Edit budget guard values
   - **Disable fail-closed**: Allow translations despite limit (not recommended)

---

#### 6. "Network error: Connection timeout"

**Cause:** No internet or firewall blocking

**Solution:**
1. Check internet connection
2. Test connectivity: `ping translate.googleapis.com`
3. Check corporate firewall/proxy
4. Whitelist domains:
   - `*.googleapis.com`
   - `accounts.google.com`
   - `oauth2.googleapis.com`

---

#### 7. "CredentialStore not initialized"

**Cause:** Old version or corrupted installation

**Solution:**
1. Update to latest version (commit `e0535e7+`)
2. Restart application
3. If persists, reinstall HDLE Premium

---

### Debug Logs

Enable debug logging for troubleshooting:

**Windows:**
- Log file: `M:\V_book\HDLE\logs\hdle.log`
- Search for: `google_cloud_translate`

**Example log entries:**
```
2026-02-08 15:30:00 - app.infra.translators.providers.google_cloud_translate_provider - INFO - Translation request sent (trace: batch-123)
2026-02-08 15:30:00 - app.infra.translators.providers.google_cloud_translate_provider - INFO - Translation successful (250ms, 5 chars)
```

**Error logs:**
```
2026-02-08 15:30:00 - app.infra.translators.providers.google_cloud_translate_provider - ERROR - Translation failed: 401 Unauthorized
```

---

## Cost Optimization

### Best Practices

1. **Enable Budget Guards**
   - Set realistic daily/monthly limits
   - Enable fail-closed enforcement
   - Monitor usage regularly

2. **Use Cache**
   - HDLE caches translations in `mt_cache` table
   - Reusing translations is free
   - Clear cache periodically to save disk space

3. **Batch Wisely**
   - Large batches more efficient (fewer API calls)
   - But stay within budget limits
   - Use "Fill Empty" mode to skip existing translations

4. **Choose Right Provider**
   - Google Cloud Translate: High quality, paid
   - Google Translate Free: Lower quality, free
   - Local MT (NLLB): Offline, free, GPU recommended

5. **Monitor Alerts**
   - Set up GCP billing alerts
   - Check HDLE usage statistics weekly
   - Review monthly billing in GCP Console

### Cost Comparison

| Provider | Cost | Quality | Speed | Offline |
|----------|------|---------|-------|---------|
| **Google Cloud Translate v3** | $20/M chars | ★★★★★ | Fast | ❌ |
| Google Translate (Free) | Free | ★★★★☆ | Fast | ❌ |
| Local MT (NLLB) | Free | ★★★☆☆ | Slow* | ✅ |

*Slow on CPU, fast on GPU

### Monthly Cost Examples

**Light usage** (100k chars/month):
- Cost: $2/month
- Use case: Personal projects, light translation

**Medium usage** (1M chars/month):
- Cost: $20/month
- Use case: Professional translators, small teams

**Heavy usage** (10M chars/month):
- Cost: $200/month
- Use case: Translation agencies, large projects

**Recommendation:** Start with low budget guards, increase as needed.

---

## Migration Notes

### From Free Google Translate

If migrating from free Google Translate provider:

1. **Backup existing translations:**
   ```sql
   -- Export mt_cache table
   SELECT * FROM mt_cache WHERE provider_id = 'google_translate';
   ```

2. **Configure Google Cloud Translate** (follow guide above)

3. **Set "Fill Empty" mode** in batch translate:
   - Preserves existing translations
   - Only translates empty cells
   - Avoids re-translating same content

4. **Force provider in batch translate:**
   - Select: `force: google_cloud_translate`
   - Ensures new translations use paid API

5. **Disable free provider** (optional):
   - Settings → MT Providers → Google Translate (Free)
   - Uncheck "Enable MT provider"

### Schema Requirements

**Minimum schema version:** 9

**Required tables:**
- `mt_usage` (migration 009)
- `credentials` (migration 008)
- `schema_meta` (key-value format)

**Check schema version:**
```sql
SELECT value FROM schema_meta WHERE key = 'schema_version';
```

**Expected result:** `9`

---

## Security Considerations

### Credential Encryption

HDLE encrypts Service Account JSON at rest:

1. **Algorithm**: AES-256-GCM (authenticated encryption)
2. **Master key**: Stored in Windows Credential Manager
3. **Database**: Encrypted ciphertext in `credentials` table
4. **Format**: Base64(nonce || ciphertext || tag)

**Security Properties:**
- Confidentiality: AES-256 encryption
- Integrity: GCM authentication tag
- Key isolation: Master key outside database
- Tamper detection: Tag verification on decrypt

### Key Rotation

Rotate encryption keys periodically:

1. **Service Account Key** (recommended: 90 days)
2. **Master Encryption Key** (recommended: 1 year)

**Master key location:**
```
Windows Credential Manager → Generic Credentials → hdle_credential_store_master_key
```

### Audit Logging

Security events logged in `security_audit_log` table:

```sql
SELECT * FROM security_audit_log
WHERE event_type LIKE 'credential_%'
ORDER BY timestamp DESC
LIMIT 10;
```

**Logged events:**
- `credential_set` - Credential saved
- `credential_get` - Credential retrieved
- `credential_delete` - Credential deleted

---

## Support

### Getting Help

1. **Documentation**: This guide
2. **GitHub Issues**: https://github.com/SindromRadioSpb/v_book/issues
3. **Logs**: `M:\V_book\HDLE\logs\hdle.log`

### Reporting Bugs

Include in bug report:

1. **Error message** (exact text)
2. **Steps to reproduce**
3. **Log file** (last 50 lines)
4. **Schema version**: `SELECT value FROM schema_meta WHERE key='schema_version'`
5. **HDLE version**: Check git commit hash

---

## Changelog

### Version 1.0 (2026-02-08)

**Added:**
- Google Cloud Translation API v3 provider
- Service Account JSON authentication
- Budget guards (per-request, per-minute, per-day, per-month)
- Usage tracking (atomic counters, real-time enforcement)
- Encrypted credential storage (AES-256-GCM)
- Retry policy (exponential backoff with jitter)
- UI integration (Provider Settings Dialog advanced tab)
- Test connection functionality
- Documentation (this guide)

**Migrations:**
- 009: `mt_usage` table for usage tracking
- 008: `credentials` table for encrypted storage

**Commits:**
- `6d87b3b` - PATCH-05: Usage tracking
- `1d79679` - PATCH-06: UI integration
- `083d5a8` - PATCH-07: Provider registration
- `f36a30a` - Migration fix
- `e0535e7` - CredentialStore fix

---

## Appendix: API Reference

### Google Cloud Translation API v3 Endpoints

**Translate Text:**
```
POST https://translation.googleapis.com/v3/projects/{project}/locations/global:translateText
```

**Request Body:**
```json
{
  "sourceLanguageCode": "en",
  "targetLanguageCode": "ru",
  "contents": ["Hello, world!"],
  "mimeType": "text/plain"
}
```

**Response:**
```json
{
  "translations": [
    {
      "translatedText": "Привет, мир!",
      "detectedLanguageCode": "en"
    }
  ]
}
```

### Rate Limits (Default Quotas)

| Quota | Limit | Notes |
|-------|-------|-------|
| Requests per minute | 300 | Per project |
| Requests per minute per user | 60 | Per service account |
| Characters per request | 30,000 | Hard limit |
| Characters per day | Unlimited | Billed |

**Request quota increase:**
- GCP Console → IAM & Admin → Quotas & System Limits
- Select quota → Edit Quotas → Submit request

---

## Glossary

- **Service Account**: Non-human account for programmatic API access
- **IAM**: Identity and Access Management
- **JSON Key**: Private key file for service account authentication
- **Budget Guard**: Usage limit enforced by HDLE
- **Fail-Closed**: Block operation when limit exceeded (vs fail-open: allow with warning)
- **AES-256-GCM**: Authenticated encryption algorithm
- **Atomic Operation**: Database operation that completes fully or not at all (no partial updates)

---

**Document Version:** 1.0
**Last Updated:** 2026-02-08
**Author:** HDLE Premium Development Team
**License:** Internal Use Only
