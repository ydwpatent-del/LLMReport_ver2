import sys
import tempfile
import subprocess
from pathlib import Path

# UTF-8 출력 설정
sys.stdout.reconfigure(encoding='utf-8')

from app.utils import (
    is_valid_content_image,
    stitch_adjacent_pdf_images,
    clean_pdf_decorative_images,
    enrich_composite_overlay_images
)

source_path = Path("Source/통합_C20499_퀀텀닷_20260609_R.pdf").resolve()
with tempfile.TemporaryDirectory() as temp_dir:
    temp_dir_path = Path(temp_dir)
    temp_out_md = temp_dir_path / "output_raw.md"
    cmd = f'cmd /c npx -y kordoc@^4 "{source_path}" -p 1-3 -o "{temp_out_md}"'
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
    
    img_dir = temp_dir_path / "images"
    raw_md = temp_out_md.read_text(encoding="utf-8", errors="replace")
    
    print("=== [1] kordoc 직후 추출된 이미지 목록 ===")
    for f in sorted(img_dir.glob("*.png")):
        print(f"  - {f.name}: {f.stat().st_size} bytes")
        
    print("\n=== [2] raw_md 내 이미지 태그 ===")
    import re
    tags = re.findall(r'!\[.*?\]\([^\)]+\)', raw_md)
    for t in tags:
        print("  Tag:", t)
        
    print("\n=== [3] stitch_adjacent_pdf_images 실행 후 ===")
    search_dirs = [img_dir, temp_dir_path]
    md_after_stitch = stitch_adjacent_pdf_images(source_path, raw_md, search_dirs)
    print("  image_004 in md after stitch?:", "image_004" in md_after_stitch)
    print("  image_004 file exists?:", (img_dir / "image_004.png").exists())
    
    print("\n=== [4] clean_pdf_decorative_images 실행 후 ===")
    md_after_clean = clean_pdf_decorative_images(source_path, md_after_stitch, search_dirs)
    print("  image_004 in md after clean?:", "image_004" in md_after_clean)
    print("  image_004 file exists?:", (img_dir / "image_004.png").exists())

    print("\n=== [5] enrich_composite_overlay_images 실행 후 ===")
    md_after_enrich = enrich_composite_overlay_images(source_path, md_after_clean, search_dirs)
    print("  image_004 in md after enrich?:", "image_004" in md_after_enrich)
    print("  image_004 file exists?:", (img_dir / "image_004.png").exists())
    for f in sorted(img_dir.glob("*.png")):
        print(f"    current img: {f.name} ({f.stat().st_size} bytes)")
        
    print("\n=== [6] is_valid_content_image 테스트 ===")
    for f in sorted(img_dir.glob("*.png")):
        valid = is_valid_content_image(f, has_caption=True)
        print(f"  {f.name}: is_valid_content_image={valid}")
