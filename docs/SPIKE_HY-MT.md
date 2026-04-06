# SPIKE-2: HY-MT Validation on HDLE Domain

> Статус: **ЗАКРЫТ ✅** — валидация завершена 2026-04-06, результат: **GO**
> Реализация: PATCH-00..03 завершены (2026-04-06). Подробности: `SPIKE_HY-MT_results.md`

---

## Итоги SPIKE-2 (закрыт ✅)

Все GO-критерии выполнены. Модель: `tencent/HY-MT1.5-1.8B` | Device: `cuda` | Dtype: `bfloat16`

| Критерий | Target | Факт | Статус |
|----------|--------|------|--------|
| Avg latency | < 5.0s | 1.39s | ✅ |
| Pass rate | ≥ 75% | 100% (19/19) | ✅ |
| Placeholder preservation | 100% | 100% | ✅ |
| Hallucination rate | < 10% | 0% | ✅ |

Полные результаты: `docs/SPIKE_HY-MT_results.md`

### Ключевые находки SPIKE-2

- `apply_chat_template()` с user-only messages давал неверный результат: инструкции попадали в user content и переводились моделью вместо исходного текста.
- Корректный путь: worker строит raw HY-MT template (`<BOS><system><SEP><User>…<Assistant>`) напрямую.
- Placeholder format `HDLE_PH_N` (ASCII) надёжнее XML `<ph id="N"/>` в RTL-контексте.
- Stop tokens (`<｜hy_end▁of▁sentence｜>`) обязательны — без них модель продолжает генерацию.

---

## Итоги SPIKE-1 (закрыт)

**Вопрос**: Адаптируем ли `worker_process.py` для decoder-only LM?
**Ответ**: ДА, тривиально. Конкретно:

Существующая `"transformers"` ветка использует `AutoModelForSeq2SeqLM` + NLLB-специфичные атрибуты
(`tokenizer.src_lang`, `tokenizer.tgt_lang`, `forced_bos_token_id`) — они не работают для causal LM.

Нужно добавить ветку `"transformers_causal"` с двумя новыми функциями:

```python
# worker_process.py — новые функции
def _load_transformers_causal_model(model_path: str):
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        torch_dtype=torch.bfloat16,  # или float16
        device_map="auto",
        trust_remote_code=True,
    )
    return {"model": model, "tokenizer": tokenizer}


def _translate_transformers_causal(model_dict: dict, prompt_text: str) -> str:
    """Inference для decoder-only LLM. prompt_text = уже собранный полный промпт."""
    model = model_dict["model"]
    tokenizer = model_dict["tokenizer"]

    inputs = tokenizer(prompt_text, return_tensors="pt").to(model.device)
    prompt_len = inputs["input_ids"].shape[1]

    outputs = model.generate(
        **inputs,
        max_new_tokens=512,
        do_sample=True,
        top_k=20,
        top_p=0.6,
        temperature=0.7,
        repetition_penalty=1.05,
        pad_token_id=tokenizer.eos_token_id,
    )

    # Декодировать ТОЛЬКО новые токены (не промпт)
    new_tokens = outputs[0][prompt_len:]
    return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
```

**Ключевой архитектурный выбор**: провайдер строит полный промпт → кладёт в `WorkerRequest.text` →
воркер делает только `tokenize → generate → decode new tokens`.
`WorkerRequest` не изменяется. Промпт строится в `LocalHYMTProvider.translate()` (основной процесс, с доступом к DB/TM).

---

## SPIKE-2: что проверяем

1. **Latency**: короткое предложение / 10 предложений / 50 предложений
2. **Quality (basic)**: связный he→ru перевод
3. **Terminology injection**: термины из промпта попадают в перевод
4. **Placeholder protection**: `{name}`, `<tag>`, `%s` сохраняются без порчи
5. **Mixed-language**: иврит + английские технические термины
6. **Stability**: нет hallucination / explanatory drift

---

## Запуск SPIKE-2

```powershell
# Из директории проекта, с активированным venv
cd E:\projects\Project_Vibe\V_book
.\.venv\Scripts\Activate.ps1

# Запустить SPIKE
python scripts\spike_hymt_validation.py `
    --model-id tencent/HY-MT1.5-1.8B `
    --device cuda `
    --dtype bfloat16 `
    --output-report docs\SPIKE_HY-MT_results.md
```

---

## GO / NO-GO критерии

| Критерий | GO | NO-GO |
|----------|-----|-------|
| Latency 1 предложение | < 5с | > 10с |
| Latency 10 предложений | < 45с | > 90с |
| Basic quality | Понятный перевод | Мусор / отказ |
| Terminology применяется | ≥ 70% совпадений | < 40% |
| Placeholder preservation | 100% сохранены | Любая порча |
| Hallucination rate | < 10% | > 25% |

---

## Ожидаемые результаты (до запуска)

- Latency 1.8B bfloat16 на RTX 3070: **2-4с** (50-200 токенов вывода)
- Терминология: при точном prompt-injection **> 85%** совпадений для коротких терминов
- Placeholder: при XML-обёртке (`<ph id="1"/>`) **100%** сохранение
- Hallucination: при жёстком промпте (`without additional explanation`) **< 5%**
