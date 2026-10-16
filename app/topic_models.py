"""주제별 종합 보고서의 구조화된 생성 및 결정론적 마크다운 조립을 위한 Pydantic 데이터 모델."""

from typing import Optional
from pydantic import BaseModel, Field


class TableBlock(BaseModel):
    """보고서에 포함되는 구조화된 마크다운 표 블록."""
    title: Optional[str] = Field(default=None, description="표 제목 또는 설명")
    headers: list[str] = Field(default_factory=list, description="표 열 헤더 목록 (예: ['구분', '2024년', '2029년(E)', 'CAGR'])")
    rows: list[list[str]] = Field(default_factory=list, description="표 데이터 행 목록")
    caption: Optional[str] = Field(default=None, description="표 하단 단위 및 출처 주석 (예: '단위: 억 달러, 자료: MarketsandMarkets')")


class ImageAssetBlock(BaseModel):
    """보고서 본문에 인라인 결합되는 시각 자산 블록."""
    url: str = Field(description="이미지 경로 (예: '/api/assets/DOC_ID/image_001.png')")
    alt: str = Field(description="이미지 대체 텍스트")
    caption: Optional[str] = Field(default=None, description="시각적 캡션 (예: '도표: 글로벌 AI 에이전트 시장 규모')")


class SectionBlock(BaseModel):
    """5대 표준 목차의 개별 섹션 블록."""
    section_number: int = Field(description="목차 번호 (1: 기술개요, 2: 기술동향, 3: 시장동향, 4: 주요업체, 5: 데이터출처)")
    title: str = Field(description="섹션 제목 (예: '기술개요', '기술동향')")
    insight: Optional[str] = Field(default=None, description="1장 핵심 요약 (Key Insight)")
    paragraphs: list[str] = Field(default_factory=list, description="본문 문단 목록 (각 문단 종결부에 출처 표기 포함)")
    tables: list[TableBlock] = Field(default_factory=list, description="섹션에 포함된 필수 비교/전망 표 목록")
    images: list[ImageAssetBlock] = Field(default_factory=list, description="섹션에 인라인 배치된 시각 도표 이미지 목록")


class FootnoteItem(BaseModel):
    """문서 최하단에 수록되는 표준 GFM 각주 항목."""
    index: int = Field(description="각주 번호 (1, 2, 3...)")
    term: str = Field(description="전문 용어 (예: '트랜스포머', '환각')")
    definition: str = Field(description="용어 해설 내용")


class StructuredTopicReport(BaseModel):
    """Gemini LLM이 생성하는 5대 표준 목차 구조화된 종합 보고서 최상위 모델."""
    title: str = Field(description="보고서 정식 명칭 (예: '양자 컴퓨팅 종합 기술 및 시장 분석 보고서')")
    topic: str = Field(description="보고서 주제어 (예: '양자 컴퓨팅')")
    sections: list[SectionBlock] = Field(default_factory=list, description="1장부터 5장까지의 순차적 섹션 블록")
    sources: list[str] = Field(default_factory=list, description="5장 데이터 출처에 수록될 원본 문서 마크다운 링크 목록")
    footnotes: list[FootnoteItem] = Field(default_factory=list, description="표준 GFM 각주 목록")


def assemble_markdown_from_structured_report(report: StructuredTopicReport) -> str:
    """구조화된 보고서 Pydantic 객체를 100% 무결성을 갖춘 표준 GFM 마크다운으로 결정론적 조립(Assemble)한다.
    
    - 표 헤더-구분선 사이 무개행 및 표 앞뒤 개행 2개(\n\n) 엄격 격리
    - 출처 태그 직후 개행 누락 원천 차단
    - 도표 이미지와 캡션의 단독 행 배치
    - 각주 정의 최하단 분리 수록
    """
    lines: list[str] = []

    # 1. 메타데이터 헤더
    lines.append(f"# {report.title.strip()}")
    lines.append("> - **문서분류**: 🤖 AI 생성 주제 보고서 (Synthesized Report)")
    lines.append(f"> - **주제어**: {report.topic.strip()}")
    lines.append(f"> - **생성일시**: {report.title}")  # 이후 상위에서 갱신 가능
    lines.append("> - **기반 데이터**: WikiDB 지식 저장소 심층 합성")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 2. 섹션 1~4 조립
    for sec in report.sections:
        if sec.section_number == 5:
            continue  # 5장은 하단에서 별도 일원화 처리

        lines.append(f"## {sec.section_number}. {sec.title.strip()}")

        # 1장의 핵심 요약 인용구
        if sec.section_number == 1 and sec.insight:
            lines.append(f"> 💡 **핵심 요약 (Key Insight)**: {sec.insight.strip()}")
            lines.append("")

        # 본문 문단들 조립
        for para in sec.paragraphs:
            p_clean = para.strip()
            if p_clean:
                lines.append(p_clean)
                lines.append("")

        # 섹션 내 표 조립
        for tbl in sec.tables:
            if not tbl.headers:
                continue

            if tbl.title:
                lines.append(f"### {tbl.title.strip()}")
                lines.append("")

            # 표 헤더 행
            header_line = "| " + " | ".join(h.strip() for h in tbl.headers) + " |"
            sep_line = "|:---" * len(tbl.headers) + "|"

            lines.append(header_line)
            lines.append(sep_line)

            for row in tbl.rows:
                # 열 개수 맞춤
                padded = row + [""] * max(0, len(tbl.headers) - len(row))
                row_line = "| " + " | ".join(c.strip() for c in padded[:len(tbl.headers)]) + " |"
                lines.append(row_line)

            lines.append("")  # 표 블록 명시적 종결

            if tbl.caption:
                lines.append(f"*({tbl.caption.strip()})*")
                lines.append("")

        # 섹션 내 이미지 조립
        for img in sec.images:
            lines.append(f"![{img.alt.strip()}]({img.url.strip()})")
            caption_text = img.caption.strip() if img.caption else f"도표: {img.alt.strip()}"
            lines.append(f"*({caption_text})*")
            lines.append("")

    # 3. 5장 데이터 출처 조립
    lines.append("## 5. 데이터 출처")
    if report.sources:
        for src in report.sources:
            s_clean = src.strip()
            if s_clean.startswith("-"):
                lines.append(s_clean)
            else:
                lines.append(f"- {s_clean}")
    else:
        lines.append("- WikiDB 등록 문헌 심층 합성")
    lines.append("")

    # 4. 최하단 GFM 각주 조립
    if report.footnotes:
        lines.append("---")
        lines.append("")
        lines.append("### 📌 각주 (Footnotes)")
        lines.append("")
        for fn in sorted(report.footnotes, key=lambda x: x.index):
            lines.append(f"[^{fn.index}]: **{fn.term.strip()}**: {fn.definition.strip()}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"
