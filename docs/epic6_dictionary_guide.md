# Dictionary View — User Guide (Epic 6)

> Relevant for: HDLE Premium, Dictionary panel
> Updated: 2026-03-23

---

## What's New in Epic 6

Epic 6 brings three layers of improvement to the Dictionary view:

- **6A — Provenance tracking:** the system now records *who* and *when* assigned noise/valid status to each lemma.
- **6B — Visible semantics:** that provenance data surfaces directly in the table as badges, tooltips, and a status-bar metric.
- **6C — This guide:** documenting what you see and how to read it.

The guiding principle: **backend truth → product truth.**
The data was already correct — now it's *visible* in daily work.

---

## Table Columns

### Column layout (Dictionary / Lemma table)

| # | Column | Notes |
|---|--------|-------|
| 0 | UD | User dictionary indicator + study state |
| 1 | Lemma | Hebrew text |
| 2 | POS | Part of speech |
| 3 | Freq | Absolute frequency |
| 4 | Docs | Document frequency |
| 5 | Translation | Editable inline |
| 6 | Source | Translation source |
| 7 | Status | Translation status |
| 8 | Noise | Noise/Valid badge with provenance suffix |
| 9 | Entity Class | NER class (if detected) |
| 10 | Last Review | Study review grade |
| 11 | Niqqud | Pronunciation (hover for full details) |
| 12 | Audio | Audio status |

---

## Reading the Noise Column (col 8)

The Noise column tells you two things at once:

1. **What the lemma is:** Noise or Valid
2. **Who made that decision** (the provenance suffix)

### Badge values

| Badge | Meaning |
|-------|---------|
| `Noise (auto)` | NLP pipeline classified this as noise automatically |
| `Noise (manual)` | A user explicitly marked this as noise |
| `Valid (auto)` | NLP pipeline classified this as valid automatically |
| `Valid (manual)` | A user explicitly confirmed this as valid |
| `Noise` | Noise — source unknown (legacy record, pre-Epic 6A) |
| `Valid` | Valid — source unknown (legacy record, pre-Epic 6A) |
| *(empty)* | Not yet classified |

### Tooltip

Hover over any Noise cell to see the full provenance:

- For `auto` entries: date of automatic classification
- For `manual` entries: date of manual decision
- For legacy entries: "source unknown (legacy data)" — this is expected, not a bug

**Why no date for legacy records?**
Records created before Epic 6A did not store a classification date. The system shows `source unknown (legacy data)` to make this explicit — it is not an error, it is a transparent statement about data age.

---

## Reading the Entity Class Column (col 9)

If the Hebrew NLP pipeline detected a named entity in a lemma, the entity class appears here.

### Common NER codes

| Code | Meaning |
|------|---------|
| `GPE` | Geo-Political Entity (country, city, region) |
| `PER` | Person name |
| `ORG` | Organization |
| `LOC` | Location |
| `FAC` | Facility (building, infrastructure) |
| `MISC` | Miscellaneous named entity |

Hover over the cell to see the full description. An empty cell means no named entity was detected for this lemma.

---

## Status Bar: Noise Counter

At the bottom of the Dictionary panel you will see two numbers:

```
Found: 312 lemmas   |   Noise: 47
```

**Important:** `Noise: 47` is the **project-wide** count of noise lemmas — it is **not** filtered by your current search.

This is an intentional design choice: the noise count is a *project health metric*, not a projection of the current filter. Its purpose is to give you a stable sense of how much noise the project contains, regardless of what you are searching for at the moment.

If you filter to 20 rows and see `Noise: 47` — that means 47 lemmas in the *entire project* are marked as noise, not that 47 of your 20 results are noise.

---

## Semantic Axes Explained

The Dictionary UI currently surfaces two distinct semantic axes. They are kept separate by design.

### Axis 1 — Noise Provenance

*Who* set the noise or valid state, and when.

| State | Badge | Tooltip |
|-------|-------|---------|
| Auto-classified noise | `Noise (auto)` | Date of classification |
| Manually marked noise | `Noise (manual)` | Date of marking |
| Auto-classified valid | `Valid (auto)` | Date of classification |
| Manually confirmed valid | `Valid (manual)` | Date of confirmation |
| Legacy noise | `Noise` | "source unknown (legacy data)" |
| Legacy valid | `Valid` | "source unknown (legacy data)" |
| Not classified | *(empty)* | "Not yet classified" |

### Axis 2 — Source Lifecycle

*Whether* the lemma is still linked to an active corpus source.

| State | Meaning |
|-------|---------|
| `linked` | Lemma exists and is active in the current corpus extraction |
| `source_missing` | Source was deleted after this entry was created (entry preserved) |
| `manual` | Entry created manually — no corpus source link |
| `auto_only` | Created automatically with no user involvement |

> **Note:** Source lifecycle information is currently surfaced in the **TM (Translation Management) panel**, not in the Dictionary row tooltip. It is a planned extension for a future patch. The vocabulary is documented here so the two axes are never confused.

---

## Troubleshooting

**Why does a lemma have no date in the tooltip?**
Records created before Epic 6A (March 2026) do not have provenance metadata. The system marks them as `legacy data`. This is correct behaviour, not a bug.

**Why does the tooltip not show detailed information for some cells?**
Tooltips are shown only for cells that have data. Empty Entity Class cells, unclassified noise cells, and rows without pronunciation text will show no tooltip or a minimal one.

**Why does the Noise counter not match the number of rows I see?**
The noise counter is project-wide, not filtered. See "Status Bar: Noise Counter" above.

**Why do I see both `Noise` and `Noise (auto)` in the same table?**
`Noise` without a suffix is a legacy record (no provenance stored). `Noise (auto)` is a newer record where the NLP pipeline's decision was recorded. Both mean the lemma is classified as noise — the difference is whether we know *who* made that decision.
