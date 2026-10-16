import sys
import tempfile
import subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
from app.utils import is_valid_content_image

source_path = Path("Source/통합_C20499_퀀텀닷_20260609_R.pdf").resolve()
with tempfile.TemporaryDirectory() as temp_dir:
    temp_out_md = Path(temp_dir) / "output_raw.md"
    cmd = f'cmd /c npx -y kordoc@^4 "{source_path}" -p 2 -o "{temp_out_md}"'
    subprocess.run(cmd, shell=True, capture_output=True)
    img_dir = Path(temp_dir) / "images"
    for f in img_dir.glob("*.png"):
        if f.stat().st_size > 500000:
            print("Found large image:", f.name, f.stat().st_size)
            print("  has_caption=True ->", is_valid_content_image(f, has_caption=True))
            print("  has_caption=False ->", is_valid_content_image(f, has_caption=False))
