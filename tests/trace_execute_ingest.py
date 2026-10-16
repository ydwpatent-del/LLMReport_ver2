import sys
import tempfile
import subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

from app.kordoc_wiki_agent import KordocWikiAgent

source_path = Path("Source/통합_C20499_퀀텀닷_20260609_R.pdf").resolve()
doc_id = "test_doc_quantum"
file_hash = "test_hash"

with tempfile.TemporaryDirectory() as temp_dir:
    temp_dir_path = Path(temp_dir)
    docs_dir = temp_dir_path / "docs"
    assets_dir = temp_dir_path / "assets"
    agent = KordocWikiAgent(docs_dir=docs_dir, assets_dir=assets_dir)
    
    # execute_ingest를 skip_lint=True로 실행해보자 (LLM 호출 여부도 확인)
    print("API KEY present?:", bool(agent.api_key))
    target_md, extracted_imgs, title = agent.execute_ingest(
        source_path=source_path,
        doc_id=doc_id,
        file_hash=file_hash,
        skip_lint=True
    )
    
    print("\n=== execute_ingest 완료 ===")
    print("Extracted images count:", len(extracted_imgs))
    for p in extracted_imgs:
        print("  - Returned img:", p.name)
        
    doc_asset_dir = assets_dir / doc_id
    print("\nFiles in doc_asset_dir:")
    if doc_asset_dir.exists():
        for f in sorted(doc_asset_dir.glob("*.*")):
            print("  - Asset file:", f.name, f.stat().st_size)
            
    if target_md.exists():
        content = target_md.read_text(encoding="utf-8")
        import re
        tags = re.findall(r'!\[.*?\]\([^\)]+\)', content)
        print("\nImage tags in generated Markdown:")
        for t in tags:
            print("  MD Tag:", t)
            
        print("\nIs image_004 mentioned in MD?:", "image_004" in content)
