# Epic 5C Completion Report — Candidate Persistence

**Дата:** 2026-03-22
**Схема:** v46 (без миграций — все колонки уже существовали)
**algo_version:** 1 → 2
**Тесты:** +14 (5 новых в epic5c + 9 обновлённых в params_hash suite)
**Test baseline:** 1644 passed, 0 regression

---

## Контекст и мотивация

До Epic 5C `min_freq` был **extraction-time фильтром**: кандидат с частотой ниже порога
никогда не записывался в БД. Это создавало три фундаментальные проблемы:

1. **Irreversibility**: снизить `min_freq` после извлечения = полное переизвлечение
2. **Exploration cost**: сравнить корпус при `min_freq=2` vs `min_freq=5` = два отдельных
   запуска, каждый занимает минуты
3. **Resume gap**: изменение `min_freq` между сессиями → params_hash не совпадает →
   пользователь теряет прогресс незавершённого run'а

Epic 5C решает все три: **store once, filter at display time**.

---

## Что изменилось

### Extraction pipeline

| Точка | До | После |
|---|---|---|
| `_store_ngrams()` | `if freq < min_freq: continue` × 2 | Все кандидаты сохраняются |
| `_store_np_chunks()` | `if freq < min_freq: continue` | Все NP кандидаты сохраняются |
| `_iter_term_extract_accumulator_batches()` | `WHERE freq_abs >= min_freq` | Нет фильтра по частоте |

### params_hash / resume

| | До | После |
|---|---|---|
| `_TERM_EXTRACT_ALGO_VERSION` | 1 | 2 |
| `min_freq` в hash payload | да | нет |
| `min_freq` в resume WHERE | `TermExtractRun.min_freq == N` | отсутствует |
| Resume при изменении min_freq | невозможен | возможен |

### UI

`on_min_freq_changed()` теперь вызывает `perform_search()` — изменение spinner'а
мгновенно перестраивает список кластеров без переизвлечения.
Идентично поведению `on_min_doc_freq_changed()`.

### Без изменений

- Схема БД: все колонки `freq_abs` уже существовали, новых миграций нет
- `list_term_clusters()`: `WHERE freq_abs >= min_freq` — display-time фильтр работал
  и до 5C, просто теперь в БД есть данные для всех уровней частоты
- `TermExtractRun.min_freq`: колонка сохранена (backward compat), хранит
  информационный снимок, больше не влияет на resume-matching

---

## Ключевые решения

**min_freq остаётся в сигнатурах функций как legacy param** — не удалён из
`_store_ngrams`, `_store_np_chunks`, `_iter_term_extract_accumulator_batches`.
Это избегает каскадного рефакторинга вызывающего кода и не влияет на семантику
(параметр принимается, не используется для фильтрации).

**algo_version bump = явная инвалидация** — старые staged runs с v1 params_hash
не будут resumable. Это корректно: они сохранили только подмножество кандидатов
(с freq >= old_min_freq), и resume с новой семантикой дал бы неполные данные.

**Нет предупреждения о росте объёма** — сознательно отложено в Epic 5D.
На средних проектах (100–500 документов) прирост данных не создаёт UX-проблем.
Для больших корпусов это отдельная задача.

---

## Scope & File Map

### Изменённые файлы

| Файл | Изменения |
|------|-----------|
| `app/services/term_extraction_service.py` | 3 фильтра удалены, algo_version 1→2, min_freq убран из hash/resume |
| `app/ui/terms_view.py` | `on_min_freq_changed()` + `perform_search()` |
| `tests/test_term_extract_params_hash.py` | 9 тестов обновлены под новый контракт |

### Новые файлы

| Файл | Назначение |
|------|-----------|
| `tests/test_epic5c_candidate_persistence.py` | 5 тестов (algo_version, hash independence, store freq=1 for ngrams/NPs, accumulator batch) |
| `docs/epic5c_completion.md` | Этот документ |

---

## Тест-покрытие

**5 новых тестов** в `test_epic5c_candidate_persistence.py`:
- `test_algo_version_is_2` — контракт версии
- `test_params_hash_independent_of_min_freq` — hash не зависит от min_freq
- `test_store_ngrams_keeps_freq_1_candidates` — freq=1 записывается в ngram + NgramProjectStat
- `test_store_np_chunks_keeps_freq_1_candidates` — freq=1 NP записывается
- `test_accumulator_batch_yields_low_freq_rows` — accumulator отдаёт все строки

**9 обновлённых тестов** в `test_term_extract_params_hash.py`:
- `min_freq=N` убран из всех вызовов `_build_term_extract_params_hash()`
- `test_params_hash_changes_with_min_freq` → `test_params_hash_independent_of_min_freq`
- `test_params_hash_does_not_include_min_freq` — новый, проверяет структуру payload
- `test_params_hash_includes_algo_version` — обновлён: версия 2 current, версия 1 invalid

---

## Что явно за рамками (Epic 5D)

- **Hidden count в UI**: «Hidden by current min_freq: N» — отдельная задача
- **Предупреждение о росте данных**: для больших корпусов при низком min_freq
- **Freq-distribution статистика**: гистограмма частот перед выбором порога
- **Quick presets**: кнопки All / Common / Strict / High-confidence
- **Storage policy для huge corpora**: soft warning, настройка "store hapax" toggle

---

## DoD Checklist

- [x] `min_freq` не фильтрует кандидатов при извлечении (ngrams, NP, accumulator)
- [x] `min_freq` применяется только при отображении (`list_term_clusters`)
- [x] Изменение min_freq spinner → мгновенный refresh без переизвлечения
- [x] Resume работает при изменённом min_freq между сессиями
- [x] `_TERM_EXTRACT_ALGO_VERSION` = 2 (старые staged runs инвалидированы)
- [x] 5 новых тестов добавлены и проходят
- [x] params_hash suite обновлён (9 тестов)
- [x] Regression suite: 1644 passed, 0 новых падений
- [x] Нет изменений схемы БД (все колонки существовали)
- [x] Docs: completion report + обновлённая пользовательская документация
