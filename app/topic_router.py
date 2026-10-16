"""주제 기반 보고서 생성, 추천 키워드 및 생성 이력 관리를 위한 FastAPI 라우터 모듈."""

import logging
import re
import urllib.parse
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Response
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.topic_generator import TopicReportGenerator
from app.report_reviewer import ReportReviewAgent
from app.html_doc_exporter import HtmlDocExporter
from app.topic_search import search_relevant_sections
from app.task_manager import TaskManager, get_task_manager, AgentTask

logger = logging.getLogger("TopicRouter")

topic_router = APIRouter(prefix="/api/topic", tags=["Topic Reports"])

class TopicGenerateRequest(BaseModel):
    """보고서 생성 요청 DTO."""
    topic: str

class TopicRefineRequest(BaseModel):
    """보고서 보정 요청 DTO."""
    feedback: dict
    max_iterations: int = 3
    target_score: int = 90

class TopicReportItemResponse(BaseModel):
    """보고서 목록 항목 DTO."""
    id: str
    title: str
    topic: str
    original_filename: str
    file_size: int
    modified_time: float
    status: str
    ingested_at: str
    is_synthesized: bool = True

class AsyncTaskResponse(BaseModel):
    """비동기 작업 등록 응답 DTO."""
    task_id: str
    message: str

_generator_cache: Optional[TopicReportGenerator] = None
_reviewer_cache: Optional[ReportReviewAgent] = None
_exporter_cache: Optional[HtmlDocExporter] = None

def get_generator(settings: Settings = Depends(get_settings)) -> TopicReportGenerator:
    """TopicReportGenerator 의존성 주입 프로바이더 (설정 변경 대응)."""
    global _generator_cache
    expected_reports_dir = settings.wiki_db_dir / "reports"
    if _generator_cache is None or _generator_cache.reports_dir.resolve() != expected_reports_dir.resolve():
        _generator_cache = TopicReportGenerator(reports_dir=expected_reports_dir)
    return _generator_cache

def get_reviewer() -> ReportReviewAgent:
    """ReportReviewAgent 의존성 주입 프로바이더."""
    global _reviewer_cache
    if _reviewer_cache is None:
        _reviewer_cache = ReportReviewAgent()
    return _reviewer_cache

def get_html_doc_exporter(settings: Settings = Depends(get_settings)) -> HtmlDocExporter:
    """HtmlDocExporter 의존성 주입 프로바이더 (설정 변경 대응)."""
    global _exporter_cache
    if _exporter_cache is None or _exporter_cache.assets_dir.resolve() != settings.assets_dir.resolve():
        _exporter_cache = HtmlDocExporter(assets_dir=settings.assets_dir)
    return _exporter_cache

@topic_router.post("/generate")
def generate_topic_report(
    req: TopicGenerateRequest,
    settings: Settings = Depends(get_settings),
    generator: TopicReportGenerator = Depends(get_generator)
):
    """주제를 입력받아 관련 마크다운 섹션과 이미지를 검색하고 Gemini LLM 보고서를 생성 및 저장한다."""
    topic = req.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="주제어를 1글자 이상 입력해 주십시오.")

    try:
        result = generator.generate_report(topic=topic, docs_dir=settings.docs_dir)
        return result
    except ValueError as e:
        # API 키 누락 등 설정 오류
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        # LLM 호출 실패 또는 검색 결과 없음
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception(f"보고서 생성 중 예기치 못한 오류 발생: {e}")
        raise HTTPException(status_code=500, detail=f"보고서 생성 중 오류가 발생했습니다: {str(e)}")

@topic_router.post("/generate/async", response_model=AsyncTaskResponse)
def generate_topic_report_async(
    req: TopicGenerateRequest,
    settings: Settings = Depends(get_settings),
    generator: TopicReportGenerator = Depends(get_generator),
    task_manager: TaskManager = Depends(get_task_manager)
):
    """주제를 입력받아 백그라운드 스레드에서 보고서 생성 및 무결성 조립을 비동기로 실행한다."""
    topic = req.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="주제어를 1글자 이상 입력해 주십시오.")

    task_id = task_manager.create_task("topic_generate")
    docs_dir = settings.docs_dir

    def _worker():
        task_manager.update_task(task_id, 20, f"'{topic}' 관련 지식 및 시각 도표 탐색 중...")
        result = generator.generate_report(topic=topic, docs_dir=docs_dir)
        task_manager.update_task(task_id, 95, "보고서 무결성 치유 및 최종 저장 완료...")
        return result

    task_manager.submit_task(task_id, _worker)
    return AsyncTaskResponse(task_id=task_id, message="보고서 생성이 비동기 작업으로 시작되었습니다.")

@topic_router.get("/tasks/{task_id}", response_model=AgentTask)
def get_task_status_endpoint(
    task_id: str,
    task_manager: TaskManager = Depends(get_task_manager)
):
    """비동기 에이전트 작업의 진행률(0~100%), 상태(PENDING/RUNNING/COMPLETED/FAILED) 및 결과 데이터를 조회한다."""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="해당 작업을 찾을 수 없습니다.")
    return task

@topic_router.get("/suggestions")
async def get_topic_suggestions(settings: Settings = Depends(get_settings)):
    """WikiDB에 존재하는 문서 제목과 엔티티를 바탕으로 상위 추천 검색어 목록을 반환한다."""
    suggestions = []
    seen = set()

    # 대표적인 핵심 기술 키워드 우선 배치
    curated = ["칩렛", "인공지능 반도체", "전고체 배터리", "이차전지 양극재", "SoC", "자율주행 센서", "양자 컴퓨팅", "생성형 AI"]
    for c in curated:
        seen.add(c)
        suggestions.append(c)

    # WikiDB/docs 내 파일명에서 추가 키워드 추출
    if settings.docs_dir.exists():
        for md_file in settings.docs_dir.glob("*.md"):
            name = md_file.stem
            # 특수문자 및 접두사 정리
            clean = re.sub(r'^(통합_|플러스_|[0-9_A-Z]+_)', '', name)
            clean = re.sub(r'_\d+_[a-f0-9]+$', '', clean)
            parts = [p.strip() for p in re.split(r'[_()]+', clean) if len(p.strip()) >= 2 and not p.strip().isdigit()]
            for p in parts:
                if p not in seen and len(suggestions) < 15:
                    seen.add(p)
                    suggestions.append(p)

    return {"suggestions": suggestions}

@topic_router.get("/reports", response_model=list[TopicReportItemResponse])
async def list_topic_reports(generator: TopicReportGenerator = Depends(get_generator)):
    """생성되어 저장된 AI 보고서 목록을 최신순으로 반환한다."""
    reports = generator.get_all_reports()
    return reports

@topic_router.get("/reports/{report_id}")
async def get_topic_report_detail(
    report_id: str,
    generator: TopicReportGenerator = Depends(get_generator)
):
    """특정 AI 생성 보고서의 상세 메타데이터와 마크다운 본문을 반환한다."""
    report = generator.get_report_detail(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="해당 생성 보고서를 찾을 수 없습니다.")
    return report

@topic_router.delete("/reports/{report_id}")
async def delete_topic_report_endpoint(
    report_id: str,
    generator: TopicReportGenerator = Depends(get_generator)
):
    """특정 AI 생성 보고서를 삭제한다."""
    success = generator.delete_report(report_id)
    if not success:
        raise HTTPException(status_code=404, detail="해당 생성 보고서를 찾을 수 없습니다.")
    return {"message": "보고서가 성공적으로 삭제되었습니다.", "deleted_id": report_id}

@topic_router.post("/reports/{report_id}/review")
def review_topic_report_endpoint(
    report_id: str,
    deep_audit: bool = False,
    settings: Settings = Depends(get_settings),
    generator: TopicReportGenerator = Depends(get_generator),
    reviewer: ReportReviewAgent = Depends(get_reviewer)
):
    """특정 AI 생성 보고서의 품질 및 정합성을 5대 기준 및 최신 지식DB 동기화 상태에 따라 검수하고 결과를 반환한다."""
    logger.info(f"[검수 시작] 보고서 ID: {report_id}, deep_audit: {deep_audit}")
    report = generator.get_report_detail(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="해당 생성 보고서를 찾을 수 없습니다.")

    # 보고서 작성/수정 시점 이후 WikiDB에 신규 등재되었거나 본문에 미반영된 관련 문서 탐색
    topic = report.get("topic")
    if not topic or topic == report_id:
        title = report.get("title", "")
        clean_title = re.sub(r'^(?:\[.*?\]\s*|\(.*?\)\s*|AI\s*보고서\s*|종합\s*기술\s*및\s*시장\s*분석\s*보고서\s*)+', '', title).strip()
        topic = clean_title or re.sub(r'^(?:REPORT_)?(.*?)(?:_\d+)?$', r'\1', report_id)
    current_md = report["content"]
    report_mtime = report.get("modified_time", 0.0)
    target_docs_dir = settings.docs_dir

    logger.info(f"[검수 단계 1] 주제어: '{topic}', 신규 지식 탐색 시작...")
    fresh_docs = []
    latest_matched = []
    if target_docs_dir.exists():
        try:
            latest_matched = search_relevant_sections(topic, target_docs_dir, top_k=5)
            logger.info(f"[검수 단계 1 완료] 탐색된 관련 문서: {len(latest_matched)}건")
            for doc in latest_matched:
                is_newer = doc.get("mtime", 0.0) > report_mtime
                is_unseen = doc["doc_id"] not in current_md and doc["title"] not in current_md
                if is_newer or is_unseen:
                    fresh_docs.append({
                        "doc_id": doc["doc_id"],
                        "title": doc["title"],
                        "mtime": doc.get("mtime", 0.0),
                        "sections_count": len(doc.get("sections", []))
                    })
        except Exception as e:
            logger.warning(f"검수 중 신규 지식 탐색 오류: {e}")

    # 탐색된 관련 문서로부터 컨텍스트 문자열 및 유효 이미지 화이트리스트 추출
    context_blocks = []
    valid_image_urls = []
    for doc in latest_matched:
        doc_title = doc.get("title", doc.get("doc_id", "참고 문서"))
        doc_id = doc.get("doc_id", "")
        sec_texts = []
        for sec in doc.get("sections", []):
            heading = getattr(sec, "heading", "") if not isinstance(sec, dict) else sec.get("heading", "")
            text = getattr(sec, "text", "") if not isinstance(sec, dict) else sec.get("text", "")
            images = getattr(sec, "images", []) if not isinstance(sec, dict) else sec.get("images", [])

            if heading and text:
                sec_texts.append(f"### {heading}\n{text}")
            elif text:
                sec_texts.append(text)

            if images:
                for img in images:
                    url = img.get("url") if isinstance(img, dict) else (img if isinstance(img, str) else None)
                    if url and url not in valid_image_urls:
                        valid_image_urls.append(url)

        if sec_texts:
            context_blocks.append(f"## [문서] {doc_title} (ID: {doc_id})\n" + "\n\n".join(sec_texts))
        elif doc.get("content"):
            context_blocks.append(f"## [문서] {doc_title} (ID: {doc_id})\n" + str(doc.get("content"))[:2000])

    context_str = "\n\n---\n\n".join(context_blocks).strip()

    logger.info(f"[검수 단계 2] 룰베이스/LLM 품질 감사 시작 (신규 문서: {len(fresh_docs)}건, deep_audit: {deep_audit})...")
    try:
        review_result = reviewer.review_report(
            report_markdown=current_md,
            topic=topic,
            context=context_str if context_str else None,
            fresh_docs=fresh_docs,
            valid_image_urls=valid_image_urls if valid_image_urls else None,
            deep_audit=deep_audit,
        )
        logger.info(f"[검수 단계 2 완료] 검수 결과 도출 완료")
        return {
            "report_id": report_id,
            "review": review_result,
            "fresh_docs_count": len(fresh_docs),
            "fresh_docs": fresh_docs,
            "deep_audit": deep_audit,
        }
    except Exception as e:
        logger.exception(f"보고서 검수 중 오류 발생: {e}")
        raise HTTPException(status_code=500, detail=f"보고서 검수 중 오류가 발생했습니다: {str(e)}")

@topic_router.post("/reports/{report_id}/refine", response_model=TopicReportItemResponse)
def refine_topic_report_endpoint(
    report_id: str,
    req: TopicRefineRequest,
    settings: Settings = Depends(get_settings),
    generator: TopicReportGenerator = Depends(get_generator),
    reviewer: ReportReviewAgent = Depends(get_reviewer)
):
    """검수 피드백을 기반으로 자율 반추 루프(Self-Reflection Loop)를 통해 보고서를 최적화 갱신하고 결과를 반환한다."""
    existing = generator.get_report_detail(report_id)
    if not existing:
        raise HTTPException(status_code=404, detail="해당 생성 보고서를 찾을 수 없습니다.")

    try:
        generator.refine_report_with_loop(
            report_id=report_id,
            initial_feedback=req.feedback,
            reviewer=reviewer,
            max_iterations=req.max_iterations,
            target_score=req.target_score,
            docs_dir=settings.docs_dir
        )
    except RuntimeError as e:
        logger.exception(f"보고서 보정 실행 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception(f"보고서 보정 중 예기치 못한 오류 발생: {e}")
        raise HTTPException(status_code=500, detail=f"보고서 보정 중 오류가 발생했습니다: {str(e)}")

    updated_detail = generator.get_report_detail(report_id)
    if not updated_detail:
        raise HTTPException(status_code=500, detail="보정된 보고서 메타데이터 조회에 실패했습니다.")
    return updated_detail

@topic_router.post("/reports/{report_id}/refine/async", response_model=AsyncTaskResponse)
def refine_topic_report_async_endpoint(
    report_id: str,
    req: TopicRefineRequest,
    settings: Settings = Depends(get_settings),
    generator: TopicReportGenerator = Depends(get_generator),
    reviewer: ReportReviewAgent = Depends(get_reviewer),
    task_manager: TaskManager = Depends(get_task_manager)
):
    """검수 피드백을 기반으로 자율 반추 루프(Self-Reflection Loop) 보정을 백그라운드에서 비동기로 수행한다."""
    existing = generator.get_report_detail(report_id)
    if not existing:
        raise HTTPException(status_code=404, detail="해당 생성 보고서를 찾을 수 없습니다.")

    task_id = task_manager.create_task("topic_refine")
    docs_dir = settings.docs_dir

    def _worker():
        task_manager.update_task(task_id, 20, "자율 반추 수렴 루프를 가동하여 보정 중...")
        result = generator.refine_report_with_loop(
            report_id=report_id,
            initial_feedback=req.feedback,
            reviewer=reviewer,
            max_iterations=req.max_iterations,
            target_score=req.target_score,
            docs_dir=docs_dir
        )
        task_manager.update_task(task_id, 95, "보고서 보정 최적화 및 저장 완료...")
        return result

    task_manager.submit_task(task_id, _worker)
    return AsyncTaskResponse(task_id=task_id, message="보고서 자율 반추 보정이 비동기 작업으로 시작되었습니다.")

@topic_router.get("/reports/{report_id}/export/html")
def export_topic_report_html(
    report_id: str,
    download: bool = False,
    generator: TopicReportGenerator = Depends(get_generator),
    exporter: HtmlDocExporter = Depends(get_html_doc_exporter)
):
    """특정 AI 생성 보고서를 /html-doc 스킬 규격의 독립 실행형 편집 가능 HTML 문서로 내보낸다."""
    report = generator.get_report_detail(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="해당 생성 보고서를 찾을 수 없습니다.")

    title = report.get("title", f"AI_Report_{report_id}")
    try:
        # 브라우저 직접 보기일 때는 가볍고 빠른 로딩을 위해 서버 상대경로 사용, 파일 다운로드일 때는 Base64 인라인화
        html_content = exporter.export_html(report["content"], title=title, embed_images=download)
    except Exception as e:
        logger.exception(f"HTML 보고서 생성 중 오류 발생: {e}")
        raise HTTPException(status_code=500, detail=f"HTML 보고서 생성 중 오류가 발생했습니다: {str(e)}")

    headers = {"Content-Type": "text/html; charset=utf-8"}
    if download:
        safe_ascii = re.sub(r'[^a-zA-Z0-9_-]', '_', report_id)
        quoted_filename = urllib.parse.quote(f"{report_id}.html")
        headers["Content-Disposition"] = f'attachment; filename="{safe_ascii}.html"; filename*=UTF-8\'\'{quoted_filename}'

    return Response(content=html_content, media_type="text/html", headers=headers)

@topic_router.get("/reports/{report_id}/export/pdf")
def export_topic_report_pdf(
    report_id: str,
    generator: TopicReportGenerator = Depends(get_generator),
    exporter: HtmlDocExporter = Depends(get_html_doc_exporter)
):
    """특정 AI 생성 보고서를 pymupdf.Story 엔진 기반의 A4 규격 PDF 바이너리로 변환하여 다운로드한다."""
    report = generator.get_report_detail(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="해당 생성 보고서를 찾을 수 없습니다.")

    title = report.get("title", f"AI_Report_{report_id}")
    try:
        pdf_bytes = exporter.export_pdf(report["content"], title=title)
    except Exception as e:
        logger.exception(f"PDF 생성 중 오류 발생: {e}")
        raise HTTPException(status_code=500, detail=f"PDF 생성 중 오류가 발생했습니다: {str(e)}")

    safe_ascii = re.sub(r'[^a-zA-Z0-9_-]', '_', report_id)
    quoted_filename = urllib.parse.quote(f"{report_id}.pdf")
    headers = {
        "Content-Disposition": f'attachment; filename="{safe_ascii}.pdf"; filename*=UTF-8\'\'{quoted_filename}',
        "Content-Length": str(len(pdf_bytes)),
    }
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


