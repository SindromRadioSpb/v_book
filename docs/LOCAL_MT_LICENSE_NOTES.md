# Local MT License Notes

**Document Version:** 1.0
**Date:** 2026-02-08

---

## Overview

This document provides license information for Local MT components in HDLE Premium. **This is not legal advice** — please review upstream licenses directly before using these models in your specific context.

---

## Translation Models

### NLLB-200 (No Language Left Behind)

**Model:** `facebook/nllb-200-distilled-1.3B`
**Provider:** Meta AI (Facebook Research)
**License:** CC-BY-NC 4.0 (Creative Commons Attribution-NonCommercial 4.0)

**License Summary:**
- ✅ **Allowed:** Research, internal use, academic use
- ✅ **Allowed:** Modification, distribution (with attribution)
- ❌ **Not Allowed:** Commercial use (requires separate licensing)
- ⚠️ **Attribution Required:** Must credit Meta AI and NLLB project

**License URL:**
- Full license: https://creativecommons.org/licenses/by-nc/4.0/
- Model card: https://huggingface.co/facebook/nllb-200-distilled-1.3B

**Citation:**
```
@article{nllb2022,
  title={No Language Left Behind: Scaling Human-Centered Machine Translation},
  author={NLLB Team and others},
  journal={arXiv preprint arXiv:2207.04672},
  year={2022}
}
```

**What is "Commercial Use"?**
- Commercial use typically means: using the model to generate revenue, selling translations, or providing translation as a paid service
- Internal company use (translating internal documents) may be allowed under CC-BY-NC 4.0, but consult your legal team
- If in doubt, contact Meta AI for commercial licensing options

**HDLE Premium Position:**
- HDLE Premium is an **internal tool** for CAT (Computer-Assisted Translation) workflows
- Users are responsible for ensuring their specific use case complies with CC-BY-NC 4.0
- For commercial translation services, consider paid alternatives (DeepL, Google Translate) or contact Meta AI for licensing

---

### Seamless M4T v2 (Future)

**Model:** `facebook/seamless-m4t-v2-large` (not yet integrated)
**Provider:** Meta AI (Facebook Research)
**License:** CC-BY-NC 4.0 (Creative Commons Attribution-NonCommercial 4.0)

**License Summary:** Same as NLLB-200 (see above)

**License URL:**
- Full license: https://creativecommons.org/licenses/by-nc/4.0/
- Model card: https://huggingface.co/facebook/seamless-m4t-v2-large

---

## Dependencies

### CTranslate2

**Project:** OpenNMT/CTranslate2
**License:** MIT License
**URL:** https://github.com/OpenNMT/CTranslate2

**License Summary:**
- ✅ **Allowed:** Commercial use, modification, distribution, private use
- ⚠️ **Condition:** Include MIT License notice in distributions

**MIT License Text:**
```
Copyright (c) 2020-present OpenNMT

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software...
```

Full license: https://github.com/OpenNMT/CTranslate2/blob/master/LICENSE

---

### Hugging Face Transformers

**Project:** huggingface/transformers
**License:** Apache License 2.0
**URL:** https://github.com/huggingface/transformers

**License Summary:**
- ✅ **Allowed:** Commercial use, modification, distribution, patent use
- ⚠️ **Condition:** Include Apache 2.0 License notice, state changes

**License URL:**
- Full license: https://github.com/huggingface/transformers/blob/main/LICENSE
- Apache 2.0: https://www.apache.org/licenses/LICENSE-2.0

---

### SentencePiece (Tokenizer)

**Project:** google/sentencepiece
**License:** Apache License 2.0
**URL:** https://github.com/google/sentencepiece

**License Summary:** Same as Transformers (Apache 2.0)

**License URL:**
- Full license: https://github.com/google/sentencepiece/blob/master/LICENSE

---

## HDLE Premium License

**HDLE Premium:** [Your project's license]

**Local MT Integration:**
- HDLE Premium acts as a **client** to Local MT models
- Users are responsible for complying with model licenses (CC-BY-NC 4.0)
- HDLE Premium does not redistribute model files (users download from Hugging Face)
- HDLE Premium provides integration layer only (worker process, segmentation, glossary postprocess)

---

## Attributions

When using Local MT in HDLE Premium, consider including the following attributions in your translated documents or project credits:

**For NLLB-200 Translations:**
```
Translation powered by NLLB-200 (Meta AI)
https://github.com/facebookresearch/fairseq/tree/nllb
License: CC-BY-NC 4.0
```

**For CTranslate2 Inference:**
```
Inference powered by CTranslate2 (OpenNMT)
https://github.com/OpenNMT/CTranslate2
License: MIT
```

---

## Third-Party Model Licenses

**Important:** Model licenses on Hugging Face may change. Always check the model card for the latest license information before downloading or using models.

**Where to check:**
1. Model card: https://huggingface.co/facebook/nllb-200-distilled-1.3B
2. Files and versions tab: Check `LICENSE` or `README.md`
3. Model metadata: `config.json` may include license field

**If license is unclear:**
- Contact model author (Meta AI for NLLB/Seamless)
- Use paid alternatives (DeepL, Google Translate) with clear commercial licenses

---

## Compliance Checklist

Before using Local MT in production:

- [ ] Review CC-BY-NC 4.0 license terms (https://creativecommons.org/licenses/by-nc/4.0/)
- [ ] Confirm your use case is non-commercial (or obtain commercial license)
- [ ] Verify model license on Hugging Face has not changed
- [ ] Include attribution in project credits (if redistributing translations)
- [ ] Consult legal team (if using for commercial translation services)
- [ ] Document model version used (for reproducibility and license tracking)

---

## Resources

**License References:**
- Creative Commons CC-BY-NC 4.0: https://creativecommons.org/licenses/by-nc/4.0/
- MIT License: https://opensource.org/licenses/MIT
- Apache License 2.0: https://www.apache.org/licenses/LICENSE-2.0

**Model Cards:**
- NLLB-200: https://huggingface.co/facebook/nllb-200-distilled-1.3B
- Seamless M4T v2: https://huggingface.co/facebook/seamless-m4t-v2-large
- CTranslate2: https://github.com/OpenNMT/CTranslate2
- Transformers: https://github.com/huggingface/transformers

**Contact:**
- Meta AI Licensing: opensource@meta.com
- Hugging Face Support: https://huggingface.co/support

---

**Disclaimer:** This document is provided for informational purposes only and does not constitute legal advice. HDLE Premium and its contributors are not responsible for license compliance violations. Users are solely responsible for ensuring their use of Local MT models complies with applicable licenses and laws.

---

**Last Updated:** 2026-02-08
**Document Version:** 1.0
