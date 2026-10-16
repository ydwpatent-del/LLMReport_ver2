"""누락 이미지 12개 문서 대상 안전한 일괄 외과적 복원(Safe In-place Patch) 스크립트. (API 비용 $0)"""

import re
import sys
import shutil
from pathlib import Path

# UTF-8 출력 보장
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.manifest import ManifestManager

def run_batch_patch():
    settings = get_settings()
    manifest_mgr = ManifestManager(settings.manifest_path)
    docs = manifest_mgr.get_all_documents()

    print("================================================================================")
    print("🩹 [WikiDB 누락 이미지 2단계 일괄 외과적 복원 가동]")
    print("================================================================================\n")

    patched_docs_count = 0
    total_injected_images = 0

    for idx, doc in enumerate(docs, 1):
        doc_id = doc.id
        title = doc.title or doc.original_filename
        md_path = Path(doc.target_md_path) if doc.target_md_path else settings.docs_dir / f"{doc_id}.md"
        asset_dir = Path(doc.assets_dir) if doc.assets_dir else settings.assets_dir / doc_id

        if not md_path.exists() or not asset_dir.exists():
            continue

        original_md = md_path.read_text(encoding="utf-8", errors="replace")

        # 1. 에셋 파일과 본문 태그 대조
        linked_matches = re.findall(rf'/api/assets/{re.escape(doc_id)}/([^\)\s"\'<>]+)', original_md)
        if not linked_matches:
            linked_matches = [
                Path(m.group(1)).name
                for m in re.finditer(r'!\[.*?\]\([^\)]*?assets/[^/]+/([^\)\s]+)\)', original_md)
            ]
        linked_set = set(linked_matches)

        actual_files = sorted([f.name for f in asset_dir.glob("*.png") if f.is_file()])
        for ext in ("*.jpg", "*.jpeg", "*.webp"):
            actual_files.extend(sorted([f.name for f in asset_dir.glob(ext) if f.is_file()]))
        actual_set = set(actual_files)

        missing_files = sorted(list(actual_set - linked_set))
        if not missing_files:
            continue

        patched_docs_count += 1
        print(f"[{idx:02d}] 🛠️ 복원 작업 대상: {title} (누락 {len(missing_files)}건)")

        updated_md = original_md

        for mf in missing_files:
            reinject_tag = f"\n\n![도표/인포그래픽](/api/assets/{doc_id}/{mf})\n\n"
            injected = False

            # 전략 1: 번호 순서(image_NNN.png) 기반 인접 이미지 위치 탐색
            num_match = re.search(r'image_(\d+)', mf)
            if num_match:
                curr_num = int(num_match.group(1))

                # 1-1. 바로 직전 번호의 이미지(curr_num - 1, -2, ...) 태그 뒤에 삽입
                for prev_num in range(curr_num - 1, 0, -1):
                    prev_pat = rf'(!\[.*?\]\([^\)]*?image_{prev_num:03d}[^\)]*\)[^\n]*\n*(?:\*\([^\n]+\)\*)?)'
                    m_prev = re.search(prev_pat, updated_md)
                    if m_prev:
                        pos = m_prev.end()
                        updated_md = updated_md[:pos] + reinject_tag + updated_md[pos:]
                        injected = True
                        print(f"       └─ 💉 [순서 탐색]: {mf} -> image_{prev_num:03d} 바로 뒤 외과적 삽입 성공")
                        break

                # 1-2. 직전 번호가 없으면 바로 직후 번호의 이미지(curr_num + 1, +2, ...) 태그 앞에 삽입
                if not injected:
                    for next_num in range(curr_num + 1, curr_num + 15):
                        next_pat = rf'(!\[.*?\]\([^\)]*?image_{next_num:03d}[^\)]*\))'
                        m_next = re.search(next_pat, updated_md)
                        if m_next:
                            pos = m_next.start()
                            updated_md = updated_md[:pos] + reinject_tag + updated_md[pos:]
                            injected = True
                            print(f"       └─ 💉 [순서 탐색]: {mf} -> image_{next_num:03d} 바로 앞 외과적 삽입 성공")
                            break

            # 전략 2: composite_pXXX 또는 특수 인포그래픽 탐색
            if not injected:
                comp_match = re.search(r'composite_p(\d+)', mf)
                page_num = int(comp_match.group(1)) if comp_match else 2

                # 2페이지 인포그래픽인 경우 산업 개요/업종/기술 섹션 탐색
                section_candidates = [
                    r'(###?\s+업종[^\n]*)',
                    r'(###?\s+산업\s*분류[^\n]*)',
                    r'(###?\s+산업\s*구조[^\n]*)',
                    r'(##\s+산업\s*개요[^\n]*)',
                    r'(##\s+기술\s*동향[^\n]*)',
                ]
                for sec_pat in section_candidates:
                    m_sec = re.search(sec_pat, updated_md)
                    if m_sec:
                        # 해당 섹션 라인 뒤의 빈 줄 위치에 삽입
                        nl_pos = updated_md.find('\n\n', m_sec.end())
                        insert_pos = nl_pos + 2 if nl_pos != -1 else m_sec.end()
                        updated_md = updated_md[:insert_pos] + reinject_tag + updated_md[insert_pos:]
                        injected = True
                        print(f"       └─ 💉 [섹션 탐색]: {mf} -> '{m_sec.group(1).strip()}' 뒤 외과적 삽입 성공")
                        break

            # 전략 3: 본문 말미 결합 (안전 폴백)
            if not injected:
                updated_md = updated_md.strip() + reinject_tag
                print(f"       └─ 💉 [폴백 결합]: {mf} -> 본문 말미 결합 완료")

            total_injected_images += 1

        # 연속된 불필요 빈 줄 정돈
        updated_md = re.sub(r'\n{4,}', '\n\n', updated_md)

        # 디스크 안전 덮어쓰기
        md_path.write_text(updated_md, encoding="utf-8")
        print(f"   ✅ 파일 저장 완료: {md_path.name}\n")

    print("================================================================================")
    print(f"🏁 [일괄 외과적 복원 완료]")
    print(f"   - 복원 처리된 문서 수: {patched_docs_count}건")
    print(f"   - 본문에 재주입된 이미지 수: 총 {total_injected_images}개")
    print("================================================================================\n")

if __name__ == "__main__":
    run_batch_patch()
