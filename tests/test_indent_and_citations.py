"""동일 위계 문단 들여쓰기 정상화 및 위키문서 인용 링크 자동 복원 단위 테스트 모듈."""

import re
import pytest
import markdown
from pathlib import Path
from app.utils import clean_markdown_typography, resolve_citation_links
from app.html_doc_exporter import HtmlDocExporter


def test_misindented_bullets_flattened_to_same_level():
    """과거 버그로 첫 번째 항목만 2칸 들여쓰기이고 후속 항목들이 4칸 들여쓰기된 경우 동일 위계로 평탄화되는지 검증."""
    raw_md = (
        "### 3.2 시장 성장을 견인하는 핵심 동인\n"
        "  - **모바일 기기 및 웨어러블의 고성능화 및 소형화:** 설명1\n"
        "    - **전기차 및 자율주행차 시장 성장:** 설명2\n"
        "    - **Edge AI 및 온디바이스 AI의 확산:** 설명3\n"
        "    - **AI 모델의 Context Window 확장:** 설명4\n"
    )

    cleaned = clean_markdown_typography(raw_md)
    lines = [l.rstrip() for l in cleaned.splitlines() if l.strip().startswith("-")]

    # 모든 항목이 동일한 들여쓰기로 시작해야 함
    indents = [len(l) - len(l.lstrip()) for l in lines]
    assert len(set(indents)) == 1, f"불릿 들여쓰기가 서로 다릅니다: {indents}"

    # 마크다운 파싱 시 하위 <ul>(서브리스트) 없이 단일 <ul>로 렌더링되어야 함
    html = markdown.markdown(cleaned, extensions=["markdown.extensions.sane_lists"])
    ul_matches = re.findall(r'<ul\b', html)
    assert len(ul_matches) == 1, f"하위 서브리스트가 생성되었습니다: {html}"


def test_hierarchical_bullets_preserved_with_circle():
    """kordoc 3단계(□ 대항목 -> ○ 중항목 -> - 소항목) 계층 구조는 0칸-2칸-4칸으로 온전히 보존되는지 검증."""
    raw_md = (
        "## 1. 개요\n\n"
        "□ 대항목 1\n"
        "  ○ 중항목 1-1\n"
        "    - 소항목 1-1-1\n"
        "    - 소항목 1-1-2\n"
        "  ○ 중항목 1-2\n"
    )
    cleaned = clean_markdown_typography(raw_md)
    lines = [l.rstrip() for l in cleaned.splitlines() if l.strip()]

    assert "□ 대항목 1" in lines[1]
    assert "  ○ 중항목 1-1" in lines[2]
    assert "    - 소항목 1-1-1" in lines[3]
    assert "    - 소항목 1-1-2" in lines[4]
    assert "  ○ 중항목 1-2" in lines[5]


def test_resolve_citation_links_with_doc_id():
    """본문에 doc_id만 적힌 출처 태그가 올바른 마크다운 하이퍼링크로 복원되는지 검증."""
    sample = (
        "LPDDR5X는 ASIL-D 등급을 획득하였다 <출처: 015-027__홍아름_220호_최종_1790038492_a0339d78>.\n\n"
        "## 5. 데이터 출처\n"
        "- [015-027. 홍아름_220호_최종](/api/documents/015-027__홍아름_220호_최종_1790038492_a0339d78)\n"
    )
    resolved = resolve_citation_links(sample)

    assert "<출처: [015-027. 홍아름_220호_최종](/api/documents/015-027__홍아름_220호_최종_1790038492_a0339d78)>" in resolved


def test_resolve_citation_links_with_bracket_title():
    """제목에 대괄호가 포함된 출처([ibk투자증권] ...)가 올바른 마크다운 하이퍼링크로 복원되는지 검증."""
    sample = (
        "초당 약 15토큰을 처리할 수 있는 수준이다 <출처: [ibk투자증권] 반도체: Shortage! Shortage! Shortage!>.\n\n"
        "## 5. 데이터 출처\n"
        "- [[ibk투자증권] 반도체: Shortage! Shortage! Shortage!](/api/documents/ibk투자증권_반도체_20260102_1789372106_a7256497)\n"
    )
    resolved = resolve_citation_links(sample)

    assert "/api/documents/ibk투자증권_반도체_20260102_1789372106_a7256497" in resolved
    assert "<출처: [[ibk투자증권] 반도체: Shortage! Shortage! Shortage!](/api/documents/ibk투자증권_반도체_20260102_1789372106_a7256497)>" in resolved


def test_resolve_multiple_citations_in_one_tag():
    """하나의 출처 태그 안에 쉼표로 연결된 복수 출처가 각각 올바르게 분리 및 링크화되는지 검증."""
    sample = (
        "다양한 Edge AI 애플리케이션에서 LPDDR이 채택되고 있다 <출처: [ibk투자증권] 반도체: Shortage! Shortage! Shortage!, 015-027__홍아름_220호_최종_1790038492_a0339d78>.\n\n"
        "## 5. 데이터 출처\n"
        "- [[ibk투자증권] 반도체: Shortage! Shortage! Shortage!](/api/documents/ibk투자증권_반도체_20260102_1789372106_a7256497)\n"
        "- [015-027. 홍아름_220호_최종](/api/documents/015-027__홍아름_220호_최종_1790038492_a0339d78)\n"
    )
    resolved = resolve_citation_links(sample)

    assert "<출처: [[ibk투자증권] 반도체: Shortage! Shortage! Shortage!](/api/documents/ibk투자증권_반도체_20260102_1789372106_a7256497)>" in resolved
    assert "<출처: [015-027. 홍아름_220호_최종](/api/documents/015-027__홍아름_220호_최종_1790038492_a0339d78)>" in resolved


def test_html_and_pdf_export_without_sublist_indentation():
    """보고서 마크다운을 HTML 및 PDF로 내보낼 때 3.2절 리스트에 하위 들여쓰기 <ul>이 없고 링크가 올바르게 렌더링되는지 검증."""
    report_file = Path("WikiDB/reports/REPORT_LPDDR_1789461052.md")
    if not report_file.exists():
        pytest.skip("REPORT_LPDDR_1789461052.md 파일이 없습니다.")

    report_md = report_file.read_text(encoding="utf-8")
    exporter = HtmlDocExporter()
    html_body = exporter.markdown_to_html_body(report_md, embed_images=False)

    m = re.search(r'<h3\b[^>]*>3\.2.*?</h3>\s*<ul>(.*?)</ul>\s*(?=<h[23]|<figure|<p|$)', html_body, re.DOTALL)
    assert m is not None, "3.2절 <ul> 목록을 찾을 수 없습니다."
    ul_content = m.group(1)
    sub_uls = re.findall(r'<ul\b', ul_content)
    assert len(sub_uls) == 0, f"3.2절 내부에 비정상 하위 서브리스트 <ul>이 존재합니다: {ul_content}"

    doc_links = re.findall(r'href=[\"\']/api/documents/([^\"\']+)[\"\']', html_body)
    assert len(doc_links) >= 10, f"출처 링크 개수가 부족합니다: {len(doc_links)}"
    assert any("015-027" in link for link in doc_links), "015-027 문서 링크가 누락되었습니다."
    assert any("ibk" in link.lower() for link in doc_links), "ibk투자증권 문서 링크가 누락되었습니다."
    assert any("SOCAMM" in link for link in doc_links), "SOCAMM 문서 링크가 누락되었습니다."
