# Epic 5A — TM Safety & Provenance: Completion Report

**Дата завершения:** 2026-03-22
**Схема:** v44 → v45 (migration 045)
**Commits:** 6956bfe → 688b278 (6 коммитов)

---

## Цель

Устранить фундаментальный дефект: переизвлечение терминов молча осиротевляло
TM-записи (`cluster_id → NULL`) без уведомления пользователя и без audit trail.
Добавить провенанс, lifecycle-статусы и защитный preview перед destructive операцией.

---

## Что добавили

### PATCH-01 — Migration 045: провенанс-колонки

Три новых колонки на `tm_entry`:

| Колонка | Тип | Семантика |
|---------|-----|-----------|
| `promoted_from_cluster_id` | `INTEGER` (plain, no FK) | Снимок `cluster_id` в момент промоции. Никогда не перезаписывается. Переживает удаление кластера. |
| `promoted_at_params_hash` | `TEXT` | SHA-256[:16] параметров извлечения на момент промоции. Скопирован из `term_extract_run.params_hash`. |
| `promoted_at_run_id` | `INTEGER FK → term_extract_run(SET NULL)` | Мягкая ссылка на run; идёт в NULL при удалении run'а (run'ы могут прунироваться). |

### PATCH-02 — Заполнение провенанса при промоции

Два места установки `cluster_id` теперь также заполняют провенанс:

- `_attach_source_links()` — одиночные записи
- `update_item_translation()` bulk creation path

**Правило idempotency:** `promoted_from_cluster_id` устанавливается **один раз** при
первой привязке. При повторных re-link — **не перезаписывается**.

Новый helper: `_get_last_run_provenance(session, project_id)` → последний `ok`-run.

### PATCH-03 — Impact preview перед Full Overwrite

`TermExtractionService.get_overwrite_impact(session, project_id)` — два COUNT-запроса:
- сколько кластеров будет удалено
- сколько TM-записей потеряют активную ссылку (станут `source_cluster_missing`)

В `terms_view.on_extract()`: если `linked_tm_entries > 0` — показывается
`QMessageBox.question` с конкретными числами перед стартом воркера.
Показывается **только** при наличии угрозы, иначе — silent start.

### PATCH-04 — source_status в TM UI

**`source_status` — вычисляемый, не хранимый:**

| Значение | Условие | Смысл |
|----------|---------|-------|
| `linked` | `cluster_id IS NOT NULL` | Кластер жив |
| `source_cluster_missing` | `cluster_id IS NULL AND promoted_from_cluster_id IS NOT NULL` | Кластер удалён при переизвлечении |
| `manual` | `cluster_id IS NULL AND promoted_from_cluster_id IS NULL` | Добавлена вручную |

Реализован как `@property` на `TMEntry` (SA model) и `TMEntryDTO` (domain).

В `TranslationManagementTableModel` — новая колонка **"Src"** (col 14):
- ● зелёный — `linked`
- ● красный — `source_cluster_missing`
- ● серый — `manual`

Tooltip на `source_cluster_missing`: оригинальный `cluster_id` + `params_hash`.

### PATCH-05 — Lifecycle тесты

5 интеграционных тестов: переход `linked → source_cluster_missing` после delete,
permanence `promoted_from_cluster_id`, соответствие DTO ↔ SA model, прогноз impact.

---

## User-visible changes

1. **TM panel**: колонка "Src" показывает состояние связи с кластером-источником.
   Красный ● → сразу видно, что этот термин был в extraction, кластер удалён,
   но перевод сохранён.

2. **Extract Terms**: если в TM есть активные ссылки на кластеры, перед стартом
   появляется диалог: "847 кластеров / 124 TM-записи потеряют активную ссылку.
   Продолжить?" Пользователь может отменить.

3. **Tooltip на красной ●**: показывает `promoted_from_cluster_id` и `params_hash`,
   при котором термин был извлечён — полный audit trail.

---

## Data model changes

```
tm_entry
  + promoted_from_cluster_id  INTEGER          -- plain int, no FK, permanent
  + promoted_at_params_hash   TEXT             -- snapshot of params at promotion
  + promoted_at_run_id        INTEGER FK(SET NULL) → term_extract_run(run_id)
```

**Migration:** `app/infra/migrations/045_tm_entry_provenance.sql`
**Schema version:** 45

---

## Lifecycle contract

```
[term_cluster]  ← volatile, freely re-extracted
      ↓  promote (explicit user action)
[tm_entry]      ← curated library
  cluster_id            = live FK link (→ NULL on re-extraction)
  promoted_from_cluster_id = historical snapshot (permanent, never NULL after first promotion)
  promoted_at_params_hash  = which extraction settings produced this cluster
  promoted_at_run_id       = which run (soft, SET NULL when run pruned)

source_status (computed):
  cluster_id IS NOT NULL                                    → 'linked'
  cluster_id IS NULL AND promoted_from_cluster_id IS NOT NULL → 'source_cluster_missing'
  cluster_id IS NULL AND promoted_from_cluster_id IS NULL   → 'manual'
```

**Key invariant:** TM entry никогда не удаляется при переизвлечении.
Только `cluster_id` идёт в NULL (FK SET NULL). Провенанс — вечен.

---

## Тестовое покрытие

| Файл теста | Тестов | Что проверяет |
|-----------|--------|---------------|
| `test_epic5a_patch01_provenance_schema.py` | 9 | Колонки, nullable, FK SET NULL, source_status property |
| `test_epic5a_patch02_provenance_populate.py` | 5 | Заполнение при промоции, idempotency, ok-run selection, no-run fallback |
| `test_epic5a_patch03_overwrite_impact.py` | 5 | Impact counts: empty, cluster count, linked/unlinked, project scoping |
| `test_epic5a_patch05_lifecycle.py` | 5 | E2E lifecycle: delete → status change, DTO parity, impact forecast |

**Итого:** 24 новых теста. Полная регрессия: **1606 passed**.

---

## Deferred items (не входят в 5A)

- **Фильтр в TM view**: "Показать только source_cluster_missing" — задача для Epic 5A+
- **Bulk re-link**: "Найти новый кластер по canonical_key и переприкрепить" — Epic 5B+
- **Audit log**: запись в отдельную таблицу когда `cluster_id` идёт в NULL — Future

---

## Следующий этап

**Epic 5B — Layered Extraction Modes** (migration 046):
- `ngram_n_set` на `term_cluster` (различать n=2 от n=3)
- Режимы: Full Overwrite / Merge / Replace Layer
- Scoped delete по n-слою вместо бланкетного `_clear_existing_terms()`
