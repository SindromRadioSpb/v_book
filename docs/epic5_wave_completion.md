# Epic 5 Wave Completion Report — TM Safety & Layered Extraction

**Дата завершения:** 2026-03-22
**Охват:** Epic 5A (PATCH-01..05) + Epic 5B (PATCH-06..10)
**Схема:** v44 → v46 (миграции 045, 046)
**Installer:** `HDLE_Premium_Setup.exe` (2426 MB, build 2026-03-22)
**Test baseline:** 1638 passed, 0 regression

---

## Контекст и мотивация

До Epic 5 переизвлечение терминов было фундаментально небезопасной операцией:
- TM-записи молча теряли ссылки (`cluster_id → NULL`) без уведомления
- Не было audit trail: неизвестно, когда и из какого кластера создана запись
- Единственный режим — Full Overwrite: нельзя было переизвлечь только один n-слой
- Нельзя было добавить новые паттерны без уничтожения кюрации на кластерах

Epic 5 решает обе проблемы как единую инженерную задачу:
**5A** — защита существующего (провенанс + lifecycle статусы),
**5B** — инструмент управления (три режима извлечения).

---

## Epic 5A — TM Safety & Provenance

### Что добавлено

**Провенанс на `tm_entry` (migration 045):**

| Колонка | Семантика |
|---------|-----------|
| `promoted_from_cluster_id` | Снимок cluster_id в момент промоции. Permanent, no FK. |
| `promoted_at_params_hash` | SHA-256[:16] параметров extraction run. |
| `promoted_at_run_id` | FK → term_extract_run, SET NULL при удалении run. |

**source_status — вычисляемый lifecycle-статус:**

| Статус | Условие |
|--------|---------|
| `linked` | cluster_id IS NOT NULL |
| `source_cluster_missing` | cluster_id IS NULL AND promoted_from_cluster_id IS NOT NULL |
| `manual` | cluster_id IS NULL AND promoted_from_cluster_id IS NULL |

**Impact preview (Full Overwrite):**
`get_overwrite_impact()` — два COUNT-запроса перед destructive операцией.
Диалог подтверждения с конкретными числами (кластеры / linked TM).
Показывается только при наличии реальной угрозы.

**UI:** Колонка "Src" в TM панели — цветной индикатор ● (зелёный/красный/серый),
tooltip с деталями провенанса при `source_cluster_missing`.

### Ключевые решения

- `promoted_from_cluster_id` — plain INTEGER, не FK. Переживает удаление кластера навсегда.
- `source_status` — вычисляется в runtime, не хранится. Исключает drift денормализованного поля.
- `promoted_at_run_id` FK SET NULL — run'ы можно прунировать, провенанс не теряется.

---

## Epic 5B — Layered Extraction Modes

### Что добавлено

**ngram_n_set на term_cluster (migration 046):**
Canonical JSON-массив n-размеров кластера: `"[2]"`, `"[3]"`, `"[2,3]"`, NULL для NP.
Индекс `(project_id, ngram_n_set)` для скоупированных удалений.

**Три режима в UI (combo box в Terms view):**

| Режим | Что делает | Что сохраняет |
|-------|-----------|---------------|
| Full Overwrite | Удаляет всё, переизвлекает заново | TM-записи + провенанс |
| Merge | Добавляет новые кластеры/ngrams, не удаляя | Всё существующее + кюрацию |
| Replace Layer | Удаляет только кластеры целевого n-set, переизвлекает их | NP + другие слои + кюрацию |

**Service dispatch:**
- `"overwrite"` → `_extract_terms_for_project_chunked(overwrite=True)`
- `"merge"` → chunked с `overwrite=False` (INSERT OR IGNORE + pre-check)
- `"replace_layer"` → `_clear_terms_for_layer(ngram_ns)` + chunked, `resume_latest=False`

**Merge semantics (overwrite=False):**
- ngrams: `sqlite_insert().on_conflict_do_nothing()` + SELECT для id
- clusters: pre-check на existing canonical_key; если есть — link только новые члены, кюрация не затронута
- NgramProjectStat: вставляется только для новых ngrams

**Replace Layer:**
`_clear_terms_for_layer` — удаляет по exact match `ngram_n_set`, не задевает другие слои и NP.
Backward-compat: `overwrite=False` с дефолтным `extraction_mode` → merge.

### Ключевые решения

- `ngram_n_set` как JSON, не enum — расширяемо на 4-граммы без изменения схемы.
- Replace Layer — exact match по `ngram_n_set`. Кластер `"[2,3]"` не удалится при Replace `"[2]"`.
- `resume_latest=False` в Replace Layer — checkpoint стал невалидным после удаления слоя.
- Выбор режима сохраняется в QSettings между сессиями.

---

## Scope & File Map

### Новые файлы
| Файл | Назначение |
|------|-----------|
| `app/infra/migrations/045_tm_entry_provenance.sql` | Провенанс-колонки |
| `app/infra/migrations/046_term_cluster_ngram_n_set.sql` | ngram_n_set + index |
| `tests/test_epic5a_patch01_provenance_schema.py` | 9 тестов |
| `tests/test_epic5a_patch02_provenance_populate.py` | 5 тестов |
| `tests/test_epic5a_patch03_overwrite_impact.py` | 5 тестов |
| `tests/test_epic5a_patch05_lifecycle.py` | 5 тестов |
| `tests/test_epic5b_patch06_ngram_n_set.py` | 10 тестов |
| `tests/test_epic5b_patch07_extraction_mode.py` | 8 тестов |
| `tests/test_epic5b_patch08_merge_mode.py` | 5 тестов |
| `tests/test_epic5b_patch09_replace_layer.py` | 10 тестов |
| `docs/epic5a_completion.md` | Epic 5A completion report |
| `docs/epic5b_extraction_modes.md` | User guide + design reference |

### Изменённые файлы
- `app/infra/sa_models.py` — TMEntry (3 колонки + source_status), TermCluster (ngram_n_set)
- `app/domain/dto.py` — TMEntryDTO (3 колонки + source_status)
- `app/services/term_extraction_service.py` — canonical_ngram_n_set, get_overwrite_impact, extraction_mode dispatch, _clear_terms_for_layer, merge-aware insert
- `app/services/user_dictionary_service.py` — _get_last_run_provenance, _attach_source_links
- `app/services/translation_admin_service.py` — _entry_to_dto маппинг
- `app/ui/terms_view.py` — extraction mode combo, impact preview
- `app/ui/models_qt.py` — "Src" колонка (col 14)
- `app/ui/workers.py` — extraction_mode kwarg
- `hdle_premium_installer.spec` — translation_admin_service в hiddenimports

---

## Тест-покрытие

**57 новых тестов** в 8 файлах.
Полный suite: **1638 passed, 0 regression** (1 pre-existing broken test — вне scope).

Тест-категории:
- Schema (column presence, FK constraints, SET NULL behavior)
- Populate (provenance fills, idempotency)
- Impact (COUNT accuracy, scoping)
- Lifecycle (source_status transitions)
- ngram_n_set (canonical format, dedup, sort)
- Extraction mode dispatch (worker kwargs, service routing)
- Merge semantics (OR IGNORE, pre-check, member linking)
- Replace Layer (clear scope, n-set precision, NP preservation)

---

## Packaging

- Prebuild validation: ✅ 5/5 checks (включая первое применение migration 045+046 к prod DB)
- Автоматический backup перед миграцией: ✅ создан
- PyInstaller: ✅ exit 0, нет новых WARNING
- Migrations 045/046 в `dist/_internal/`: ✅
- Inno Setup installer: ✅ 2426 MB
- Post-build smoke: ✅ PASS, exit code 0

---

## Что за рамками (явно)

- **Epic 5C** (Candidate Persistence): min_freq как display-time фильтр, расширенный пул кандидатов — отдельная волна.
- Обновление частот существующих кластеров в Merge mode — не реализовано по дизайну (additive-only семантика).
- Replace Layer для NP-слоя — не поддерживается; workaround: Merge с include_np=True.

---

## DoD Checklist

- [x] Epic 5A: провенанс записывается при промоции (два пути)
- [x] Epic 5A: source_status отображается в TM UI
- [x] Epic 5A: impact preview перед Full Overwrite
- [x] Epic 5B: три режима извлечения в UI
- [x] Epic 5B: Merge сохраняет кюрацию кластеров
- [x] Epic 5B: Replace Layer изолирует удаление по n-слою
- [x] Миграции 045+046 применены к prod DB
- [x] 57 тестов добавлены и проходят
- [x] Regression suite: 0 новых падений
- [x] Docs: completion report + user guide
- [x] Packaging: installer собран и smoke-проверен
