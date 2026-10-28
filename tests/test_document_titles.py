"""
tests/test_document_titles.py
문서 마크다운(# H1) 기반 문서 제목 추출 및 매니페스트/API 동기화 검증 테스트
"""
import inspect
from pathlib import Path
import pytest
from app.manifest import ManifestManager, DocumentEntry, _extract_title_from_markdown
from app.config import Settings
from app.server import create_app


def execute_coroutine(coro):
    """파이썬 3.14 윈도우 환경에서도 이벤트루프 블로킹 없이 순수 코루틴을 즉시 평가하는 헬퍼."""
    if inspect.iscoroutine(coro):
        try:
            coro.send(None)
        except StopIteration as e:
            return e.value
    return coro


def test_extract_title_from_markdown(tmp_path: Path):
    """마크다운 파일에서 H1 대제목을 정확하고 안전하게 추출하는지 검증한다."""
    # 1. 일반적인 첫 줄 H1
    md_file1 = tmp_path / "doc1.md"
    md_file1.write_text("# 자율주행 인공지능 기술 동향\n\n본문 내용입니다.", encoding="utf-8")
    assert _extract_title_from_markdown(md_file1) == "자율주행 인공지능 기술 동향"

    # 2. 마크다운 볼드 및 인라인 태그가 포함된 H1
    md_file2 = tmp_path / "doc2.md"
    md_file2.write_text("# **[산업 보고서]** 2026 AI 반도체 *시장 분석*\n\n본문 내용", encoding="utf-8")
    assert _extract_title_from_markdown(md_file2) == "[산업 보고서] 2026 AI 반도체 시장 분석"

    # 3. 앞부분에 메타데이터 블록이나 주석이 있고 이후 H1이 나타나는 경우 (멀티라인 파싱)
    md_file3 = tmp_path / "doc3.md"
    md_file3.write_text(
        "---\n작성자: 홍길동\n날짜: 2026-10-28\n---\n\n# 차세대 에너지 저장장치 로드맵\n\n상세 본문...",
        encoding="utf-8"
    )
    assert _extract_title_from_markdown(md_file3) == "차세대 에너지 저장장치 로드맵"

    # 4. H1이 없고 일반 텍스트만 있는 경우
    md_file4 = tmp_path / "doc4.md"
    md_file4.write_text("제목 없는 문서입니다.\n내용만 있습니다.", encoding="utf-8")
    assert _extract_title_from_markdown(md_file4) is None


def test_reconcile_with_disk_heals_document_titles(tmp_path: Path):
    """reconcile_with_disk 실행 시 파일명으로 고착된 doc.title이 마크다운 H1 제목으로 치유되는지 검증한다."""
    docs_dir = tmp_path / "docs"
    assets_dir = tmp_path / "assets"
    docs_dir.mkdir()
    assets_dir.mkdir()

    manifest_file = tmp_path / "manifest.json"
    mgr = ManifestManager(manifest_file)

    # 마크다운 파일 생성
    md_path = docs_dir / "file5325371307356059324-216301.md"
    md_path.write_text(
        "# 자율주행 인공지능 기술 동향\n\n- 원본 파일명: file5325371307356059324-216301.pdf\n\n본문 내용",
        encoding="utf-8"
    )

    # 기존 매니페스트에 title이 파일명으로 잘못 등록된 상태 시뮬레이션
    entry = DocumentEntry(
        id="file5325371307356059324-216301",
        original_filename="file5325371307356059324-216301.pdf",
        source_path="",
        file_hash="abc123hash",
        file_size=md_path.stat().st_size,
        modified_time=md_path.stat().st_mtime,
        target_md_path=str(md_path.resolve()),
        assets_dir=str(assets_dir.resolve()),
        status="completed",
        title="file5325371307356059324-216301"  # 파일명으로 잘못 들어간 제목
    )
    mgr.add_or_update_document(entry)

    # 디스크 정합성 검사 및 자가 치유 실행
    res = mgr.reconcile_with_disk(docs_dir, assets_dir)
    assert res["reconciled"] >= 1

    # 치유 결과 검증
    saved_doc = mgr.get_document("file5325371307356059324-216301")
    assert saved_doc is not None
    assert saved_doc.title == "자율주행 인공지능 기술 동향"


def test_list_documents_api_returns_clean_title(tmp_path: Path):
    """GET /api/documents 호출 시 마크다운 H1 기반의 제목이 반환되는지 검증한다."""
    docs_dir = tmp_path / "docs"
    assets_dir = tmp_path / "assets"
    docs_dir.mkdir()
    assets_dir.mkdir()

    manifest_file = tmp_path / "manifest.json"
    mgr = ManifestManager(manifest_file)

    md_path = docs_dir / "sample_doc.md"
    md_path.write_text("# 인공지능 기반 지식 관리 시스템\n\n본문...", encoding="utf-8")

    entry = DocumentEntry(
        id="sample_doc",
        original_filename="sample_doc.hwp",
        source_path="",
        file_hash="hash999",
        file_size=md_path.stat().st_size,
        modified_time=md_path.stat().st_mtime,
        target_md_path=str(md_path.resolve()),
        assets_dir=str(assets_dir.resolve()),
        status="completed",
        title="인공지능 기반 지식 관리 시스템"
    )
    mgr.add_or_update_document(entry)

    settings = Settings(
        source_dir=tmp_path / "source",
        wikidb_dir=tmp_path / "wikidb",
        manifest_path=manifest_file,
        docs_dir=docs_dir,
        assets_dir=assets_dir
    )

    app = create_app(settings=settings, manifest_mgr=mgr)

    route_handler = None
    for route in app.routes:
        if getattr(route, "path", None) == "/api/documents" and "GET" in getattr(route, "methods", []):
            route_handler = route.endpoint
            break

    assert route_handler is not None, "/api/documents 엔드포인트가 등록되어 있어야 합니다."

    resp_docs = execute_coroutine(route_handler())
    assert isinstance(resp_docs, list)
    assert len(resp_docs) >= 1
    target = next((d for d in resp_docs if getattr(d, "id", None) == "sample_doc"), None)
    assert target is not None
    assert getattr(target, "title", None) == "인공지능 기반 지식 관리 시스템"
