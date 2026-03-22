# Epic 6 — Dictionary Maturity / Lemma Workflow Hardening
## Audit Findings + Implementation Plan (rev. 2)

**Дата аудита:** 2026-03-22
**Ревизия плана:** 2026-03-23 — применены рекомендации архитектора
**Базовый шаблон:** Epic 4/5 (provenance → safety → observability → docs)
**Текущий baseline:** 1651 тестов, схема v46

---

## Предварительные артефакты (зафиксировать до кода)

### A. Таблица семантики статусов

Без явной семантики логика расползётся по UI и сервисам.
source_lifecycle **вычисляется**, не хранится физически.

| Состояние | Условие | Что значит для пользователя |
|-----------|---------|----------------------------|
| `linked` | `lemma_id IS NOT NULL` (живая lemma существует) | Запись поддержана текущим корпусом |
| `manual` | `lemma_id IS NULL AND orphaned_lemma_id IS NULL AND origin IN ('user_edit','manual')` | Ручная сущность, никогда не была привязана к derived source |
| `source_missing` | `lemma_id IS NULL AND orphaned_lemma_id IS NOT NULL` | Источник был, потом исчез (orphan cleanup) — ручные данные сохранены |
| `auto_only` | `lemma_id IS NULL AND origin = 'mt_auto' AND orphaned_lemma_id IS NULL` | Авто-перевод без пользовательского вклада |

> `stale_against_current_analysis` — отложено за пределы Epic 6.
> source_lifecycle не хранится в БД (computed). Хранятся только поля,
> которые нельзя восстановить после destructive operation: `orphaned_lemma_id`.

---

### B. Матрица stable vs derived fields

| Поле | Тип | Переживает orphan cleanup | Переживает reprocess | Переживает overwrite import |
|------|-----|--------------------------|---------------------|----------------------------|
| `TMEntry.translation` (user_edit) | **stable** | да | да | должно (R2 fix) |
| `TMEntry.status` (approved) | **stable** | да | да | должно (R2 fix) |
| `TMEntry.origin` | **stable** | да | да | должно (R2 fix) |
| `Lemma.is_noise` (manual override) | **stable** | да | да (не пересчитывается) | да |
| `TMEntry.lemma_id` | **hybrid** | → NULL (FK SET NULL) | да | да |
| `TMEntry.orphaned_lemma_id` | **stable** | snapshot перед DELETE | — | — |
| `Lemma.is_noise` (auto) | **derived** | — | не обновляется (bug) | — |
| `Lemma.noise_source` | **stable** (после 6A) | да | да | да |
| `Lemma.noise_updated_at` | **stable** (после 6A) | да | да | да |
| `LemmaProjectStat.freq_abs` | **derived** | пересчитывается | пересчитывается | — |
| `LemmaProjectStat.entity_class` | **derived** | при orphan cleanup: удаляется | обновляется | — |
| `TMEntry.mt_auto translation` | **derived** | да | да | перезаписывается |

---

### C. Перечень destructive operations и их impact surface

| Операция | Код | Поля, которые меняются | Stable fields, которые ОБЯЗАНЫ выжить | Impact preview сейчас |
|----------|-----|------------------------|---------------------------------------|-----------------------|
| Удаление документа | `ingest_service.py:338` | `lemma_doc_stat` (delete), `lemma_project_stat` (delta), orphan `lemma` (delete), `TMEntry.lemma_id` (→NULL) | `TMEntry.translation`, `TMEntry.status`, `TMEntry.origin`, `TMEntry.orphaned_lemma_id` | НЕТ |
| reprocess_document | `process_service.py:2361` | sentences (delete/recreate), `lemma_doc_stat` (delta), `lemma_project_stat` (delta), NOT `Lemma.is_noise` | всё stable в TMEntry | НЕТ |
| orphan lemma cleanup | `process_service.py:1276` | `lemma` (delete), `TMEntry.lemma_id` (→NULL) | `TMEntry.translation`, `TMEntry.orphaned_lemma_id` (нужен snapshot) | НЕТ |
| Batch Translate OVERWRITE | `batch_mt_translate_service.py:501` | `TMEntry.translation`, `TMEntry.origin` (→`mt_auto`) | user_edit+approved не трогать | confirm >100 строк |
| set_lemmas_noise_status_bulk | `dictionary_view.py:1646` | `Lemma.is_noise`, `noise_source` (после 6A) | — | confirm >100 строк |
| _clear_ngrams_and_clusters | `term_extraction_service.py:1126` | `TermCluster`, `Ngram`, `TMEntry.cluster_id` (→NULL) | `TMEntry.promoted_from_cluster_id` (уже snap) | В extraction worker |

---

### D. Write-policy matrix для batch translation

Текущее состояние: два режима (`FILL_EMPTY`, `OVERWRITE`), но нет явной политики
по отношению к manual/approved записям. R2 fix в 6A закрывает минимум.

| Режим | Трогает пустые | Трогает mt_auto | Трогает user_edit | Трогает approved | Приоритет |
|-------|---------------|-----------------|-------------------|-----------------|-----------|
| Fill empty only | да | нет | нет | нет | ✅ сейчас (FILL_EMPTY) |
| Overwrite MT-generated only | нет | да | **нет** | да | 🔲 6A guard (минимум) |
| Overwrite all except approved | нет | да | да | **нет** | 🔲 будущий режим |
| Overwrite all | да | да | да | да | 🔲 с explicit confirm |

**6A минимум:** guard на `origin='user_edit' AND status='approved'` → skip + log.
**Документировать** эту матрицу в docs, чтобы не потерять направление при следующем расширении batch translate.

---

## Подтверждённые риски (по аудиту)

### R1 — Молчаливая потеря TMEntry.lemma_id (HIGH / HIGH)

```
Документ удалён → _cleanup_orphaned_lemmas_for_ids()
→ DELETE lemma → FK ON DELETE SET NULL → TMEntry.lemma_id = NULL
→ source_lifecycle = "manual" (неверно: источник был, просто исчез)
```

Файлы: `process_service.py:1276-1286`, `sa_models.py:942`

**Что не хватает:** snapshot `orphaned_lemma_id` перед DELETE.
С ним: source_lifecycle корректно = `source_missing` (был источник, исчез).

### R2 — Batch Translate OVERWRITE уничтожает user_edit+approved (HIGH / HIGH)

```python
# batch_mt_translate_service.py:505 — всегда, без проверки origin:
existing.origin = "mt_auto"
```

**Минимальный fix 6A:** guard `user_edit+approved → skip`.
**Более полное решение:** write-policy matrix (таблица D выше, в plan).

### R3 — Lemma.is_noise без провенанса (HIGH / MED)

Нет `noise_source`, нет `noise_updated_at`. Нельзя различить auto-classification
от manual override. При reprocess is_noise не обновляется — устаревшая
классификация без временной метки.

**Минимальный fix 6A:** два поля: `noise_source` + `noise_updated_at`.
*Не нужны:* `noise_basis`, `classifier_version` — преждевременно.

### R4 — Observability gaps (HIGH / LOW-MED)

`entity_class` в DTO, но нет колонки. Нет счётчика hidden noise. Нет
status badges для source_lifecycle в Dictionary view.

---

## Implementation Plan

### Epic 6A — Dictionary Safety & Provenance (P0)

#### PATCH-01: Schema — additive fields

Файлы:
- `app/infra/migrations/047_lemma_provenance.sql` (CREATE)
- `app/infra/sa_models.py` — +3 поля
- `app/domain/dto.py` — +2 поля в LemmaStats

```sql
-- 047_lemma_provenance.sql
BEGIN;
ALTER TABLE lemma ADD COLUMN noise_source TEXT;
    -- "auto" (classifier) | "manual" (user override) | NULL (legacy)

ALTER TABLE lemma ADD COLUMN noise_updated_at TEXT;
    -- ISO8601 timestamp, NULL для legacy

ALTER TABLE tm_entry ADD COLUMN orphaned_lemma_id INTEGER;
    -- plain INTEGER, NO FK — snapshot перед orphan DELETE
    -- аналог promoted_from_cluster_id (Epic 5A pattern)

-- Backfill: все существующие classified lemma = auto
UPDATE lemma SET noise_source = 'auto'
  WHERE is_noise IS NOT NULL AND noise_source IS NULL;
COMMIT;
```

```python
# sa_models.py — Lemma:
noise_source = Column(String)      # "auto" | "manual" | None (legacy)
noise_updated_at = Column(String)  # ISO8601 | None

# sa_models.py — TMEntry:
orphaned_lemma_id = Column(Integer)  # snapshot, no FK

# dto.py — LemmaStats:
noise_source: str | None = None
noise_updated_at: str | None = None
```

DoD: migration применяется, все тесты зелёные, behavior без изменений.

#### PATCH-02: Core — R1 snapshot + R2 guard + noise_source writes + source_lifecycle

Файлы:
- `app/services/process_service.py` — orphan cleanup + `_get_or_create_lemmas()`
- `app/services/batch_mt_translate_service.py` — `_write_lemma()`
- `app/ui/dictionary_view.py` — noise override UI
- `app/services/dictionary_service.py` — `compute_source_lifecycle()` helper

**R1 fix** (`process_service.py:1276`): snapshot перед DELETE orphan lemmas:
```python
# UPDATE tm_entry SET orphaned_lemma_id = lemma_id
# WHERE lemma_id IN (:chunk_ids) AND orphaned_lemma_id IS NULL
# (chunked, внутри существующего chunk-цикла, ДО DELETE)
```

**R2 fix** (`batch_mt_translate_service.py:501`):
```python
if existing.origin == "user_edit" and existing.status == "approved":
    logger.info("Skipping user_edit+approved TMEntry tm_id=%d", existing.tm_id)
    return  # защищаем stable fields
```

**noise_source + noise_updated_at writes:**
- `_get_or_create_lemmas()`: при CREATE → `noise_source='auto'`, `noise_updated_at=utcnow()`
- `set_lemma_noise_status()` + bulk: при UPDATE → `noise_source='manual'`, `noise_updated_at=utcnow()`

**source_lifecycle computation** (`dictionary_service.py`):
```python
@staticmethod
def compute_source_lifecycle(lemma_id, orphaned_lemma_id, origin) -> str:
    """Computed (not stored). Maps provenance fields to semantic status."""
    if lemma_id is not None:
        return "linked"
    if orphaned_lemma_id is not None:
        return "source_missing"
    if origin in ("user_edit", "manual"):
        return "manual"
    return "auto_only"
```

DoD:
- [ ] Orphan cleanup сохраняет `orphaned_lemma_id` в TMEntry
- [ ] `source_lifecycle("source_missing")` детектируется корректно
- [ ] Batch Translate OVERWRITE пропускает user_edit+approved
- [ ] Новые леммы: `noise_source='auto'`, `noise_updated_at=now()`
- [ ] Ручной toggle noise: `noise_source='manual'`, `noise_updated_at=now()`
- [ ] Write-policy matrix задокументирована в `docs/epic6_batch_translate_write_policy.md`

#### PATCH-03: Tests

Файл: `tests/test_epic6a_lemma_provenance.py` — 8 тест-кейсов:

1. `test_orphan_cleanup_snapshots_lemma_id` — orphan cleanup → `orphaned_lemma_id` сохранён
2. `test_orphan_cleanup_no_double_snapshot` — idempotency: повторный cleanup не перезаписывает
3. `test_source_lifecycle_linked` — `lemma_id IS NOT NULL` → `"linked"`
4. `test_source_lifecycle_source_missing` — `lemma_id=NULL, orphaned_lemma_id=X` → `"source_missing"`
5. `test_source_lifecycle_manual` — `lemma_id=NULL, orphaned=NULL, origin='user_edit'` → `"manual"`
6. `test_batch_translate_skips_user_edit_approved` — OVERWRITE не перезаписывает
7. `test_batch_translate_overwrites_mt_auto` — regression: mt_auto перезаписывается
8. `test_noise_source_auto_on_create` / `test_noise_source_manual_on_override`

**6A DoD (acceptance criteria):**
- [ ] Удаление/cleanup source не переводит запись молча в `manual` без trace
- [ ] `TMEntry.translation` и `TMEntry.origin` user_edit+approved переживают orphaning
- [ ] `source_missing` однозначно детектируется через `compute_source_lifecycle()`
- [ ] Batch translate OVERWRITE не затирает manual/approved без явного режима
- [ ] `noise_source` manual vs auto различимы и timestamped
- [ ] Regression тесты покрывают: orphan cleanup, delete doc, batch overwrite, reprocess path

---

### Epic 6B — Observability + Status Semantics (P1)

**6B = не просто "видимость", а объяснимость состояния.**
Пользователь должен понимать, что значит каждый badge.

#### PATCH-01: entity_class колонка + noise count + source_lifecycle badge

Файлы: `models_qt.py`, `dictionary_service.py`, `dictionary_view.py`

⚠️ **Основной риск:** column index shift в `LemmaTableModel`.
Translation остаётся col 5. Необходимо обновить ВСЕ `col ==` в `data()`,
`flags()`, `setData()`, tooltips. Regression тест: "Translation editable at col 5".

Изменения:
- Вставить "Entity Class" как col 9 (после "Noise"), сдвинуть 9–11 → 10–12
- `count_noise_lemmas(session, project_id)` → status bar: "N noise hidden"
- source_lifecycle badge в Noise column или отдельная колонка "Status"

#### PATCH-02: Tooltips с полной семантикой

Для каждого состояния — пояснение в tooltip:

| Badge | Tooltip |
|-------|---------|
| linked | "Translation backed by current corpus (lemma exists)" |
| source_missing | "Lemma was deleted from corpus. Translation preserved." |
| manual | "Manually created entry, not linked to corpus" |
| Noise (auto) | "Automatically classified as noise. Source: classifier" |
| Noise (manual) | f"Manually marked as noise on {noise_updated_at}" |

#### PATCH-03: Tests + Docs

Файл: `tests/test_epic6b_dictionary_observability.py` — 6 тест-кейсов

---

### Epic 6C — User Explainability & Docs (P1/P2)

**6C = пользовательский и управленческий контур.**
Не декоративный UX, а user trust: пользователь понимает систему.

#### PATCH-01: User-facing guide

Файл: `docs/epic6_dictionary_guide.md`

Содержание:
- Что значат статусы: linked / source_missing / manual
- Что происходит при reprocess (is_noise не меняется — почему это правильно)
- Почему lemma может стать source_missing
- Как работает batch translate по write-policy matrix
- Troubleshooting: "запись потеряла связь", "перевод стал MT после overwrite"
- Status legend — inline или в sidebar

#### PATCH-02: Completion report + noise badge (small)

Файл: `docs/epic6_completion.md`

Noise badge ("Noise (manual)" / "Valid (manual)") — минимально.
Quick filter "Manual overrides only" — если приоритет оправдан.

---

## Что НЕ входит в Epic 6

| Что | Почему |
|-----|--------|
| `noise_basis` / `classifier_version` | Преждевременно, нет текущего риска |
| `stale_against_current_analysis` | За пределами scope, требует versioning pipeline |
| source_status как в TM (cluster-based) | Другая провенанс-модель; Dictionary = lemma-centric |
| Layered extraction modes для Dictionary | Epic 6D при необходимости |
| FTS health indicator в UI | Отдельная задача |
| Undo для noise override | noise_source+timestamp+manual достаточно |
| Full reprocess with reclassification | Epic 6E |

---

## Risk Register

| Риск | Вероятность | Серьёзность | Митигация |
|------|------------|-------------|-----------|
| Column shift сломает inline Translation edit (col 5) | HIGH (если пропустить `col ==`) | HIGH | Проверить ВСЕ references; regression тест |
| Migration 047 fails | LOW | MED | ALTER TABLE ADD COLUMN в SQLite безопасна; backfill с WHERE IS NULL идемпотентен |
| R2 guard ломает ожидания (хочет overwrite manual) | MED | MED | Только user_edit+approved защищены; skip логируется; write-policy задокументирована |
| orphaned_lemma_id snapshot медленный | LOW | LOW | Chunked; orphan count обычно < 100 строк |
| noise_source backfill неточен для legacy | LOW | LOW | Все legacy = 'auto' — корректно (manual provenance до 6A не писался) |

---

## Rollback Notes

- **6A-01:** поля остаются в schema (SQLite), но NULL и игнорируются. Safe.
- **6A-02:** revert commit. snapshot и guard снимаются.
- **6B-01:** revert LemmaTableModel. Column widths сбросятся автоматически.

---

## Рекомендуемый порядок

```
6A (P0): Safety + Provenance — критические потери данных
  → smoke test на dev DB (проверить orphaned_lemma_id на реальных данных)

6B (P1): Observability + Status Semantics
  → осторожно: column shift в LemmaTableModel

6C (P1/P2): User guide + completion report
```
