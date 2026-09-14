"""주제 기반 보고서 생성, 추천 키워드 및 생성 이력 관리를 위한 FastAPI 라우터 모듈."""

import logging
import re
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.topic_generator import TopicReportGenerator

logger = logging.getLogger("TopicRouter")

topic_router = APIRouter(prefix="/api/topic", tags=["Topic Reports"])

class TopicGenerateRequest(BaseModel):
    """보고서 생성 요청 DTO."""
    topic: str

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

def get_generator(settings: Settings = Depends(get_settings)) -> TopicReportGenerator:
    """TopicReportGenerator 의존성 주입 프로바이더 (매 요청 재생성 방지)."""
    global _generator_cache
    if _generator_cache is None:
        reports_dir = settings.wiki_db_dir / "reports"
        _generator_cache = TopicReportGenerator(reports_dir=reports_dir)
    return _generator_cache

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
