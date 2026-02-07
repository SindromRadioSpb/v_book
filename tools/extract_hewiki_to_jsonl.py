import json
import os
import sys
import importlib
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

WX_REPO = r"J:\Project_Vibe\V_book\tools\Wikiextractor-V2"
DUMP_PATH = r"J:\Project_Vibe\V_book\ref_corpora\hewiki\raw\hewiki-20260201-pages-articles.xml.bz2"
TEMPLATES_PATH = r"J:\Project_Vibe\V_book\ref_corpora\hewiki\raw\templates-he.xml"
OUT_JSONL = r"J:\Project_Vibe\V_book\ref_corpora\hewiki\hewiki_docs.jsonl"

SOURCE = "hewiki"
DUMP_VERSION = os.path.basename(DUMP_PATH)

def one_line(text: str) -> str:
    return " ".join((text or "").split())

def load_wx_main():
    """
    Robust loader for Wikiextractor-V2 main():
    1) Prefer package import: wikiextractor.WikiExtractor (keeps package context)
    2) Fallback: load WikiExtractor.py by absolute path (handles namespace/import collisions)
    """
    if WX_REPO not in sys.path:
        sys.path.insert(0, WX_REPO)

    # Attempt 1: module import (recommended by V2 README for module usage)
    try:
        mod = importlib.import_module("wikiextractor.WikiExtractor")
        main_fn = getattr(mod, "main", None)
        if callable(main_fn):
            return main_fn, getattr(mod, "__file__", "wikiextractor.WikiExtractor")
    except Exception:
        pass

    # Attempt 2: direct file load (last resort)
    candidates = [
        Path(WX_REPO) / "wikiextractor" / "WikiExtractor.py",
        Path(WX_REPO) / "WikiExtractor.py",
    ]
    wx_path = None
    for p in candidates:
        if p.is_file():
            wx_path = p
            break
    if not wx_path:
        raise FileNotFoundError(
            "Cannot locate WikiExtractor.py in Wikiextractor-V2 repo. "
            f"Checked: {', '.join(str(p) for p in candidates)}"
        )

    spec = importlib.util.spec_from_file_location("wikiextractor_v2_WikiExtractor", str(wx_path))
    if not spec or not spec.loader:
        raise RuntimeError(f"Failed to create import spec for {wx_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]

    main_fn = getattr(mod, "main", None)
    if not callable(main_fn):
        raise AttributeError(f"'main' not found in loaded module: {wx_path}")
    return main_fn, str(wx_path)

def main() -> None:
    if not os.path.isfile(DUMP_PATH):
        raise FileNotFoundError(f"Dump not found: {DUMP_PATH}")

    wx_main, wx_origin = load_wx_main()
    print("WikiExtractor loaded from:", wx_origin)

    aargs = [
        DUMP_PATH,
        "--generator",
        "--json",
        "--discard_sections",
        "--discard_templates",
        "--ignore_templates",
        "-ns",
        "0",
    ]
    kkwargs = {"--templates": TEMPLATES_PATH}

    extracted_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    n = 0

    out_path = Path(OUT_JSONL)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as out:
        for item in wx_main(*aargs, **kkwargs):
            # V2 generator yields either dict (json mode) or tuple
            if isinstance(item, dict):
                doc_id = item.get("doc_id") or item.get("id") or ""
                title = item.get("title") or ""
                url = item.get("url") or ""
                language = item.get("language") or ""
                text = item.get("text") or ""
            else:
                doc_id, title, url, language, text = item

            doc_id = str(doc_id) if doc_id is not None else ""
            title = str(title) if title is not None else ""
            if not doc_id:
                doc_id = title

            rec = {
                "doc_id": doc_id,
                "title": title,
                "text": one_line(str(text)),
                "url": str(url),
                "language": str(language),
                "source": SOURCE,
                "dump_version": DUMP_VERSION,
                "extracted_at": extracted_at,
            }
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
            if n % 10000 == 0:
                print(f"Wrote {n} docs...")

    print("DONE. Total docs:", n)
    print("OUT:", str(out_path))

if __name__ == "__main__":
    main()
