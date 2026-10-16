import sys
import tempfile
import subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

from app.utils import (
    stitch_adjacent_pdf_images,
    clean_pdf_decorative_images,
    enrich_composite_overlay_images,
    is_valid_content_image
)
from app.kordoc_wiki_agent import KordocWikiAgent

def test_pipeline(pdf_name):
    source_path = Path(f"Source/{pdf_name}").resolve()
    print(f"\n==================== TESTING {pdf_name} ====================")
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        temp_out_md = temp_dir_path / "output_raw.md"
        cmd = f'cmd /c npx -y kordoc@^4 "{source_path}" -p 1-3 -o "{temp_out_md}"'
        subprocess.run(cmd, shell=True, capture_output=True)
        
        search_dirs = [temp_dir_path / "images", temp_dir_path]
        temp_raw = temp_out_md.read_text(encoding="utf-8", errors="replace")
        
        print("[kordoc extracted images]:")
        for f in sorted((temp_dir_path / "images").glob("*.png")):
            print(f"  {f.name} ({f.stat().st_size} bytes)")
            
        temp_raw = stitch_adjacent_pdf_images(source_path, temp_raw, search_dirs)
        temp_raw = clean_pdf_decorative_images(source_path, temp_raw, search_dirs)
        temp_raw = enrich_composite_overlay_images(source_path, temp_raw, search_dirs)
        
        print("\n[After enrich_composite_overlay_images]:")
        for f in sorted((temp_dir_path / "images").glob("*.png")):
            print(f"  {f.name} ({f.stat().st_size} bytes)")
            
        doc_asset_dir = temp_dir_path / "doc_assets"
        agent = KordocWikiAgent(docs_dir=temp_dir_path, assets_dir=temp_dir_path)
        raw_md, extracted_images_info = agent._extract_and_inline_images(
            temp_raw, "test_doc", doc_asset_dir, search_dirs
        )
        
        print("\n[Images kept in extracted_images_info]:")
        for info in extracted_images_info:
            print(f"  Kept: {info['filename']}")
            
        import re
        tags = re.findall(r'!\[.*?\]\([^\)]+\)', raw_md)
        print("\n[Image tags in raw_md]:")
        for t in tags:
            print(" ", t)

test_pipeline("통합_C20499800_난연제_20260527_NR.pdf")
test_pipeline("통합_C20499_퀀텀닷_20260609_R.pdf")
