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

from app.topic_search import search_relevant_sections

logger = logging.getLogger("TopicReportGenerator")

class TopicReportGenerator:
    """기존 파싱된 완본 마크다운과 이미지를 종합하여 5대 목차 체계의 신규 보고서를 생성하는 엔진."""

    def __init__(self, reports_dir: Optional[Path] = None, api_key: Optional[str] = None):
        self.reports_dir = reports_dir or (Path(__file__).resolve().parent.parent / "WikiDB" / "reports")
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

    @staticmethod
    def normalize_source_title(title: str) -> str:
        """출처 제목에서 괄호, 특수문자, 공백을 정규화하여 동일 문헌 여부를 판별한다."""
        return re.sub(r'[\s_()\[\]\-\.]+', '', title).lower()

    @classmethod
    def deduplicate_citations(cls, markdown_text: str) -> str:
        """보고서 마크다운 내 인접한 동일 문헌 출처 및 5번 데이터 출처 중복을 제거한다."""
        if not markdown_text:
            return ""

        # 1. 본문 내 인접한 동일 문헌 출처 병합
        citation_group_pattern = re.compile(r'(?:<출처\s*:\s*\[([^\]]+)\]\(([^)]+)\)>\s*,?\s*)+')

        def merge_citation_match(match):
            full_chunk = match.group(0)
            items = re.findall(r'<출처\s*:\s*\[([^\]]+)\]\(([^)]+)\)>', full_chunk)
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

        cleaned_text = citation_group_pattern.sub(merge_citation_match, markdown_text)

        # 2. 5번 데이터 출처 섹션 내의 bullet list 중복 제거
        sec5_pattern = re.compile(r'(## 5\.\s*데이터\s*출처.*?)(?=\n##|\Z)', re.DOTALL)
        sec5_match = sec5_pattern.search(cleaned_text)
        if sec5_match:
            sec5_content = sec5_match.group(1)
            lines = sec5_content.splitlines()
            new_lines = []
            seen_keys = set()

            for line in lines:
                bullet_match = re.match(r'^\s*[-*]\s*\[([^\]]+)\]\(([^)]+)\)\s*$', line)
                if bullet_match:
                    title = bullet_match.group(1)
                    key = cls.normalize_source_title(title)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    new_lines.append(line)
                else:
                    new_lines.append(line)

            new_sec5 = "\n".join(new_lines)
            cleaned_text = cleaned_text[:sec5_match.start(1)] + new_sec5 + cleaned_text[sec5_match.end(1):]

        return cleaned_text

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

                context_parts.append(
                    f"### [참고 문서: {title}] - 섹션: {sec.heading} (분류: {getattr(sec, 'category', 'general')})\n"
                    f"출처 문서 ID: `{doc_id}`\n"
                    f"본문 데이터:\n{sec.text[:3000]}\n"
                    f"{table_desc}\n"
                    f"{img_desc}\n"
                )

        full_context = "\n---\n".join(context_parts)
        sources_summary = "\n".join(source_metadata)

        prompt = f"""당신은 첨단 산업 기술 및 시장 분석 수석 연구원입니다.
아래 제공된 '기존 완본 문서 데이터베이스 컨텍스트'를 심층 분석하여, 요청된 주제 '{topic}'에 대한 고품질의 종합 리서치 보고서를 마크다운(Markdown) 형식으로 작성해 주십시오.

[작성 및 서식 절대 준수 규칙]
1. [보고서 목차 및 체계 엄격 준수]:
   보고서는 반드시 아래의 5대 목차 순서와 제목, 헤더 형식을 엄격하게 준수해야 합니다. 첫 줄은 반드시 `#` 제목으로 시작하며, 불필요한 AI 인사말이나 서두/결말 멘트("안녕하세요", "보고서를 작성합니다", "도움이 되길 바랍니다" 등)는 일절 작성하지 마십시오.

   # {topic} 종합 기술 및 시장 분석 보고서
   > - **문서분류**: 🤖 AI 생성 주제 보고서 (Synthesized Report)
   > - **주제어**: {topic}
   > - **생성일시**: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}
   > - **기반 데이터**: WikiDB 지식 저장소 심층 합성
   
   ---
   
   ## 1. 기술개요
   - 기술의 개념적 정의, 해결하고자 하는 핵심 난제(기존 기술의 병목 및 한계), 핵심 메커니즘을 인과 관계 중심으로 상세히 서술하십시오.
   - 논리적 완성도와 가독성을 위해 세부 소제목(예: `### 1.1 기술 개념 및 등장 배경`, `### 1.2 핵심 메커니즘 및 동작 원리`)을 구성하여 체계적으로 기술하십시오.
   
   ## 2. 기술동향
   - 세부 기술 분류, 아키텍처 혁신, 공정 및 인터페이스 표준화(예: UCIe 등) 동향을 구체적인 기술 규격(nm, Gbps 등)과 함께 서술하십시오.
   - [필수 요약 표]: 세부 기술/방식별 특징, 장단점, 주요 적용처를 대비하는 **'핵심 기술 방식 비교 요약 표(Markdown Table)'**를 반드시 1개 이상 작성하십시오.
   - 관련 아키텍처 및 기술 다이어그램 이미지를 설명 직하단에 인라인으로 결합하십시오.
   
   ## 3. 시장동향 (국내/세계시장 규모 데이터)
   - [필수 주의]: 컨텍스트에 포함된 국내 시장 규모, 세계 시장 규모 수치 및 연도별 예측 데이터, 연평균 성장률(CAGR), 시장 통계 표를 반드시 상세히 인용하십시오. '자료가 없다'고 단정하지 말고 제공된 수치(억 원, 억 달러 단위 및 연도별 추이)를 빠짐없이 기술하십시오.
   - [필수 전망 표]: 연도별 시장 규모 및 CAGR 추이를 한눈에 파악할 수 있는 **'시장 규모 및 전망 데이터 표(Markdown Table)'**를 필수로 구성하십시오.
   - 시장 성장을 견인하는 핵심 동인(Growth Drivers) 및 시장 진입/확장의 주요 병목(리스크 및 기술적 난제)을 심층 분석하십시오.
   - 관련 시장 차트 및 통계 도표 이미지를 인라인으로 배치하십시오.
   
   ## 4. 주요업체
   - 글로벌 선도 기업 및 국내 핵심 기업들의 개발 현황, 주력 제품 라인업, 기술력 비교, 상용화 동향을 객관적으로 분석하십시오.
   - [필수 기업 비교 표]: 주요 기업별 핵심 기술/제품, 개발 단계, 전략적 포지셔닝을 대비하는 **'주요 기업별 기술 및 개발 현황 비교 표(Markdown Table)'**를 반드시 구성하십시오.
   
   ## 5. 데이터 출처
   - 인용에 활용된 원본 문서 목록을 나열하고 링크를 제공하십시오.

2. [인용 이미지 및 도표 배치 필수 규칙]:
   - 컨텍스트에 제공된 '사용가능 이미지' 중 유의미한 아키텍처 다이어그램, 시장 규모 차트, 기술 비교 표 이미지를 적극 인용하십시오.
   - 인용한 텍스트 문단 바로 직하단에 해당 마크다운 이미지 태그를 줄바꿈 후 단독 행으로 배치하십시오.
   - 형식 예시:
     ... 초고속 인터커넥트 UCIe 표준을 적용하여 패키징 효율을 극대화합니다. <출처: [칩렛(Chiplet) 문서](/api/documents/chiplet_doc)>
     
     ![칩렛 패키징 아키텍처 다이어그램](/api/assets/chiplet_doc/image_005.png)
     *(도표: 칩렛 인터커넥트 구조 - 출처: 칩렛(Chiplet) 문서)*

3. [본문과 출처 링크 시각적 구분 필수 규칙]:
   - 본문 문장과 출처 링크가 명확하게 시각적으로 분리되도록, 인용된 문장/문단 끝에는 반드시 `<출처: [{{문서제목}}](/api/documents/{{문서ID}})>` 형식(꺾쇠 괄호 `<`와 `>`로 감싼 하이퍼링크)으로 작성하십시오.
   - 절대 평문으로 섞어 쓰지 마시고, 링크 문법을 빠짐없이 갖추어 작성하십시오.

4. [전문 리서치 문체 및 정량 데이터 분석 절대 원칙]:
   - **정량적 팩트 중심 서술**: 추상적 수사("급격히 성장함", "우수한 성능")를 지양하고, 구체적인 수치, 연도, 규격, 단위(nm, Gbps, 억원, 달러, % 등)를 명확히 제시하십시오.
   - **일관된 전문 보고서 문체**: 격식 있는 개조식 및 보고서 서술 종결 어미(~다, ~임, ~함 등)를 일관되게 사용하십시오.
   - **인공지능 상투어 차단**: 보고서 본문 외에 사용자에 대한 인사말, 프롬프트 해설, 서두/말미의 안내 문구를 일절 배제하고 마크다운 보고서 본문만 순수하게 출력하십시오.

5. 5번 데이터 출처 섹션:
   - 인용된 모든 문서의 제목과 ID를 링크 형태로 정리하여 bullet list로 명시하십시오:
     - [{{문서제목}}](/api/documents/{{문서ID}})

[참고 컨텍스트 데이터]
{full_context}

[참고 대상 원본 문서 목록]
{sources_summary}
"""
        return prompt

    def generate_report(self, topic: str, docs_dir: Path) -> dict:
        """지정된 주제에 대해 WikiDB를 검색하고 Gemini LLM을 통해 5대 목차 보고서를 생성한다."""
        if not self.api_key or not self.client:
            raise ValueError(
                "Gemini API 키가 설정되지 않았습니다. .env 파일에 GEMINI_API_KEY를 확인해 주십시오."
            )

        # 1. 관련 문서 및 유의미한 이미지 섹션 검색
        matched_docs = search_relevant_sections(topic, docs_dir, top_k=5)
        if not matched_docs:
            raise RuntimeError(
                f"주제 '{topic}'와 관련된 문서를 WikiDB에서 찾을 수 없습니다. 다른 키워드로 검색해 보십시오."
            )

        # 2. 프롬프트 구성
        prompt = self._build_prompt(topic, matched_docs)

        # 3. Gemini LLM 호출
        # 검증된 Gemini 모델만 사용 (안정적인 fallback 모델 설정)
        model_names = ["gemini-2.5-flash", "gemini-2.0-flash"]
        response_text = None
        last_error = None

        for model_name in model_names:
            try:
                logger.info(f"Gemini 모델 '{model_name}'으로 보고서 생성 시도 중: {topic}")
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                if response and response.text:
                    response_text = response.text
                    break
            except genai_errors.APIError as e:
                logger.warning(f"Gemini 모델 '{model_name}' 호출 오류: {e}")
                last_error = e
            except Exception as e:
                logger.warning(f"Gemini 모델 '{model_name}' 일반 오류: {e}")
                last_error = e

        if not response_text:
            error_msg = f"Gemini API 호출에 실패하였습니다 ({last_error}). 잠시 후 다시 시도해 주십시오."
            raise RuntimeError(error_msg)

        # 4. 출처 정보 정리
        sources = [
            {"doc_id": d["doc_id"], "title": d["title"], "score": d["score"]}
            for d in matched_docs
        ]

        # 5. 생성된 보고서를 WikiDB/reports/ 에 저장
        saved_info = self.save_report(topic=topic, markdown=response_text, sources=sources)
        return saved_info

    def save_report(self, topic: str, markdown: str, sources: list) -> dict:
        """생성된 보고서를 마크다운 파일로 영구 저장하고 식별자 정보를 반환한다."""
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        clean_topic = re.sub(r'[^a-zA-Z0-9가-힣_-]', '_', topic)[:40]
        report_id = f"REPORT_{clean_topic}_{timestamp}"
        file_name = f"{report_id}.md"
        file_path = self.reports_dir / file_name

        # 출처 중복 정규화 및 단일화 후처리 적용
        cleaned_markdown = self.deduplicate_citations(markdown)

        # 저장
        file_path.write_text(cleaned_markdown, encoding="utf-8")
        logger.info(f"생성 보고서 저장 완료: {file_path}")

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

        return safe_remove_file(target_file)

    def _build_refine_prompt(self, current_markdown: str, topic: str, feedback: dict) -> str:
        """기존 보고서 내용과 리뷰어 피드백을 결합한 보정 전용 프롬프트를 구성한다."""
        defects_str = "\n".join(f"- {d}" for d in feedback.get("defects", []))
        suggestions_str = "\n".join(f"- {s}" for s in feedback.get("actionable_suggestions", []))

        prompt = f"""당신은 첨단 산업 기술 및 시장 분석 수석 감수위원입니다.
아래에 제공된 기존 보고서를 정밀 검토하고, 독립 품질 감사 에이전트가 지적한 결함(Defects)과 개선 권고사항을 완벽히 보강하여 최상급의 완성본 마크다운 보고서로 재작성해 주십시오.

[기존 작성 보고서 원본]
{current_markdown}

[감수 에이전트 지적 결함 목록]
{defects_str}

[구체적 개선 요구사항]
{suggestions_str}

[보정 절대 준수 규칙]
1. 기존 보고서에서 이미 충실하게 작성된 문단과 구조, 정상적인 표 및 이미지는 훼손하지 말고 최대한 보존하십시오.
2. [지적 결함] 및 [개선 요구사항]에 명시된 누락 항목(예: 2장 기술 비교표, 3장 시장 전망표, 4장 기업 비교표, 정량 수치 보강 등)을 해당 섹션 내에 자연스럽고 정밀하게 추가/보완하십시오.
3. 머리말 헤더 메타데이터 영역에 `> - **검수 상태**: ✨ AI 리뷰어 피드백 반영 보정 완료` 항목을 추가하십시오. 단, 점수(XX점 등) 관련 문구는 일절 기재하지 마십시오.
4. 첫 행은 반드시 `# {topic} 종합 기술 및 시장 분석 보고서`로 시작하며, 불필요한 AI 인사말이나 서두/말미의 안내 문구("수정본을 작성했습니다" 등)는 일절 작성하지 마십시오.
"""
        return prompt

    def refine_report(self, report_id: str, feedback: dict) -> dict:
        """기존 보고서와 리뷰 피드백을 기반으로 LLM 보정을 수행하고 In-place 덮어쓰기 저장한다."""
        detail = self.get_report_detail(report_id)
        if not detail:
            raise RuntimeError(f"보정할 보고서 '{report_id}'를 찾을 수 없습니다.")

        topic = detail.get("topic") or report_id
        current_md = detail["content"]

        prompt = self._build_refine_prompt(current_md, topic, feedback)

        # Gemini LLM 호출
        model_names = ["gemini-2.5-flash", "gemini-2.0-flash"]
        response_text = None
        last_error = None

        if not self.client:
            raise RuntimeError("Gemini 클라이언트가 초기화되지 않았습니다.")

        for model_name in model_names:
            try:
                logger.info(f"Gemini 모델 '{model_name}'으로 보고서 보정(Refine) 시도 중: {report_id}")
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                if response and response.text:
                    response_text = response.text
                    break
            except Exception as e:
                logger.warning(f"보정 호출 중 오류 ({model_name}): {e}")
                last_error = e

        if not response_text:
            raise RuntimeError(f"보고서 보정 LLM 호출 실패: {last_error}")

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


