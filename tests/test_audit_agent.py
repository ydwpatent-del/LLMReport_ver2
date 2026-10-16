"""원문 대조 AI 검수 및 자율 보정 엔진(AuditAgent) 단위 테스트 모듈."""

import pymupdf
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.audit_agent import (
    AuditAgent,
    AuditReport,
    AuditIssue,
    BackupManager,
    QualityGate,
)


def test_backup_and_rollback(tmp_path: Path):
    """수정 전 자동 백업 생성 및 롤백 기능 검증."""
    doc_file = tmp_path / "test_doc.md"
    doc_file.write_text("# Original Content\nInitial text.", encoding="utf-8")

    mgr = BackupManager(backup_dir=tmp_path / ".backup")
    backup_file = mgr.create_backup(doc_file)

    assert backup_file.exists()
    assert backup_file.read_text(encoding="utf-8") == "# Original Content\nInitial text."

    # 내용 변경 시뮬레이션
    doc_file.write_text("# Modified Content\nCorrupted text.", encoding="utf-8")

    # 롤백 수행
    success = mgr.rollback(doc_file, backup_file)
    assert success is True
    assert doc_file.read_text(encoding="utf-8") == "# Original Content\nInitial text."


def test_audit_detects_missing_table_and_content(tmp_path: Path):
    """원문 PDF에 존재하는 표와 섹션이 마크다운에서 누락되었을 때 감지(Dry-Run) 검증."""
    pdf_path = tmp_path / "source.pdf"
    doc = pymupdf.open()

    page = doc.new_page(width=600, height=800)
    # 본문 문단
    p1 = "Chapter 1. Industry Overview\n\nThis chapter explains the basic supply chain of the sector.\n\n"
    # 표 구조화 데이터 문단 (독립 단락)
    p2 = "Supply Chain Structure Table\nUpstream: Raw Petrochemical Materials\nCore Industry: High Value Synthetics\nDownstream: Electronic Semiconductor Devices"

    page.insert_text((50, 100), p1 + p2, fontsize=11)

    doc.save(str(pdf_path))
    doc.close()

    # 표가 누락된 마크다운 (표준 헤더 포함)
    incomplete_md = (
        "# Industry Overview\n\n"
        "> - **원본 파일명**: source.pdf\n"
        "> - **발행기관**: Test Institute\n"
        "> - **발행일자**: 2026년 01월 01일\n"
        "> - **문서분류**: 리서치 보고서\n"
        "> - **핵심 엔티티**: #Overview\n"
        "> - **원본형식**: PDF (100% 무삭제 전수 인제스트)\n"
        "> - **인제스트 일시**: 2026-01-01 00:00:00 UTC\n"
        "> - **무결성 해시 (SHA-256)**: 1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef\n"
        "> - **데이터 보존 원칙**: 100% 무삭제 완본 (Full-Text Ingestion)\n"
        "---\n\n"
        "## Chapter 1. Industry Overview\n\n"
        "This chapter explains the basic supply chain of the sector.\n\n"
        "## Chapter 2. Technology\n"
    )
    md_path = tmp_path / "test_doc.md"
    md_path.write_text(incomplete_md, encoding="utf-8")

    agent = AuditAgent(docs_dir=tmp_path, backup_dir=tmp_path / ".backup")
    report = agent.audit_document(
        doc_id="test_doc",
        source_path=pdf_path,
        md_path=md_path
    )

    assert isinstance(report, AuditReport)
    assert report.is_healthy is False
    assert len(report.missing_tables) > 0 or len(report.missing_sections) > 0


def test_quality_gate_rejects_red_flags():
    """AI 보정 산출물에 축약/중략 등 Red Flag 결함이 포함된 경우 게이트에서 거부되는지 검증."""
    corrupted_content = (
        "# Sample Document\n\n"
        "## 1. Summary\n\n"
        "세부 실적 및 재무제표는 ...(중략)... 처리함.\n"
        "기타 항목 10개 외 생략 등...\n"
    )

    is_valid, reasons = QualityGate.validate(corrupted_content)
    assert is_valid is False
    assert len(reasons) > 0


def test_quality_gate_accepts_clean_content():
    """kordoc 규격을 준수한 완전한 본문은 게이트를 정상 통과하는지 검증."""
    clean_content = (
        "# Sample Document\n\n"
        "## 1. 개요\n\n"
        "전체 세부 실적을 100% 무삭제로 수록함.\n\n"
        "| 구분 | 실적 |\n"
        "|:---|:---|\n"
        "| 매출액 | 5,000억원 |\n"
    )

    is_valid, reasons = QualityGate.validate(clean_content)
    assert is_valid is True
    assert len(reasons) == 0


def test_audit_and_heal_all_tiered_healing(tmp_path: Path):
    """audit_and_heal_all이 서식 결함(Tier 1)과 치명적 결함(Tier 2)을 각각 올바르게 분기 치유하는지 검증."""
    from unittest.mock import MagicMock
    from app.manifest import DocumentEntry

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()

    # 1. Tier 1 대상 문서 생성 (불릿 이중기호 및 들여쓰기 미흡)
    t1_source = source_dir / "t1.txt"
    t1_source.write_text("샘플 본문입니다.", encoding="utf-8")
    t1_md = docs_dir / "doc_t1.md"
    t1_md.write_text(
        "# T1 Document\n\n"
        "> - **원본 파일명**: `t1.txt`\n"
        "> - **발행기관**: 기관\n"
        "> - **무결성 해시 (SHA-256)**: `h1`\n"
        "> - **데이터 보존 원칙**: 완본\n\n"
        "## 목차\n\n- [1. 개요](#1-개요)\n\n"
        "## 1. 개요\n\n"
        "□ 대항목 1\n"
        "- ○ 중항목 1-1\n",
        encoding="utf-8"
    )

    entry_t1 = DocumentEntry(
        id="doc_t1",
        original_filename="t1.txt",
        source_path=str(t1_source),
        file_hash="h1",
        file_size=100,
        modified_time=1.0,
        target_md_path=str(t1_md),
        assets_dir="",
        status="completed",
        title="T1 Document"
    )

    # 2. Tier 2 대상 문서 생성 (깨진 표가 포함된 치명적 결함 문서)
    t2_source = source_dir / "t2.pdf"
    t2_source.write_text("PDF Dummy Content", encoding="utf-8")
    t2_md = docs_dir / "doc_t2.md"
    t2_md.write_text(
        "# T2 Broken Document\n\n"
        "## 1. 개요\n\n"
        "| 깨진표라인\n",
        encoding="utf-8"
    )

    entry_t2 = DocumentEntry(
        id="doc_t2",
        original_filename="t2.pdf",
        source_path=str(t2_source),
        file_hash="h2",
        file_size=200,
        modified_time=2.0,
        target_md_path=str(t2_md),
        assets_dir="",
        status="completed",
        title="T2 Broken Document"
    )

    mock_manifest = MagicMock()
    mock_manifest.get_all_documents.return_value = [entry_t1, entry_t2]

    # Engine Mock (Tier 2 재인제스트 시 완본 반환)
    mock_engine = MagicMock()
    mock_engine.execute_ingest.return_value = (
        t2_md,
        [],
        "T2 Healed Document"
    )

    agent = AuditAgent(docs_dir=docs_dir, backup_dir=backup_dir)
    stats = agent.audit_and_heal_all(
        manifest_mgr=mock_manifest,
        engine=mock_engine,
        source_dir=source_dir,
        docs_dir=docs_dir,
        assets_dir=assets_dir
    )

    assert stats["audited"] == 2
    assert stats["tier1_healed"] == 1
    assert stats["tier2_healed"] == 1
    assert stats["failed"] == 0

    # Tier 1 결과물에 들여쓰기(2칸) 적용 확인
    t1_fixed = t1_md.read_text(encoding="utf-8")
    assert "  ○ 중항목 1-1" in t1_fixed

    # Tier 2 재인제스트 호출 검증
    mock_engine.execute_ingest.assert_called_once()


def test_backup_manager_default_path_is_absolute(tmp_path):
    """AuditAgent 기본 생성 시 backup_dir이 절대 경로여야 한다."""
    from app.audit_agent import AuditAgent

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    auditor = AuditAgent(docs_dir=docs_dir)

    assert auditor.backup_mgr.backup_dir.is_absolute(), \
        f"backup_dir이 절대 경로가 아닙니다: {auditor.backup_mgr.backup_dir}"


def test_audit_and_heal_single_recovers_truncated_doc_from_valid_backup(tmp_path: Path):
    """현재 마크다운이 조기 절단(1.5KB)되어 있고 재인제스트도 절단된 결과를 반환할 때,
    백업 폴더 내의 완본 스냅샷을 복원하고 표 파손까지 치유하여 정상 완본으로 복구하는지 검증."""
    from app.manifest import DocumentEntry

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    backup_dir = docs_dir / ".backup"
    backup_dir.mkdir()
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    # 3페이지짜리 원문 PDF 생성
    pdf_path = source_dir / "hbf_brief.pdf"
    doc = pymupdf.open()
    for p_idx in range(3):
        p = doc.new_page()
        p.insert_text((50, 100), f"Page {p_idx+1} HBF High Bandwidth Flash memory architecture content detail.")
    doc.save(str(pdf_path))
    doc.close()

    # 현재 디스크의 마크다운은 목차에서 잘린 200자 파손본
    md_path = docs_dir / "doc_hbf.md"
    md_path.write_text(
        "# HBF의 등장\n> - **원본 파일명**: hbf_brief.pdf\n---\n## 목차\n- [HBF](#hbf-",
        encoding="utf-8"
    )

    # 백업 폴더에는 본문 전체가 다 들어있지만 표 중간에 줄바꿈 파손만 있던 완본 백업이 존재
    full_backup_content = (
        "# HBF의 등장\n"
        "> - **원본 파일명**: hbf_brief.pdf\n"
        "> - **발행기관**: 산업기술리서치센터\n"
        "> - **무결성 해시 (SHA-256)**: hash123\n"
        "> - **데이터 보존 원칙**: 100% 무삭제 완본\n"
        "---\n\n"
        "## 1. HBF 개요\n\n"
        "Page 1 HBF High Bandwidth Flash memory architecture content detail.\n\n"
        "Page 2 HBF High Bandwidth Flash memory architecture content detail.\n\n"
        "## 2. 계층 비교\n\n"
        "Page 3 HBF High Bandwidth Flash memory architecture content detail.\n\n"
        "| 구분 | As-Is | 구분 | To-Be |\n"
        "|:---|:---|:---|:---|\n"
        "| HBM | Hot 데이터 | HBM | Hot 데이터 |\n"
        "| \n\n"
        "| | | Warm 데이터 일부 |\n"
        "| - | 성능 공백 | HBF | Warm 데이터 |\n"
    )
    (backup_dir / "doc_hbf_20260928_104324.bak.md").write_text(full_backup_content, encoding="utf-8")

    entry = DocumentEntry(
        id="doc_hbf",
        original_filename="hbf_brief.pdf",
        source_path=str(pdf_path),
        file_hash="hash123",
        file_size=1000,
        modified_time=1.0,
        target_md_path=str(md_path),
        assets_dir="",
        status="completed",
        title="HBF의 등장"
    )
    mock_manifest = MagicMock()
    mock_manifest.get_document.return_value = entry

    # 엔진 재인제스트가 또다시 200자짜리 절단된 결과를 덮어쓰는 상황 시뮬레이션
    mock_engine = MagicMock()
    def fake_bad_ingest(source_path, doc_id, file_hash, skip_lint=False):
        md_path.write_text("# HBF의 등장\n## 목차\n- [잘림](#", encoding="utf-8")
        return md_path, [], "HBF의 등장"
    mock_engine.execute_ingest.side_effect = fake_bad_ingest

    auditor = AuditAgent(docs_dir=docs_dir, backup_dir=backup_dir)
    success, msg, _ = auditor.audit_and_heal_single(
        doc_id="doc_hbf",
        manifest_mgr=mock_manifest,
        engine=mock_engine,
        source_dir=source_dir,
        docs_dir=docs_dir
    )

    assert success is True
    healed_text = md_path.read_text(encoding="utf-8")
    post_report = auditor.audit_document("doc_hbf", pdf_path, md_path)
    assert post_report.is_healthy is True, f"치유 후에도 결함이 남아있습니다: {post_report.red_flags}, {post_report.missing_sections}"


def test_audit_document_handles_pdf_unspaced_text_without_false_positives(tmp_path: Path):
    """PDF에서 글자 간 공백이 없이 추출된 단락이더라도, 마크다운 본문에 정상 띄어쓰기로
    존재하는 경우 누락 단락(missing_sections)으로 오탐하지 않는지 검증."""
    pdf_path = tmp_path / "unspaced.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)

    # PDF에서 단락 내 일부 어절이 붙어서 추출되는 복합 단락 시뮬레이션
    unspaced_text = "• AI 개발속도는인간의추종을불허하는수준. 단순진보가아닌압축적도약이현실화. GPU 컴퓨팅효율화 3배."
    page.insert_text((50, 100), unspaced_text, fontsize=11)
    doc.save(str(pdf_path))
    doc.close()

    # 마크다운 본문에는 정상적인 한국어 띄어쓰기로 복원된 경우
    valid_spaced_md = (
        "# AI 현황 보고서\n\n"
        "> - **원본 파일명**: unspaced.pdf\n"
        "> - **발행기관**: 리서치센터\n"
        "> - **발행일자**: 2026년 01월 01일\n"
        "> - **문서분류**: 리서치 보고서\n"
        "> - **핵심 엔티티**: #AI #GPU\n"
        "> - **원본형식**: PDF (100% 무삭제 전수 인제스트)\n"
        "> - **인제스트 일시**: 2026-01-01 00:00:00 UTC\n"
        "> - **무결성 해시 (SHA-256)**: 1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef\n"
        "> - **데이터 보존 원칙**: 100% 무삭제 완본 (Full-Text Ingestion)\n"
        "---\n\n"
        "## I. 개요\n\n"
        "• AI 개발 속도는 인간의 추종을 불허하는 수준. 단순 진보가 아닌 압축적 도약이 현실화. GPU 컴퓨팅 효율화 3배.\n"
    )
    md_path = tmp_path / "test_unspaced.md"
    md_path.write_text(valid_spaced_md, encoding="utf-8")

    agent = AuditAgent(docs_dir=tmp_path, backup_dir=tmp_path / ".backup")
    report = agent.audit_document(
        doc_id="test_unspaced",
        source_path=pdf_path,
        md_path=md_path
    )

    assert len(report.missing_sections) == 0, f"정상 본문이 누락으로 오탐되었습니다: {report.missing_sections}"
    assert report.is_healthy is True




