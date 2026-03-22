# Epic 5: TM Safety, Provenance & Layered Extraction

**Status:** Epic 5A complete; Epic 5B planned
**Schema:** v44 → v45 (Epic 5A), v46 (Epic 5B)

---

## Главная проблема

Система содержит два мира с несовместимыми жизненными циклами:

| Слой | Таблицы | Жизненный цикл |
|------|---------|----------------|
| **Volatile** | `term_cluster`, `ngram` | Свободно переизвлекается, перезаписывается |
| **Stable** | `tm_entry`, `tm_global` | Курируемая библиотека знаний, не должна разрушаться |

Сейчас переизвлечение молча осиротевляет TM-записи (`cluster_id → NULL`) без уведомления пользователя и без каких-либо lifecycle-статусов. Это недопустимое поведение для профессиональной системы.

**Правильная модель:**

```
[Corpus documents]
      ↓  extract (volatile, freely re-runnable)
[term_cluster]   ← candidates layer
      ↓  promote (explicit user action: translate/curate)
[tm_entry / tm_global]  ← knowledge library, must survive re-extraction
      ↓  audit trail
[provenance: params_hash, run_id, promoted_from_cluster_id]
```

---

## Ключевые факты (confirmed from codebase)

- `cluster_id` на `tm_entry` устанавливается **после** создания записи, через
  `_attach_source_links()` / bulk creation в `user_dictionary_service.py`
- `FK cluster_id → term_cluster` имеет `ondelete="SET NULL"` — при удалении кластера
  TM-запись **выживает, но теряет ссылку**
- `source_kinds` в `term_cluster` различает только `'ngram'` vs `'np'` —
  **не различает n=2 (bigrams) и n=3 (trigrams)**
- `_clear_existing_terms()` — бланкетное удаление по `project_id`, без возможности
  выбора слоя
- `params_hash` есть только на `term_extract_run`, на `tm_entry` — **нет**

---

## Patch Series

### Epic 5A — TM Safety & Provenance

| Patch | Status | Description |
|-------|--------|-------------|
| PATCH-01 | ✅ done | Migration 045: provenance columns на tm_entry |
| PATCH-02 | ✅ done | Populate provenance при promotion (attach + bulk create) |
| PATCH-03 | ✅ done | Impact preview перед destructive overwrite |
| PATCH-04 | ✅ done | source_status в UI Translation Management |
| PATCH-05 | ✅ done | Тесты: провенанс, статусы, impact count |

### Epic 5B — Layered Extraction Modes

| Patch | Status | Description |
|-------|--------|-------------|
| PATCH-06 | ✅ done | Migration 046: ngram_n_set на term_cluster |
| PATCH-07 | ✅ done | Extraction mode selector в UI + worker/service wiring (overwrite/merge/replace_layer) |
| PATCH-08 | ✅ done | Merge mode: chunked path с overwrite=False; INSERT OR IGNORE для ngrams; pre-check для clusters |
| PATCH-09 | 🔄 planned | Replace Layer mode: скоупированное удаление по n-слою |
| PATCH-10 | 🔄 planned | Тесты: все три режима, граничные случаи |

### Epic 5C — Candidate Persistence (future)

| Patch | Status | Description |
|-------|--------|-------------|
| PATCH-11+ | 🔄 future | min_freq как display-time фильтр вместо extraction-time |
| PATCH-12+ | 🔄 future | Хранение расширенного пула кандидатов |

---

## Epic 5A — TM Safety & Provenance (детали)

### PATCH-01 — Migration 045: provenance columns

**Новые колонки на `tm_entry`:**

```sql
ALTER TABLE tm_entry ADD COLUMN promoted_from_cluster_id INTEGER;
-- Снимок cluster_id в момент промоции. Обычный INTEGER, не FK (не CASCADE).
-- Никогда не обнуляется автоматически. Сохраняет историю даже после удаления кластера.

ALTER TABLE tm_entry ADD COLUMN promoted_at_params_hash TEXT;
-- SHA-256[:16] хэш параметров извлечения на момент промоции.
-- Берётся из term_extract_run.params_hash активного run'а.

ALTER TABLE tm_entry ADD COLUMN promoted_at_run_id INTEGER
    REFERENCES term_extract_run(run_id) ON DELETE SET NULL;
-- Ссылка на run, при котором кластер был промоутирован.
```

**`source_status` — вычисляемый, не хранимый:**

```python
# Вычисляется at query time, не хранится в БД
def compute_source_status(tm_entry) -> str:
    if tm_entry.cluster_id is not None:
        return "linked"
    if tm_entry.promoted_from_cluster_id is not None:
        return "source_cluster_missing"
    return "manual"
```

| Значение | Условие | Смысл |
|----------|---------|-------|
| `linked` | `cluster_id IS NOT NULL` | Кластер жив, связь активна |
| `source_cluster_missing` | `cluster_id IS NULL AND promoted_from_cluster_id IS NOT NULL` | Кластер был удалён (re-extraction) |
| `manual` | `cluster_id IS NULL AND promoted_from_cluster_id IS NULL` | Добавлена вручную, без кластера-источника |

---

### PATCH-02 — Populate provenance при promotion

**Два места установки `cluster_id`:**

1. `user_dictionary_service.py` → `_attach_source_links()` (одиночная запись)
2. `user_dictionary_service.py` → bulk creation

В обоих местах при установке `cluster_id` → также устанавливать:
- `promoted_from_cluster_id = cluster_id` (если ещё NULL — первичная промоция)
- `promoted_at_params_hash` — запросить `term_extract_run.params_hash` для проекта
- `promoted_at_run_id` — ID последнего успешного run

**Правило:** `promoted_from_cluster_id` устанавливается **один раз** при первой привязке к кластеру. При повторных привязках (после merge/re-extraction) — **не перезаписывается**, сохраняет историческую ссылку.

---

### PATCH-03 — Impact preview перед destructive overwrite

**Где внедрить:** перед вызовом `_clear_existing_terms()` в `extract_terms_for_project()`
(режим Full Overwrite).

**Impact query:**

```python
def _get_overwrite_impact(session: Session, project_id: int) -> dict:
    cluster_count = session.execute(
        select(func.count()).where(TermCluster.project_id == project_id)
    ).scalar() or 0

    linked_tm_count = session.execute(
        select(func.count())
        .select_from(TMEntry)
        .where(TMEntry.project_id == project_id)
        .where(TMEntry.cluster_id.is_not(None))
    ).scalar() or 0

    return {"clusters": cluster_count, "linked_tm_entries": linked_tm_count}
```

**UI диалог (не просто QMessageBox.question):**

```
⚠ Full Overwrite будет выполнен

Будет удалено:
  • 847 кластеров терминов
  • 124 TM-записи потеряют активную связь с кластером
    (они сохранятся в TM, но получат статус "source_cluster_missing")

Продолжить?  [Отмена]  [Да, пересобрать]
```

Показывается только если `linked_tm_count > 0`.

---

### PATCH-04 — source_status в UI Translation Management

**В TM view (колонка Source / Status):**

| Индикатор | source_status | Tooltip |
|-----------|--------------|---------|
| 🟢 | `linked` | Кластер активен в текущем извлечении |
| 🔴 | `source_cluster_missing` | Источник удалён при переизвлечении. Запись сохранена. |
| ⚫ | `manual` | Добавлена вручную, без источника-кластера |

**Дополнительно:**
- Фильтр в TM view: «Показать только source_cluster_missing»
- Tooltip на 🔴 записях: «Извлечено при params_hash=XXXX, run #N»

---

### PATCH-05 — Тесты

- Провенанс заполняется при первой привязке (`promoted_from_cluster_id` не NULL)
- Повторная привязка не перезаписывает `promoted_from_cluster_id`
- После re-extraction: `cluster_id=NULL`, `promoted_from_cluster_id` сохранён
- `compute_source_status()` для всех трёх состояний
- `_get_overwrite_impact()` корректно считает linked TM entries
- Impact preview не показывается если `linked_tm_count == 0`

---

## Epic 5B — Layered Extraction Modes (детали)

### PATCH-06 — Migration 046: ngram_n_set на term_cluster

**Проблема:** `source_kinds` различает только `'ngram'` vs `'np'`. Для Replace Layer нужно
знать, какие **n-размеры** входят в кластер (n=2, n=3, или оба).

```sql
ALTER TABLE term_cluster ADD COLUMN ngram_n_set TEXT;
-- Значения: '2', '3', '2,3', NULL (для NP-only кластеров)
-- Формат: sorted comma-separated n-values
-- Примеры: кластер из только биграмм → '2'
--           кластер из биграмм и триграмм → '2,3' (теоретически невозможно
--           при раздельном извлечении, но возможно в merge mode)
```

**Устанавливается в `_insert_cluster_from_members()`:**

```python
ngram_ns = sorted({
    int(m["n"]) for m in members
    if m["source_kind"] == "ngram" and m.get("n") is not None
})
ngram_n_set = ",".join(str(n) for n in ngram_ns) if ngram_ns else None
```

---

### PATCH-07 — Extraction mode selector в UI

**Три режима** (заменяют текущий чекбокс `overwrite`):

| Режим | Поведение | Когда использовать |
|-------|-----------|-------------------|
| **Full Overwrite** | Удалить всё, пересобрать (текущее поведение) | Первый запуск, или полная пересборка |
| **Merge** | Добавить новые термины, не удаляя существующие | Добавить триграммы к уже извлечённым биграммам |
| **Replace Layer** | Заменить только указанный n-слой или NP | Переизвлечь только биграммы с новым min_freq |

**UI:** RadioButton-группа или ComboBox в Extraction Controls.
При выборе «Replace Layer» → показать чекбоксы выбора слоя (Bigrams / Trigrams / NP).

**Замечание:** Первое извлечение может быть Bigrams, Bigrams+Trigrams, или только Trigrams —
Replace Layer должен корректно работать в любом случае. Если слой не существует в проекте —
Replace Layer для него эквивалентен Merge (добавляет, не удаляет).

---

### PATCH-08 — Merge mode

**Алгоритм:**

1. НЕ вызывать `_clear_existing_terms()`
2. Запустить extraction pipeline (collect ngrams/NP)
3. При вставке в `term_cluster`: если `canonical_key` уже существует →
   **upsert**: обновить `freq_abs`, `doc_freq`, `members_count`, метрики
4. При вставке в `ngram`: если `(project_id, surface_text, source_kind, n)` уже есть →
   обновить freq, не дублировать
5. После кластеризации: пересчитать `ngram_n_set` для затронутых кластеров

**Правило для `params_hash`:**

В режиме Merge `params_hash` в run описывает параметры **добавленного слоя**, а не всего проекта.
Resume gating не применяется (Merge всегда создаёт новый run).

---

### PATCH-09 — Replace Layer mode

**Алгоритм для Replace n-слоя (например, n=3):**

```python
def _clear_terms_by_layer(
    session: Session,
    project_id: int,
    *,
    ngram_ns: tuple[int, ...] | None = None,  # (2,), (3,), (2,3)
    clear_np: bool = False,
) -> dict:
    """Selective delete: only specified layers."""

    # 1. Find ngrams to delete
    ngram_query = select(Ngram.ngram_id).where(Ngram.project_id == project_id)
    if ngram_ns:
        ngram_query = ngram_query.where(Ngram.n.in_(ngram_ns))
        if not clear_np:
            ngram_query = ngram_query.where(Ngram.source_kind == "ngram")

    ngram_ids = [r[0] for r in session.execute(ngram_query).all()]

    # 2. Find clusters whose ALL members belong to deleted layer
    #    (clusters with members from other layers must survive)
    # ... (see implementation notes below)

    # 3. Delete orphaned clusters only
    # 4. Delete target ngrams (CASCADE removes their members, stats, components)
```

**Сложный случай:** кластер с `ngram_n_set='2,3'` (Merge после раздельного извлечения):
при Replace Layer n=3 → не удалять кластер, но обновить `ngram_n_set='2'`.

---

### PATCH-10 — Тесты

- Full Overwrite: существующие TM entries получают `source_cluster_missing`
- Merge n=3 при существующих n=2: биграммовые кластеры не тронуты
- Replace Layer n=3: триграммовые кластеры удалены, биграммовые живы
- Replace Layer несуществующего слоя: без ошибок, без изменений
- params_hash отражает добавленный слой в Merge mode
- Impact preview корректно считает для Full Overwrite (Merge и Replace не требуют preview)

---

## Epic 5C — Candidate Persistence (future)

**Цель:** `min_freq` и аналогичные параметры переводятся из extraction-time в display-time фильтры.

**Текущее состояние:**
- `min_freq` — extraction-time: термины ниже порога **не сохраняются** в БД
- `min_doc_freq` — display-time (PATCH-10 Epic 4): термины сохраняются, скрываются в UI

**Целевое состояние:**
- Хранить более широкий пул кандидатов при извлечении
- Фильтровать при отображении и ранжировании
- Destructive re-extract только при явном намерении пользователя

**Переход:**

PATCH-11: `min_freq` как display-time фильтр (по аналогии с `min_doc_freq`)
- При извлечении использовать низкий системный порог (например, 1)
- В UI добавить slider/spin с предупреждением «Не влияет на хранимые данные»

PATCH-12: Candidate pool management
- UI для просмотра всех кандидатов включая "ниже порога"
- Возможность вручную промоутировать кандидата ниже порога в TM

---

## Схема изменений

### Migration 045 (Epic 5A, PATCH-01)

```sql
ALTER TABLE tm_entry ADD COLUMN promoted_from_cluster_id INTEGER;
ALTER TABLE tm_entry ADD COLUMN promoted_at_params_hash TEXT;
ALTER TABLE tm_entry ADD COLUMN promoted_at_run_id INTEGER
    REFERENCES term_extract_run(run_id) ON DELETE SET NULL;
```

### Migration 046 (Epic 5B, PATCH-06)

```sql
ALTER TABLE term_cluster ADD COLUMN ngram_n_set TEXT;
-- NULL для NP-only кластеров
-- '2' для биграммовых кластеров
-- '3' для триграммовых
-- '2,3' для смешанных (в merge mode)
```

---

## Требования (утверждены)

| ID | Приоритет | Требование |
|----|-----------|-----------|
| T1 | P0 | TM не теряет смысловую целостность при re-extraction. Записи сохраняются с понятным статусом. |
| T2 | P0 | Каждая TM-запись хранит провенанс: `promoted_from_cluster_id`, `promoted_at_params_hash`, `promoted_at_run_id` |
| T3 | P1 | Extract имеет три явных режима: Full Overwrite / Merge / Replace Layer |
| T4 | P1 | TM UI показывает `source_status`: linked / source_cluster_missing / manual |
| T5 | P1 | Destructive overwrite показывает impact preview (кол-во кластеров + TM-записей) |
| T6 | P2 | Replace Layer работает по n-размеру (Bigrams / Trigrams / NP) независимо |
| T7 | P2 | Merge mode не удаляет существующие кластеры другого слоя |
| T8 | P3 | min_freq переводится в display-time фильтр (Epic 5C) |

---

## Риски

| Риск | Митигация |
|------|-----------|
| Merge создаёт дубликаты при конкурентном запуске | Unique constraint на (project_id, canonical_key) в term_cluster; upsert через INSERT OR REPLACE |
| Replace Layer для смешанного кластера (n=2+n=3 в Merge) | Кластер выживает, `ngram_n_set` обновляется, не удаляется |
| params_hash в Merge описывает только добавленный слой, а не весь проект | Документировать: params_hash всегда относится к конкретному run, не к проекту |
| Большой impact preview при первом обнаружении проблемы (много TM-сирот) | Batch fix: отдельный диалог «Repair provenance» для существующих TM-записей |

---

## Troubleshooting (будущий)

**TM-запись показывает 🔴 source_cluster_missing:**
Кластер был удалён при re-extraction. Запись сохранена. Данные `promoted_from_cluster_id`
и `promoted_at_params_hash` показывают, при каком извлечении она была создана.
Действие: используйте Merge или вручную свяжите с новым кластером.

**Impact preview показывает 0 при наличии TM-записей:**
TM-записи были созданы без привязки к кластеру (legacy или ручное добавление).
У них `cluster_id IS NULL` и `promoted_from_cluster_id IS NULL` → статус `manual`.

**Replace Layer не удаляет ожидаемые кластеры:**
Проверьте `ngram_n_set` кластеров через Terms view (нужен диагностический режим).
Возможно, кластеры были созданы в Merge mode и содержат члены из другого слоя.
