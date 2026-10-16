import sys
import tempfile
import subprocess
from pathlib import Path
import pymupdf

sys.stdout.reconfigure(encoding='utf-8')

source_path = Path("Source/통합_C20499_퀀텀닷_20260609_R.pdf").resolve()
doc = pymupdf.open(str(source_path))
page = doc[1] # page 2
images = page.get_images()
print("Page 2 xrefs and pix sizes:")
for img in images:
    xref = img[0]
    pix = pymupdf.Pixmap(doc, xref)
    print(f"  xref {xref}: {pix.width}x{pix.height}")

with tempfile.TemporaryDirectory() as temp_dir:
    temp_dir_path = Path(temp_dir)
    temp_out_md = temp_dir_path / "output_raw.md"
    cmd = f'cmd /c npx -y kordoc@^4 "{source_path}" -p 2 -o "{temp_out_md}"'
    subprocess.run(cmd, shell=True, capture_output=True)
    img_dir = temp_dir_path / "images"
    print("\nkordoc extracted images on page 2:")
    for f in sorted(img_dir.glob("*.png")):
        pix = pymupdf.Pixmap(str(f))
        print(f"  {f.name}: {pix.width}x{pix.height} ({f.stat().st_size} bytes)")
