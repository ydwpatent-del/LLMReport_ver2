import sys
import tempfile
import subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

source_path = Path("Source/통합_C20499800_난연제_20260527_NR.pdf").resolve()
with tempfile.TemporaryDirectory() as temp_dir:
    temp_out_md = Path(temp_dir) / "output_raw.md"
    cmd = f'cmd /c npx -y kordoc@^4 "{source_path}" -p 1-3 -o "{temp_out_md}"'
    subprocess.run(cmd, shell=True, capture_output=True)
    if temp_out_md.exists():
        raw_md = temp_out_md.read_text(encoding="utf-8", errors="replace")
        import re
        tags = re.findall(r'!\[.*?\]\([^\)]+\)', raw_md)
        print("Nan-yeon-jae kordoc raw image tags:")
        for t in tags:
            print(" ", t)
            
        # image_004 주변 텍스트 확인
        idx = raw_md.find("image_004")
        if idx != -1:
            start = max(0, idx - 200)
            end = min(len(raw_md), idx + 200)
            print("\nContext around image_004:")
            print(raw_md[start:end])
