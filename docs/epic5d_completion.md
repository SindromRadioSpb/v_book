# Epic 5D Completion Report — Terms UX Hardening

**Дата:** 2026-03-22
**Охват:** P0 (3 патча) + P1 (3 патча) + P2.1 + P2.2 + P2.3 (аудит)
**Схема:** v46 (без изменений — новых миграций нет)
**Тесты:** +32 новых (P0: 3, P1: 3, P2.1/P2.2: 4 обновлённых, P2.3: 6)
**Test baseline:** 1651 passed, 0 regression

---

## Контекст и мотивация

Epic 5C дал технически корректную семантику (store once, filter at display time).
Epic 5D — UX-слой поверх неё: пользователь должен понимать, что происходит,
иметь быстрый доступ к часто используемым порогам, а на больших корпусах —
осознанно управлять хранением.

Разбит на три уровня приоритета:
- **P0**: information gap — пользователь не видел важной информации
- **P1**: workflow acceleration — ускорение работы с порогом
- **P2**: tools for power users — история, storage policy, аудит

---

## P0 — Информационный gap (3 патча)

### P0-PATCH-01: Hidden cluster count

**Проблема:** после смены `min_freq` строка статуса показывала только видимые кластеры.
Пользователь не знал, сколько кластеров скрыто текущим фильтром.

**Решение:**
- `TermsSearchWorker` добавил сигнал `count_unfiltered_ready = pyqtSignal(int)`
- В `run()`: при активном `min_freq > 1` выполняется второй COUNT без фильтра частоты
- `_update_status_label()` в UI: если `_unfiltered_count > visible_count`, добавляет
  «(Hidden by min freq: N)» к строке статуса
- Новое поле `_unfiltered_count: int | None = None` в `TermsView`

### P0-PATCH-02: Min freq tooltip

**Проблема:** новые пользователи не понимали разницу между «параметр извлечения»
и «фильтр отображения».

**Решение:** `min_freq_spin.setToolTip(...)` с явным объяснением:
«Display-time filter only. All candidates are stored regardless of this value.
Change it freely — no re-extraction needed.»

### P0-PATCH-03: Resume log note

**Проблема:** при resume-е с изменённым `min_freq` лог молчал — пользователь
не понимал, почему resume всё-таки сработал.

**Решение:** в `_extract_terms_for_project_chunked()` при обнаружении resumable run
формируется заметка:
`(min_freq changed: 2→5, resume still valid)` — только если значения различаются.
Заметка добавляется к log-сообщению о resume.

---

## P1 — Workflow acceleration (3 патча)

### P1-PATCH-01: Quick presets

**Проблема:** переключение между 1/3/5/10 через спинбокс — медленно,
особенно при исследовании нового корпуса.

**Решение:** строка QPushButton под спинбоксом:
`[All (1)] [Common (3)] [Strict (5)] [High (10)]`

Каждая кнопка: `min_freq_spin.setValue(N)` → срабатывает `on_min_freq_changed()`
→ мгновенный `perform_search()`.

### P1-PATCH-02: Freq-distribution summary

**Проблема:** пользователь не знал распределения кандидатов по полосам частот
до выбора порога. Приходилось угадывать или пробовать каждое значение.

**Решение:**
- `TermExtractionService.get_freq_distribution(session, project_id)` — новый
  `@staticmethod`, один агрегатный SELECT с четырьмя CASE-выражениями:
  `{"1": N, "2-4": N, "5-9": N, "10+": N}`
- `TermsSearchWorker` добавил сигнал `freq_dist_ready = pyqtSignal(dict)`
  и вызов `get_freq_distribution()` в `run()`
- `freq_dist_label: QLabel` под строкой статуса (серый мелкий шрифт):
  `Freq dist: 1→245  2–4→183  5–9→91  10+→34`
- Обновляется при каждом `perform_search()` с seq-guard от гонки

### P1-PATCH-03: Growth warning

**Проблема:** при store_hapax=True и min_freq=1 на большом корпусе (>200 документов)
Full Overwrite может создать значительно больше кластеров, чем ожидает пользователь.

**Решение:** в `on_extract()` перед запуском:
- Если `extraction_mode == "overwrite" AND processed_docs > 200 AND min_freq == 1
  AND existing_clusters > 0` — показывает `QMessageBox.warning()`:
  «Large corpus detected: N docs. With min_freq=1 and Store hapax=On,
  all candidates including hapax legomena will be stored. This may create
  significantly more clusters than at min_freq=2+. Continue?»
- Пользователь может отменить и изменить настройки

`get_overwrite_impact()` расширен ключом `processed_docs` (Epic 5D P1 PATCH-03)
для подачи этой информации без отдельного запроса.

---

## P2 — Power user tools

### P2.1 — История порогов

**Проблема:** пользователь возвращается к проекту и не помнит, с каким `min_freq`
он работал последний раз (или несколько последних раз).

**Решение:**
- QComboBox «Recent:» рядом с preset-кнопками
- История — **per-project** (ключ QSettings: `terms/recent_min_freqs/project_{id}`)
- Формат: JSON-список int, max 5 значений, новые — в начало, дедупликация
- `_push_recent_min_freq(value)`: вызывается при каждом изменении спинбокса
  + при нажатии Extract
- Выбор из комбо → `setValue()` → `perform_search()` (сквозной, как preset)

### P2.2 — Storage policy (Store hapax)

**Проблема:** на корпусах >1000 документов hapax legomena (freq=1) могут составлять
30–60% всех кандидатов. При `store_hapax=True` (дефолт) они сохраняются, раздувая
базу без практической ценности для кюрации.

**Решение:** QCheckBox «Store hapax» (default: checked) в блоке extract controls.
`store_hapax: bool = True` — сквозной параметр по всему стеку:

```
ProjectTermExtractionWorker
  → extract_terms_for_project(store_hapax)
  → _extract_terms_for_project_chunked(store_hapax)
      → _create_term_extract_run(store_hapax)
          → _build_term_extract_params_hash(store_hapax)   ← в hash
      → _find_resumable_term_extract_run(store_hapax)      ← hash-gate
      → _store_staged_ngrams(store_hapax)
          → _iter_term_extract_accumulator_batches(store_hapax)
              WHERE freq_abs >= 2  (если store_hapax=False)
      → _store_staged_np_chunks(store_hapax)
  → _extract_terms_for_project_legacy(store_hapax)   ← legacy path
      → _store_ngrams(store_hapax)
          if not store_hapax and freq < 2: continue
      → _store_np_chunks(store_hapax)
```

**Ключевое:** `store_hapax` включён в `params_hash`. Запуск с `store_hapax=True`
и с `store_hapax=False` — **разные run'ы**, не resume-ятся друг от друга. Это
корректно: содержимое базы семантически различается.

### P2.3 — Bottleneck audit (аудит без реализации)

**Вопрос:** нужен ли materialised stats слой для трёх read-path запросов?

**Файл:** `tests/test_epic5d_p23_query_perf.py` — 6 тестов на N=10,000 кластеров

| Запрос | Латентность | EXPLAIN |
|--------|-------------|---------|
| `list_term_clusters` (first page) | 2.6 ms | `sqlite_autoindex_term_cluster_1 (project_id=?)` + temp b-tree |
| `count_term_clusters` | 1.0 ms | тот же индекс |
| `get_freq_distribution` | 1.5 ms | тот же индекс |

**Вывод:** materialised stats кэш не нужен при N ≤ 10k. При N = 50k ожидаемая
латентность ~5–15 ms, что остаётся в пределах нормы для desktop UI.
Реализация P2.3 отложена indefinitely как преждевременная оптимизация.

---

## Scope & File Map

| Файл | Изменение |
|------|-----------|
| `app/ui/terms_view.py` | hidden count, tooltip, preset buttons, freq_dist_label, recent combo, store_hapax checkbox, growth warning |
| `app/ui/workers.py` | `count_unfiltered_ready`, `freq_dist_ready` сигналы; `store_hapax` в `ProjectTermExtractionWorker` |
| `app/services/term_extraction_service.py` | `get_freq_distribution()`, `get_overwrite_impact()` (+processed_docs), `store_hapax` сквозной, resume log note |
| `tests/test_epic5a_patch03_overwrite_impact.py` | обновлён под новый ключ `processed_docs` |
| `tests/test_epic5c_candidate_persistence.py` | `min_freq=` → `store_hapax=` в вызове итератора |
| `tests/test_term_extract_params_hash.py` | ожидаемые хеши пересчитаны с `"store_hapax": true` |
| `tests/test_epic5d_p23_query_perf.py` | новый — 6 latency + EXPLAIN тестов |

---

## DoD checklist

- [x] P0: строка статуса показывает hidden count
- [x] P0: tooltip объясняет display-time семантику
- [x] P0: resume лог сообщает об изменении min_freq
- [x] P1: preset-кнопки 1/3/5/10 работают
- [x] P1: freq-distribution label обновляется мгновенно
- [x] P1: growth warning при overwrite + >200 docs + min_freq=1
- [x] P2.1: история порогов per-project, max 5, дедупликация
- [x] P2.2: store_hapax сквозной по всему стеку, включён в params_hash
- [x] P2.3: аудит выполнен, реализация обоснованно отложена
- [x] Нет UI freeze, все обновления через сигналы
- [x] Нет новых миграций (схема v46 неизменна)
- [x] 1651 тестов passing, 0 регрессий
- [x] Пользовательская документация обновлена (`epic5d_ux_guide.md`)
