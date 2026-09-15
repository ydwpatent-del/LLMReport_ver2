"""AI 생성 보고서 품질 검수 및 사실 정합성 평가 에이전트 모듈."""

import json
import logging
import os
import re
from typing import Optional
from google import genai

logger = logging.getLogger("ReportReviewAgent")


class ReportReviewAgent:
    """5대 핵심 기준(목차, 3대 표, 정량 데이터, 이미지, 전문 어조)을 감수하는 평가 에이전트."""

    def __init__(self, api_key: Optional[str] = None):
        """ReportReviewAgent 초기화.

        Args:
            api_key: Gemini API 키. 전달되지 않으면 환경 변수에서 탐색.
        """
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

    def _rule_based_audit(self, md: str) -> tuple[dict, list[str], list[str]]:
        """정규식 및 휴리스틱 기반 초고속 룰베이스 품질 검수.

        Args:
            md: 검수할 보고서 마크다운 텍스트

        Returns:
            checklist: 5대 기준 충족 여부 딕셔너리
            defects: 발견된 결함 목록
            suggestions: 개선 권고사항 목록
        """
        checklist = {
            "structure_valid": False,
            "tables_valid": False,
            "quantitative_data_valid": False,
            "images_valid": False,
            "tone_valid": True,
        }
        defects = []
        suggestions = []

        # 1. 5대 목차 준수도 점검
        required_headers = [
            r"##\s*1\.\s*기술\s*개요",
            r"##\s*2\.\s*기술\s*동향",
            r"##\s*3\.\s*시장\s*동향",
            r"##\s*4\.\s*주요\s*업체",
            r"##\s*5\.\s*데이터\s*출처",
        ]
        missing_headers = []
        for pat in required_headers:
            if not re.search(pat, md):
                missing_headers.append(pat.replace(r"\s*", " ").replace(r"##", "## "))

        if not missing_headers:
            checklist["structure_valid"] = True
        else:
            defects.append(f"5대 표준 목차 중 누락된 섹션이 있습니다: {', '.join(missing_headers)}")
            suggestions.append("5대 표준 목차(1.기술개요~5.데이터출처)를 빠짐없이 구성하십시오.")

        # 2. 3대 필수 표 구비 점검
        table_matches = re.findall(r"\|[^\n]+\|\s*\n\s*\|[\s\-:|]+\|", md)
        if len(table_matches) >= 3:
            checklist["tables_valid"] = True
        else:
            defects.append(
                f"필수 비교 표(기술 비교표, 시장 전망표, 기업 비교표) 중 일부가 누락되었습니다 (현재 {len(table_matches)}개 발견, 최소 3개 필요)."
            )
            suggestions.append(
                "2장(기술 비교 요약 표), 3장(시장 규모 및 전망 표), 4장(주요 기업 비교 표)을 마크다운 표로 작성하십시오."
            )

        # 3. 정량 데이터 충실도 점검
        has_numbers = re.search(r"\b(202[0-9]|203[0-9])년", md) and re.search(
            r"(\d+(?:\.\d+)?\s*(?:억\s*원|억\s*달러|조\s*원|%|CAGR|nm|Gbps|W))", md, re.IGNORECASE
        )
        if has_numbers:
            checklist["quantitative_data_valid"] = True
        else:
            defects.append("시장 규모, 연도별 추이 수치 또는 핵심 기술 규격 데이터가 부족합니다.")
            suggestions.append("구체적인 연도, 금액 단위(억 원/달러), CAGR %, 규격 수치를 본문과 표에 명시하십시오.")

        # 4. 시각 자산 결합 점검
        has_images = bool(re.search(r"!\[.*?\]\(.*?\)", md))
        if has_images:
            checklist["images_valid"] = True
        else:
            defects.append("인라인 도표 또는 아키텍처 다이어그램 이미지가 배치되지 않았습니다.")
            suggestions.append("컨텍스트에서 제공된 유의미한 차트 및 구조도 이미지를 단독 행으로 결합하십시오.")

        # 5. 전문 어조 및 AI 상투어 배제 점검
        greetings = ["안녕하세요", "작성해 드립니다", "보고서를 작성합니다", "도움이 되길", "이상으로 보고서를"]
        found_greetings = [g for g in greetings if g in md]
        if found_greetings:
            checklist["tone_valid"] = False
            defects.append(f"보고서에 불필요한 AI 인사말 또는 안내 문구가 포함되어 있습니다: {', '.join(found_greetings)}")
            suggestions.append("서두/말미의 인사말과 메타 발언을 모두 삭제하고 순수한 보고서 본문만 기술하십시오.")

        return checklist, defects, suggestions

    def review_report(
        self, report_markdown: str, topic: str, context: Optional[str] = None
    ) -> dict:
        """보고서 본문을 검수하여 체크리스트, 결함 목록, 개선 제안을 반환한다.

        Args:
            report_markdown: 검수할 보고서 마크다운 문자열
            topic: 보고서의 주제어
            context: 검색 컨텍스트 (선택 사항)

        Returns:
            dict: passed_all, checklist, defects, actionable_suggestions 포함 결과
        """
        checklist, defects, suggestions = self._rule_based_audit(report_markdown)
        passed_all = all(checklist.values()) and len(defects) == 0

        return {
            "passed_all": passed_all,
            "checklist": checklist,
            "defects": defects,
            "actionable_suggestions": suggestions,
        }
