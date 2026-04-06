# SPIKE-2: HY-MT Validation Results

> Model: `tencent/HY-MT1.5-1.8B` | Device: `cuda` | Dtype: `bfloat16`
> Model load time: **5.6s**

## Summary

| Metric | Value |
|--------|-------|
| Total tests | 19 |
| Passed | 19 (✅) |
| Failed | 0 (✅) |
| Avg latency | 1.39s |
| Min latency | 0.65s |
| Max latency | 2.30s |

## ✅ GO

| Criterion | Target | Actual | Status |
|-----------|--------|--------|--------|
| Avg latency | < 5.0s | 1.39s | ✅ |
| Pass rate | ≥ 75% | 100% | ✅ |
| Placeholder preservation | 100% | 100% | ✅ |
| Hallucination rate | < 10% | 0/19 | ✅ |

## Results by Category

### Basic (5/5 passed)

| ID | Source | Translation | Latency | Expected | Status |
|----|--------|------------|---------|----------|--------|
| basic_01 | שלום עולם | Шалом, мир вам! | 1.16s | мир | ✅ |
| basic_02 | הספרייה הלאומית של ישראל | Национальная библиотека Израиля | 0.88s | национальн, библиотек, израил | ✅ |
| basic_03 | מערכת ניהול מסדי נתונים יחסיים | Система управления относительными базами данных | 1.01s | систем, баз, данн | ✅ |
| basic_04 | הוראות שימוש במוצר זה חייבות להיקרא לפני... | Инструкции по использованию данного продукта необходимо проч... | 2.20s | инструкц, использован, перед | ✅ |
| basic_05 | לחץ על הכפתור כדי להמשיך | Нажмите на кнопку, чтобы продолжить. | 1.05s | нажмите, кнопку, продолжить | ✅ |

### Terminology (4/4 passed)

| ID | Source | Translation | Latency | Expected | Status |
|----|--------|------------|---------|----------|--------|
| term_01 | מאגר הנתונים אינו פעיל | База данных не работает. | 0.65s | база данных | ✅ |
| term_02 | יש לפתוח את תפריט ההגדרות | Необходимо открыть меню настроек. | 0.91s | меню | ✅ |
| term_03 | מנהל הרשת אחראי על אבטחת המידע | Сетевой администратор отвечает за обеспечение информационной... | 1.75s | сетевой администратор | ✅ |
| term_04 | קובץ הקוד מכיל שגיאת תחביר | Файл с кодом содержит синтаксические ошибки. | 1.58s | синтаксическ | ✅ |

### Placeholder (5/5 passed)

| ID | Source | Translation | Latency | Expected | Status |
|----|--------|------------|---------|----------|--------|
| placeholder_01 | שלום, {name}! ברוך הבא. | Здравствуйте, {name}! Добро пожаловать. | 1.59s | Добро пожаловать | ✅ |
| placeholder_02 | לחץ על <כפתור>המשך</כפתור> כדי להמשיך | Нажмите на <כפתור> и </כפתור>, чтобы продолжить. | 1.53s | Нажмите, продолжить | ✅ |
| placeholder_03 | נותרו %d פריטים ב-%s | В разделе %s осталось ещё один элемент с идентификатором %d. | 2.25s | остал | ✅ |
| placeholder_04 | הקובץ {filename} נשמר ב-{path} | Файл {filename} сохранен в файле {path}. | 1.49s | файл | ✅ |
| placeholder_05 | שגיאה: <error code="404">דף לא נמצא</err... | Ошибка: Файл <error code="404">דף не найден. Также файл </er... | 2.30s | Ошибка | ✅ |

### Mixed_Language (3/3 passed)

| ID | Source | Translation | Latency | Expected | Status |
|----|--------|------------|---------|----------|--------|
| mixed_01 | אנחנו משתמשים ב-database לאחסון נתונים | Мы используем базу данных для хранения информации. | 1.49s | данн | ✅ |
| mixed_02 | יש להריץ את ה-script לאחר ה-deployment | Необходимо выполнить запуск скрипта после его развертывания. | 1.73s | запуск, скрипт, разверт | ✅ |
| mixed_03 | הגדרת ה-API key בקובץ ה-config | Определение ключа API в файле config | 0.92s | API, config | ✅ |

### Contextual (2/2 passed)

| ID | Source | Translation | Latency | Expected | Status |
|----|--------|------------|---------|----------|--------|
| context_01 | הפעל אותו | Включите его в процесс развертывания сервера. | 1.16s | Включите | ✅ |
| context_02 | לחץ עליו | Нажмите на этот кнопку. | 0.83s | Нажмите | ✅ |

## Full Translations

### basic_01 [basic] — ✅ PASS
**Source**: `שלום עולם`
**Translation**: Шалом, мир вам!
**Latency**: 1.16s
**Expected (missing)**: ['привет', 'здравствуй']

### basic_02 [basic] — ✅ PASS
**Source**: `הספרייה הלאומית של ישראל`
**Translation**: Национальная библиотека Израиля
**Latency**: 0.88s

### basic_03 [basic] — ✅ PASS
**Source**: `מערכת ניהול מסדי נתונים יחסיים`
**Translation**: Система управления относительными базами данных
**Latency**: 1.01s

### basic_04 [basic] — ✅ PASS
**Source**: `הוראות שימוש במוצר זה חייבות להיקרא לפני ההפעלה`
**Translation**: Инструкции по использованию данного продукта необходимо прочитать перед началом его эксплуатации.
**Latency**: 2.20s

### basic_05 [basic] — ✅ PASS
**Source**: `לחץ על הכפתור כדי להמשיך`
**Translation**: Нажмите на кнопку, чтобы продолжить.
**Latency**: 1.05s

### term_01 [terminology] — ✅ PASS
**Source**: `מאגר הנתונים אינו פעיל`
**Translation**: База данных не работает.
**Latency**: 0.65s

### term_02 [terminology] — ✅ PASS
**Source**: `יש לפתוח את תפריט ההגדרות`
**Translation**: Необходимо открыть меню настроек.
**Latency**: 0.91s
**Expected (missing)**: ['настройки']

### term_03 [terminology] — ✅ PASS
**Source**: `מנהל הרשת אחראי על אבטחת המידע`
**Translation**: Сетевой администратор отвечает за обеспечение информационной безопасности.
**Latency**: 1.75s
**Expected (missing)**: ['информационная безопасность']

### term_04 [terminology] — ✅ PASS
**Source**: `קובץ הקוד מכיל שגיאת תחביר`
**Translation**: Файл с кодом содержит синтаксические ошибки.
**Latency**: 1.58s

### placeholder_01 [placeholder] — ✅ PASS
**Source**: `שלום, {name}! ברוך הבא.`
**Translation**: Здравствуйте, {name}! Добро пожаловать.
**Latency**: 1.59s
**Expected (missing)**: ['Привет']

### placeholder_02 [placeholder] — ✅ PASS
**Source**: `לחץ על <כפתור>המשך</כפתור> כדי להמשיך`
**Translation**: Нажмите на <כפתור> и </כפתור>, чтобы продолжить.
**Latency**: 1.53s

### placeholder_03 [placeholder] — ✅ PASS
**Source**: `נותרו %d פריטים ב-%s`
**Translation**: В разделе %s осталось ещё один элемент с идентификатором %d.
**Latency**: 2.25s

### placeholder_04 [placeholder] — ✅ PASS
**Source**: `הקובץ {filename} נשמר ב-{path}`
**Translation**: Файл {filename} сохранен в файле {path}.
**Latency**: 1.49s
**Expected (missing)**: ['сохранён']

### placeholder_05 [placeholder] — ✅ PASS
**Source**: `שגיאה: <error code="404">דף לא נמצא</error>`
**Translation**: Ошибка: Файл <error code="404">דף не найден. Также файл </error> также не найден.
**Latency**: 2.30s
**Expected (missing)**: ['не найдена']

### mixed_01 [mixed_language] — ✅ PASS
**Source**: `אנחנו משתמשים ב-database לאחסון נתונים`
**Translation**: Мы используем базу данных для хранения информации.
**Latency**: 1.49s
**Expected (missing)**: ['database']

### mixed_02 [mixed_language] — ✅ PASS
**Source**: `יש להריץ את ה-script לאחר ה-deployment`
**Translation**: Необходимо выполнить запуск скрипта после его развертывания.
**Latency**: 1.73s
**Expected (missing)**: ['script', 'развёрт', 'deployment']

### mixed_03 [mixed_language] — ✅ PASS
**Source**: `הגדרת ה-API key בקובץ ה-config`
**Translation**: Определение ключа API в файле config
**Latency**: 0.92s

### context_01 [contextual] — ✅ PASS
**Source**: `הפעל אותו`
**Translation**: Включите его в процесс развертывания сервера.
**Latency**: 1.16s
**Expected (missing)**: ['Запустите', 'Активируйте']

### context_02 [contextual] — ✅ PASS
**Source**: `לחץ עליו`
**Translation**: Нажмите на этот кнопку.
**Latency**: 0.83s

## Architecture Notes

### Worker design decision
Provider builds full prompt → `WorkerRequest.text` = prompt → worker does tokenize/generate/decode.
`WorkerRequest` protocol unchanged.

### `worker_process.py` changes required
```python
# New backend: "transformers_causal"
# New functions: _load_transformers_causal_model(), _translate_transformers_causal()
# Existing NLLB branches unchanged
```

### placeholder protection
**MANDATORY, not optional.** Every `LocalHYMTProvider.translate()` call must:
1. `protect_placeholders(source_text)` → protected text + mapping
2. Build prompt with protected text
3. Inference
4. `restore_placeholders(translation, mapping)` + validate missing

### terminology_mode
Default: `both` (prompt injection + `apply_glossary()` postprocess). Hardcoded, not a user toggle.
