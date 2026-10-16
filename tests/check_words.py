import sys
from pathlib import Path
import pymupdf

sys.stdout.reconfigure(encoding='utf-8')

for pdf_name in ["통합_C20499800_난연제_20260527_NR.pdf", "통합_C20499_퀀텀닷_20260609_R.pdf"]:
    source_path = Path(f"Source/{pdf_name}").resolve()
    doc = pymupdf.open(str(source_path))
    page = doc[1] # page 2
    all_words = page.get_text("words")
    rects = page.get_image_rects(31)
    r = rects[0] if rects else None
    print(f"\n[{pdf_name}] Page 2:")
    print(f"  total words on page: {len(all_words)}")
    print(f"  image rect: {r}")
    if r:
        intersecting = [w[4] for w in all_words if pymupdf.Rect(w[:4]).intersects(r)]
        print(f"  intersecting words count: {len(intersecting)}")
        print(f"  sample intersecting words: {intersecting[:15]}")
