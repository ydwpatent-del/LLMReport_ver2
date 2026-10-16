"""마크다운 표 종결 경계 자율 치유 및 인라인 이미지 격리 단위 테스트 모듈."""

import pytest
import markdown
from pathlib import Path
from app.utils import heal_markdown_table_boundaries, clean_markdown_typography


def test_table_terminator_boundary_healing():
    """표 데이터 행 바로 뒤에 빈 줄 없이 단위/출처 주석이 올 때 빈 줄을 강제 삽입하여 표가 정상 종결되는지 검증."""
    broken_md = (
        "| 구분 | 기준 | 전망 |\n"
        "|:---|:---|:---|\n"
        "| 글로벌 | 100 | 200 |\n"
        "*(단위: 억 달러, 자료: 조사기관)*\n"
        "다음 본문 문단입니다."
    )

    healed_md = heal_markdown_table_boundaries(broken_md)
    assert "| 글로벌 | 100 | 200 |\n\n*(단위:" in healed_md

    # 파이썬 markdown 파서로 변환 시 <table> 내부에 *(단위...)* 텍스트가 <td>로 들어가지 않음을 증명
    html = markdown.markdown(healed_md, extensions=["tables"])
    assert "*(단위: 억 달러" not in html.split("</table>")[0]
    assert "</table>" in html


def test_table_terminator_image_attachment_healing():
    """표 마지막 행 뒤에 출처와 이미지 태그가 인라인으로 붙어 있을 때 표와 이미지가 독립 블록으로 분리되는지 검증."""
    broken_md = (
        "| 구분 | 규모 |\n"
        "|:---|:---|\n"
        "| 국내시장 | 500 |\n"
        "*(단위: 억원)* <출처: [문서A](/api/documents/docA)>![도표 차트](/api/assets/docA/img01.png)\n"
        "*(도표: 국내 시장 규모)*"
    )

    healed_md = heal_markdown_table_boundaries(broken_md)

    # 1. 표 뒤에 빈 줄 보장
    assert "| 국내시장 | 500 |\n\n*(단위:" in healed_md
    # 2. 이미지 태그 앞에 빈 줄 보장 (독립 문단 격리)
    assert "\n\n![도표 차트](/api/assets/docA/img01.png)" in healed_md

    # 파이썬 markdown 파서로 변환 시 <table> 태그 내부에 <img> 태그가 절대 들어가지 않음을 증명
    html = markdown.markdown(healed_md, extensions=["tables"])
    table_part = html.split("</table>")[0]
    assert "<img" not in table_part


def test_table_header_boundary_healing():
    """표 헤더 행 시작 직전에 빈 줄이 없는 경우 빈 줄을 자동 삽입하여 표 렌더링 파손을 방지하는지 검증."""
    broken_md = (
        "본문 서술 문단입니다. <출처: [문서](/api/documents/doc)>\n"
        "| 헤더1 | 헤더2 |\n"
        "|:---|:---|\n"
        "| 값1 | 값2 |"
    )

    healed_md = heal_markdown_table_boundaries(broken_md)
    assert "본문 서술 문단입니다. <출처: [문서](/api/documents/doc)>\n\n| 헤더1 | 헤더2 |" in healed_md


def test_clean_markdown_typography_integration():
    """clean_markdown_typography 종합 함수를 거쳤을 때 표 경계 치유와 각주/불릿 정돈이 함께 완벽히 수행되는지 검증."""
    broken_md = (
        "## 3. 시장동향\n\n"
        "| 항목 | 실적 |\n"
        "|---|---|\n"
        "| AI | 1000 |\n"
        "*(자료: 기관)*![차트](/api/assets/doc/img.png)\n"
        "*(도표: 설명)*\n"
    )

    result = clean_markdown_typography(broken_md)
    assert "| AI | 1000 |\n\n*(자료:" in result
    assert "\n\n![차트](/api/assets/doc/img.png)" in result


def test_normal_table_and_code_blocks_preserved():
    """정상적인 마크다운 표, 리스트, 코드 블록 내부의 파이프 기호가 변형 없이 보존되는지 검증."""
    normal_md = (
        "```python\n"
        "# 파이프 포함 코드\n"
        "x = a | b\n"
        "```\n\n"
        "| Col1 | Col2 |\n"
        "|---|---|\n"
        "| Val1 | Val2 |\n\n"
        "다음 문단입니다."
    )

    healed_md = heal_markdown_table_boundaries(normal_md)
    assert "x = a | b" in healed_md
    assert "| Val1 | Val2 |\n\n다음 문단입니다." in healed_md


def test_real_report_healing(tmp_path):
    """실제 보고서 파일(또는 샘플)에 대해 TopicReportGenerator.get_report_detail 호출 시 표 파손이 치유되는지 검증."""
    from app.topic_generator import TopicReportGenerator

    broken_content = (
        "# 테스트 보고서\n\n"
        "## 3. 시장동향\n\n"
        "| 시장 | 실적 | 전망 |\n"
        "|---|---|---|\n"
        "| 글로벌 | 100 | 200 |\n"
        "*(단위: 억 달러)* <출처: [문서](/api/documents/doc)>![도표](/api/assets/doc/img.png)\n"
        "*(도표: 설명)*\n"
    )

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    report_file = reports_dir / "REPORT_TEST_123.md"
    report_file.write_text(broken_content, encoding="utf-8")

    generator = TopicReportGenerator(reports_dir=reports_dir)
    detail = generator.get_report_detail("REPORT_TEST_123")

    assert detail is not None
    healed = detail["content"]

    # 1. 파일 내용이 자율 치유되어 표 뒤에 개행 2개가 생겼는지 검증
    assert "| 글로벌 | 100 | 200 |\n\n*(단위:" in healed
    assert "\n\n![도표](/api/assets/doc/img.png)" in healed

    # 2. 마크다운 파서로 HTML 변환 시 <table> 안에 <img>가 절대 들어가지 않는지 검증
    html = markdown.markdown(healed, extensions=["tables"])
    table_part = html.split("</table>")[0]
    assert "<img" not in table_part


def test_split_table_header_and_separator_healed():
    """표 헤더 행과 구분 행 사이에 빈 줄이 끼어 파손된 표가 단일 표 블록으로 자동 봉합되는지 검증."""
    split_md = (
        "| 구분 | 기준 실적 | 전망 규모 |\n\n"
        "|:---|:---|:---|\n"
        "| 국내시장 | 1,000 | 5,000 |\n"
    )

    healed_md = heal_markdown_table_boundaries(split_md)
    # 헤더와 구분선 사이의 빈 줄이 제거되어 연속되어야 함
    assert "| 구분 | 기준 실적 | 전망 규모 |\n|:---|:---|:---|" in healed_md

    # markdown 파서로 렌더링 시 <table>이 정상 생성되는지 검증
    html = markdown.markdown(healed_md, extensions=["tables"])
    assert "<table>" in html
    assert "<th" in html and "구분" in html


def test_citation_followed_by_table_header_separated():
    """일반 문단 끝 출처 태그 직후 개행 없이 붙은 표 헤더가 빈 줄로 완벽히 분리되는지 검증."""
    glued_md = (
        "급격한 성장이 예상됩니다. <출처: [칩렛](/api/documents/doc)>| 연도 | 시장 규모 (억 원) |\n\n"
        "|:---|---:|\n"
        "| 2024년 | 2,616 |"
    )

    healed_md = heal_markdown_table_boundaries(glued_md)
    assert "<출처: [칩렛](/api/documents/doc)>\n\n| 연도 | 시장 규모 (억 원) |\n|:---|---:|" in healed_md

    html = markdown.markdown(healed_md, extensions=["tables"])
    assert "<table>" in html
    assert "<th" in html and "연도" in html


def test_nested_citation_tags_flattened():
    """중첩된 <출처: [A](urlA), <출처: [B](urlB)>> 비정상 태그가 단일 태그로 평탄화되는지 검증."""
    nested_md = (
        "복합 작업을 수행합니다. <출처: [칩렛](/api/documents/doc1), <출처: [[KISTEP] AI](/api/documents/doc2)>|\n"
    )

    healed_md = heal_markdown_table_boundaries(nested_md)
    assert "<출처: [칩렛](/api/documents/doc1), [[KISTEP] AI](/api/documents/doc2)>|" in healed_md
    assert "<출처" in healed_md
    assert healed_md.count("<출처") == 1


def test_all_12_reports_integrity():
    """WikiDB/reports 디렉터리의 실제 보고서들이 5대 목차와 유효한 표를 갖추고 있는지 전수 검증."""
    import re
    reports_dir = Path("WikiDB/reports")
    if not reports_dir.exists():
        pytest.skip("WikiDB/reports 디렉터리가 존재하지 않습니다.")

    report_files = sorted(reports_dir.glob("*.md"))
    assert len(report_files) >= 12, f"보고서 파일이 12개 미만입니다: {len(report_files)}개"

    for r_file in report_files:
        content = r_file.read_text(encoding="utf-8")
        
        # 5대 필수 목차 존재 검증
        for sec_num, sec_name in [(1, "기술\\s*개요"), (2, "기술\\s*동향"), (3, "시장\\s*동향"), (4, "주요\\s*업체"), (5, "데이터\\s*출처")]:
            pat = rf"##\s*{sec_num}\.\s*{sec_name}"
            assert re.search(pat, content), f"{r_file.name}에서 목차 {sec_num}. {sec_name}이 누락되었습니다."

        # 헤더와 구분선 사이가 분리된 파손 표(빈 줄 삽입)가 0건인지 검증
        split_tables = re.findall(r'\|[^\n]+\|\n\s*\n\|(?:\s*:?-+:?\s*\|)+', content)
        assert len(split_tables) == 0, f"{r_file.name}에 분리된 파손 표가 {len(split_tables)}건 있습니다."

        # 출처 중첩 비정상 태그가 0건인지 검증
        nested_cites = re.findall(r'<출처[^>]*<출처', content)
        assert len(nested_cites) == 0, f"{r_file.name}에 중첩된 출처 태그가 {len(nested_cites)}건 있습니다."

        # 표 개수가 최소 3개 이상인지 검증
        valid_tables = re.findall(r'(?:^|\n)\|[^\n]+\|\n\|(?:\s*:?-+:?\s*\|)+', content)
        assert len(valid_tables) >= 3, f"{r_file.name}의 유효 표 개수가 {len(valid_tables)}개로 3개 미만입니다."


def test_inline_heading_isolation_healing():
    """출처 태그나 일반 문장 뒤에 개행 없이 인라인으로 붙어버린 소제목(### 2.1)이 빈 줄(\\n\\n)로 분리 복원되는지 검증."""
    broken_md = (
        "주요 음극활물질은 탄소계, 실리콘계로 분류된다. <출처: [음극재](/api/documents/doc1)> ### 2.1 흑연계 음극재의 진화\n"
        "현재 음극재 시장의 대부분은 천연흑연과 인조흑연이다. <출처: [음극재](/api/documents/doc1)>### 2.2 고용량 음극재\n"
        "리튬금속은 차세대 소재이다."
    )
    healed = heal_markdown_table_boundaries(broken_md)
    assert "<출처: [음극재](/api/documents/doc1)>\n\n### 2.1 흑연계 음극재의 진화" in healed
    assert "<출처: [음극재](/api/documents/doc1)>\n\n### 2.2 고용량 음극재" in healed


def test_tilde_numerical_range_preserved():
    """수치 범위(92~95%, 5~15%, ~370mAh/g) 표기가 정보 손실 없이 안전하게 보존되는지 검증."""
    md_with_tildes = (
        "초기 충·방전 효율(92~95%), 용량 한계(~370mAh/g), 첨가 비율(5~15%)이 기록되어 있습니다."
    )
    from app.utils import clean_markdown_typography
    cleaned = clean_markdown_typography(md_with_tildes)
    assert "92~95%" in cleaned
    assert "~370mAh/g" in cleaned
    assert "5~15%" in cleaned


