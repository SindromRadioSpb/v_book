# Аудит и план внедрения HY-MT как MT-провайдера в HDLE

> Дата: 2026-04-06
> Статус: **AUDIT + PLAN** — код не менялся. SPIKE-1 закрыт.
> Пилотный маршрут: **Hebrew → Russian**
> Модель: **HY-MT1.5-1.8B only** (7B не рассматривается)

---

## Корректировки после review (2026-04-06)

1. **Лицензия** — проект некоммерческий, license review не нужен. Убрать из kill criteria.
2. **Только 1.8B** — 7B не рассматривается в pilot и в дальнейшем.
3. **HY-MT — не "ещё один провайдер"**: внедрять сразу со всеми 4 capabilities (terminology injection, contextual, placeholder protection, mixed-language). Обнулять выбор HY-MT через raw text → generate — неприемлемо.
4. **Placeholder protection — MANDATORY**: не опциональная настройка. Каждый `translate()` вызов ОБЯЗАН делать protect/restore. `{name}` или XML-тег сломает продукт хуже, чем плохой перевод.
5. **`terminology_mode="both"` — hardcoded default**: prompt injection + `apply_glossary()` постпроцессинг. Не пользовательский toggle.
6. **`MT_PROVIDER_INTEGRATION_GUIDE.md`** — внутренний стандарт для всех будущих провайдеров.

---

## 1. Repo Audit Findings

### 1.1 Source-of-truth файлы

| Роль | Файл |
|------|------|
| Базовый контракт провайдера | `app/infra/translators/base_provider.py` |
| Реестр провайдеров (singleton) | `app/infra/translators/providers_registry.py` |
| Схема конфигурации + QSettings-ключи | `app/infra/translators/provider_config.py` |
| Загрузка/сохранение конфигов | `app/infra/translators/provider_config_manager.py` |
| Регистрация локальных провайдеров | `app/infra/translators/local_providers_setup.py` |
| Эталонный паттерн локального провайдера | `app/infra/translators/providers/local_nllb_provider.py` |
| Subprocess-воркер (IPC) | `app/infra/local_mt/worker_process.py` |
| Менеджер путей моделей | `app/services/local_models/model_resource_manager.py` |
| Сервис перевода (chain/dispatch) | `app/services/translation_service.py` |
| UI диалог настроек провайдеров | `app/ui/provider_settings_dialog.py` |
| Глоссарный постпроцессинг | `app/services/local_mt/glossary_postprocess.py` |
| Сегментация текста | `app/services/local_mt/segmentation.py` |

### 1.2 Классы, сервисы, воркеры

**Базовый контракт** (`base_provider.py`):
```
BaseProvider (ABC)
  @property provider_id: str          # "local_hymt"
  @property display_name: str         # "HY-MT 1.5 (Offline)"
  @property supports_glossary: bool
  @property supports_batch: bool
  def translate(request: TranslationRequest) -> TranslationResult  # MUST NOT raise
  def get_model_version() -> str       # for cache key
  def healthcheck() -> bool
```

**TranslationRequest / TranslationResult** — datclass'ы в `base_provider.py`. Ключевые поля:
- `source_text`, `source_lang`, `target_lang`, `glossary`, `glossary_hash`, `trace_id`
- Result: `translated_text`, `provider_id`, `used_glossary`, `cache_hit`, `latency_ms`, `error_kind`, `meta`

**ProvidersRegistry** (`providers_registry.py`):
- Singleton (`__new__`), `_providers: dict[str, BaseProvider]`
- `register(provider)` — ValueError если дубль
- `get(provider_id)` → `BaseProvider | None`
- `reset()` — только для тестов

**LOCAL_PROVIDERS_CONFIG** (`local_providers_setup.py`):
```python
LOCAL_PROVIDERS_CONFIG = [
    {
        "provider_class": LocalNLLBProvider,
        "model_id": "facebook/nllb-200-distilled-1.3B",
        "backend": "ctranslate2",
        "enabled_by_default": True,
    },
    # HY-MT добавляется сюда
]
```
Функции: `initialize_local_providers()`, `initialize_provider_lazy()`, `check_local_providers_available()`.

**Worker subprocess** (`local_mt/worker_process.py`):
- Использует `multiprocessing.spawn` (Windows-safe)
- Протокол IPC: dict `{"type": "ping|translate|shutdown", "data": ...}`
- Текущие backends в `_worker_main()`: `"ctranslate2"` и `"transformers"`
- Ветка `"transformers"` вызывает `_load_transformers_model()` / `_translate_transformers()`
- **КРИТИЧНО**: нужно убедиться, что transformers-ветка поддерживает causal LM (decoder-only) с кастомным prompt-шаблоном

**ModelResourceManager** (`model_resource_manager.py`):
- Путь моделей Windows: `%LOCALAPPDATA%\HDLE\models`
- Формат директории: `{safe_model_id}_{backend}` (например `tencent_HY-MT1.5-1.8B_transformers`)
- Верификация через `manifest.json` с sha256

### 1.3 Цепочка вызова перевода

```
UI Surface (dictionary_view / terms_view / sentences_view / etc.)
  └─► BatchTranslateWorkerV2 (QThread)
        └─► BatchTranslateEngineV2.execute()
              └─► TranslationService.resolve_translation()
                    ├─► _lookup_tm()         # TM override (приоритет 1)
                    ├─► _lookup_tm_aliases() # TM aliases (приоритет 2)
                    ├─► _lookup_dict()       # Offline dict (приоритет 3)
                    ├─► _lookup_mt_cache()   # MT cache (приоритет 4)
                    └─► _translate_via_provider_chain()  # MT провайдер (приоритет 5)
                          └─► ProvidersRegistry.get(provider_id)
                                └─► provider.translate(request)
```

**Force-provider режим**: через `BatchTranslateOptions.provider_mode = "force:<provider_id>"`.
**Chain-режим**: порядок из `QSettings["mt/providers/chain"]` (drag-drop в UI).

### 1.4 Translation surfaces

| Surface | Файл | Как вызывает MT |
|---------|------|-----------------|
| Dictionary | `ui/dictionary_view.py` | через `BatchTranslateWorkerV2` / `TranslationService` |
| Terms | `ui/terms_view.py` | через `BatchTranslateWorkerV2` |
| User Dictionaries | `ui/user_dictionaries_view.py` | через `TranslationService` |
| Sentences | `ui/sentences_view.py` | через `TranslationService` |
| Translation Management | `ui/translation_management_panel.py` | через `BatchTranslateEngineV2` |

Все surfaces используют единый `TranslationService` → единая точка интеграции.

### 1.5 Глоссарий / TM механизм

- `GlossaryBuilderService.build_canonical_glossary()` строит глоссарий перед MT-запросом
- `apply_glossary()` в `services/local_mt/glossary_postprocess.py` — постпроцессинг: заменяет MT-выход утверждёнными TM-терминами по точному совпадению (`src_norm`)
- Подходит для HY-MT как **постпроцессинг после MT** (дополнительно к prompt-level terminology injection)

### 1.6 UI Provider Settings диалог

`ui/provider_settings_dialog.py` содержит **захардкоженный** словарь `PROVIDERS`:
```python
PROVIDERS = {
    "google_translate": {...},
    "google_cloud_translate": {...},
    "deepl": {...},
    "microsoft": {...},
    "libretranslate": {...},
    "local_nllb": {...},
    "local_seamless": {...},  # placeholder
}
```
Добавление HY-MT требует: (a) новой записи в `PROVIDERS` и (b) опционально нового таба для local-специфичных настроек (model_path, device, dtype, max_new_tokens).

### 1.7 Риски текущей архитектуры

| Риск | Описание |
|------|----------|
| `worker_process.py` transformers-ветка | Реализована под encoder-decoder (NLLB). Нужна проверка и адаптация для decoder-only + prompt-шаблон HY-MT |
| `ProviderSettingsDialog.PROVIDERS` | Захардкожен. Добавление нового провайдера требует ручного изменения + нет plugin-реестра |
| Cold start latency | 1.8B модель грузится 5-15с. UI может зависнуть при lazy init в главном потоке |
| Glossary pre-injection | `GlossaryBuilderService` строит глоссарий, но не передаёт в prompt для HY-MT (только постпроцессинг). Нужен механизм prompt-level injection |
| `segment_text()` | Сегментация разработана под encoder-decoder (NLLB max 512 tokens). HY-MT decoder-only может принимать длиннее, но нужна адаптация |

---

## 2. HY-MT Fit Assessment for HDLE

### Архитектура модели
- **Тип**: Decoder-only causal LM (как Qwen/LLaMA, NOT encoder-decoder как NLLB)
- **Семейство**: HY-MT1.5 (Tencent Hunyuan)
- **Языки**: 33+ языка, Hebrew (he) и Russian (ru) **подтверждены**
- **Inference**: `transformers.AutoModelForCausalLM`, vLLM (OpenAI API), llama.cpp (GGUF)
- **Параметры генерации**: `top_k=20, top_p=0.6, temperature=0.7, repetition_penalty=1.05`

### Strengths

1. **Hebrew→Russian нативно поддерживается** — оба языка в списке 33 поддерживаемых
2. **Terminology intervention через prompt** — встроенный механизм в формате `{src_term} 翻译成 {tgt_term}`
3. **Formatted translation** — поддержка XML-тегов для защиты плейсхолдеров
4. **Mixed-language** — задекларирована поддержка code-switching
5. **GGUF/llama.cpp** — доступна квантованная версия для CPU-fallback без GPU
6. **1.8B model** — умещается в 4GB VRAM (bfloat16), ~2GB (FP8), ~0.7GB (Int4)
7. **Offline operation** — не требует API-ключей, полностью локально

### Weak points

1. **Нет CTranslate2** — decoder-only LM несовместим с CTranslate2 (разработан для enc-dec). Нужен другой backend
2. **Decoder hallucination risk** — LLM-модели склонны к explanatory drift ("I see that you want me to translate..."), нужны жёсткие generation constraints
3. **He→Ru специфично не бенчмаркировалась** публично — качество неизвестно на нашем домене (техдоки, учебные материалы, глоссарии)
4. **RTL/LTR mixing в prompt** — Hebrew + английские/русские термины в одном промпте могут вызвать порчу порядка токенов (нужен spike)
5. **Нет official BPE для Hebrew** — токенизация иврита может быть неоптимальной (unknown wordpiece фрагменты)
6. **Latency выше NLLB** — LLM autoregressive decode медленнее encoder-decoder при том же размере
7. **Generation stop** — нужен explicit `eos_token_id` или `stop` sequence, иначе модель продолжит генерировать

### Unknowns (требуют spike)

- Реальное качество he→ru на HDLE-домене
- Токенизация иврита (покрытие Hebrew alphabet, niqqud, mixed RTL/LTR)
- Latency на RTX 3070: 1 предложение, пачка 10 предложений, длинный сегмент
- Насколько `apply_glossary` (постпроцессинг) совместим с HY-MT-выходом (может быть нестабильная punctuation/spacing)
- Точное поведение formatted translation (XML tags preservation)

### Blockers (нужно снять перед реализацией)

- [SPIKE-1] Проверить, что `worker_process.py` transformers-ветка адаптируема для causal LM с кастомным промптом
- [SPIKE-2] Запустить HY-MT1.5-1.8B на пилотной машине, измерить latency и качество для 10-20 he→ru пар из реального HDLE-контента

---

## 3. Deployment Options Matrix

| # | Вариант | Backend path | Windows | RTX 3070 8GB | Latency (1 sent) | Сложность impl | Integration risk | Рекомендация |
|---|---------|-------------|---------|---------------|-------------------|----------------|-----------------|--------------|
| 1 | transformers in-process | `AutoModelForCausalLM` в главном процессе | ✓ | ✓ (1.8B fits) | 2-5с (bfloat16) | Низкая | ВЫСОКИЙ — блокирует UI | ❌ НЕТ |
| 2 | transformers in subprocess | `AutoModelForCausalLM` в spawn-процессе (как NLLB) | ✓ | ✓ | 2-5с | Средняя | Низкий — изолирован | ✅ **РЕКОМЕНДУЕТСЯ** |
| 3 | GGUF + llama.cpp subprocess | `llama-cpp-python` или `llama.cpp` binary | ✓ | ✓ (GPU layers) | 0.5-2с (Int4) | Средняя | Средний — новая зависимость | ✓ (альтернатива) |
| 4 | vLLM server | REST API к локальному vLLM | ✓ (WSL2) | ✓ | 0.3-1с | Высокая | Высокий — внешний процесс | ❌ Слишком тяжело для pilot |
| 5 | CPU fallback (GGUF Q4) | `llama-cpp-python` CPU only | ✓ | n/a | 15-60с | Средняя | Низкий | ✓ (только как fallback) |

**Итог:** Вариант 2 (subprocess + transformers) — продолжает паттерн LocalNLLBProvider, минимальные изменения в архитектуре.

---

## 4. Recommended Pilot Architecture

### Выбор: Subprocess + transformers backend (HY-MT specific)

**Почему этот путь:**
- Изолирует VRAM/память в отдельном процессе → crash не роняет главный процесс
- Продолжает существующий паттерн `LocalMTWorker` (понятный код, минимальный риск регрессий)
- `AutoModelForCausalLM` — официальный inference путь HY-MT
- Windows-safe через `multiprocessing.spawn`

**Почему альтернативы хуже на первом проходе:**
- GGUF/llama.cpp: дополнительная зависимость `llama-cpp-python`, нужна сборка с CUDA поддержкой на Windows — риск
- vLLM: требует Linux/WSL2 для производительного использования, не вписывается в desktop-first архитектуру
- In-process: блокирует UI при load + inference — нарушает правила PyQt6

**Рекомендуемый model variant для pilot:**
- `tencent/HY-MT1.5-1.8B` в bfloat16 (4GB VRAM) — единственный вариант в pilot

**Что HY-MT должен делать в HDLE (не "ещё один провайдер"):**

| Capability | Реализация в `LocalHYMTProvider.translate()` |
|-----------|----------------------------------------------|
| Terminology injection | Топ-10 TM-терминов → prompt reference block (hardcoded ON) |
| Placeholder protection | **MANDATORY** protect → prompt → inference → restore + validate |
| XML / formatted tags | XML-обёртка `<ph id="N"/>` + инструкция preserve |
| Contextual translation | Document-level context в промпт (опционально) |
| Mixed-language | no-translate инструкция для кода/терминов |

**`terminology_mode="both"` — hardcoded default**: prompt injection + `apply_glossary()`. Не пользовательский toggle, всегда включено.

**Сознательные компромиссы:**
- Worker process запускается при первом запросе (lazy init) → первый запрос медленный (cold start 5-15с)
- Нет real-time streaming (polling IPC как в NLLB)
- Batch translation последовательный (один запрос за раз в первой версии)

**Что нужно изменить в worker_process.py:**
- Добавить backend-ветку `"transformers_causal"` рядом с `"ctranslate2"` / `"transformers"`
- `_load_transformers_causal_model(model_path)` — `AutoModelForCausalLM.from_pretrained()`
- `_translate_transformers_causal(model, tokenizer, text, src_lang, tgt_lang)` — prompt-template + generate + extract

---

## 5. File-Level Integration Plan

| # | Файл | Зачем | Тип изменений | Risk | Порядок |
|---|------|-------|---------------|------|---------|
| 1 | `app/infra/local_mt/worker_process.py` | Добавить backend `"transformers_causal"` для decoder-only LM | Новые функции `_load_transformers_causal_model`, `_translate_transformers_causal` | Средний — не ломает NLLB | PATCH-01 |
| 2 | `app/infra/translators/providers/local_hymt_provider.py` | Новый класс `LocalHYMTProvider(BaseProvider)` | Новый файл | Низкий — изолирован | PATCH-02 |
| 3 | `app/infra/translators/local_providers_setup.py` | Добавить HY-MT в `LOCAL_PROVIDERS_CONFIG` | +1 dict entry | Низкий | PATCH-02 |
| 4 | `app/ui/provider_settings_dialog.py` | Добавить `"local_hymt"` в `PROVIDERS` + опциональный advanced tab | +1 dict entry + UI виджеты | Средний — UI регрессия | PATCH-03 |
| 5 | `app/infra/translators/providers/__init__.py` | Экспортировать `LocalHYMTProvider` | +1 import | Низкий | PATCH-02 |
| 6 | `app/services/local_models/model_resource_manager.py` | Убедиться что manifest HY-MT поддерживается (нет изменений если backend = `"transformers_causal"`) | Проверка, возможно без изменений | Низкий | PATCH-00 |
| 7 | `scripts/install_local_mt_model.py` (если есть) или новый | Скрипт загрузки HY-MT с HuggingFace + создание manifest | Новый скрипт | Низкий | PATCH-00 |
| 8 | `tests/test_local_hymt_provider.py` | Unit + integration тесты | Новый файл | Низкий | PATCH-04 |
| 9 | `docs/MT_PROVIDER_INTEGRATION_GUIDE.md` | Документация (уже создаётся в этом проходе) | Новый файл | Нет | Сейчас |

---

## 6. Settings / UX Plan

### Запись в `ProviderSettingsDialog.PROVIDERS`

```python
"local_hymt": {
    "name": "HY-MT 1.5 (Offline, He→Ru)",
    "default_rate_limit": 9999,      # unlimited for local
    "default_enabled": False,         # disabled until model installed
    "supports_advanced": True,        # local-specific settings tab
},
```

### QSettings-ключи (формат `mt/providers/{provider_id}/...`)

| Ключ | Тип | По умолчанию | Назначение |
|------|-----|-------------|-----------|
| `mt/providers/local_hymt/enabled` | bool | False | Мастер-включатель |
| `mt/providers/local_hymt/model_variant` | str | `"HY-MT1.5-1.8B"` | Вариант модели |
| `mt/providers/local_hymt/device` | str | `"auto"` | `cuda` / `cpu` / `auto` |
| `mt/providers/local_hymt/dtype` | str | `"bfloat16"` | `bfloat16` / `fp8` / `int4` |
| `mt/providers/local_hymt/max_new_tokens` | int | 512 | Лимит генерации |
| `mt/providers/local_hymt/timeout_seconds` | float | 60.0 | Worker timeout |
| `mt/providers/local_hymt/warmup_on_startup` | bool | False | Загружать модель при старте |
| `mt/providers/local_hymt/temperature` | float | 0.7 | Generation temperature (advanced) |
| `mt/providers/local_hymt/top_k` | int | 20 | Top-K sampling |
| `mt/providers/local_hymt/top_p` | float | 0.6 | Top-P sampling |
| `mt/providers/local_hymt/repetition_penalty` | float | 1.05 | Repetition penalty |

### Validation rules

- `model_variant` = `"HY-MT1.5-1.8B"` (единственный вариант в pilot)
- `device` ∈ {`"auto"`, `"cuda"`, `"cpu"`}
- `dtype` ∈ {`"bfloat16"`, `"float16"`, `"fp8"`, `"int4"`}
- `max_new_tokens` ∈ [64, 2048]
- При `device="cuda"` и `dtype="bfloat16"`: предупредить если VRAM < 4GB (через healthcheck)

### Health status / degraded mode

| Состояние | Что показывается |
|-----------|-----------------|
| Модель не скачана | Запись в PROVIDERS серым, tooltip: "Model not installed" |
| GPU недоступен / VRAM < required | Предупреждение при активации, fallback на CPU |
| Worker упал (OOM, crash) | `healthcheck()` возвращает False → provider пропускается в chain |
| Model загружается (cold start) | Статус "Loading..." в batch progress dialog |

### User flow для первого включения

1. Tools → Translation → MT Provider Setting
2. В Rate Limits tab: "HY-MT 1.5 (Offline, He→Ru)" → Enable
3. В Advanced Settings tab (HY-MT секция):
   - "Download Model" кнопка (запускает PowerShell-скрипт загрузки)
   - Device / dtype / max_new_tokens поля
   - "Test Translation" кнопка (ping + тестовый запрос)
4. В Provider Chain tab: перетащить HY-MT на нужную позицию (обычно выше NLLB для he→ru)

---

## 7. Runtime / Worker / Safety Plan

### Process model

```
MainProcess (PyQt6 UI)
  └─► LocalHYMTProvider.translate()
        └─► LocalMTWorker (IPC client)
              └─►[multiprocessing.spawn] HYMTWorkerProcess
                    └─► transformers.AutoModelForCausalLM (GPU/CPU)
```

### Worker lifecycle

1. **Init**: `LocalHYMTProvider.__init__()` → проверяет модель через `ModelResourceManager` → вызывает `start_worker(backend="transformers_causal", ...)`
2. **Warmup** (опционально): при `warmup_on_startup=True` — init при старте приложения через `initialize_local_providers()`
3. **Lazy init**: при первом запросе через `initialize_provider_lazy("local_hymt")`
4. **Cold start**: ~5-15с для 1.8B (зависит от NVMe vs HDD)
5. **Работа**: IPC ping/translate/shutdown через `multiprocessing.Pipe`
6. **Shutdown**: через `provider.shutdown()` → `worker.shutdown()` → процесс завершается

### Queue / batch behavior

- Один запрос за раз (IPC serial) в первой версии
- Batch из `BatchTranslateEngineV2` приходит последовательно, дедуплицирован
- Для будущего: queue внутри воркера для batch inference (вторая версия)

### Timeout / cancel

- Timeout `timeout_seconds` (по умолчанию 60.0) на уровне `LocalMTWorker.translate()`
- При timeout: `WorkerError` → `TranslationResult(error_kind=NETWORK)`
- Cancel: `BatchTranslateWorkerV2._cancel_requested` проверяется между чанками
- Воркер не имеет cancel mid-generation (нет streaming) — только между запросами

### OOM / crash recovery

- Worker process изолирован → OOM убивает только его, не UI
- После краша: `healthcheck()` → False → provider помечается недоступным в chain
- Перезапуск: через кнопку "Reload Provider" в UI или перезапуск приложения
- Логировать OOM через `logger.error()` с VRAM usage в `meta`

### Thread-safety

- `LocalMTWorker` НЕ thread-safe: один воркер на один provider, один запрос за раз
- Concurrent translate запросы через `threading.Lock` или последовательный queue
- DB session: передаётся при инициализации, не используется из воркер-процесса

### Structured logging fields

```python
logger.info("hymt_translate", extra={
    "trace_id": request.trace_id,
    "src_lang": request.source_lang,
    "tgt_lang": request.target_lang,
    "src_len": len(request.source_text),
    "segment_count": len(segments),
    "inference_ms": total_inference_ms,
    "latency_ms": latency_ms,
    "model_variant": self.model_variant,
    "used_glossary": used_glossary,
    "terminology_mode": self.terminology_mode,
})
```

---

## 8. Terminology / Formatting / Mixed-Language Strategy

### 8.1 Terminology intervention

HY-MT поддерживает **prompt-level** terminology constraints:

```
Translate the following segment into Russian.
Reference translations:
מאגר נתונים → база данных
מנהל קבצים → файловый менеджер

Source:
{source_text}
```

**Связь с HDLE glossary:**
1. `GlossaryBuilderService.build_canonical_glossary()` уже строит глоссарий из TM
2. Нужен конвертер `canonical_glossary → HY-MT prompt references`
3. Максимум 5-10 терминов в prompt (чтобы не раздувать контекст)
4. **Постпроцессинг** через `apply_glossary()` — дополнительный safety net

**Рекомендуемый режим**: `terminology_mode="both"` — prompt injection + постпроцессинг.

**Отбор терминов для prompt:**
- Только термины, встречающиеся в `source_text` (substring match)
- Приоритет: статус `approved` > `draft`
- Лимит: топ-10 по frequency / confidence

### 8.2 Защита placeholders / тегов

HY-MT поддерживает **Formatted Translation** через XML-теги. Стратегия:

1. **Перед переводом**: заменить `{placeholder}`, `<tag>`, `%s` на XML-теги: `<ph id="1"/>`
2. **Промпт**: добавить инструкцию `Preserve all XML tags exactly as they appear`
3. **После перевода**: восстановить оригинальные значения по `id`
4. **Validation**: если тег не сохранён → fallback или пометка ошибки

```python
# Пример защиты
"Добро пожаловать, {name}!"
→ prompt: "Добро пожаловать, <ph id='1'/>!"
→ HY-MT: "ברוך הבא, <ph id='1'/>!"
→ restore: "ברוך הבא, {name}!"
```

### 8.3 Mixed-language / RTL-LTR

- Hebrew RTL + русские/английские LTR термины в одном сегменте — нужен spike на реальных примерах
- Стратегия: не пытаться исправить RTL в промпте, доверить модели
- Numerics: не защищать (модель обычно сохраняет цифры корректно)
- Code-like fragments (`var_name`, `CONSTANT`): защищать как placeholders

### 8.4 Pre/post-processing layer

```
Input text
  → protect_placeholders()       # заменить {} / %s / XML → <ph id=N/>
  → build_hymt_prompt()          # собрать промпт с terminology + instructions
  → worker.translate()           # HY-MT inference
  → validate_placeholders()      # проверить что теги сохранены
  → restore_placeholders()       # восстановить оригинальные токены
  → apply_glossary()             # TM постпроцессинг
Output text
```

### 8.5 Segmentation

- Существующий `segment_text()` разработан под NLLB (max 512 токенов enc-dec)
- HY-MT принимает длиннее (~1024-2048 токенов контекста)
- Для pilot: использовать существующую сегментацию (короткие сегменты — безопаснее)
- Для v2: адаптировать под HY-MT лимиты

---

## 9. Validation & Test Strategy

### Smoke tests
```powershell
# Проверка импорта
python -c "from app.infra.translators.providers.local_hymt_provider import LocalHYMTProvider; print('OK')"

# Проверка регистрации провайдера (с установленной моделью)
python -c "
from app.infra.translators.local_providers_setup import initialize_local_providers
n = initialize_local_providers(force_register=False)
print(f'Registered: {n} providers')
"
```

### Provider health tests
```powershell
python -m pytest tests/test_local_hymt_provider.py::test_healthcheck -v
python -m pytest tests/test_local_hymt_provider.py::test_translate_he_ru_basic -v
```

### He→Ru quality sanity tests (ручные + автоматизированные)

| Тест | Входной текст | Ожидание |
|------|--------------|----------|
| Простое предложение | `שלום עולם` | "Привет, мир" (или эквивалент) |
| Технический термин | `מאגר נתונים` | "база данных" (с глоссарием) |
| Длинное предложение (>10 слов) | реальный HDLE пример | связный русский перевод |
| Mixed-lang (he + en) | `אנחנו משתמשים ב-database` | корректная передача "database" |
| Niqqud | `שָׁלוֹם` | не хуже без niqqud |

### Terminology enforcement tests
```python
# При включённом terminology_mode="both": термин из TM должен присутствовать в переводе
def test_terminology_applied():
    # Дано: TM содержит approved: "מאגר נתונים" → "база данных"
    # Когда: переводим текст, содержащий "מאגר נתונים"
    # Ожидаем: результат содержит "база данных"
```

### Placeholders / tags preservation tests
```python
def test_placeholder_preserved():
    result = provider.translate(TranslationRequest(
        source_text="שלום, {name}!",
        source_lang="he", target_lang="ru"
    ))
    assert "{name}" in result.translated_text
```

### Batch translation tests
```python
def test_batch_10_items():
    # 10 уникальных he→ru пар, проверить что все вернули результат
    # и latency суммарно < 60с
```

### Cancellation tests
```python
def test_cancel_mid_batch():
    # Запустить batch из 20 items, отменить на 5м
    # Проверить что отмена применяется, DB не повреждена
```

### Settings persistence tests
```python
def test_settings_round_trip():
    # Сохранить config → перезагрузить → значения совпадают
```

### Offline / no-model tests
```python
def test_provider_not_registered_when_model_missing():
    # При отсутствии модели провайдер не регистрируется
    # translate() возвращает error, не exception
```

### Regression risks для существующих провайдеров
- `test_local_nllb_provider.py` — запустить полный suite, убедиться что NLLB не сломан
- `test_translation_service.py` — chain logic не изменилась
- `test_provider_settings_dialog.py` — UI диалог загружается с новой записью

### Manual QA сценарии по surfaces

| Surface | Сценарий |
|---------|----------|
| Dictionary | Перевести 5 лемм he→ru, выбрав HY-MT как force-provider |
| Terms | Batch перевод 20 терминов с включённым глоссарием |
| User Dictionaries | Открыть, убедиться что HY-MT появился в списке провайдеров |
| Sentences | Одиночный перевод предложения через HY-MT |
| Translation Management | Batch с provider_mode="force:local_hymt", проверить log |

---

## 10. Patch Plan

### PATCH-00: Environment & Model Download Preparation
**Goal**: Воспроизводимая установка модели на Windows без UI изменений

**Files**:
- `scripts/install_hymt_model.py` (новый) — скачивает `tencent/HY-MT1.5-1.8B` с HuggingFace, создаёт `manifest.json`
- Проверить `app/services/local_models/model_resource_manager.py` — достаточно ли манифеста для нового backend

**Changes**:
```powershell
# Smoke: скрипт должен отработать без ошибок
python scripts/install_hymt_model.py --model HY-MT1.5-1.8B --device cuda
```

**DoD**:
- [ ] Модель скачана в `%LOCALAPPDATA%\HDLE\models\tencent_HY-MT1.5-1.8B_transformers_causal`
- [ ] `manifest.json` создан и содержит корректные поля
- [ ] `ModelResourceManager.is_installed()` возвращает True

---

### PATCH-01: Worker subprocess backend для decoder-only (transformers_causal)
**Goal**: Расширить `worker_process.py` поддержкой causal LM без поломки NLLB-ветки

**Files**:
- `app/infra/local_mt/worker_process.py`

**Changes**:
- Новая функция `_load_transformers_causal_model(model_path, model_id)` → returns `(model, tokenizer)`
- Новая функция `_translate_transformers_causal(model, tokenizer, text, src_lang, tgt_lang, params)` с HY-MT prompt-шаблоном
- Добавить ветку `elif backend == "transformers_causal":` в `_worker_main()`

**HY-MT prompt шаблон (для he→non-CJK направлений)**:
```
Translate the following segment into {target_language}, without additional explanation.

{source_text}
```

**Generation params**: `max_new_tokens=512, do_sample=True, top_k=20, top_p=0.6, temperature=0.7, repetition_penalty=1.05`

**Why this order**: Worker изменяется первым — он основа для провайдера.

**Test scope**:
- `test_worker_process_transformers_causal.py` — unit test без реальной модели (mock)
- Smoke: `worker_process.py` запускается с `backend="ctranslate2"` — NLLB не сломан

**DoD**:
- [ ] NLLB-тесты проходят без изменений
- [ ] Новая ветка `transformers_causal` не падает при `ping`

---

### PATCH-02: LocalHYMTProvider class
**Goal**: Новый провайдер, реализующий BaseProvider через PATCH-01 worker

**Files**:
- `app/infra/translators/providers/local_hymt_provider.py` (новый)
- `app/infra/translators/providers/__init__.py`
- `app/infra/translators/local_providers_setup.py`

**Changes**:
- `LocalHYMTProvider(BaseProvider)`:
  - `provider_id = "local_hymt"`
  - `display_name = "HY-MT 1.5 (Offline, He→Ru)"`
  - `supports_glossary = True`
  - `translate()`: protect_placeholders → build_prompt → worker → restore → apply_glossary
  - `healthcheck()`: ping worker
  - `shutdown()`: worker.shutdown()
- Добавить в `LOCAL_PROVIDERS_CONFIG`:
  ```python
  {
      "provider_class": LocalHYMTProvider,
      "model_id": "tencent/HY-MT1.5-1.8B",
      "backend": "transformers_causal",
      "enabled_by_default": False,
  }
  ```

**Test scope**:
- `tests/test_local_hymt_provider.py` — unit тесты с mock worker
- `tests/test_local_providers_setup.py` — регрессия

**DoD**:
- [ ] `LocalHYMTProvider` инициализируется (с реальной моделью)
- [ ] `translate()` возвращает `TranslationResult` без исключений
- [ ] Glossary постпроцессинг применяется при наличии TM-терминов

---

### PATCH-03: UI Integration (Provider Settings Dialog)
**Goal**: HY-MT появляется в MT Provider Setting

**Files**:
- `app/ui/provider_settings_dialog.py`

**Changes**:
- Добавить запись в `PROVIDERS` dict
- Опционально: новая секция в Advanced Settings tab для HY-MT-специфичных полей (model_variant, device, dtype)

**Test scope**:
- `tests/test_provider_settings_dialog.py` — UI диалог грузится с новой записью

**DoD**:
- [ ] HY-MT отображается в списке провайдеров
- [ ] Enable/disable сохраняется в QSettings
- [ ] Включение HY-MT не ломает другие провайдеры в диалоге

---

### PATCH-04: Tests & Hardening
**Goal**: Полное покрытие тестами, safety guards

**Files**:
- `tests/test_local_hymt_provider.py`
- `tests/test_worker_process_hymt.py`
- `tests/test_hymt_placeholder_protection.py`
- `tests/test_hymt_terminology.py`

**Changes**:
- Тест offline (нет модели) → не крашит
- Тест placeholder protection
- Тест glossary integration
- Тест cancel/timeout

**DoD**:
- [ ] Все тесты проходят
- [ ] `python -m pytest -v` — регрессия полная проходит
- [ ] Smoke через PowerShell отрабатывает

---

## 11. Pilot Rollout Plan for Windows/PowerShell

### Шаг 1: Environment prep
```powershell
# Активировать venv
cd E:\projects\Project_Vibe\V_book
.\.venv\Scripts\Activate.ps1

# Проверить наличие torch+CUDA
python -c "import torch; print(torch.cuda.is_available(), torch.version.cuda)"

# Убедиться в transformers >= 4.56.0 (требование HY-MT)
python -c "import transformers; print(transformers.__version__)"

# Если нужно обновить:
pip install "transformers>=4.56.0"
```

### Шаг 2: Model acquisition
```powershell
# Скачать модель (требует HuggingFace account или публичный доступ)
python scripts/install_hymt_model.py --model HY-MT1.5-1.8B --device cuda --dtype bfloat16

# Проверить что модель установлена
python -c "
from app.services.local_models.model_resource_manager import ModelResourceManager
mgr = ModelResourceManager()
ok, reason = mgr.is_installed('tencent/HY-MT1.5-1.8B', 'transformers_causal')
print(f'Installed: {ok}, reason: {reason}')
"
```

### Шаг 3: Smoke verification (без UI)
```powershell
# Тест worker subprocess
python -c "
from app.infra.local_mt.worker_process import start_worker, WorkerRequest
import pathlib
model_path = pathlib.Path(r'%LOCALAPPDATA%\HDLE\models\tencent_HY-MT1.5-1.8B_transformers_causal')
worker = start_worker(model_path=str(model_path), backend='transformers_causal', model_id='tencent/HY-MT1.5-1.8B')
print('Worker started:', worker.ping())
req = WorkerRequest(text='שלום עולם', source_lang='he', target_lang='ru')
result = worker.translate(req)
print('Translation:', result.text)
worker.shutdown()
"
```

### Шаг 4: Provider integration smoke
```powershell
python -c "
from app.infra.translators.local_providers_setup import initialize_local_providers
from app.infra.translators.providers_registry import ProvidersRegistry
from app.infra.translators.base_provider import TranslationRequest

n = initialize_local_providers()
print(f'Registered {n} providers')

registry = ProvidersRegistry()
provider = registry.get('local_hymt')
if provider:
    req = TranslationRequest(source_text='שלום עולם', source_lang='he', target_lang='ru')
    result = provider.translate(req)
    print(f'Result: {result.translated_text} (latency: {result.latency_ms}ms)')
else:
    print('Provider not registered')
"
```

### Шаг 5: Staged enablement in app
1. Запустить приложение: `python -m app.main --db-path "...\hdle_premium.db"`
2. Tools → Translation → MT Provider Setting
3. Rate Limits tab: включить "HY-MT 1.5 (Offline, He→Ru)"
4. Provider Chain tab: поставить HY-MT перед/после NLLB
5. Открыть Dictionary → выбрать слово → Translate → убедиться что результат пришёл

### Rollback plan
- Если HY-MT ломает UI: снять флаг `enabled` в QSettings (`mt/providers/local_hymt/enabled = false`)
- Если worker_process.py изменения сломали NLLB: `git revert PATCH-01`
- HY-MT провайдер изолирован — rollback не затрагивает других провайдеров

---

## 12. Risks / Unknowns / Kill Criteria

### Главные риски

| # | Риск | Вероятность | Митигация |
|---|------|------------|-----------|
| R1 | He→Ru качество неприемлемо на HDLE-домене | Средняя | SPIKE-2: тест 20 пар до реализации |
| R2 | Decoder hallucination: добавляет объяснения вместо перевода | Средняя | жёсткий промпт + generation stop + validation |
| R3 | VRAM конфликт с аудио-моделью (TTS) при одновременном использовании | Высокая | lazy init + отдельный процесс, документировать |
| R4 | Cold start 15с блокирует UX восприятие | Высокая | warmup option + async lazy init + progress indicator |
| R5 | Токенизация Hebrew неоптимальна (большие out-of-vocab фрагменты) | Средняя | spike: проверить tokenizer coverage |
| R6 | VRAM конфликт 1.8B + TTS при одновременной нагрузке | Средняя | задокументировать, lazy init, мониторить |

### Неизвестные (требуют spike/POC до реализации)

- **SPIKE-1**: Адаптируем ли `worker_process.py` transformers-ветку под causal LM — прочитать реализацию `_load_transformers_model` / `_translate_transformers` детально
- **SPIKE-2**: Запустить HY-MT1.5-1.8B на RTX 3070 → 20 he→ru пар из HDLE → оценить качество и latency
- ~~**SPIKE-3**: License review~~ — проект некоммерческий, не нужен

### Kill criteria (остановить pilot)

- He→Ru качество ниже NLLB на >30% BLEU при одинаковом домене
- Latency >10с на короткое предложение (1.8B, RTX 3070, bfloat16) — неприемлемо для interactive UI
- Hallucination rate >20% (добавляет объяснения/отказывается переводить)
- ~~Лицензия запрещает коммерческое использование~~ — н/п (проект некоммерческий)
- Невозможно адаптировать worker_process.py без полной переработки

### GO criteria (переходить к реализации)

- ✅ SPIKE-1: **ЗАКРЫТ** — `_load_transformers_causal_model` + `_translate_transformers_causal`, не ломает NLLB
- SPIKE-2: latency < 5с, placeholder preservation 100%, quality pass rate ≥ 75%

---

## 13. Final Recommendation

### Verdict: **GO WITH CONSTRAINTS**

**Почему GO:**
- Hebrew→Russian подтверждён в списке языков
- 1.8B влезает в 4GB VRAM из 8GB доступных (с запасом)
- Архитектура HDLE готова к локальным провайдерам (паттерн NLLB отработан)
- Terminology intervention + formatted translation — задекларированы и нужны нам

**Constraints (что нужно сделать перед impl):**
1. **SPIKE-2 обязателен** — запустить 20 he→ru пар вручную, убедиться в приемлемом качестве
2. **License review** — прочитать License.txt полностью, не полагаться на "commercial permitted"
3. **Прочитать** `worker_process.py::_load_transformers_model` и `_translate_transformers` — убедиться что адаптация тривиальна

**Начинать с:** `tencent/HY-MT1.5-1.8B`, backend `transformers_causal`, device `cuda`, dtype `bfloat16`

**Что НЕ делать на первом этапе:**
- Не внедрять 7B (не влезет в 8GB в полной точности, сложнее управлять)
- Не делать vLLM server mode (лишняя инфраструктура)
- Не делать fine-tuning (выходит за scope)
- Не делать streaming/incremental output (усложняет IPC)
- Не рефакторить существующий `worker_process.py` под общий интерфейс (отдельный task)

---

## Executive Summary (для принятия решения)

1. Архитектура HDLE полностью готова к добавлению HY-MT — паттерн LocalNLLBProvider даёт готовый шаблон
2. HY-MT — decoder-only LLM (не encoder-decoder как NLLB) → нужна новая ветка backend `transformers_causal` в `worker_process.py`
3. Единственная точка регистрации провайдера: `LOCAL_PROVIDERS_CONFIG` в `local_providers_setup.py`
4. Единственное место для UI: `PROVIDERS` dict в `provider_settings_dialog.py` (захардкожен)
5. HY-MT1.5-1.8B: ~4GB VRAM (bfloat16) — влезает на RTX 3070 с запасом
6. Hebrew→Russian подтверждён в списке 33 языков
7. Terminology intervention работает через prompt-level injection + постпроцессинг (`apply_glossary`)
8. Placeholder/tag защита через XML-обёртку — нативно поддерживается HY-MT
9. Cold start 5-15с — критичный UX риск, нужен warmup или прогресс-индикатор
10. Главный неизвестный: реальное качество he→ru на HDLE-домене — обязателен SPIKE до реализации
11. Лицензия HY-MT: коммерческое использование задекларировано как разрешённое — нужна детальная проверка License.txt
12. Deployment без весов: ship без модели, user скачивает сам — стандартный паттерн (как NLLB)
13. VRAM конфликт с TTS (LightBlueTTS/MMS) при одновременной работе — задокументировать, мониторить
14. Patch series: 4 патча (PATCH-00..03) + тесты, независимы, можно откатить по отдельности
15. Kill decision после SPIKE-2: если latency >10с или качество неприемлемо → рассмотреть GGUF/llama.cpp вариант
