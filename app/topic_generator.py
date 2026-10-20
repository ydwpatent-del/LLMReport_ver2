"""Gemini LLM 기반 주제별 5대 목차 마크다운 보고서 자동 생성 및 저장 관리자 모듈."""

import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import errors as genai_errors
from dotenv import load_dotenv

load_dotenv()

from app.topic_search import search_relevant_sections
from app.utils import get_gemini_api_keys_list, is_gemini_key_exhausted_or_invalid, is_gemini_key_permanently_exhausted

logger = logging.getLogger("TopicReportGenerator")

class TopicReportGenerator:
    """기존 파싱된 완본 마크다운과 이미지를 종합하여 5대 목차 체계의 신규 보고서를 생성하는 엔진."""

    def __init__(self, reports_dir: Optional[Path] = None, api_key: Optional[str] = None, api_keys: Optional[list[str]] = None):
        self.reports_dir = reports_dir or (Path(__file__).resolve().parent.parent / "WikiDB" / "reports")
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        if api_keys:
            self.api_keys = api_keys
        elif api_key:
            self.api_keys = [api_key]
        else:
            self.api_keys = get_gemini_api_keys_list()
        self.api_key = self.api_keys[0] if self.api_keys else None
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None


    @staticmethod
    def normalize_source_title(title: str) -> str:
        """출처 제목에서 괄호, 특수문자, 공백을 정규화하여 동일 문헌 여부를 판별한다."""
        return re.sub(r'[\s_()\[\]\-\.]+', '', title).lower()

    @classmethod
    def deduplicate_citations(cls, markdown_text: str) -> str:
        """보고서 마크다운 내 인접한 동일 문헌 출처 및 5번 데이터 출처 중복을 제거하고
        누락된 출처 링크를 자동 복원(Linkify)하며 타이포그래피 서식을 정돈한다."""
        if not markdown_text:
            return ""

        # 0. 본문 내 누락된 출처 표기 자동 링크화(Auto-linkify) 선제 적용
        from .utils import resolve_citation_links, clean_markdown_typography
        cleaned_text = resolve_citation_links(markdown_text)

        # 1. 본문 내 인접한 동일 문헌 출처 병합 (대괄호 중첩 지원, 뒤따르는 개행문자 보존)
        citation_group_pattern = re.compile(r'(?:<출처\s*:\s*\[(.*?)\]\(((?:/api/documents/)?[^)]+)\)>[ \t]*,?[ \t]*)+')

        def merge_citation_match(match):
            full_chunk = match.group(0)
            items = re.findall(r'<출처\s*:\s*\[(.*?)\]\(((?:/api/documents/)?[^)]+)\)>', full_chunk)
            if not items:
                return full_chunk

            seen_keys = set()
            unique_items = []
            for title, link in items:
                key = cls.normalize_source_title(title)
                if key not in seen_keys:
                    seen_keys.add(key)
                    unique_items.append((title, link))

            return ", ".join(f"<출처: [{t}]({l})>" for t, l in unique_items)

        cleaned_text = citation_group_pattern.sub(merge_citation_match, cleaned_text)

        # 2. 5번 데이터 출처 섹션 내의 bullet list 중복 제거
        sec5_pattern = re.compile(r'(##\s*5\.\s*데이터\s*출처.*?)(?=\n##|\Z)', re.DOTALL)
        sec5_match = sec5_pattern.search(cleaned_text)
        if sec5_match:
            sec5_content = sec5_match.group(1)
            lines = sec5_content.splitlines()
            new_lines = []
            seen_keys = set()

            for line in lines:
                bullet_match = re.match(r'^\s*[-*]\s*\[(.*?)\]\(((?:/api/documents/)?[^)]+)\)\s*$', line)
                if bullet_match:
                    title = bullet_match.group(1)
                    key = cls.normalize_source_title(title)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    new_lines.append(f"- [{title}]({bullet_match.group(2)})")
                else:
                    new_lines.append(line)

            new_sec5 = "\n".join(new_lines)
            cleaned_text = cleaned_text[:sec5_match.start(1)] + new_sec5 + cleaned_text[sec5_match.end(1):]

        # 3. 마크다운 서식 정돈, 불릿 위계 정렬, 각주 일원화 및 파손 표 자율 치유(Self-Healing) 적용
        cleaned_text = clean_markdown_typography(cleaned_text)

        return cleaned_text

    @staticmethod
    def _extract_smart_section_text(sec_text: str, max_chars: int = 3500) -> str:
        """섹션 텍스트가 제한 길이를 초과할 경우 단순 절단 대신 핵심 정량 데이터 및 소제목 문단을 우선 보존하여 스마트 컨텍스트를 구성한다."""
        if not sec_text:
            return ""

        text_stripped = sec_text.strip()
        if len(text_stripped) <= max_chars:
            return text_stripped

        # 문단 경계(\n\n) 기준으로 분할
        paragraphs = [p.strip() for p in text_stripped.split("\n\n") if p.strip()]
        if not paragraphs:
            return text_stripped[:max_chars].rsplit(" ", 1)[0]

        # 단일 문단만 존재하는 특수 경우 처리
        if len(paragraphs) == 1:
            p = paragraphs[0]
            if len(p) <= max_chars:
                return p
            cut = p[:max_chars]
            last_period = cut.rfind(".")
            if last_period > max_chars // 2:
                return cut[:last_period + 1]
            return cut.rsplit(" ", 1)[0]

        # 각 문단별 핵심 정량 데이터 및 소제목 가중치 산출
        scored_paras = []
        for idx, p in enumerate(paragraphs):
            score = 0
            # 1. 소제목 가중치
            if p.startswith("#"):
                score += 10
            # 2. 첫 문단 (도입부 맥락 유지)
            if idx == 0:
                score += 5
            # 3. 연도 패턴 (예: 2025년, 2030년)
            if re.search(r'(?:19|20)\d{2}년|\b(?:19|20)\d{2}\b', p):
                score += 6
            # 4. 성장률 및 시장 통계 지표 (CAGR, 연평균, 성장률)
            if re.search(r'(?i)\bcagr\b|연평균|성장률', p):
                score += 6
            # 5. 금액 단위 (억 원, 조 원, 억 달러, 조 달러)
            if re.search(r'억\s*원|조\s*원|억\s*달러|조\s*달러', p):
                score += 6
            # 6. 정량 수치 및 백분율 (%)
            if re.search(r'\d+(?:\.\d+)?%', p):
                score += 4
            # 7. 기술 규격 단위 (nm, Gbps, Tbps, GHz, MHz, W 등)
            if re.search(r'(?i)\b\d+\s*(?:nm|gbps|tbps|ghz|mhz|w|μm|um)\b', p):
                score += 5
            # 8. 시장/기술 핵심 명사
            if re.search(r'시장\s*규모|전망|매출|점유율|아키텍처|인터커넥트|표준', p):
                score += 3

            scored_paras.append((idx, p, score, len(p)))

        # 점수 기반 우선 선택 (높은 점수 우선, 동점 시 원래 인덱스 순)
        candidates = sorted(scored_paras, key=lambda item: (-item[2], item[0]))

        selected_indices = set()
        current_len = 0

        # 중요 문단 우선 포함
        for idx, p, score, p_len in candidates:
            if score == 0:
                continue
            sep_len = 2 if selected_indices else 0
            if current_len + sep_len + p_len <= max_chars:
                selected_indices.add(idx)
                current_len += sep_len + p_len

        # 잔여 용량이 있을 경우 일반 문단도 원래 순서대로 추가 시도
        for idx, p, score, p_len in sorted(scored_paras, key=lambda item: item[0]):
            if idx in selected_indices:
                continue
            sep_len = 2 if selected_indices else 0
            if current_len + sep_len + p_len <= max_chars:
                selected_indices.add(idx)
                current_len += sep_len + p_len

        # 최소 1개 문단도 못 들어간 극단적 경우 (첫 중요 문단이 max_chars보다 긴 경우 등)
        if not selected_indices:
            first_p = paragraphs[0]
            return first_p[:max_chars].rsplit(" ", 1)[0]

        # 원래 문서 순서대로 정렬하여 문단 재결합
        ordered_paragraphs = [paragraphs[i] for i in sorted(selected_indices)]
        return "\n\n".join(ordered_paragraphs)

    def _build_prompt(self, topic: str, matched_docs: list[dict]) -> str:
        """Gemini LLM에게 전달할 프롬프트 및 컨텍스트를 구성한다."""
        context_parts = []
        source_metadata = []

        # 동일 문헌 중복 전달 방지
        unique_matched_docs = []
        seen_keys = set()
        for doc in matched_docs:
            clean_key = self.normalize_source_title(doc.get("title", ""))
            if clean_key not in seen_keys:
                seen_keys.add(clean_key)
                unique_matched_docs.append(doc)
        matched_docs = unique_matched_docs

        for doc in matched_docs:
            doc_id = doc["doc_id"]
            title = doc["title"]
            source_metadata.append(f"- 제목: {title} (ID: {doc_id})")

            all_secs = doc.get("sections", [])
            # 카테고리별 섹션 분류
            market_secs = [s for s in all_secs if getattr(s, 'category', '') == "market" or any(w in s.heading for w in ["시장", "규모", "전망", "cagr"])]
            tech_secs = [s for s in all_secs if getattr(s, 'category', '') == "tech" or any(w in s.heading for w in ["기술", "동향", "인터커넥트", "패키징", "아키텍처"])]
            overview_secs = [s for s in all_secs if getattr(s, 'category', '') == "overview" or any(w in s.heading for w in ["개요", "정의", "특징", "구조"])]
            company_secs = [s for s in all_secs if getattr(s, 'category', '') == "company" or any(w in s.heading for w in ["업체", "기업", "현황"])]
            other_secs = [s for s in all_secs if s not in (market_secs + tech_secs + overview_secs + company_secs)]

            # 5대 목차에 맞춰 골고루 필수 섹션 큐레이션 (특히 시장 규모 섹션 필수 포함)
            selected_secs = []
            if overview_secs:
                selected_secs.append(overview_secs[0])
            if tech_secs:
                selected_secs.extend(tech_secs[:2])
            if market_secs:
                # 시장 데이터가 있는 섹션(국내 시장, 세계 시장 등)을 최우선으로 최대 3개 전수 포함
                selected_secs.extend(market_secs[:3])
            if company_secs:
                selected_secs.extend(company_secs[:2])

            # 섹션이 부족할 경우 기타 섹션 보충
            if len(selected_secs) < 5:
                for s in (market_secs + tech_secs + other_secs):
                    if s not in selected_secs:
                        selected_secs.append(s)
                    if len(selected_secs) >= 7:
                        break

            for sec in selected_secs:
                img_desc = ""
                if sec.images:
                    img_lines = []
                    for img in sec.images[:3]:
                        caption_str = f" *({img['caption']})*" if img['caption'] else ""
                        img_lines.append(f"  * 사용가능 이미지: ![{img['alt']}]({img['url']}){caption_str}")
                    img_desc = "\n" + "\n".join(img_lines)

                # 표 내용 강조 전달
                table_desc = ""
                if sec.tables:
                    table_desc = "\n[포함된 핵심 데이터 표]:\n" + "\n\n".join(sec.tables[:2])

                # 긴 섹션 텍스트는 핵심 정량 데이터와 소제목을 보존하는 스마트 컨텍스트 추출 적용
                smart_body = self._extract_smart_section_text(sec.text, max_chars=3500)

                context_parts.append(
                    f"### [참고 문서: {title}] - 섹션: {sec.heading} (분류: {getattr(sec, 'category', 'general')})\n"
                    f"출처 문서 ID: `{doc_id}`\n"
                    f"본문 데이터:\n{smart_body}\n"
                    f"{table_desc}\n"
                    f"{img_desc}\n"
                )

        full_context = "\n---\n".join(context_parts)
        sources_summary = "\n".join(source_metadata)

        prompt = f"""당신은 첨단 산업 기술 및 시장 분석 수석 연구원입니다.
아래 제공된 '기존 완본 문서 데이터베이스 컨텍스트'를 심층 분석하여, 요청된 주제 '{topic}'에 대한 고품질의 종합 리서치 보고서를 마크다운(Markdown) 형식으로 작성해 주십시오.

[1. 분석가 역할 및 보고서 개요]
- 당신은 첨단 산업 기술 및 시장 분석 수석 연구원으로서 기술 혁신과 시장 전망을 융합한 심층 전문 보고서를 작성합니다.
- 불필요한 AI 인사말이나 서두/결말 멘트("안녕하세요", "보고서를 작성합니다", "도움이 되길 바랍니다" 등)는 일절 작성하지 마십시오.
- 첫 줄은 반드시 아래의 `#` 헤더와 표준 메타데이터 인용구 블록으로 시작해야 합니다:

# {topic} 종합 기술 및 시장 분석 보고서
> - **문서분류**: 🤖 AI 생성 주제 보고서 (Synthesized Report)
> - **주제어**: {topic}
> - **생성일시**: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}
> - **기반 데이터**: WikiDB 지식 저장소 심층 합성

---

[2. 5대 표준 목차 및 필수 섹션 스펙]
보고서는 아래의 5대 표준 목차 순서와 제목, 헤더 형식을 엄격하게 준수해야 합니다:

## 1. 기술개요
- [핵심 요약]: 본문 시작 직후 `> 💡 **핵심 요약 (Key Insight)**: (1~2문장 기술 본질 요약)` 인용구 블록을 먼저 배치하십시오.
- 기술의 개념적 정의, 해결하고자 하는 핵심 난제(기존 기술의 물리적·경제적 병목 및 한계), 핵심 메커니즘을 인과 관계 중심으로 상세히 서술하십시오.
- 논리적 완성도와 가독성을 위해 세부 소제목(예: `### 1.1 기술 개념 및 등장 배경`, `### 1.2 핵심 메커니즘 및 동작 원리`)을 구성하여 체계적으로 기술하십시오.

## 2. 기술동향
- 세부 기술 분류, 아키텍처 혁신, 공정 및 인터페이스 표준화(예: UCIe, HBM 표준 등) 동향을 구체적인 기술 규격(nm, Gbps, 층수 등)과 함께 서술하십시오.
- [필수 비교 표]: 아래 3번 항목에 정의된 5열 구조를 갖춘 **'핵심 기술 방식 비교 요약 표(Markdown Table)'**를 반드시 1개 이상 작성하십시오.
- 관련 아키텍처 및 기술 다이어그램 이미지를 설명 직하단에 인라인으로 결합하십시오.

## 3. 시장동향 (국내/세계시장 규모 데이터)
- [원천 데이터 엄수]: 컨텍스트에 포함된 국내 시장 규모, 세계 시장 규모 수치 및 연도별 예측 데이터, 연평균 성장률(CAGR), 시장 통계 표를 반드시 상세히 인용하십시오. 컨텍스트에 없는 수치를 임의로 날조(Fabricate)하지 마시고, 수치가 부재한 항목은 '자료상 세부 통계 미제시'로 솔직히 기술하십시오.
- [필수 전망 표]: 아래 3번 항목에 정의된 5열 구조를 갖춘 **'시장 규모 및 전망 데이터 표(Markdown Table)'**를 필수로 구성하고, 표 하단에 `*(단위: 억 달러/조 원, 자료: 컨텍스트 출처)*`를 명시하십시오.
  *(안내: 컨텍스트에 국내와 글로벌 시장 데이터가 모두 존재할 경우, 행(Row)을 '국내 시장', '글로벌 시장'으로 나누어 각각 1행씩 병렬 수록하십시오.)*
- 시장 성장을 견인하는 핵심 동인(Growth Drivers) 및 시장 진입/확장의 주요 병목(리스크 및 기술적 난제)을 심층 분석하십시오.
- 관련 시장 차트 및 통계 도표 이미지를 인라인으로 배치하십시오.

## 4. 주요업체
- 글로벌 선도 기업 및 국내 핵심 기업들의 개발 현황, 주력 제품 라인업, 기술력 비교, 상용화 동향을 객관적으로 분석하십시오.
- [필수 기업 비교 표]: 아래 3번 항목에 정의된 5열 구조를 갖춘 **'주요 기업별 기술 및 개발 현황 비교 표(Markdown Table)'**를 반드시 구성하십시오.
- 산업 생태계 전·후방 밸류체인 관점에서 기업 포지셔닝을 분석하십시오.

## 5. 데이터 출처
- 인용에 활용된 원본 문서 목록을 나열하고 링크를 제공하십시오.
- 형식: `- [{{문서제목}}](/api/documents/{{문서ID}})`
- 작성 규칙: 5장 목록에는 본문용 출처 태그(`<출처:...>`)를 중복 표기하지 말고 순수 불릿 하이퍼링크 형식으로만 작성하십시오.

[3. 3대 필수 표 5열 표준 구조 정의]
보고서 내 필수 작성해야 하는 3대 마크다운 표는 다음 5열 구조(Markdown Table)를 반드시 갖추어야 합니다:
1. 2장 기술동향 - 핵심 기술 방식 비교 요약 표(Markdown Table):
   `| 세부 기술/방식 | 핵심 아키텍처/원리 | 주요 장점 및 효익 | 기술적 과제 및 난제 | 대표 적용처/분야 |`
2. 3장 시장동향 - 시장 규모 및 전망 데이터 표(Markdown Table):
   `| 시장 구분 (국내/글로벌) | 기준 연도 실적 | 전망 연도 규모 | 연평균 성장률(CAGR) | 핵심 성장 동인 |`
3. 4장 주요업체 - 주요 기업별 기술 및 개발 현황 비교 표(Markdown Table):
   `| 기업명 | 주력 제품/기술 | 양산 및 상용화 단계 | 핵심 경쟁력/차별화 포인트 | 생태계 협력 파트너 |`

- **[논리 충돌 해소 - 정보 부재 시 표 작성 규칙]**:
  3대 필수 표 작성 시 컨텍스트에 특정 열(예: 세부 파트너, 특정 연도 전망치 등)의 정보가 부분적으로 부재할 경우, 임의로 수치를 지어내지 말고 `'자료상 미제시'`, `'추후 공개 예정'`, `'공개 협력사 중심'` 등 객관적이고 사실에 기반한 문구로 기재하여 **5열 표준 구조 준수와 사실 무결성을 동시에 만족**하십시오.

[4. 원천 데이터 보존 및 이미지 화이트리스트 규칙]
- **위키 문서 100% 엄격한 팩트 그라운딩 (Strict Wiki Grounding)**:
  - 컨텍스트에 제공된 [참고 문서]에 실제로 서술된 기술 규격, 시장 통계, 기업 사례만을 정확히 추출하여 조립하십시오.
  - LLM의 일반적인 사전 학습 지식에만 의존하여 가상의 기술 스펙이나 미확인 통계치를 임의로 보충하거나 날조(Fabrication)하지 마십시오. 컨텍스트에 정보가 부재한 세부 항목은 `자료상 세부 내용 미제시` 또는 `공개 자료 기준 미확인`으로 명시하십시오.
- **1차 조사기관 출처와 2차 위키DB 링크 구분 명시**:
  - 참고 위키 문서 내에 가트너(Gartner), IDC, 트렌드포스, 산업연구원 등 1차 시장조사기관/연구기관 출처가 명시되어 있는 경우, 본문 서술 시 `**가트너(Gartner, 2024)** 조사에 따르면...`과 같이 1차 출처를 정확히 병기하십시오.
  - 문단 종결부에는 항상 시스템 내부 링크인 `<출처: [{{문서제목}}](/api/documents/{{문서ID}})>` 태그를 부착하십시오.
- **원천 데이터 보존 및 날조 차단**: 컨텍스트에 제시된 실제 정량 데이터(수치, 연도, 통계)를 왜곡 없이 보존하며 없는 데이터를 자의적으로 날조하지 마십시오.
- **엄격한 화이트리스트**: 오직 컨텍스트의 각 섹션 하단에 명시된 `* 사용가능 이미지: ![]()` 태그의 실제 존재하는 URL만 인용하십시오. 가공의 허구 이미지 파일명을 생성하지 마십시오.
- **중복 도배 금지 및 문맥 호응 (Visual Anchoring)**: 하나의 이미지는 가장 관련성이 높은 본문 문단 아래에 단 1회만 단독 행으로 배치하며, 상단 본문에서 해당 도표의 핵심 시사점을 자연스럽게 연계 서술하십시오.
- **이미지 배치 형식 예시**:
  ... 초고속 인터커넥트 UCIe 표준을 적용하여 패키징 효율을 극대화합니다. <출처: [칩렛(Chiplet) 문서](/api/documents/chiplet_doc)>
  
  ![칩렛 패키징 아키텍처 다이어그램](/api/assets/chiplet_doc/image_005.png)
  *(도표: 칩렛 인터커넥트 구조 - 출처: 칩렛(Chiplet) 문서)*
- **본문과 출처 링크 시각적 구분 및 배치 밀도 규칙 (출처 영역 분리)**:
  - **1~4장 본문 문단 종결부**: 각 문단이 끝나는 종결부마다 `<출처: [{{문서제목}}](/api/documents/{{문서ID}})>` 형식(꺾쇠 괄호 `<`와 `>`로 감싼 하이퍼링크)으로 작성하십시오. 단어마다 출처를 남발하지 말고 문단 단위로 정돈하십시오.
  - **5장 데이터 출처 섹션**: 본문용 꺾쇠 태그 없이 순수 마크다운 목록인 `- [{{문서제목}}](/api/documents/{{문서ID}})`로만 기재하십시오.

[5. 기술-시장 3단계 인과 논리 및 최신성 우선 원칙 (품질 극대화 및 심층 분석 심화 규칙)]
- **다중 위키 문서 간 관점 교차 융합 (Cross-Wiki Multi-Perspective Synthesis)**:
  - 복수의 위키 문서가 서로 다른 관점(예: 소자/공정 관점 vs 세트/시스템 관점, 소재 관점 vs 완제품 관점, 국내 시장 vs 글로벌 시장)을 다룰 경우, 이를 파편적으로 나열하지 말고 `[소재/공정 기술 혁신] → [시스템 레벨 탑재 및 표준화] → [글로벌 및 국내 시장 수요 견인]`으로 유기적 전주기 밸류체인 관점에서 교차 합성하십시오.
- **최신 시장 규모 자료 최우선 반영 강제 (Latest Market Data Priority)**:
  - 컨텍스트 내에 복수 연도의 시장 조사 자료나 전망치(예: 2021년 조사 vs 2024/2025년 최신 조사)가 공존할 경우, 각 문서의 등재일이 아닌 **실제 데이터 자체의 기준 연도 및 조사·발행 시점을 반드시 비교 확인하여 가장 최근에 조사된 최신 연도 기준의 실적치 및 전망치 데이터를 최우선(Primary Source)으로 채택**하여 3장 시장 규모 표 및 본문에 반영하십시오.
  - 과거 구 자료가 함께 언급될 경우, 과거 전망치 대비 최신 실적치의 궤적 변화(시장 성장 가속, 정체 요인, 세그먼트 비중 재편 등)를 인과적으로 대비하여 심층 분석하십시오.
- **기술동향-시장동향 간 논리적 연계성 및 감수 검증성 강제 (Auditability & Logical Traceability)**:
  - 2장(기술동향)에서 제시한 핵심 아키텍처 및 공정 혁신(nm 공정 미세화, 대역폭 향상, 전력 효율 등)이 3장(시장동향)의 특정 시장 세그먼트 수요 견인과 어떻게 직결되는지 기술-시장 간 명확한 인과관계로 기술하십시오.
  - 복수 문서 간에 기술적 관점이나 통계가 상충될 경우, 논리적 충돌을 방치하지 말고 기술적 전제 조건과 상호 정합성을 검토한 후 보고서 전체의 분석 논리가 일관되도록 구성하십시오.
  - 감수위원(리뷰어)이 "이 기술 규격 혁신이 왜 특정 시장 규모의 폭발적 성장을 견인하는지" 객관적으로 타당성을 검증할 수 있도록 `[기술 규격/혁신] → [물리적·경제적 병목 해결] → [전방 산업 채택 및 시장 창출]`의 **3단계 논리 구조**를 본문 서술과 표에 명확히 구축하십시오.
- **복수 문헌 간 다각적 교차 종합 (Cross-Document Synthesis)**:
  - 단일 문헌의 내용을 단순히 차례대로 요약 나열하는 구성을 엄격히 금지합니다.
  - 서로 다른 출처 문헌에서 제시된 기술적 관점, 성장률 추정치, 기업 전략을 입체적으로 교차 비교하여 분석의 객관성을 확보하십시오.
- **산업 밸류체인(Value Chain) 연계 분석**:
  - 4장(주요업체) 분석 시, 기업들을 단순 나열하지 말고 생태계 전·후방(IP/팹리스 → 파운드리 → 패키징/OSAT → 소부장 및 최종 세트업체) 관점에서 각 기업의 생태계 내 포지셔닝과 전략적 제휴 관계를 입체적으로 분석하십시오.

[6. 전문 어조 및 서식 무결성 규칙 (표 헤더 격리, 각주 격리)]
- **전문 리서치 문체 및 정량적 팩트 중심 서술**:
  - 추상적 수사("급격히 성장함", "우수한 성능")를 지양하고, 구체적인 수치, 연도, 규격, 단위(nm, Gbps, 억원, 달러, % 등)를 명확히 제시하십시오.
  - 문단 내 핵심 키워드, 기업명, 중요 통계 수치는 `**볼드체**`로 강조하여 시각적 스캐닝 효율을 높이십시오.
  - 격식 있는 개조식 및 보고서 서술 종결 어미(~다, ~임, ~함 등)의 일관된 전문 보고서 문체를 사용하십시오.
  - **인공지능 상투어 차단**: 보고서 본문 외에 사용자에 대한 인사말, 프롬프트 해설, 서두/말미의 안내 문구를 일절 배제하고 마크다운 보고서 본문만 순수하게 출력하십시오.
- **마크다운 표 문법 무결성 절대 준수 (Table Header & Terminator Isolation)**:
  - **표 시작 격리**: 모든 마크다운 표(`| 헤더 |`)는 반드시 이전 문단, 출처 태그(`<출처:...>`), 또는 캡션(`*(자료:...)*`)과 **빈 줄(개행 2개)**로 완벽하게 분리되어야 합니다. 표 헤더 행은 무조건 행의 맨 처음(`^|`)에서 시작해야 합니다.
  - **표 종결 격리**: 표의 마지막 데이터 행(`| ... |`) 직후에는 반드시 **빈 줄(개행 2개)**을 넣어 표 블록을 명시적으로 종결하십시오. 표 바로 뒤에 이어지는 단위/출처 주석(`*(단위:...)*`)이나 도표 이미지(`![]()`), 후속 본문은 표와 절대 붙여 쓰지 마십시오.
  - **이미지 단독 행 격리**: 출처 태그(`<출처:...>`)와 이미지 태그(`![]()`)를 한 줄에 연달아 붙여 쓰지 말고 반드시 빈 줄을 두고 별도의 독립 행으로 배치하십시오.
- **소제목 및 헤딩 독립 행 격리 (Heading Isolation)**:
  - 모든 대제목/소제목(`## 1.`, `### 1.1`, `### 2.1` 등)은 반드시 앞 문장, 마침표, 출처 태그(`<출처:...>`)와 분리하여 **독립된 새로운 행(빈 줄 1개 이상, 개행 2회)**에서 시작해야 합니다.
  - 문장 끝이나 출처 태그 바로 뒤에 한 줄로 소제목을 붙여 쓰는 것을 엄격히 금지합니다.
- **표준 GFM 각주(Footnotes) 격리 수록 및 문서 최하단 구조 위계**:
  - 전문 용어 해설을 본문 중간에 리스트로 나열하지 마십시오.
  - 본문 인용부에는 `용어[^1]` 형태로 표기하십시오.
  - **문서 최하단 위계 순서**: `## 5. 데이터 출처` 목록 완료 → 빈 줄 후 `---` 구분선 → `### 📌 각주 (Footnotes)` 헤딩 후 `[^1]: **용어**: 설명` 형식으로 격리 수록하십시오 (5장 목록 내에 각주를 섞지 마십시오).

[참고 컨텍스트 데이터]
{full_context}

[참고 대상 원본 문서 목록]
{sources_summary}
"""
        return prompt

    def _build_incremental_update_prompt(
        self,
        current_markdown: str,
        topic: str,
        new_docs: list[dict],
        existing_docs: Optional[list[dict]] = None,
    ) -> str:
        """기존 작성된 보고서, 기존 작성분의 근거 위키 문서 데이터, 신규/갱신된 위키 문서 데이터를 바탕으로
        데이터 최신성 및 논리적 정합성을 사전 리뷰한 뒤 기존 서술을 무손실 보존하며 증분 개정하는 프롬프트를 구성한다.
        """
        existing_context_parts = []
        if existing_docs:
            seen_existing = set()
            for doc in existing_docs:
                clean_key = self.normalize_source_title(doc.get("title", ""))
                if clean_key in seen_existing:
                    continue
                seen_existing.add(clean_key)
                doc_id = doc["doc_id"]
                title = doc["title"]
                for sec in doc.get("sections", [])[:3]:
                    table_desc = (
                        f"\n[기존 근거 핵심 표]:\n" + "\n\n".join(sec.tables[:1])
                        if getattr(sec, "tables", None)
                        else ""
                    )
                    smart_body = self._extract_smart_section_text(getattr(sec, "text", ""), max_chars=1800)
                    existing_context_parts.append(
                        f"### [기존 작성분 근거 문서: {title}] - 섹션: {sec.heading}\n"
                        f"출처 문서 ID: `{doc_id}`\n"
                        f"본문 데이터:\n{smart_body}\n"
                        f"{table_desc}\n"
                    )

        full_existing_context = (
            "\n---\n".join(existing_context_parts)
            if existing_context_parts
            else "(기존 보고서 본문에 이미 수록된 출처 및 정량 데이터를 기존 근거 기준으로 삼으십시오.)"
        )

        context_parts = []
        new_source_metadata = []
        new_doc_titles = []

        seen_keys = set()
        for doc in new_docs:
            clean_key = self.normalize_source_title(doc.get("title", ""))
            if clean_key in seen_keys:
                continue
            seen_keys.add(clean_key)

            doc_id = doc["doc_id"]
            title = doc["title"]
            new_doc_titles.append(title)
            new_source_metadata.append(f"- 제목: {title} (ID: {doc_id})")

            for sec in doc.get("sections", [])[:4]:
                img_desc = ""
                if getattr(sec, "images", None):
                    img_lines = [
                        f"  * 사용가능 이미지: ![{img['alt']}]({img['url']})"
                        for img in sec.images[:2]
                    ]
                    img_desc = "\n" + "\n".join(img_lines)
                table_desc = (
                    f"\n[신규 핵심 데이터 표]:\n" + "\n\n".join(sec.tables[:1])
                    if getattr(sec, "tables", None)
                    else ""
                )
                smart_body = self._extract_smart_section_text(getattr(sec, "text", ""), max_chars=2500)
                context_parts.append(
                    f"### [신규/개정 참고 문서: {title}] - 섹션: {sec.heading} (분류: {getattr(sec, 'category', 'general')})\n"
                    f"출처 문서 ID: `{doc_id}`\n"
                    f"본문 데이터:\n{smart_body}\n"
                    f"{table_desc}\n"
                    f"{img_desc}\n"
                )

        full_new_context = "\n---\n".join(context_parts) if context_parts else "(신규 등재된 위키 문서의 추가 텍스트가 없습니다.)"
        sources_summary = "\n".join(new_source_metadata)
        new_titles_str = ", ".join(new_doc_titles) if new_doc_titles else "최신 지식DB 동기화"
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        prompt = f"""당신은 첨단 산업 기술 및 시장 분석 수석 연구원입니다.
아래에 제공된 [기존 작성 보고서 원본]과 [기존 작성분의 근거 위키 문서 데이터], 그리고 새롭게 등재/갱신된 [최신 위키 문서 데이터]를 상호 대조·분석하십시오.
마구잡이로 내용을 단순 추가(맹목적 증분)하는 것을 엄격히 금지합니다. 반드시 **데이터의 실제 최신성 여부와 기술-시장 간 논리적 정합성을 먼저 리뷰(검증)**한 후, 검증된 델타 지식만을 반영하여 기존 보고서를 외과적 증분 개정(Surgical Incremental Revision)하십시오.

[1. 기존 작성 보고서 원본]
{current_markdown}

[2. 기존 작성분의 근거가 되는 위키 문서 데이터 (Existing Basis Data)]
{full_existing_context}

[3. 새롭게 반영 검토할 최신 위키 문서 데이터 (New Candidate Data)]
{full_new_context}

[4. 신규 반영 대상 위키 문서 목록]
{sources_summary}

[본문 작성 전 필수 수행: 데이터 최신성 및 논리적 정합성 3단계 사전 리뷰 프로토콜 (Pre-Update Review Protocol)]
- **Step 1. 데이터 최신성 및 기준 연도 정밀 리뷰 (Recency & Base-Year Verification)**:
  - 신규 등재 문서라고 해서 무조건 최신 데이터로 맹신하여 마구잡이로 증분하지 마십시오.
  - 반드시 [기존 작성분 및 기존 근거 문서 데이터]에 수록된 통계/전망치와 [신규 위키 문서 데이터]의 통계/전망치에 명시된 **실제 기준 연도 및 조사·발행 시점(Survey/Base Year)**을 직접 대조하십시오.
  - 만약 신규 문서의 통계가 기존 보고서에 이미 수록된 통계보다 과거 시점의 데이터이거나 구형 전망치인 경우, **기존 보고서의 최신 주력 통계를 절대로 구형 수치로 덮어쓰거나 무분별하게 혼재시키지 마십시오(역행 갱신 절대 금지)**.
  - 신규 문서의 데이터가 실제로 더 최근에 조사된 최신 지표임이 입증된 경우에만 최신 주력 수치로 채택·갱신하되, 과거 전망치 대비 최신 전망치의 변화 궤적(Trajectory)을 인과적으로 서술하십시오.
- **Step 2. 논리적 정합성 및 기술-시장 3단계 인과관계 리뷰 (Logical Consistency & Causality Review)**:
  - 신규 문서의 기술 및 시장 데이터를 반영하기 전에, 기존 보고서에 확립된 핵심 아키텍처 원리 및 `[기술 규격/혁신] → [물리적·경제적 병목 해결] → [전방 산업 채택 및 시장 창출]`의 3단계 인과 논리와 **논리적 모순이나 충돌(Contradiction)이 발생하지 않는지 사전 리뷰**하십시오.
  - 기존 작성분과 신규 문서 간에 기술적 관점이나 시장 추정치가 상충할 경우, 무작정 이어 붙이지 말고 각 데이터의 전제 조건(공정 세대 차이, 조사 기관별 산정 범위 차이, 국내 vs 글로벌 세그먼트 차이)을 규명하여 보고서 전체의 분석 논리가 일관되도록 유기적으로 통합하십시오.
- **Step 3. 자체 검수 후 본문 확정 (Self-Review Before Finalizing)**:
  - 초안 구성 후 ① 구형 데이터가 최신 데이터를 덮어쓰지 않았는지, ② 2장(기술동향)과 3장(시장동향) 간 인과 논리가 깨지지 않았는지, ③ 3대 필수 표(5열 구조)와 출처 태그가 누락 없이 정합성을 유지하는지 최종 리뷰한 뒤 본문을 출력하십시오.

[외과적 증분 업데이트 및 무손실 보존 5대 불변 원칙 (Surgical Incremental Update Principles)]
1. 기존 내용 불변 보존 (Non-destructive Update):
   - 기존 보고서의 1~4장 문단, 전문 분석, 3대 표의 기존 행, 기존 이미지 배치는 신규 데이터와 명백히 상충되지 않는 한 100% 원형 그대로 보존하십시오. 임의로 문장을 요약하거나 축소하지 마십시오.
2. 검증된 델타 지식(Delta Knowledge) 식별 및 유기적 결합:
   - 위 [3단계 사전 리뷰 프로토콜]을 통과하여 최신성과 논리적 정합성이 검증된 ① 신규 기술 규격/공정/인터페이스 표준, ② 최신 연도 시장 통계 및 예측치, ③ 신규 진입 기업/양산 발표만을 추출하여 1~4장의 가장 적합한 위치에 문단으로 통합하거나 표에 행(Row)으로 추가하십시오.
   - 1차 조사기관(가트너, IDC 등)이 명시된 경우 본문에 `**가트너(Gartner, 2024)**`와 같이 1차 출처를 표기하고, 문단 끝에는 `<출처: [문서제목](/api/documents/문서ID)>`를 부착하십시오.
3. 시장 및 기술 데이터 궤적(Trajectory) 서술:
   - 기존 보고서의 통계와 신규 위키 문서의 통계가 다를 경우(예: 기준 연도 2024년 vs 2025년), 기존 수치를 단순히 지우기만 하지 말고 "당초 2024년 조사에서는 X억 달러로 전망되었으나, 2025년 최신 분석에 따르면 Y억 달러로 상향 조정됨"과 같이 시장의 진화 궤적으로 입체적 서술하십시오.
4. 3대 필수 표 행(Row) 증분 확장 및 5열 규격 준수:
   - 2장 기술 비교표, 3장 시장 전망표, 4장 기업 비교표에 신규 위키 문서에서 검증된 새로운 항목을 새로운 행(Row)으로 추가하되, 기존 5열 규격을 엄격히 유지하십시오.
5. 머리말 메타데이터 개정 이력 기록 및 5장 출처 갱신:
   - 상단 인용구 블록의 메타데이터를 다음과 같이 개정하십시오:
     > - **문서분류**: 🤖 AI 생성 주제 보고서 (위키 지식 개정본)
     > - **주제어**: {topic}
     > - **최종 개정일시**: {now_str}
     > - **반영된 신규 위키 지식**: {new_titles_str}
   - 5장 데이터 출처 섹션에 새롭게 인용된 신규 위키 문서(`- [문서제목](/api/documents/문서ID)`)를 목록에 추가하십시오.
6. 마크다운 표 및 헤딩 문법 무결성 (Table & Heading Isolation):
   - 표 시작 전/종결 후 반드시 빈 줄(개행 2개)을 두고, 표 내부에 이미지를 넣지 마십시오.
   - 모든 소제목은 반드시 독립된 행에서 시작하십시오.
   - 불필요한 AI 인사말이나 서두/말미의 안내 문구("수정본을 작성했습니다" 등)는 일절 작성하지 마십시오.
"""
        return prompt

    def _call_gemini_api(self, prompt: str, log_subject: str) -> str:
        """다중 API 키 로테이션 및 모델 Fallback을 적용하여 Gemini LLM 텍스트 생성을 수행한다."""
        model_names = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-2.5-flash", "gemini-flash-latest"]
        response_text = None
        last_error = None

        keys_to_try = self.api_keys or ([self.api_key] if self.api_key else get_gemini_api_keys_list())
        if not keys_to_try:
            raise ValueError("등록된 Gemini API 키가 없습니다. .env 파일의 GEMINI_API_KEY를 확인해 주십시오.")

        for key_idx, current_key in enumerate(keys_to_try, 1):
            if self.client and hasattr(self.client, "models") and "Mock" in self.client.__class__.__name__:
                client = self.client
            else:
                client = genai.Client(api_key=current_key)
            key_masked = f"{current_key[:8]}...{current_key[-4:]}" if len(current_key) > 12 else "key"
            key_failed = False

            for model_name in model_names:
                try:
                    logger.info(f"Gemini 모델 '{model_name}' (키 #{key_idx}: {key_masked}) 호출 시도 중: {log_subject}")
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt
                    )
                    if response and response.text:
                        response_text = response.text
                        break
                except Exception as e:
                    last_error = e
                    if is_gemini_key_permanently_exhausted(e):
                        logger.warning(
                            f"Gemini API 키 #{key_idx}({key_masked}) 크레딧 소진 또는 인증 오류 감지 ({e}). "
                            f"다음 대체 키로 자동 전환을 시도합니다."
                        )
                        key_failed = True
                        break
                    else:
                        logger.warning(f"Gemini 모델 '{model_name}' (키 #{key_idx}) 호출 오류 ({e}), 다음 모델로 폴백합니다.")

            if response_text:
                break

        if not response_text:
            err_str = str(last_error)
            if "402" in err_str or "RESOURCE_EXHAUSTED" in err_str or "depleted" in err_str:
                error_msg = f"등록된 모든 Gemini API 키의 크레딧이 소진되었습니다 ({last_error}). Google AI Studio에서 새 무료 프로젝트 키를 발급받아 교체해 주십시오."
            else:
                error_msg = f"Gemini API 호출에 실패하였습니다 ({last_error}). 잠시 후 다시 시도해 주십시오."
            raise RuntimeError(error_msg)

        return response_text

    def update_report_with_wiki_docs(
        self,
        report_id: str,
        docs_dir: Optional[Path] = None,
        force_all_matched: bool = False,
        reviewer: Optional[object] = None,
    ) -> dict:
        """기존 보고서와 기존 근거 문서, 신규/갱신 위키 문서를 대조하여 증분 초안을 작성하고,
        논리적 정합성 및 최신 데이터 반영 여부를 리뷰(검수) 및 보정한 뒤 최종 본문을 In-place 저장한다.
        """
        detail = self.get_report_detail(report_id)
        if not detail:
            raise RuntimeError(f"업데이트할 보고서 '{report_id}'를 찾을 수 없습니다.")

        topic = detail.get("topic") or report_id
        current_md = detail["content"]
        report_mtime = detail.get("modified_time", 0.0)

        target_docs_dir = docs_dir or (self.reports_dir.parent / "docs")
        if not target_docs_dir.exists():
            raise RuntimeError(f"WikiDB 문서 디렉터리를 찾을 수 없습니다: {target_docs_dir}")

        matched_docs = search_relevant_sections(topic, target_docs_dir, top_k=7)
        if not matched_docs:
            return {"updated": False, "message": "관련 위키 문서를 찾을 수 없습니다.", **detail}

        new_matched_docs = []
        existing_basis_docs = []
        for doc in matched_docs:
            is_newer = doc.get("mtime", 0.0) > report_mtime
            is_unseen = doc["doc_id"] not in current_md and doc["title"] not in current_md
            if is_newer or is_unseen:
                new_matched_docs.append(doc)
            else:
                existing_basis_docs.append(doc)
                if force_all_matched:
                    new_matched_docs.append(doc)

        if not new_matched_docs and not force_all_matched:
            logger.info(f"보고서 '{report_id}'에 이미 최신 위키 문서들이 모두 반영되어 있습니다.")
            return {"updated": False, "message": "이미 최신 위키 문서들이 모두 반영되어 있습니다.", **detail}

        docs_to_merge = new_matched_docs if new_matched_docs else matched_docs
        logger.info(
            f"보고서 '{report_id}' 증분 업데이트 시작: "
            f"기존 근거 문서 {len(existing_basis_docs)}건 대조, 신규/갱신 위키 문서 {len(docs_to_merge)}건 융합"
        )

        # 1단계: 기존 작성분 + 기존 근거 문서 데이터 + 신규 문서 데이터를 토대로 사전 리뷰 지침이 포함된 증분 작성
        prompt = self._build_incremental_update_prompt(
            current_markdown=current_md,
            topic=topic,
            new_docs=docs_to_merge,
            existing_docs=existing_basis_docs,
        )

        draft_markdown = self._call_gemini_api(prompt, log_subject=f"보고서 증분 개정 1차 작성 ({report_id})")
        final_markdown = draft_markdown

        # 2단계: 작성된 증분 본문에 대한 논리적 정합성, 최신 데이터 반영 및 사실 무결성 리뷰 (Review & Self-Correction)
        review_result = None
        try:
            from app.report_reviewer import ReportReviewAgent
            active_reviewer = reviewer or ReportReviewAgent(api_key=self.api_key)

            # 기존 근거 문서 + 신규 근거 문서 통합 컨텍스트 및 이미지 화이트리스트 구축
            review_context_blocks = []
            valid_image_urls = re.findall(r'!\[.*?\]\(([^\)]+)\)', current_md)
            for doc in matched_docs:
                doc_title = doc.get("title", doc.get("doc_id", "참고 문서"))
                doc_id = doc.get("doc_id", "")
                sec_texts = []
                for sec in doc.get("sections", []):
                    heading = getattr(sec, "heading", "")
                    text = getattr(sec, "text", "")
                    images = getattr(sec, "images", [])
                    if heading and text:
                        sec_texts.append(f"### {heading}\n{text}")
                    elif text:
                        sec_texts.append(text)
                    for img in (images or []):
                        url = img.get("url") if isinstance(img, dict) else (img if isinstance(img, str) else None)
                        if url and url not in valid_image_urls:
                            valid_image_urls.append(url)
                if sec_texts:
                    review_context_blocks.append(f"## [근거 문서] {doc_title} (ID: {doc_id})\n" + "\n\n".join(sec_texts))

            combined_context_str = "\n\n---\n\n".join(review_context_blocks).strip()

            review_result = active_reviewer.review_report(
                report_markdown=draft_markdown,
                topic=topic,
                context=combined_context_str if combined_context_str else None,
                fresh_docs=[],
                valid_image_urls=valid_image_urls if valid_image_urls else None,
                deep_audit=True,
            )

            defects = review_result.get("defects", [])
            checklist = review_result.get("checklist", {})
            logic_or_fact_flaw = (
                not checklist.get("factuality_valid", True)
                or not checklist.get("causality_valid", True)
                or len(defects) > 0
            )

            # 리뷰에서 논리적 정합성 결함, 최신성/사실 불일치 또는 구조적 결함이 발견된 경우 즉시 리뷰 반영 재보정 수행
            if logic_or_fact_flaw and combined_context_str:
                logger.info(
                    f"보고서 '{report_id}' 증분 초안 리뷰 결과 결함 {len(defects)}건 감지 "
                    f"(점수: {review_result.get('quality_score', 0)}점) -> 논리/최신성 정밀 보정 실행"
                )
                refine_prompt = self._build_refine_prompt(
                    current_markdown=draft_markdown,
                    topic=topic,
                    feedback=review_result,
                    fresh_context_str=combined_context_str[:12000],
                )
                refined_candidate = self._call_gemini_api(
                    refine_prompt,
                    log_subject=f"보고서 증분 후 리뷰 피드백 반영 보정 ({report_id})",
                )
                if refined_candidate and len(refined_candidate.strip()) >= len(draft_markdown.strip()) * 0.7:
                    final_markdown = refined_candidate
                    review_result = active_reviewer.review_report(
                        report_markdown=final_markdown,
                        topic=topic,
                        context=combined_context_str,
                        fresh_docs=[],
                        valid_image_urls=valid_image_urls if valid_image_urls else None,
                        deep_audit=False,
                    )
        except Exception as rev_err:
            logger.warning(f"보고서 '{report_id}' 증분 업데이트 후 자체 리뷰 단계 스킵 (초안 유지): {rev_err}")

        # 3단계: 퇴행 방어 안전장치 (기존 보고서가 5대 목차를 모두 갖추었을 때 목차 누락 또는 비정상 절단 방지)
        required_headers = [
            r"##\s*1\.\s*기술\s*개요",
            r"##\s*2\.\s*기술\s*동향",
            r"##\s*3\.\s*시장\s*동향",
            r"##\s*4\.\s*주요\s*업체",
            r"##\s*5\.\s*데이터\s*출처",
        ]
        has_all_headers_before = all(re.search(p, current_md) for p in required_headers)
        has_all_headers_after = all(re.search(p, final_markdown) for p in required_headers)
        if has_all_headers_before and not has_all_headers_after:
            raise RuntimeError("증분 업데이트 결과에서 필수 5대 목차가 누락되어 기존 보고서 원형을 보호합니다.")
        if len(current_md.strip()) > 500 and len(final_markdown.strip()) < len(current_md.strip()) * 0.6:
            raise RuntimeError("증분 업데이트 결과가 기존 본문 대비 60% 미만으로 비정상 축소되어 기존 보고서를 보호합니다.")

        # 4단계: 출처 목록 구성 (기존 + 신규) 및 대상 보고서 파일 In-place 저장
        all_sources = list(detail.get("sources", []))
        existing_doc_ids = {s.get("doc_id") for s in all_sources if isinstance(s, dict)}
        for d in docs_to_merge:
            if d["doc_id"] not in existing_doc_ids:
                all_sources.append({"doc_id": d["doc_id"], "title": d["title"], "score": d.get("score", 0.0)})

        cleaned_markdown = self.deduplicate_citations(final_markdown)
        clean_id = Path(report_id).stem
        target_file = self.reports_dir / f"{clean_id}.md"
        if not target_file.exists():
            for f in self.reports_dir.glob("*.md"):
                if f.stem == clean_id or clean_id in f.stem:
                    target_file = f
                    break

        target_file.write_text(cleaned_markdown, encoding="utf-8")
        logger.info(f"보고서 증분 업데이트 In-place 저장 완료: {target_file}")
        self._sync_report_to_remote(target_file)

        first_heading = re.search(r'^#\s+(.+)$', cleaned_markdown, re.MULTILINE)
        title = first_heading.group(1).strip() if first_heading else detail.get("title", f"{topic} 분석 보고서")

        saved_info = {
            "id": target_file.stem,
            "title": title,
            "topic": topic,
            "markdown": cleaned_markdown,
            "file_name": target_file.name,
            "file_path": str(target_file),
            "file_size": target_file.stat().st_size,
            "created_at": detail.get("ingested_at"),
            "modified_time": target_file.stat().st_mtime,
            "sources": all_sources,
            "is_synthesized": True,
            "updated": True,
            "new_docs_count": len(docs_to_merge),
            "merged_docs_count": len(docs_to_merge),
            "existing_basis_docs_count": len(existing_basis_docs),
        }
        if review_result is not None:
            saved_info["review"] = review_result
            saved_info["review_score"] = review_result.get("quality_score")
        return saved_info

    def generate_report(self, topic: str, docs_dir: Path, update_if_exists: bool = True, force: bool = False) -> dict:
        """지정된 주제에 대해 WikiDB를 검색하고 Gemini LLM을 통해 5대 목차 보고서를 생성한다.
        동일 주제어의 기존 보고서가 존재할 경우 방안 A(증분 업데이트)를 우선 적용한다.
        """
        clean_topic = re.sub(r'[^a-zA-Z0-9가-힣_-]', '_', topic.strip()).strip('_')[:40]
        now = time.time()

        # 최근 60초 내에 동일 주제어로 생성된 보고서가 있다면 중복 생성 차단 및 기존 결과 반환
        if not force and self.reports_dir.exists():
            for f in self.reports_dir.glob("*.md"):
                if f.stem.startswith(f"REPORT_{clean_topic}_"):
                    try:
                        # 60초 디바운스
                        if now - f.stat().st_mtime < 60:
                            logger.info(f"동일 주제어 '{topic}' 최근 생성 보고서 발견 (60초 디바운스 가드 작동): {f.name}")
                            detail = self.get_report_detail(f.stem)
                            if detail:
                                return detail

                        # [방안 A 적용]: 60초가 지난 기존 보고서가 이미 존재하는 경우, 백지 재생성 대신 최신 위키 문서 증분 업데이트 수행
                        if update_if_exists:
                            logger.info(f"동일 주제어 '{topic}' 기존 보고서 감지 -> [방안 A] 위키 문서 기반 증분 업데이트 실행: {f.name}")
                            return self.update_report_with_wiki_docs(f.stem, docs_dir=docs_dir)
                    except Exception as check_err:
                        logger.warning(f"기존 보고서 증분 업데이트 처리 중 오류 (신규 생성으로 폴백): {check_err}")

        # 1. 관련 문서 및 유의미한 이미지 섹션 검색
        matched_docs = search_relevant_sections(topic, docs_dir, top_k=5)
        if not matched_docs:
            raise RuntimeError(
                f"주제 '{topic}'와 관련된 문서를 WikiDB에서 찾을 수 없습니다. 다른 키워드로 검색해 보십시오."
            )

        # 2. 프롬프트 구성
        prompt = self._build_prompt(topic, matched_docs)

        # 3. Gemini LLM 호출
        response_text = self._call_gemini_api(prompt, log_subject=f"보고서 신규 생성 ({topic})")



        # 4. 출처 정보 정리
        sources = [
            {"doc_id": d["doc_id"], "title": d["title"], "score": d["score"]}
            for d in matched_docs
        ]

        # 5. 생성된 보고서를 WikiDB/reports/ 에 저장
        saved_info = self.save_report(topic=topic, markdown=response_text, sources=sources)
        return saved_info

    def save_report(self, topic: str, markdown: str, sources: list) -> dict:
        """생성된 보고서를 마크다운 파일로 영구 저장하고 식별자 정보를 반환한다. 동일 주제어는 In-place 갱신한다."""
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        clean_topic = re.sub(r'[^a-zA-Z0-9가-힣_-]', '_', topic.strip()).strip('_')[:40]

        # 동일 주제어의 기존 보고서 검색 (In-place 갱신으로 목록 내 중복 파일 양산 차단)
        existing_file = None
        for f in self.reports_dir.glob("*.md"):
            if f.stem.startswith(f"REPORT_{clean_topic}_"):
                existing_file = f
                break

        if existing_file:
            file_path = existing_file
            report_id = existing_file.stem
            file_name = existing_file.name
            logger.info(f"동일 주제어 기존 보고서 In-place 갱신 대상 매칭: {file_name}")
        else:
            timestamp = int(time.time())
            report_id = f"REPORT_{clean_topic}_{timestamp}"
            file_name = f"{report_id}.md"
            file_path = self.reports_dir / file_name

        # 출처 중복 정규화 및 단일화 후처리 적용
        cleaned_markdown = self.deduplicate_citations(markdown)

        # 저장
        file_path.write_text(cleaned_markdown, encoding="utf-8")
        logger.info(f"생성 보고서 저장 완료: {file_path}")
        self._sync_report_to_remote(file_path)

        first_heading = re.search(r'^#\s+(.+)$', cleaned_markdown, re.MULTILINE)
        title = first_heading.group(1).strip() if first_heading else f"{topic} 분석 보고서"

        return {
            "id": report_id,
            "title": title,
            "topic": topic,
            "markdown": cleaned_markdown,
            "file_name": file_name,
            "file_path": str(file_path),
            "file_size": file_path.stat().st_size,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "sources": sources,
            "is_synthesized": True
        }

    def _sync_report_to_remote(self, file_path: Path) -> None:
        """클라우드/Google Drive 연동이 활성화된 경우 생성·보정된 보고서를 원격 스토리지에 백업한다."""
        try:
            explicit_storage = getattr(self, "gdrive_storage", None)
            default_reports_dir = Path(__file__).resolve().parent.parent / "WikiDB" / "reports"
            if explicit_storage is None and self.reports_dir.resolve() != default_reports_dir.resolve():
                return

            from app.gdrive_storage import get_gdrive_storage

            storage = explicit_storage or get_gdrive_storage()
            if storage is not None and (storage.is_cloud_mode or storage.is_configured):
                storage.upload_report(file_path)
        except Exception as e:
            logger.debug(f"원격 보고서 백업 스킵 ({file_path.name}): {e}")

    def _delete_report_from_remote(self, report_id: str) -> None:
        """클라우드/Google Drive 연동이 활성화된 경우 원격 스토리지에서도 보고서를 삭제한다."""
        try:
            explicit_storage = getattr(self, "gdrive_storage", None)
            default_reports_dir = Path(__file__).resolve().parent.parent / "WikiDB" / "reports"
            if explicit_storage is None and self.reports_dir.resolve() != default_reports_dir.resolve():
                return

            from app.gdrive_storage import get_gdrive_storage

            storage = explicit_storage or get_gdrive_storage()
            if storage is not None and (storage.is_cloud_mode or storage.is_configured):
                storage.delete_report(report_id)
        except Exception as e:
            logger.debug(f"원격 보고서 삭제 스킵 ({report_id}): {e}")

    def get_all_reports(self) -> list[dict]:
        """저장된 모든 AI 생성 보고서 목록을 반환한다."""
        if not self.reports_dir.exists():
            return []

        reports = []
        for file in sorted(self.reports_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True):
            try:
                content = file.read_text(encoding="utf-8", errors="replace")
                first_heading = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
                title = first_heading.group(1).strip() if first_heading else file.stem

                topic_match = re.search(r'\*\*주제어\*\*:\s*(.+)$', content, re.MULTILINE)
                topic = topic_match.group(1).strip() if topic_match else file.stem

                created_match = re.search(r'\*\*생성일시\*\*:\s*(.+)$', content, re.MULTILINE)
                created_at = created_match.group(1).strip() if created_match else datetime.fromtimestamp(file.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

                reports.append({
                    "id": file.stem,
                    "title": title,
                    "topic": topic,
                    "original_filename": file.name,
                    "file_size": file.stat().st_size,
                    "modified_time": file.stat().st_mtime,
                    "status": "completed",
                    "ingested_at": created_at,
                    "is_synthesized": True
                })
            except Exception as e:
                logger.warning(f"보고서 목록 읽기 오류 ({file.name}): {e}")

        return reports

    def get_report_detail(self, report_id: str) -> Optional[dict]:
        """특정 생성 보고서의 내용 및 메타데이터를 반환한다."""
        clean_id = Path(report_id).stem
        target_file = self.reports_dir / f"{clean_id}.md"
        if not target_file.exists():
            # 대소문자나 부분 매칭 탐색
            for f in self.reports_dir.glob("*.md"):
                if f.stem == clean_id or clean_id in f.stem:
                    target_file = f
                    break

        if not target_file.exists():
            return None

        content = target_file.read_text(encoding="utf-8", errors="replace")

        # 저장된 마크다운 내 출처 링크 누락 및 들여쓰기 서식 자율 치유(Self-Healing)
        healed_content = self.deduplicate_citations(content)
        if healed_content and healed_content != content:
            try:
                target_file.write_text(healed_content, encoding="utf-8")
                content = healed_content
                logger.info(f"보고서 자율 치유(Self-Healing) 완료 및 동기화: {target_file.name}")
            except Exception as e:
                logger.warning(f"보고서 자율 치유 저장 실패 ({target_file.name}): {e}")
                content = healed_content

        first_heading = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        title = first_heading.group(1).strip() if first_heading else target_file.stem

        topic_match = re.search(r'\*\*주제어\*\*:\s*(.+)$', content, re.MULTILINE)
        topic = topic_match.group(1).strip() if topic_match else target_file.stem

        return {
            "id": target_file.stem,
            "title": title,
            "topic": topic,
            "original_filename": target_file.name,
            "file_size": target_file.stat().st_size,
            "modified_time": target_file.stat().st_mtime,
            "status": "completed",
            "ingested_at": datetime.fromtimestamp(target_file.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "content": content,
            "is_synthesized": True
        }

    def delete_report(self, report_id: str) -> bool:
        """특정 생성 보고서를 reports_dir에서 안전하게 삭제한다."""
        from app.utils import safe_remove_file
        clean_id = Path(report_id).stem
        target_file = self.reports_dir / f"{clean_id}.md"
        if not target_file.exists():
            for f in self.reports_dir.glob("*.md"):
                if f.stem == clean_id or clean_id in f.stem:
                    target_file = f
                    break

        if not target_file.exists():
            return False

        removed = safe_remove_file(target_file)
        if removed:
            self._delete_report_from_remote(target_file.stem)
        return removed

    def _build_refine_prompt(
        self,
        current_markdown: str,
        topic: str,
        feedback: dict,
        fresh_context_str: str = "",
        existing_context_str: str = "",
    ) -> str:
        """기존 보고서 내용, 기존 작성분의 근거 위키 문서 데이터, 리뷰어 피드백, 신규 등재 문헌을 결합하여
        데이터 최신성 및 논리적 정합성을 사전 리뷰한 뒤 보정하는 전용 프롬프트를 구성한다.
        """
        defects_str = "\n".join(f"- {d}" for d in feedback.get("defects", []))
        suggestions_str = "\n".join(
            f"- {s}" for s in (feedback.get("actionable_suggestions") or feedback.get("improvement_orders") or [])
        )
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        if not existing_context_str.strip():
            existing_context_str = "(기존 보고서 본문에 이미 수록된 출처 및 정량 데이터를 기존 근거 기준으로 삼으십시오.)"

        if not fresh_context_str.strip():
            fresh_context_str = "(보고서 최초 작성 이후 신규 등재된 추가 문헌이 없습니다. 기존 지적 결함 보정에 집중하십시오.)"

        prompt = f"""당신은 첨단 산업 기술 및 시장 분석 수석 감수위원입니다.
아래에 제공된 기존 보고서를 정밀 검토하고, 독립 품질 감사 에이전트가 지적한 결함(Defects)과 개선 권고사항, [기존 작성분의 근거가 되는 위키 문서 데이터], 그리고 보고서 최초 생성 이후 지식 DB에 새롭게 등재된 최신 원본 문서 데이터를 완벽히 융합하여 기존의 충실한 분석을 온전히 보존하면서 지적된 결함 섹션만을 정밀 보정하십시오.
마구잡이로 내용을 단순 증분하는 것을 엄격히 금지하며, 반드시 **데이터의 실제 최신성 여부와 기술-시장 간 논리적 정합성을 먼저 리뷰(검증)**한 후 본문을 보정하십시오.

[기존 작성 보고서 원본]
{current_markdown}

[기존 작성분의 근거가 되는 위키 문서 데이터 (Existing Basis Data)]
{existing_context_str}

[감수 에이전트 지적 결함 목록]
{defects_str}

[구체적 개선 요구사항]
{suggestions_str}

[보고서 생성 이후 WikiDB에 신규 등재된 최신 원본 데이터]
{fresh_context_str}

[본문 보정 전 필수 수행: 데이터 최신성 및 논리적 정합성 3단계 사전 리뷰 프로토콜 (Pre-Refine Review Protocol)]
- **Step 1. 데이터 최신성 및 기준 연도 정밀 리뷰 (Recency & Base-Year Verification)**:
  - 신규 등재 문서라고 해서 무조건 최신 데이터로 맹신하여 마구잡이로 증분하지 마십시오.
  - 반드시 [기존 작성분 및 기존 근거 문서 데이터]에 수록된 통계/전망치와 [신규 등재된 최신 원본 데이터]의 통계/전망치에 명시된 **실제 기준 연도 및 조사·발행 시점(Survey/Base Year)**을 직접 대조하십시오.
  - 신규 문서의 통계가 기존 보고서에 이미 수록된 통계보다 과거 시점의 데이터이거나 구형 전망치인 경우, **기존 보고서의 최신 주력 통계를 절대로 구형 수치로 덮어쓰거나 무분별하게 혼재시키지 마십시오(역행 갱신 절대 금지)**.
  - 신규 문서의 데이터가 실제로 더 최근에 조사된 최신 지표임이 입증된 경우에만 최신 주력 수치로 채택·갱신하되, 과거 전망치 대비 최신 전망치의 변화 궤적(Trajectory)을 인과적으로 서술하십시오.
- **Step 2. 논리적 정합성 및 기술-시장 3단계 인과관계 리뷰 (Logical Consistency & Causality Review)**:
  - 보정 내용을 반영하기 전에, 기존 보고서에 확립된 핵심 아키텍처 원리 및 `[기술 규격/혁신] → [물리적·경제적 병목 해결] → [전방 산업 채택 및 시장 창출]`의 3단계 인과 논리와 **논리적 모순이나 충돌(Contradiction)이 발생하지 않는지 사전 리뷰**하십시오.
  - 기존 작성분과 신규 문서 간에 기술적 관점이나 시장 추정치가 상충할 경우, 무작정 이어 붙이지 말고 각 데이터의 전제 조건(공정 세대 차이, 조사 기관별 산정 범위 차이, 국내 vs 글로벌 세그먼트 차이)을 규명하여 보고서 전체의 분석 논리가 일관되도록 유기적으로 통합하십시오.
- **Step 3. 자체 검수 후 본문 확정 (Self-Review Before Finalizing)**:
  - 보정 초안 구성 후 ① 구형 데이터가 최신 데이터를 덮어쓰지 않았는지, ② 2장(기술동향)과 3장(시장동향) 간 인과 논리가 깨지지 않았는지, ③ 지적된 결함이 해소되고 3대 필수 표(5열 구조)와 출처 태그가 정합성을 유지하는지 최종 리뷰한 뒤 본문을 출력하십시오.

[외과적 타겟 보정 및 무손실 보존 4대 불변 원칙 (Surgical Non-regression Principles)]
1. 정상 섹션 불변 보존 (Zero Drift): 결함이 지적되지 않은 섹션(1~5장)의 서술 내용, 전문 통계, 기존 표 및 이미지는 단 하나의 문장도 임의로 축소, 요약, 변형하지 말고 100% 원형 그대로 보존하십시오.
2. 결함 섹션 국소 집중 보강 (Surgical Targeting): 지적된 결함(예: 2장 기술 비교표 누락, 3장 시장 전망표 누락, 4장 기업 비교표, 정량 수치 보강 등)이 있는 해당 섹션만을 집중적으로 보완/삽입하십시오.
3. 신규 데이터 보완적 통합: 신규 문헌 반영 시 기존의 확립된 분석 논리를 뒤엎지 않고 최신 통계와 기업 동향을 유기적으로 덧붙여 확장하십시오.
   - ★ [신규 등재 데이터 반영 절대 규칙]:
     - [보고서 생성 이후 WikiDB에 신규 등재된 최신 원본 데이터]가 제공된 경우, 기존 내용과 상충되지 않도록 최신 동향(최신 연도 시장 전망치, 새로 진입한 기업, 개정된 기술 표준 및 인터페이스 등)을 각 해당 장(1~4장)에 적극적으로 통합·갱신하십시오.
     - **통계 및 시장규모 데이터의 실제 최신성 검증 의무화 (Recency Verification)**: 신규 등재 문서라고 해서 무조건 최신 통계로 맹신하지 마십시오. 반드시 **데이터 자체의 기준 연도 및 조사/발행 시점(Survey/Base Year)**을 기존 보고서의 통계 수치와 직접 대조하십시오. 신규 문서의 통계가 기존 보고서에 이미 수록된 통계보다 과거 시점의 데이터이거나 구형 전망치인 경우, **기존 보고서의 최신 통계를 절대로 구형 수치로 덮어쓰거나 훼손하지 마십시오(역행 갱신 절대 금지)**. 신규 문서의 통계가 실제로 더 최근에 조사된 최신 지표임이 입증된 경우에만 주력 전망치로 갱신하십시오.
     - **기술동향의 기존 논리 체계와의 충돌 검토 의무화 (Logical Non-contradiction)**: 신규 문서의 기술 내용을 2장 기술동향에 반영할 때, 기존 보고서에 이미 체계화된 핵심 아키텍처 원리 및 기술-시장 3단계 인과 구조와 **논리적 모순이나 충돌(Contradiction)이 발생하지 않는지 반드시 사전에 정합성을 검토**하십시오. 신규 기술 내용이 기존 보고서의 분석 논리를 보완·확장하는 경우에만 유기적으로 통합하고, 상충되거나 파편적인 단편 견해일 경우 기존의 일관된 논리적 골격을 훼손하지 않도록 대안 견해로 비교 서술하십시오.
     - 신규 문서에 포함된 유효한 최신 도표/차트 이미지가 있다면 해당 섹션에 `<출처>` 링크와 함께 인라인으로 추가 배치하십시오.
     - 5번 데이터 출처 섹션에 새롭게 인용된 신규 문서의 제목과 링크(`- [{{문서제목}}](/api/documents/{{문서ID}})`)를 빠짐없이 추가하십시오.
4. 형식 및 메타데이터 무결성:
   - 머리말 헤더 메타데이터 영역을 다음과 같이 갱신하십시오:
     - `> - **검수 상태**: ✨ AI 리뷰어 피드백 및 최신 지식DB 동기화 완료`
     - `> - **최종 보정일시**: {now_str}`
     (단, 점수나 불필요한 메타 평가는 일절 기재하지 마십시오.)
   - 첫 행은 반드시 `# {topic} 종합 기술 및 시장 분석 보고서`로 시작하며, 불필요한 AI 인사말이나 서두/말미의 안내 문구("수정본을 작성했습니다", "최신 데이터를 반영했습니다" 등)는 일절 작성하지 마십시오.
   - ★ [최신 데이터 우선권 및 기술-시장 논리 정합성 집중 보정]:
     - [신규 등재된 최신 원본 데이터]에 최신 연도 시장 조사 자료가 포함되어 있고 기존 보고서의 통계보다 실제로 최신일 경우, 과거 통계를 최신 수치로 우선 갱신하고 연평균 성장률(CAGR)과 기준/전망 연도를 최신화하십시오. (단, 신규 문서의 통계가 구형인 경우 기존의 최신 통계를 온전히 보존하십시오.)
     - 2장 기술동향과 3장 시장동향 사이의 논리적 연계성(이 기술 규격과 아키텍처가 왜 해당 시장 성장을 이끄는지)이 미흡하다고 지적된 경우, 기술 사양 혁신과 시장 수요 창출 간의 인과관계를 본문과 비교 표에 유기적으로 보강하여 리뷰어가 기술적 타당성을 충분히 검토할 수 있도록 재구성하십시오.
     - 신규 기술 내용 반영 시 기존 보고서의 기술 분석 논리와 모순되거나 충돌되지 않는지 철저히 감수하십시오.
     - 전문 용어 해설은 본문 중간에 섞지 말고 본문 `용어[^1]` 및 문서 최하단 `[^1]: **용어**: 설명`의 표준 GFM 각주로 정돈하십시오.
   - ★ [마크다운 표 문법 무결성 절대 준수 (Table Header & Terminator Isolation)]:
     - 표 시작 격리: 모든 마크다운 표(`| 헤더 |`)는 반드시 이전 문단, 출처 태그(`<출처:...>`), 또는 캡션(`*(자료:...)*`)과 **빈 줄(개행 2개)**로 완벽하게 분리되어야 합니다. 표 헤더 행은 무조건 행의 맨 처음(`^|`)에서 시작해야 합니다.
     - 표 종결 격리: 표의 마지막 데이터 행(`| ... |`) 직후에는 반드시 **빈 줄(개행 2개)**을 넣어 표 블록을 명시적으로 종결하십시오. 표 바로 뒤에 이어지는 단위/출처 주석(`*(단위:...)*`)이나 도표 이미지(`![]()`), 후속 본문은 표와 절대 붙여 쓰지 마십시오.
     - 이미지 단독 행 격리: 출처 태그(`<출처:...>`)와 이미지 태그(`![]()`)를 한 줄에 연달아 붙여 쓰지 말고 반드시 빈 줄을 두고 별도의 독립 행으로 배치하십시오.
"""
        return prompt

    def refine_report(
        self,
        report_id: str,
        feedback: dict,
        docs_dir: Optional[Path] = None
    ) -> dict:
        """기존 보고서, 기존 작성분의 근거 위키 문서 데이터, 리뷰 피드백, 신규 등재 문헌을 기반으로
        논리적 정합성 및 최신성을 대조·보정하고 In-place 덮어쓰기 저장한다.
        """
        detail = self.get_report_detail(report_id)
        if not detail:
            raise RuntimeError(f"보정할 보고서 '{report_id}'를 찾을 수 없습니다.")

        topic = detail.get("topic") or report_id
        current_md = detail["content"]
        report_mtime = detail.get("modified_time", 0.0)

        # 보고서 기존 근거 문서 데이터 및 생성/수정 시점 이후 신규 등재 문서 분리 추출
        target_docs_dir = docs_dir or (self.reports_dir.parent / "docs")
        fresh_context_str = ""
        existing_context_str = ""

        if target_docs_dir.exists():
            try:
                latest_matched_docs = search_relevant_sections(topic, target_docs_dir, top_k=7)
                fresh_context_parts = []
                existing_context_parts = []
                for doc in latest_matched_docs:
                    is_newer = doc.get("mtime", 0.0) > report_mtime
                    is_unseen = doc["doc_id"] not in current_md and doc["title"] not in current_md

                    if is_newer or is_unseen:
                        for sec in doc.get("sections", [])[:3]:
                            img_desc = ""
                            if sec.images:
                                img_lines = [
                                    f"  * 사용가능 이미지: ![{img['alt']}]({img['url']})"
                                    for img in sec.images[:2]
                                ]
                                img_desc = "\n" + "\n".join(img_lines)
                            table_desc = (
                                f"\n[신규 핵심 데이터 표]:\n" + "\n\n".join(sec.tables[:1])
                                if sec.tables else ""
                            )
                            smart_body = self._extract_smart_section_text(getattr(sec, "text", ""), max_chars=2000)
                            fresh_context_parts.append(
                                f"### [신규 등재 문서: {doc['title']}] - 섹션: {sec.heading}\n"
                                f"출처 문서 ID: `{doc['doc_id']}`\n"
                                f"본문 데이터:\n{smart_body}\n"
                                f"{table_desc}\n"
                                f"{img_desc}\n"
                            )
                    else:
                        for sec in doc.get("sections", [])[:3]:
                            table_desc = (
                                f"\n[기존 근거 핵심 표]:\n" + "\n\n".join(sec.tables[:1])
                                if getattr(sec, "tables", None) else ""
                            )
                            smart_body = self._extract_smart_section_text(getattr(sec, "text", ""), max_chars=1800)
                            existing_context_parts.append(
                                f"### [기존 작성분 근거 문서: {doc['title']}] - 섹션: {sec.heading}\n"
                                f"출처 문서 ID: `{doc['doc_id']}`\n"
                                f"본문 데이터:\n{smart_body}\n"
                                f"{table_desc}\n"
                            )

                if fresh_context_parts:
                    fresh_context_str = "\n---\n".join(fresh_context_parts)
                    logger.info(f"보고서 보정 시 신규 등재 지식 {len(fresh_context_parts)}개 섹션 감지 및 주입")
                if existing_context_parts:
                    existing_context_str = "\n---\n".join(existing_context_parts)
                    logger.info(f"보고서 보정 시 기존 작성분 근거 지식 {len(existing_context_parts)}개 섹션 대조 주입")
            except Exception as search_err:
                logger.warning(f"보정 중 최신 지식 검색 오류 (기존 규칙으로 진행): {search_err}")

        prompt = self._build_refine_prompt(
            current_markdown=current_md,
            topic=topic,
            feedback=feedback,
            fresh_context_str=fresh_context_str,
            existing_context_str=existing_context_str,
        )

        # Gemini LLM 호출
        response_text = self._call_gemini_api(prompt, log_subject=f"보고서 보정(Refine) ({report_id})")

        # 퇴행 및 비정상 절단 방어 안전장치 (Safety Guardrail)
        required_headers = [
            r"##\s*1\.\s*기술\s*개요",
            r"##\s*2\.\s*기술\s*동향",
            r"##\s*3\.\s*시장\s*동향",
            r"##\s*4\.\s*주요\s*업체",
            r"##\s*5\.\s*데이터\s*출처",
        ]
        has_all_headers_before = all(re.search(p, current_md) for p in required_headers)
        has_all_headers_after = all(re.search(p, response_text) for p in required_headers)

        is_truncated = len(response_text.strip()) < len(current_md.strip()) * 0.6
        header_regressed = has_all_headers_before and not has_all_headers_after

        if is_truncated or header_regressed:
            reasons = []
            if is_truncated:
                reasons.append(
                    f"본문 길이 급감 (기존 {len(current_md.strip())}자 -> 보정 {len(response_text.strip())}자, 60% 미만)"
                )
            if header_regressed:
                reasons.append("기존에 존재하던 필수 5대 목차 헤더 누락")
            guardrail_msg = ", ".join(reasons)
            logger.warning(
                f"보고서 보정 퇴행 방어 안전장치 작동: {guardrail_msg}. "
                f"기존 보고서 원형을 보존하기 위해 보정 덮어쓰기를 중단합니다 (report_id={report_id})."
            )
            raise RuntimeError(
                f"보정 결과가 비정상적으로 축소되었거나 필수 목차가 누락되어 기존 본문을 보존합니다 ({guardrail_msg})."
            )

        # In-place 덮어쓰기 저장
        cleaned_markdown = self.deduplicate_citations(response_text)
        clean_id = Path(report_id).stem
        target_file = self.reports_dir / f"{clean_id}.md"
        if not target_file.exists():
            for f in self.reports_dir.glob("*.md"):
                if f.stem == clean_id or clean_id in f.stem:
                    target_file = f
                    break

        target_file.write_text(cleaned_markdown, encoding="utf-8")
        logger.info(f"보고서 보정 In-place 덮어쓰기 완료: {target_file}")
        self._sync_report_to_remote(target_file)

        first_heading = re.search(r'^#\s+(.+)$', cleaned_markdown, re.MULTILINE)
        title = first_heading.group(1).strip() if first_heading else detail["title"]

        return {
            "id": report_id,
            "title": title,
            "topic": topic,
            "markdown": cleaned_markdown,
            "file_name": target_file.name,
            "file_path": str(target_file),
            "file_size": target_file.stat().st_size,
            "created_at": detail.get("ingested_at"),
            "modified_time": target_file.stat().st_mtime,
            "is_synthesized": True
        }

    def refine_report_with_loop(
        self,
        report_id: str,
        initial_feedback: dict,
        reviewer: Optional[object] = None,
        max_iterations: int = 3,
        target_score: int = 90,
        docs_dir: Optional[Path] = None
    ) -> dict:
        """목표 품질 점수, 결함 0건, 그리고 원천 문서 대비 최신성·논리적 정합성 통과 시까지
        최대 max_iterations회 자율 반추(Self-Reflection)하여 최적 버전을 수렴 도출한다.
        """
        current_feedback = dict(initial_feedback or {})
        best_result: Optional[dict] = None
        best_score: int = -1
        last_result: Optional[dict] = None

        # 자체 품질 재검수 시 기존 근거 문서 + 신규 후보 문서 대조를 위한 컨텍스트 준비
        target_docs_dir = docs_dir or (self.reports_dir.parent / "docs")
        review_context_str = ""
        valid_image_urls: list[str] = []
        initial_detail = self.get_report_detail(report_id)
        if initial_detail:
            valid_image_urls.extend(re.findall(r'!\[.*?\]\(([^\)]+)\)', initial_detail.get("content", "")))
            if target_docs_dir.exists():
                try:
                    search_topic = initial_detail.get("topic") or report_id
                    matched_docs = search_relevant_sections(search_topic, target_docs_dir, top_k=7)
                    report_mtime = initial_detail.get("modified_time", 0.0)
                    current_md = initial_detail.get("content", "")
                    ctx_blocks = []
                    for doc in matched_docs:
                        doc_title = doc.get("title", doc.get("doc_id", "참고 문서"))
                        doc_id = doc.get("doc_id", "")
                        is_newer = doc.get("mtime", 0.0) > report_mtime
                        is_unseen = doc_id not in current_md and doc_title not in current_md
                        role_label = "신규/미반영 후보 문서" if (is_newer or is_unseen) else "기존 작성분 근거 문서"
                        sec_texts = []
                        for sec in doc.get("sections", []):
                            heading = getattr(sec, "heading", "")
                            text = getattr(sec, "text", "")
                            images = getattr(sec, "images", [])
                            if heading and text:
                                sec_texts.append(f"### {heading}\n{text}")
                            elif text:
                                sec_texts.append(text)
                            for img in (images or []):
                                url = img.get("url") if isinstance(img, dict) else (img if isinstance(img, str) else None)
                                if url and url not in valid_image_urls:
                                    valid_image_urls.append(url)
                        if sec_texts:
                            ctx_blocks.append(f"## [{role_label}] {doc_title} (ID: {doc_id})\n" + "\n\n".join(sec_texts))
                    review_context_str = "\n\n---\n\n".join(ctx_blocks).strip()
                except Exception as ctx_err:
                    logger.warning(f"자율 반추 루프 컨텍스트 구성 중 오류 (기본 검수로 진행): {ctx_err}")

        logger.info(f"🔄 [자율 반추 수렴 루프 가동] 보고서: {report_id}, 최대 반복: {max_iterations}회, 목표 점수: {target_score}점")

        for iteration in range(1, max_iterations + 1):
            logger.info(f"  ▶ [반추 턴 {iteration}/{max_iterations}] 보정 실행 중...")
            try:
                candidate = self.refine_report(
                    report_id=report_id,
                    feedback=current_feedback,
                    docs_dir=docs_dir
                )
                last_result = candidate
            except Exception as e:
                logger.warning(f"  ⚠️ [반추 턴 {iteration}] 보정 실행 중 오류: {e}")
                if best_result:
                    break
                raise

            # 리뷰어가 제공된 경우 원천 근거 문서 대비 최신성/사실 정합성 및 논리적 정합성 심층 재검수
            if reviewer and hasattr(reviewer, "review_report"):
                try:
                    try:
                        audit_res = reviewer.review_report(
                            report_markdown=candidate["markdown"],
                            topic=candidate["topic"],
                            context=review_context_str if review_context_str else None,
                            fresh_docs=[],
                            valid_image_urls=valid_image_urls if valid_image_urls else None,
                            deep_audit=bool(review_context_str),
                        )
                    except TypeError:
                        audit_res = reviewer.review_report(
                            report_markdown=candidate["markdown"],
                            topic=candidate["topic"],
                        )

                    score = audit_res.get("quality_score", 0)
                    defects = audit_res.get("defects", [])
                    checklist = audit_res.get("checklist", {})
                    logic_and_fact_ok = (
                        checklist.get("factuality_valid", True)
                        and checklist.get("causality_valid", True)
                    )
                    logger.info(
                        f"  📊 [반추 턴 {iteration} 결과] 품질 점수: {score}점, 잔여 결함: {len(defects)}건, "
                        f"최신성·논리 정합성 통과: {logic_and_fact_ok}"
                    )

                    if score > best_score:
                        best_score = score
                        best_result = candidate

                    # 수렴 조건: 목표 점수 이상, 잔여 결함 0건, 그리고 사실/최신성 및 인과 논리 정합성 모두 통과
                    if score >= target_score and len(defects) == 0 and logic_and_fact_ok:
                        logger.info(f"  ✨ [수렴 완료] 목표 품질 및 논리·최신성 정합성 달성({score}점)으로 자율 반추 루프 조기 종료")
                        break

                    # 미달 시 차기 턴 피드백 구성 (새로운 제안사항 반영)
                    current_feedback = {
                        "checklist": checklist,
                        "actionable_suggestions": audit_res.get("actionable_suggestions", []),
                        "defects": defects,
                    }
                except Exception as audit_err:
                    logger.warning(f"  ⚠️ [반추 턴 {iteration}] 자체 감사 중 오류: {audit_err}")
                    best_result = candidate
                    break
            else:
                # 리뷰어가 없는 경우 1회 보정으로 즉시 완료
                best_result = candidate
                break

        final_res = best_result or last_result
        if not final_res:
            raise RuntimeError(f"보고서 '{report_id}' 자율 반추 보정에 실패했습니다.")

        return final_res


