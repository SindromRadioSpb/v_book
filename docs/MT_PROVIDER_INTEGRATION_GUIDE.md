# MT Provider Integration Guide — HDLE Premium

> Цель: минимальное time-to-first-translation для нового MT-провайдера.
> Читать вместе с: `AUDIT_HY-MT-provider.md` (полный audit + архитектурные решения).
> Reference implementation: `local_hymt_provider.py` — HY-MT1.5-1.8B, экспериментальный
> local backend, успешно интегрирован 2026-04-06.

---

## Архитектура (5-минутный обзор)

```
BaseProvider (ABC)                         ← контракт провайдера
  ↑ implements
LocalXxxProvider                           ← твой новый провайдер
  ↓ uses
ProvidersRegistry (singleton)             ← реестр всех провайдеров
  ↑ populated by
local_providers_setup.LOCAL_PROVIDERS_CONFIG  ← конфиг регистрации

TranslationService._translate_via_provider_chain()  ← точка входа из UI
  ↓ iterates chain from QSettings["mt/providers/chain"]
  ↓ registry.get(provider_id) → provider.translate(request)

ProviderSettingsDialog.PROVIDERS           ← UI список провайдеров (захардкожен)
```

**Ключевой инвариант**: `translate()` НИКОГДА не бросает исключений.
Всегда возвращает `TranslationResult` с `error_kind` при ошибке.

---

## Чеклист нового провайдера (5 шагов)

### Шаг 1: Создать класс провайдера

**Файл**: `app/infra/translators/providers/local_{name}_provider.py`
**Шаблон**: скопировать `local_nllb_provider.py`, адаптировать.

```python
# Минимальная реализация
class LocalXxxProvider(BaseProvider):

    def __init__(self, model_id: str, backend: str, ...):
        self.model_id = model_id
        self.backend = backend
        self._init_worker()  # или другой init

    @property
    def provider_id(self) -> str:
        return "local_xxx"  # уникальный, lowercase, underscore

    @property
    def display_name(self) -> str:
        return "Xxx Model (Offline)"

    @property
    def supports_glossary(self) -> bool:
        return True  # или False

    def translate(self, request: TranslationRequest) -> TranslationResult:
        start = time.time()
        try:
            # ... inference ...
            return TranslationResult(
                translated_text=result,
                provider_id=self.provider_id,
                latency_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            logger.error(f"Translation failed: {e}")
            return TranslationResult(
                provider_id=self.provider_id,
                error_kind=TranslationErrorKind.SERVER,
                error_message=str(e),
                latency_ms=int((time.time() - start) * 1000),
            )

    def healthcheck(self) -> bool:
        # проверка без side-effects
        return self.worker is not None and self.worker.ping(timeout=5.0)

    def shutdown(self):
        if self.worker:
            self.worker.shutdown()
            self.worker = None
```

**Обязательное правило**: `translate()` не бросает исключения — ловить всё.

---

### Шаг 2: Выбрать тип backend

#### Вариант A: Subprocess worker (рекомендуется для локальных ML-моделей)

Используется для: NLLB, HY-MT и любых моделей с тяжёлым ML-инфером.

```python
# В __init__ провайдера
from app.infra.local_mt import LocalMTWorker, start_worker

self.worker = start_worker(
    model_path=model_path,    # Path к директории модели
    backend="transformers_causal",  # см. worker_process.py
    model_id=self.model_id,
    timeout=self.timeout,
)

# В translate()
from app.infra.local_mt import WorkerRequest
worker_req = WorkerRequest(text=text, source_lang=src, target_lang=tgt)
result = self.worker.translate(worker_req)  # блокирующий вызов
```

**Добавление нового backend в worker_process.py**:

Если существующие `"ctranslate2"` и `"transformers_causal"` не подходят, добавить новую ветку:

```python
# В _worker_main():
elif backend == "my_new_backend":
    model = _load_my_new_backend_model(model_path, model_id)

# Добавить функции:
def _load_my_new_backend_model(model_path, model_id):
    # загрузка модели
    ...

def _translate_my_new_backend(model, text, src_lang, tgt_lang):
    # инференс
    ...
```

#### Вариант B: HTTP API (для cloud/SaaS провайдеров)

```python
# В translate()
import requests
response = requests.post(
    url=self.api_url,
    json={"text": request.source_text, ...},
    headers={"Authorization": f"Bearer {self.api_key}"},
    timeout=request.timeout_seconds,
)
```

Примеры: `providers/deepl_provider.py`, `providers/google_translate_provider.py`.

#### Вариант C: In-process (только для лёгких утилит, не ML)

Только если модель < 100MB и не блокирует поток надолго.

---

### Шаг 3: Зарегистрировать провайдер

**Файл**: `app/infra/translators/local_providers_setup.py`

```python
LOCAL_PROVIDERS_CONFIG = [
    {
        "provider_class": LocalNLLBProvider,
        ...
    },
    # ← ДОБАВИТЬ:
    {
        "provider_class": LocalXxxProvider,
        "model_id": "vendor/ModelName",
        "backend": "transformers_causal",  # или "ctranslate2" / "transformers"
        "enabled_by_default": False,        # False — пока модель не установлена
    },
]
```

**Важно**: `enabled_by_default=False` для локальных провайдеров без гарантированной модели.

Если провайдер не локальный (SaaS), добавить отдельную функцию по образцу `register_google_cloud_translate()`.

---

### Шаг 4: Добавить в UI Provider Settings

**Файл**: `app/ui/provider_settings_dialog.py`, словарь `PROVIDERS`:

```python
PROVIDERS = {
    # ... existing ...
    "local_xxx": {
        "name": "Xxx Model (Offline)",
        "default_rate_limit": 9999,   # unlimited для local
        "default_enabled": False,
        "supports_advanced": False,    # True если нужен свой таб настроек
    },
}
```

Если нужен кастомный advanced tab (model path, device, dtype) — добавить по образцу `_create_gcp_settings()`.

**QSettings ключи** (формат `mt/providers/{provider_id}/...`):

| Ключ | Helper-функция | Назначение |
|------|---------------|-----------|
| `.../enabled` | `get_enabled_key(pid)` | вкл/выкл |
| `.../rate_limit` | `get_rate_limit_key(pid)` | лимит запросов |
| `.../auth_mode` | `get_auth_mode_key(pid)` | тип аутентификации |
| `.../api_key_credential_id` | — | ссылка на CredentialStore |

Добавлять собственные ключи: `mt/providers/local_xxx/model_path` и т.д. — любые, через `SettingsService.get_string()`.

---

### Шаг 5: Написать тесты

**Минимальный набор** (`tests/test_local_xxx_provider.py`):

```python
# 1. Провайдер не регистрируется если модель не установлена
def test_not_registered_when_model_missing(): ...

# 2. translate() не бросает исключения
def test_translate_returns_result_not_exception(): ...

# 3. translate() с пустым текстом
def test_translate_empty_text(): ...

# 4. Unsupported language → TranslationErrorKind.UNSUPPORTED
def test_translate_unsupported_lang(): ...

# 5. healthcheck() при живом воркере → True
def test_healthcheck_alive(): ...

# 6. translate() при мёртвом воркере → error, не exception
def test_translate_dead_worker(): ...
```

---

## Типы провайдеров: быстрый выбор

| Тип | Backend | Примеры | Ключевой файл |
|-----|---------|---------|---------------|
| Локальный encoder-decoder | `ctranslate2` | NLLB, Helsinki-NLP | `local_nllb_provider.py` |
| Локальный decoder-only LLM | `transformers_causal` | HY-MT, ALMA | `local_hymt_provider.py` (будущий) |
| Cloud REST API с key | HTTP + CredentialStore | DeepL, Microsoft | `deepl_provider.py` |
| Cloud REST API OAuth | HTTP + ServiceAccount | Google Cloud v3 | `google_cloud_translate_provider.py` |
| Free scraping | HTTP | Google Translate free | `google_translate_provider.py` |
| Локальный API server | HTTP к localhost | LibreTranslate | `libretranslate_provider.py` |

---

## Механизмы glossary / TM

### Постпроцессинг (работает для любого провайдера)

`apply_glossary()` в `services/local_mt/glossary_postprocess.py`:
- Сравнивает `source_segments` с TM-записями (`src_norm` exact match)
- Заменяет соответствующие `target_segments` на утверждённые TM-переводы
- Возвращает `PostprocessResult` с `match_count`

```python
# Использование в translate()
if self.db_session:
    postprocess_result = apply_glossary(
        self.db_session,
        source_segments=source_segments,
        target_segments=mt_translations,
        src_lang=src_nllb,
        tgt_lang=tgt_nllb,
        project_id=self.project_id,
    )
    mt_translations = postprocess_result.translations
    used_glossary = postprocess_result.match_count > 0
```

### Prompt-level (для LLM-провайдеров)

`GlossaryBuilderService.build_canonical_glossary()` в `services/glossary_builder_service.py`:
- Строит список `{src_term: tgt_term}` из approved TM
- Возвращает `CanonicalGlossary` с `glossary_hash`

```python
from app.services.glossary_builder_service import GlossaryBuilderService
glossary = GlossaryBuilderService(session).build_canonical_glossary(
    src_lang="he", tgt_lang="ru", project_id=None
)
# glossary.entries → list[(src_term, tgt_term)]
# glossary.glossary_hash → str (для cache key)
```

---

## Cache (MT Cache слой)

MT-результаты кэшируются в SQLite таблице `mt_cache`.
Cache key: `hash(src_norm + src_lang + tgt_lang + provider_id + model_version + glossary_hash)`.

Кэш применяется **до** вызова `provider.translate()` в `TranslationService._lookup_mt_cache()`.
Запись в кэш происходит **после** успешного перевода.

`get_model_version()` в провайдере влияет на cache key:
```python
def get_model_version(self) -> str:
    # Разные версии/квантования → разные записи в кэше
    return f"{self.model_id.replace('/', '_')}_{self.backend}_{self.dtype}"
```

---

## Конфигурация и credentials

### Локальные настройки (без auth)
Читать/писать через `SettingsService`:
```python
from app.infra.settings import SettingsService
settings = SettingsService.get_instance()
value = settings.get_string("mt/providers/local_xxx/model_path", "")
settings.set_value("mt/providers/local_xxx/model_path", "/path/to/model")
```

### API keys (cloud провайдеры)
Хранить в `CredentialStore` (OS keyring + encrypted DB):
```python
from app.infra.translators.provider_config import get_api_key_credential_id
from app.infra.security import CredentialStore

cred_id = get_api_key_credential_id("my_provider")  # "mt_provider:my_provider:api_key"
# Запись (из UI):
cred_store.set_credential(cred_id, plaintext_api_key)
# Чтение (в провайдере):
api_key = cred_store.get_credential(cred_id)
```

---

## ModelResourceManager (локальные модели)

```python
from app.services.local_models.model_resource_manager import ModelResourceManager

mgr = ModelResourceManager()

# Путь к директории модели (Windows: %LOCALAPPDATA%\HDLE\models\...)
model_dir = mgr.model_dir("vendor/ModelName", "transformers_causal")

# Проверка установки (наличие manifest.json)
is_installed, reason = mgr.is_installed("vendor/ModelName", "transformers_causal")
```

**Формат директории**: `{safe_model_id}_{backend}` (/ → _).
**Требования**: директория должна содержать `manifest.json` с полями:
- `model_id`, `backend`, `version`, `sha256` (опционально), `languages`

---

## Питфоллы и как их избежать

| Проблема | Решение |
|----------|---------|
| `translate()` бросает исключение → ломает chain | Всегда оборачивать в try/except, возвращать `TranslationResult(error_kind=...)` |
| `healthcheck()` вызывается часто и медленный | Кэшировать статус, timeout 5с максимум |
| Cold start блокирует UI при lazy init | `initialize_provider_lazy()` вызывать из background thread |
| Shared DB session между потоками | Передавать `db_session` при инициализации провайдера из главного потока только; в worker subprocess НЕ передавать |
| Дублирование регистрации | `registry.register()` бросает ValueError — использовать `if registry.get(pid): return True` |
| Забыли `shutdown()` → утечка subprocess | Всегда реализовывать `shutdown()`, вызывать из `__del__()` |
| `get_model_version()` не переопределён | Разные квантования будут использовать тот же кэш (баг качества) |
| Chain порядок в UI не обновляется | Новый провайдер добавляется в конец chain — документировать для пользователя |

---

## Lessons Learned: decoder-only LLM backend (HY-MT, 2026-04-06)

Зафиксировано по итогам интеграции `LocalHYMTProvider` (first decoder-only MT backend в HDLE).

### 1. Worker owns the template — не provider

**Проблема**: если provider кладёт инструкции в user content и передаёт как `WorkerRequest.text`,
decoder-only LLM может перевести инструкции вместо исходного текста.

**Правило**: для decoder-only LLM worker строит полный шаблон сам:
```python
# worker_process.py — _translate_transformers_causal
chat_text = f"{BOS}{SYSTEM_PROMPT}{SEP}{USER_TOKEN}Translate…\n\n{user_content}{ASSISTANT_TOKEN}"
```
Provider передаёт только `user_content` = protected source text + optional terminology line.

### 2. Placeholder protection — mandatory, не optional

Для RTL-языков (иврит) использовать ASCII-safe токены `HDLE_PH_N`, не XML `<ph id="N"/>`.
XML-токены с кавычками ломаются из-за Unicode RTL-марок (U+200E/200F), вставляемых
контекстом иврита вокруг атрибутов тегов.

### 3. Stop tokens обязательны для decoder-only

Без `eos_token_id` модель продолжает генерацию после перевода.
Регистрировать все специальные стоп-токены при загрузке модели, кэшировать в model dict.

### 4. apply_chat_template() — проверять совместимость

`apply_chat_template()` может генерировать шаблон, несовместимый с production inference моделью.
При расхождении: строить raw template string по vendor-документации / PocketPal / llama.cpp config.

### 5. Glossary / TM — критичен для технического домена

Для специализированного домена (религиозные тексты, IT-документация) без TM-постпроцессинга
качество терминологии нестабильно. `terminology_mode="both"` (prompt injection + `apply_glossary()`)
даёт лучший результат, чем только один из методов.

---

## Smoke verification (PowerShell)

После добавления нового провайдера:

```powershell
# 1. Импорт не падает
python -c "from app.infra.translators.providers.local_xxx_provider import LocalXxxProvider; print('OK')"

# 2. Регистрация (при установленной модели)
python -c "
from app.infra.translators.local_providers_setup import check_local_providers_available
status = check_local_providers_available()
for pid, info in status.items(): print(pid, info)
"

# 3. Полный test suite
python -m pytest tests/test_local_xxx_provider.py -v

# 4. Регрессия: убедиться что NLLB не сломан
python -m pytest tests/ -k "nllb or translation_service" -v
```

---

## Чеклист DoD для нового провайдера

- [ ] `provider_id` уникален, lowercase, underscore
- [ ] `translate()` никогда не бросает исключения
- [ ] `translate()` с пустым текстом возвращает `TranslationResult(translated_text="")`
- [ ] `healthcheck()` работает за < 5с
- [ ] `shutdown()` освобождает ресурсы
- [ ] `get_model_version()` уникален для каждого варианта модели
- [ ] Запись в `LOCAL_PROVIDERS_CONFIG` с `enabled_by_default=False`
- [ ] Запись в `ProviderSettingsDialog.PROVIDERS`
- [ ] `logger.error()` при каждой ошибке перед возвратом `error_kind`
- [ ] Latency логируется в `meta` dict
- [ ] Тесты: offline/no-model, empty text, unsupported lang, dead worker
- [ ] `python -m pytest -v` регрессия проходит полностью
- [ ] PowerShell smoke verification работает
