import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
from app.utils import is_valid_content_image

nan_img = Path("WikiDB/assets/통합_C20499800_난연제_20260527_NR_1788760392_3226cd92/image_004.png")
if nan_img.exists():
    print("Nan-yeon-jae image_004 size:", nan_img.stat().st_size)
    print("  has_caption=True ->", is_valid_content_image(nan_img, has_caption=True))
    print("  has_caption=False ->", is_valid_content_image(nan_img, has_caption=False))
    
    # 픽셀 공백률 직접 측정
    import pymupdf
    pix = pymupdf.Pixmap(str(nan_img))
    width, height, n, samples = pix.width, pix.height, pix.n, pix.samples
    tot_sampled = 0
    white_cnt = 0
    for y in range(0, height, 4):
        row_offset = y * width * n
        for x in range(0, width, 8):
            idx = row_offset + x * n
            r, g, b = samples[idx], samples[idx + 1], samples[idx + 2]
            a = samples[idx + 3] if n == 4 else 255
            tot_sampled += 1
            if a < 15 or (r > 240 and g > 240 and b > 240):
                white_cnt += 1
    print(f"  Nan-yeon-jae blank ratio: {white_cnt / tot_sampled:.1%}")
