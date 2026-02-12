# PowerPoint (.pptx) Import Support

## Overview

HDLE Premium now supports importing PowerPoint presentations in .pptx format.

## Features

- **Automatic text extraction** from all slides
- **Includes:**
  - Slide titles
  - Body text
  - Text in shapes
  - Table cells

- **Does NOT include:**
  - Speaker notes (can be added if needed)
  - Comments
  - Images/charts (text extraction only)

## Technical Implementation

**Library:** `python-pptx>=0.6.21`
- Mature, well-maintained library
- Pure Python, no external dependencies
- Same architecture as `python-docx`

**Files Modified:**
- `app/infra/extractors/pptx_extractor.py` - NEW text extractor
- `app/services/ingest_service.py` - Added .pptx to SUPPORTED_EXTENSIONS
- `app/ui/documents_view.py` - Updated file filters
- `pyproject.toml` - Added python-pptx dependency

## Usage

1. **Add Files:** Click "Add Files" in Documents view
2. **Select:** File dialog now shows `*.pptx` in filter
3. **Import:** Text is automatically extracted from all slides

## Testing

```python
# Create test PPTX
from pptx import Presentation
prs = Presentation()
slide = prs.slides.add_slide(prs.slide_layouts[0])
slide.shapes.title.text = "Test Slide"
prs.save("test.pptx")

# Extract text
from app.infra.extractors import pptx_extractor
text = pptx_extractor.extract_text(Path("test.pptx"))
print(text)  # Output: "Test Slide"
```

## Supported Formats Summary

After this update:
- ✅ `.txt` - Plain text
- ✅ `.docx` - Word documents
- ✅ `.pptx` - PowerPoint presentations (NEW)
- ✅ `.pdf` - PDF documents (with optional OCR)

## Future Enhancements

Potential additions (not implemented):
- `.ppt` - Legacy PowerPoint (requires pywin32 + MS Office)
- `.doc` - Legacy Word (requires pywin32 + MS Office)
- Speaker notes extraction (`.pptx` only)
