"""주제 기반 보고서 생성, 추천 키워드 및 생성 이력 관리를 위한 FastAPI 라우터 모듈."""

import logging
import re
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.topic_generator import TopicReportGenerator
from app.report_reviewer import ReportReviewAgent

logger = logging.getLogger("TopicRouter")

topic_router = APIRouter(prefix="/api/topic", tags=["Topic Reports"])

class TopicGenerateRequest(BaseModel):
    """보고서 생성 요청 DTO."""
    topic: str

class TopicRefineRequest(BaseModel):
    """보고서 보정 요청 DTO."""
    feedback: dict

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

_generator_cache: Optional[TopicReportGenerator] = None
_reviewer_cache: Optional[ReportReviewAgent] = None

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

@topic_router.post("/generate")
async def generate_topic_report(
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
async def review_topic_report_endpoint(
    report_id: str,
    generator: TopicReportGenerator = Depends(get_generator),
    reviewer: ReportReviewAgent = Depends(get_reviewer)
):
    """특정 AI 생성 보고서의 품질 및 정합성을 5대 기준에 따라 검수하고 결과를 반환한다."""
    report = generator.get_report_detail(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="해당 생성 보고서를 찾을 수 없습니다.")

    try:
        review_result = reviewer.review_report(
            report_markdown=report["content"],
            topic=report.get("topic", report_id)
        )
        return {"report_id": report_id, "review": review_result}
    except Exception as e:
        logger.exception(f"보고서 검수 중 오류 발생: {e}")
        raise HTTPException(status_code=500, detail=f"보고서 검수 중 오류가 발생했습니다: {str(e)}")

@topic_router.post("/reports/{report_id}/refine", response_model=TopicReportItemResponse)
async def refine_topic_report_endpoint(
    report_id: str,
    req: TopicRefineRequest,
    generator: TopicReportGenerator = Depends(get_generator)
):
    """검수 피드백을 기반으로 보고서를 보정하여 갱신하고 결과를 반환한다."""
    existing = generator.get_report_detail(report_id)
    if not existing:
        raise HTTPException(status_code=404, detail="해당 생성 보고서를 찾을 수 없습니다.")

    try:
        generator.refine_report(report_id=report_id, feedback=req.feedback)
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


