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

    def _build_prompt(self, topic: str, matched_docs: list[dict]) -> str:
        """Gemini LLM에게 전달할 프롬프트 및 컨텍스트를 구성한다."""
        context_parts = []
        source_metadata = []

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
1. 보고서 목차는 반드시 아래의 5대 목차 순서와 제목을 엄격하게 준수해야 합니다:
   # {topic} 종합 기술 및 시장 분석 보고서
   > - **문서분류**: 🤖 AI 생성 주제 보고서 (Synthesized Report)
   > - **주제어**: {topic}
   > - **생성일시**: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}
   > - **기반 데이터**: WikiDB 지식 저장소 심층 합성
   
   ---
   
   ## 1. 기술개요
   (기술의 개념적 정의, 해결하고자 하는 난제, 핵심 메커니즘을 상세히 서술)
   
   ## 2. 기술동향
   (세부 기술 분류, 아키텍처 혁신, 표준화 동향 등을 설명하고 관련 도표 이미지를 결합)
   
   ## 3. 시장동향 (국내/세계시장 규모 데이터)
   [필수 주의] 컨텍스트에 포함된 국내 시장 규모, 세계 시장 규모 수치 및 연도별 예측 데이터, 연평균 성장률(CAGR), 시장 통계 표를 반드시 상세히 인용하십시오. '자료가 없다'고 단정하지 말고 제공된 수치(억 원, 억 달러 단위 및 연도별 추이)를 마크다운 표와 함께 기술하고 관련 시장 차트 이미지를 인라인으로 배치하십시오.
   
   ## 4. 주요업체
   (글로벌 선도 기업 및 국내 핵심 기업들의 개발 현황, 기술력 비교, 상용화 동향)
   
   ## 5. 데이터 출처
   (인용에 활용된 원본 문서 목록을 나열하고 링크 제공)

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

4. 5번 데이터 출처 섹션:
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

        # 저장
        file_path.write_text(markdown, encoding="utf-8")
        logger.info(f"생성 보고서 저장 완료: {file_path}")

        first_heading = re.search(r'^#\s+(.+)$', markdown, re.MULTILINE)
        title = first_heading.group(1).strip() if first_heading else f"{topic} 분석 보고서"

        return {
            "id": report_id,
            "title": title,
            "topic": topic,
            "markdown": markdown,
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

        return {
            "id": target_file.stem,
            "title": title,
            "original_filename": target_file.name,
            "file_size": target_file.stat().st_size,
            "modified_time": target_file.stat().st_mtime,
            "status": "completed",
            "ingested_at": datetime.fromtimestamp(target_file.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "content": content,
            "is_synthesized": True
        }
