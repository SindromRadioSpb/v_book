# Epic 6 — Dictionary Maturity / Lemma Workflow Hardening
## Audit Findings + Implementation Plan

**Дата аудита:** 2026-03-22
**Основа:** Паттерны Epic 4 (провенанс) + Epic 5A (impact preview) + Epic 5C (display-time filters) + Epic 5D (observability)
**Текущий baseline:** 1651 тестов, схема v46

---

## Результаты аудита

### Подтверждённые риски

#### R1 — Молчаливая потеря TMEntry.lemma_id (HIGH / HIGH)

```
Документ удалён
→ remove_document_stats()
→ LemmaProjectStat.freq_abs = 0 → DELETE
→ _cleanup_orphaned_lemmas_for_ids() → DELETE lemma
→ FK ON DELETE SET NULL → TMEntry.lemma_id = NULL
→ source_status = "manual" (неверно — связь была, просто источник удалён)
```

Файлы: `process_service.py:1276-1286`, `sa_models.py:942`

Нет ни предупреждения, ни snapshot. TMEntry с `user_edit` переводом выживает,
но теряет связь с источником без признака того, что это произошло.

#### R2 — Batch Translate OVERWRITE перезаписывает user_edit+approved (HIGH / HIGH)

```
batch_mt_translate_service.py:505:
    existing.origin = "mt_auto"   ← не условное, всегда
```

Пользователь вручную перевёл запись, поставил `approved`. Затем нажал
"Translate All OVERWRITE" → перевод заменён MT, origin молча изменён на `mt_auto`.
Confirm только при >100 строках, без проверки origin.

Файл: `batch_mt_translate_service.py:501-505`

#### R3 — Нет различия auto-classified vs manual noise override (HIGH / MED)

`Lemma.is_noise` перезаписывается пользователем вручную, но нет поля `noise_source`.
Невозможно отличить «классификатор назвал noise» от «пользователь пометил noise».

При `reprocess_document()`: существующая Lemma **не обновляется** (`process_service.py:1143`).
Устаревшая классификация хранится без признака своей версии.

Нельзя: массово откатить только ручные overrides; показать "всё ли ещё автоматически шумовое?"

#### R4 — Observability gaps (HIGH / LOW-MED)

| Пробел | Что есть | Что нужно |
|--------|---------|-----------|
| hidden noise count | нет | "1,287 noise hidden" при hide_noise=True |
| entity_class | в DTO, но нет колонки | отдельная колонка в таблице |
| source_status для lemma TM | нет (только для Terms view) | отдельный дизайн |
| FTS health | только logger.warning | UI indicator |

### Что уже хорошо (не требует изменений)

- **Все UI-фильтры в Dictionary — display-time**: `hide_noise`, `pos_tags`, `search`
  применяются как WHERE при каждом запросе, данные не удаляются.
  Epic 5C-аналог здесь не нужен — всё уже реализовано.
- **source_status для Terms** (`promoted_from_cluster_id`, `promoted_at_params_hash`)
  работает корректно для cluster-kind TMEntry.

---

## Implementation Plan

### Epic 6A — Dictionary Safety & Provenance (P0)

**Цель:** устранить R1 и R2. Критические потери данных.

#### PATCH-01: Schema — additive fields (no behavior change)

Файлы:
- `app/infra/migrations/047_lemma_provenance_noise_source.sql` (CREATE)
- `app/infra/sa_models.py` — добавить 2 колонки
- `app/domain/dto.py` — добавить в LemmaStats

Изменения:
```sql
-- В migration 047:
ALTER TABLE lemma ADD COLUMN noise_source TEXT;
-- Backfill: все существующие classified = 'auto'
UPDATE lemma SET noise_source = 'auto'
  WHERE is_noise IS NOT NULL AND noise_source IS NULL;

ALTER TABLE tm_entry ADD COLUMN orphaned_lemma_id INTEGER;
-- plain INTEGER, no FK — аналог promoted_from_cluster_id
```

```python
# sa_models.py — Lemma:
noise_source = Column(String)  # "auto" | "manual" | NULL (legacy)

# sa_models.py — TMEntry:
orphaned_lemma_id = Column(Integer)  # snapshot перед orphan cleanup
```

DoD: migration применяется, все тесты зелёные, behavior без изменений.

#### PATCH-02: Core — R1 snapshot + R2 guard + noise_source writes

Файлы:
- `app/services/process_service.py` — `_cleanup_orphaned_lemmas_for_ids()` + `_get_or_create_lemmas()`
- `app/services/batch_mt_translate_service.py` — `_write_lemma()`
- `app/ui/dictionary_view.py` — `set_lemma_noise_status()` + bulk noise update

Изменения:

**R1 fix** (`process_service.py:1276`): перед DELETE orphan lemmas — snapshot:
```python
# UPDATE tm_entry SET orphaned_lemma_id = lemma_id
# WHERE lemma_id IN (:ids) AND orphaned_lemma_id IS NULL
# (chunked, внутри существующего chunk-цикла)
```

**R2 fix** (`batch_mt_translate_service.py:501`):
```python
if existing.origin == "user_edit" and existing.status == "approved":
    logger.info("Skipping user_edit+approved TMEntry tm_id=%d", existing.tm_id)
    return   # защищаем ручную работу
```

**noise_source writes**:
- `_get_or_create_lemmas()`: при CREATE нового Lemma → `noise_source='auto'`
- `set_lemma_noise_status()` + bulk: при UPDATE is_noise → `noise_source='manual'`

DoD:
- [ ] Orphan cleanup сохраняет orphaned_lemma_id в TMEntry
- [ ] OVERWRITE пропускает user_edit+approved
- [ ] Новые леммы = noise_source='auto'
- [ ] Ручной toggle noise = noise_source='manual'

#### PATCH-03: Tests

Файл: `tests/test_epic6a_lemma_provenance.py` — 7 тест-кейсов:
1. `test_orphan_cleanup_snapshots_lemma_id`
2. `test_orphan_cleanup_no_double_snapshot` (idempotency)
3. `test_batch_translate_skips_user_edit_approved`
4. `test_batch_translate_overwrites_mt_auto` (регрессия)
5. `test_noise_source_auto_on_create`
6. `test_noise_source_manual_on_override`
7. `test_noise_source_backfill` (migration 047)

---

### Epic 6B — Dictionary Observability & Noise Lifecycle (P1)

**Цель:** устранить R3 + R4. Показать пользователю то, что скрыто.

#### PATCH-01: UI — entity_class колонка + noise count

Файлы:
- `app/ui/models_qt.py` — `LemmaTableModel.headers` + `data()`
- `app/services/dictionary_service.py` — `count_noise_lemmas()`
- `app/ui/dictionary_view.py` — status bar

Изменения:
- Вставить "Entity Class" как col 9 в LemmaTableModel (после "Noise")
- Сдвинуть все существующие col 9-11 → 10-12
- Обновить все `col ==` в `data()`, `flags()`, `setData()`, tooltips

⚠️ **Основной риск этого патча**: column index shift.
Translation (col 5) не сдвигается — должна оставаться editable.
Критично проверить: все `col ==` в `setData()`, `flags()`, selection logic.

- `count_noise_lemmas(session, project_id)` → статус-бар: "1,287 noise hidden"

#### PATCH-02: noise_source display — tooltips

- Tooltip на Noise column: "Reason: X\nSource: auto/manual"
- DTO маппинг noise_source из DB → LemmaStats

#### PATCH-03: Tests + Docs

Файл: `tests/test_epic6b_dictionary_observability.py` — 5 тест-кейсов

---

### Epic 6C — Dictionary UX / Explainability (P1/P2)

**Цель:** noise source badge + quick filter "Manual overrides only".

#### PATCH-01: noise badge + filter

- Noise column: "Noise (manual)" / "Valid (manual)" / "Noise" / "Valid"
- Новый checkbox "Manual overrides only" в Dictionary filters
- `dictionary_service._apply_filters()`: поддержка `show_manual_noise_only`

#### PATCH-02: Tests

Файл: `tests/test_epic6c_dictionary_ux.py` — 3 тест-кейса

---

## Что НЕ входит в Epic 6

| Что | Почему |
|-----|--------|
| source_status для lemma-kind TMEntry | Требует отдельного дизайна: у lemma нет cluster provenance chain |
| Layered modes для Dictionary (Merge / Replace layer) | Epic 6D при необходимости |
| FTS health indicator в UI | Отдельная задача, не блокирует safety |
| Candidate persistence | Не нужна — фильтры уже display-time |
| Undo для noise override | Пользователь может повторить toggle |
| Reprocess NLP with reclassification | R3 частично решён noise_source; полная переклассификация — Epic 6E |

---

## Risk Register

| Риск | Вероятность | Серьёзность | Митигация |
|------|------------|-------------|-----------|
| Column shift сломает inline Translation edit | HIGH (если пропустить хотя бы один `col ==`) | HIGH | Проверить ВСЕ col references; regression тест "Translation editable at col 5" |
| Migration 047 на corrupted DB | LOW | MED | ALTER TABLE ADD COLUMN в SQLite идемпотентна по смыслу; backfill с WHERE IS NULL безопасен |
| R2 guard ломает ожидания пользователя | MED | MED | Только user_edit+approved защищены; mt_auto+approved перезаписывается; skip логируется |
| noise_source backfill неточен для legacy | LOW | LOW | Все legacy = 'auto' — корректно, т.к. manual provenance до 6A не писался |
| orphaned_lemma_id snapshot медленный | LOW | LOW | Обычно orphan count < 100 строк; chunked по chunk_ids |

---

## Rollback Notes

- **6A-01 rollback**: поля orphaned_lemma_id и noise_source остаются в schema
  (SQLite DROP COLUMN требует 3.35+), но NULL и игнорируются. Safe.
- **6A-02 rollback**: revert commit. R2 guard снимается, snapshot не пишется.
- **6B-01 rollback**: revert LemmaTableModel headers. QSettings column widths
  сбросятся автоматически при следующем открытии.

---

## Рекомендуемый порядок работы

1. **Epic 6A** полностью (3 патча) — критические данные
2. Smoke test на dev DB, убедиться что orphaned_lemma_id корректно пишется
3. **Epic 6B PATCH-01** осторожно (риск column shift) — entity_class + noise count
4. Regression + manual smoke
5. **Epic 6B PATCH-02-03** + **Epic 6C** по состоянию приоритетов
