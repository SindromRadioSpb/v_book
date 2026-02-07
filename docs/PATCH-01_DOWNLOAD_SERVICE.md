# PATCH-01: Download Service for Pre-Processed Reference Database

**Status:** ✅ COMPLETE
**Date:** 2026-02-07

---

## Summary

Created download service for pre-processed Hebrew Wikipedia database with:
- HTTP download with resume support (Range requests)
- SHA256 checksum verification
- Progress tracking (bytes, speed, ETA)
- Manifest-driven configuration
- Python 3.14 compatibility (no zstd dependency)

---

## Files Created

### Core Services
1. **app/services/reference_setup/__init__.py** - Module exports
2. **app/services/reference_setup/manifest.py** - Manifest management
   - `ReferenceManifest` class
   - `ManifestEntry` dataclass
   - Embedded fallback manifest
3. **app/services/reference_setup/state.py** - State machine
   - `SetupState` dataclass with persistence
   - `SetupStage` enum (NOT_STARTED → DOWNLOADING → VERIFYING → DECOMPRESSING → INSTALLING → COMPLETED)
   - Progress tracking (bytes, docs, ETA)
4. **app/services/reference_setup/download_service.py** - Download service
   - `ReferenceDownloadService` class
   - HTTP Range support for resume
   - SHA256 verification
   - Compression support (zst/gzip/none)

### Documentation
5. **docs/PATCH-01_DOWNLOAD_SERVICE.md** - This file

---

## Key Features

### 1. Resumable Downloads
```python
service = ReferenceDownloadService(download_dir, state_file)
entry = service.get_latest_entry()

# Download with resume support
db_path = service.download(entry, progress_callback=on_progress)
```

**Resume Logic:**
- Saves state after each chunk
- Resumes from last checkpoint if interrupted
- Uses HTTP Range header: `Range: bytes={start}-`

### 2. Progress Tracking
```python
def on_progress(state: SetupState):
    print(f"Progress: {state.get_progress_percentage():.1f}%")
    print(f"Downloaded: {state.bytes_downloaded:,} / {state.total_bytes:,}")
    print(f"Speed: {state.download_speed_bps / 1024 / 1024:.2f} MB/s")
    eta = state.get_eta_seconds()
    if eta:
        print(f"ETA: {eta / 60:.1f} minutes")
```

### 3. Manifest System
```python
# Embedded manifest (fallback)
from app.services.reference_setup import EMBEDDED_MANIFEST

entry = EMBEDDED_MANIFEST.get_latest()
print(f"URL: {entry.url}")
print(f"Size: {entry.size_bytes / 1024**3:.2f} GB")
print(f"SHA256: {entry.sha256}")
```

**Manifest Entry:**
```json
{
  "name": "hewiki_ref_baseline",
  "version": "20260207",
  "url": "https://github.com/.../hewiki_ref_processed_v20260207.db",
  "sha256": "...",
  "size_bytes": 2500000000,
  "compression": "none",
  "description": "Hebrew Wikipedia Baseline (387,639 documents)"
}
```

### 4. State Persistence
```python
# State automatically saved to JSON
state = SetupState.load_from_file(state_file)
if state and state.can_resume():
    print(f"Resuming from {state.bytes_downloaded:,} bytes")
```

**State File Example:**
```json
{
  "stage": "downloading",
  "mode": "download",
  "bytes_downloaded": 1250000000,
  "total_bytes": 2500000000,
  "download_speed_bps": 10485760,
  "started_at": "2026-02-07T12:00:00Z",
  "last_updated_at": "2026-02-07T12:05:30Z"
}
```

---

## Python 3.14 Compatibility

**Issue:** `zstandard` library fails to build on Python 3.14 (cffi dependency issue)

**Solution:** Support multiple compression formats with fallback:
1. **zst** (ZStandard) - Best compression, requires zstandard library
2. **gz** (Gzip) - Good compression, built-in Python support
3. **none** (Uncompressed) - No compression, works everywhere

**Current Default:** `compression: "none"` for maximum compatibility

**Future:** When Python 3.14 support improves, switch to zst (smaller downloads)

---

## Usage Example

```python
from pathlib import Path
from app.services.reference_setup import ReferenceDownloadService

# Initialize
download_dir = Path("M:/V_book/HDLE/downloads")
state_file = Path("M:/V_book/HDLE/ref_setup_state.json")
service = ReferenceDownloadService(download_dir, state_file)

# Get latest manifest entry
entry = service.get_latest_entry()
print(f"Downloading: {entry.name} ({entry.size_bytes / 1024**3:.2f} GB)")

# Download with progress callback
def show_progress(state):
    pct = state.get_progress_percentage()
    print(f"\rProgress: {pct:.1f}%", end="", flush=True)

try:
    db_path = service.download(entry, progress_callback=show_progress)
    print(f"\nDownload complete: {db_path}")
except Exception as e:
    print(f"\nDownload failed: {e}")
    if service.can_resume():
        print("Run again to resume download")
```

---

## Security

### Checksum Verification
- **SHA256** hash verification after download
- Prevents corrupted downloads
- Detects man-in-the-middle attacks

### Resume Safety
- State file tracks exact byte position
- HTTP Range request verifies server support
- Falls back to full download if resume fails

---

## Testing

### Manual Test
```bash
python -c "
from pathlib import Path
from app.services.reference_setup import ReferenceDownloadService

service = ReferenceDownloadService(
    Path('test_downloads'),
    Path('test_state.json')
)

entry = service.get_latest_entry()
print('Manifest entry:', entry.name)
print('URL:', entry.url)
print('Size:', f'{entry.size_bytes / 1024**3:.2f} GB')
print('Compression:', entry.compression)
"
```

**Expected Output:**
```
Manifest entry: hewiki_ref_baseline
URL: https://github.com/.../hewiki_ref_processed_v20260207.db
Size: 2.33 GB
Compression: none
```

---

## Next Steps (PATCH-02)

1. Create **Local Processing Service** for offline mode:
   - Download XML dump
   - Extract to JSONL
   - Import to database
   - Run NLP processing
   - Extract terms

2. Integrate with existing scripts:
   - `scripts/ref_corpora/extract_hewiki_to_jsonl.py`
   - `scripts/ref_corpora/import_ref_jsonl_to_project.py`

3. Background job support:
   - QThread integration
   - Progress signals
   - Pause/Resume/Cancel

---

## Notes

### Download Location
- **Temporary:** `M:\V_book\HDLE\downloads\hewiki_ref_baseline.db`
- **Final:** Copy to `M:\V_book\HDLE\hdle.db` after verification

### Manifest Updates
- Current manifest is embedded (placeholder URLs)
- Will be updated in PATCH-06 after pre-processing
- Can be fetched from GitHub Release for latest versions

### Production Checklist
- [ ] Pre-process database on dev machine with GPU (PATCH-06)
- [ ] Upload to GitHub Release
- [ ] Update manifest with real URL and SHA256
- [ ] Test download on clean machine
- [ ] Measure actual download time (5-15 min estimate)

---

**Author:** Claude Sonnet 4.5
**Co-Authored-By:** Claude Sonnet 4.5 <noreply@anthropic.com>
