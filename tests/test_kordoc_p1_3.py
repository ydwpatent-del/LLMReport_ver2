import tempfile, subprocess
from pathlib import Path

source_path = Path("Source/통합_C20499_퀀텀닷_20260609_R.pdf").resolve()
with tempfile.TemporaryDirectory() as temp_dir:
    temp_out_md = Path(temp_dir) / "output_raw.md"
    cmd = f'cmd /c npx -y kordoc@^4 "{source_path}" -p 1-3 -o "{temp_out_md}"'
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
    img_dir = Path(temp_dir) / "images"
    print("kordoc returncode:", res.returncode)
    if img_dir.exists():
        for f in sorted(img_dir.glob("*.*")):
            print(f"  - Extracted img: {f.name} ({f.stat().st_size} bytes)")
    if temp_out_md.exists():
        content = temp_out_md.read_text(encoding="utf-8", errors="replace")
        print("\nMarkdown excerpt:")
        print(content[:2000])
