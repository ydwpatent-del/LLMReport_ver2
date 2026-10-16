import sys
import tempfile
import subprocess
from pathlib import Path

source_path = Path("Source/통합_C20499_퀀텀닷_20260609_R.pdf").resolve()
with tempfile.TemporaryDirectory() as temp_dir:
    temp_out_md = Path(temp_dir) / "output_raw.md"
    cmd = f'cmd /c npx -y kordoc@^4 "{source_path}" -p 2 -o "{temp_out_md}"'
    subprocess.run(cmd, shell=True, capture_output=True)
    img_dir = Path(temp_dir) / "images"
    for f in img_dir.glob("*.png"):
        if f.stat().st_size > 500000:
            import shutil
            # 이 이미지를 scratch 또는 artifacts 폴더에 복사해서 확인
            shutil.copy2(f, "tests/quantum_p2_image.png")
            print("Saved quantum_p2_image.png, size:", f.stat().st_size)
