# Fix: Add Noise Column to TM Excel Export

## Date: 2026-02-14

## Problem

Translation Management панель отображает колонку "Noise" в UI таблице, но при экспорте в Excel через кнопку "Export Excel" эта колонка отсутствовала.

**UI Table Columns:**
```
ID | Kind | Source | Translation | Status | Project | Origin | Source Ref | Updated | Noise
```

**Excel Export Columns (before fix):**
```
ID | Kind | Source | Translation | Status | Project | Origin | Source Ref | Updated
```
❌ Колонка "Noise" отсутствует!

---

## Solution

Добавлена колонка "Noise" в экспорт Excel в файле `app/services/export_service.py`, метод `export_tm_filtered_xlsx()`.

### Changes Made

**File**: `app/services/export_service.py`

1. **Headers** (line ~1027-1030):
   ```python
   # Before:
   headers = [
       "ID", "Kind", "Source", "Translation", "Status",
       "Project", "Origin", "Source Ref", "Updated"
   ]

   # After:
   headers = [
       "ID", "Kind", "Source", "Translation", "Status",
       "Project", "Origin", "Source Ref", "Updated", "Noise"
   ]
   ```

2. **Row Data** (lines ~1051-1062):
   ```python
   # Before:
   ws.append([
       entry.tm_id,
       entry.kind or "",
       entry.src_text or "",
       entry.translation or "",
       entry.status or "",
       str(entry.project_id) if entry.project_id else "Global",
       entry.origin or "",
       entry.source_ref or "",
       str(entry.updated_at) if entry.updated_at else "",
   ])

   # After:
   # Format is_noise for display (same as UI table model):
   # 1 = "Noise", 0 = "Valid", None = ""
   noise_display = ""
   if entry.is_noise == 1:
       noise_display = "Noise"
   elif entry.is_noise == 0:
       noise_display = "Valid"

   ws.append([
       entry.tm_id,
       entry.kind or "",
       entry.src_text or "",
       entry.translation or "",
       entry.status or "",
       str(entry.project_id) if entry.project_id else "Global",
       entry.origin or "",
       entry.source_ref or "",
       str(entry.updated_at) if entry.updated_at else "",
       noise_display,  # NEW: Noise column
   ])
   ```

---

## Format Consistency

Noise column format matches the UI table model (`app/ui/models_qt.py`, lines 446-453):

| `is_noise` value | Display |
|------------------|---------|
| 1                | "Noise" |
| 0                | "Valid" |
| NULL             | ""      |

---

## Testing

### Automated Test

**Script**: `scripts/test_tm_export_noise_column.py`

**Result**: ✅ PASSED

```
Export completed: 22,024 entries
Headers: ['ID', 'Kind', 'Source', 'Translation', 'Status', 'Project', 'Origin', 'Source Ref', 'Updated', 'Noise']
✓ 'Noise' column found at index 10

Statistics:
  Noise entries: 3,283
  Valid entries: 18,741
  Legacy (empty): 0

✓ TEST PASSED: Noise column is present in Excel export
```

### Manual Verification Steps

1. Запустите приложение: `python -m app.main`
2. Откройте **Translation Management** панель
3. Нажмите кнопку **"📊 Export Excel"**
4. Сохраните файл (например, `translation_memory_20260214.xlsx`)
5. Откройте файл в Excel
6. **Проверка**: Последняя колонка должна быть **"Noise"** с значениями:
   - "Noise" для шумных записей (пунктуация, числа и т.д.)
   - "Valid" для обычных записей
   - Пустая ячейка для legacy записей (до добавления is_noise)

---

## Data Model

### TMEntry (SQLAlchemy)

```python
class TMEntry(Base):
    # ...
    is_noise = Column(Integer, default=0)  # 0=not noise, 1=noise, NULL=legacy
    noise_reason = Column(String)  # NOISE_PUNCT_ONLY, NOISE_NUMBER_ONLY, etc.
```

### TMEntryDTO

```python
@dataclass
class TMEntryDTO:
    # ...
    is_noise: Optional[int]  # 0=not noise, 1=noise, None=legacy
    noise_reason: Optional[str]
```

---

## Files Modified

| File | Change |
|------|--------|
| `app/services/export_service.py` | Added "Noise" column to headers and row data in `export_tm_filtered_xlsx()` |
| `scripts/test_tm_export_noise_column.py` | NEW: Automated test for Noise column export |
| `NOISE_COLUMN_EXPORT_FIX.md` | NEW: This documentation |

---

## Verification

✅ **Compilation**: All imports successful
✅ **Automated Test**: 22,024 entries exported with Noise column
✅ **Format**: Matches UI table model ("Noise"/"Valid"/"")
✅ **No Breaking Changes**: Existing exports continue to work

---

## Usage

После этого исправления все экспорты из Translation Management будут включать колонку Noise:

```bash
python -m app.main
# Translation Management → Export Excel
```

**Excel Columns (after fix):**
```
ID | Kind | Source | Translation | Status | Project | Origin | Source Ref | Updated | Noise ✓
```

---

## Related Issues

- Task 11: Noise detection and classification system
- Task 13: Bidirectional sync between lemma/term_cluster and tm_entry

---

## Commit

**Date**: 2026-02-14
**Message**: fix(export): add Noise column to TM Excel export

**Changes**:
- Added "Noise" header to export_tm_filtered_xlsx
- Added noise_display field to row data
- Format matches UI table model (Noise/Valid/empty)
- Test: 22,024 entries exported successfully with Noise column

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
