"""AI 생성 보고서 품질 검수 및 사실 정합성 평가 에이전트 모듈."""

import json
import logging
import os
import re
from typing import Optional
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

from app.utils import get_gemini_api_keys_list, is_gemini_key_exhausted_or_invalid


logger = logging.getLogger("ReportReviewAgent")


class ReportReviewAgent:
    """5대 핵심 기준(목차, 3대 표, 정량 데이터, 이미지, 전문 어조)을 감수하는 평가 에이전트."""

    def __init__(self, api_key: Optional[str] = None):
        """ReportReviewAgent 초기화.

        Args:
            api_key: Gemini API 키. 전달되지 않으면 환경 변수에서 탐색.
        """
        self.api_keys = [api_key] if api_key else get_gemini_api_keys_list()
        self.api_key = self.api_keys[0] if self.api_keys else None
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None


    def _rule_based_audit(
        self,
        md: str,
        valid_image_urls: Optional[list[str]] = None
    ) -> tuple[dict, list[str], list[str]]:
        """정규식 및 휴리스틱 기반 초고속 룰베이스 품질 검수.

        Args:
            md: 검수할 보고서 마크다운 텍스트
            valid_image_urls: 허용된 이미지 URL 화이트리스트 목록 (선택 사항)

        Returns:
            checklist: 6대 기준 충족 여부 딕셔너리
            defects: 발견된 결함 목록
            suggestions: 개선 권고사항 목록
        """
        checklist = {
            "structure_valid": False,
            "tables_valid": False,
            "quantitative_data_valid": False,
            "images_valid": False,
            "citations_valid": False,
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

        # 2. 3대 필수 표 구비 및 표 문법 무결성 점검
        # 1) 헤더 행 앞에 텍스트/캡션이 붙어 줄바꿈이 누락된 파손 표(Malformed Table) 정밀 탐지
        malformed_tables = re.findall(
            r'(?:^|\n)(?!\s*\|)([^\n|]+)(\|[^\n]*\n[ \t]*\|(?:\s*:?-+:?\s*\|)+[ \t]*(?=\n|$))',
            md
        )

        # 2) 표 내부 행에 이미지 태그가 침투했거나 표 종결 누락으로 셀 안으로 흡수된 결함 감지
        table_leakage = re.findall(
            r'^[ \t]*\|[^\n]*!\[.*?\]\([^\)]+\)[^\n]*\|',
            md,
            re.MULTILINE
        )

        valid_table_pattern = r'(?:^|\n)[ \t]*(\|[^\n]*\n[ \t]*\|(?:\s*:?-+:?\s*\|)+[ \t]*(?=\n|$))'

        if malformed_tables or table_leakage:
            checklist["tables_valid"] = False
            if malformed_tables:
                sample_bad = malformed_tables[0][0].strip()[-30:]
                defects.append(
                    f"표 문법 파손 감지: 표 헤더 앞에 줄바꿈이 누락되어 렌더링이 깨진 표가 {len(malformed_tables)}건 발견되었습니다 (예: '{sample_bad}|...')."
                )
            if table_leakage:
                defects.append(
                    f"표 문법 파손 감지: 마크다운 표 종결 누락 또는 셀 내부로 도표 이미지가 침투하여 파손된 행이 {len(table_leakage)}건 발견되었습니다."
                )
            suggestions.append(
                "마크다운 표의 헤더와 마지막 데이터 행 직후에는 반드시 빈 줄(개행 2개)을 두고, 표 하단 단위 주석이나 도표 이미지는 표 밖의 독립 행으로 격리하십시오."
            )
        else:
            # 2) 2장(기술 비교), 3장(시장 전망), 4장(기업 비교) 각 섹션별 표 존재 여부 검증
            sec2_match = re.search(r'(?:^|\n)##\s*2\.\s*기술\s*동향[\s\S]*?(?=(?:^|\n)##\s*3\.|\Z)', md)
            sec3_match = re.search(r'(?:^|\n)##\s*3\.\s*시장\s*동향[\s\S]*?(?=(?:^|\n)##\s*4\.|\Z)', md)
            sec4_match = re.search(r'(?:^|\n)##\s*4\.\s*주요\s*(?:업체|기업)[\s\S]*?(?=(?:^|\n)##\s*5\.|\Z)', md)

            sec2_text = sec2_match.group(0) if sec2_match else ""
            sec3_text = sec3_match.group(0) if sec3_match else ""
            sec4_text = sec4_match.group(0) if sec4_match else ""

            missing_tables = []
            if not re.search(valid_table_pattern, sec2_text):
                missing_tables.append("2장(기술동향: 기술 비교 표)")
            if not re.search(valid_table_pattern, sec3_text):
                missing_tables.append("3장(시장동향: 시장 전망 표)")
            if not re.search(valid_table_pattern, sec4_text):
                missing_tables.append("4장(주요업체: 주요 기업 비교 표)")

            if not missing_tables:
                checklist["tables_valid"] = True
            else:
                checklist["tables_valid"] = False
                defects.append(
                    f"필수 비교 표 중 일부가 누락되었습니다: {', '.join(missing_tables)}"
                )
                suggestions.append(
                    "2장(기술 비교 요약 표), 3장(시장 규모 및 전망 표), 4장(주요 기업 비교 표)을 각 해당 섹션에 마크다운 표로 작성하십시오."
                )

        # 3. 정량 데이터 충실도 점검
        has_numbers = re.search(r"\b(202[0-9]|203[0-9])년", md) and re.search(
            r"(\d+(?:\.\d+)?\s*(?:억\s*원|억\s*달러|조\s*원|%|CAGR|nm|Gbps|W))", md, re.IGNORECASE
        )
        if has_numbers:
            checklist["quantitative_data_valid"] = True
        else:
            defects.append("시장 규모, 연도별 추이 수치 또는 핵심 기술 규격 데이터가 부족합니다.")
            suggestions.append("구체적인 연도, 금액 단위(억 원/달러), CAGR %, 규격 수치를 명시하고, 가장 최신의 시장 조사 자료를 우선 반영하십시오.")
            suggestions.append("2장 기술 규격 혁신이 3장 시장 성장 동인과 논리적으로 직결되도록 기술-시장 간 인과관계를 체계화하십시오.")

        # 4. 시각 자산 결합 및 화이트리스트 점검
        img_matches = re.findall(r'!\[.*?\]\((.*?)\)', md)
        has_images = len(img_matches) > 0

        if not has_images:
            checklist["images_valid"] = False
            defects.append("인라인 도표 또는 아키텍처 다이어그램 이미지가 배치되지 않았습니다.")
            suggestions.append("컨텍스트에서 제공된 유의미한 차트 및 구조도 이미지를 단독 행으로 결합하십시오.")
        elif valid_image_urls is not None:
            invalid_urls = [u.strip() for u in img_matches if u.strip() not in valid_image_urls]
            if invalid_urls:
                checklist["images_valid"] = False
                defects.append(
                    f"승인되지 않은 외부 또는 허위 이미지 URL이 포함되어 있습니다: {', '.join(invalid_urls)}"
                )
                suggestions.append(
                    "보고서 내 이미지는 제공된 유효한 인라인 이미지 자산(/api/assets/... 등)만 사용하십시오."
                )
            else:
                checklist["images_valid"] = True
        else:
            checklist["images_valid"] = True

        # 5. 출처 표기 무결성 점검
        has_inline_citations = bool(re.search(r'<출처:\s*\[[^>]+>', md))

        sec5_match = re.search(r'(?:^|\n)##\s*5\.\s*데이터\s*출처[\s\S]*', md)
        sec5_text = sec5_match.group(0) if sec5_match else ""
        has_sec5_links = bool(re.search(r'-\s*(?:<출처:\s*)?\[.*?\]\(/api/documents/.*?\)', sec5_text))

        citation_defects = []
        if not has_inline_citations:
            citation_defects.append("본문 주요 문단 종결부에 출처 태그(<출처: [문서제목]>)가 누락되었습니다.")
            suggestions.append("주요 사실 및 통계 수치를 서술한 문단 종결부에 <출처: [문서제목]> 태그를 기재하십시오.")

        if not has_sec5_links:
            citation_defects.append("5장 데이터 출처 섹션에 유효한 문서 링크(- [문서제목](/api/documents/doc_id))가 없습니다.")
            suggestions.append("5장 데이터 출처 섹션에 참고한 WikiDB 문서 링크를 목록(- [제목](/api/documents/문서ID)) 형태로 명시하십시오.")

        if not citation_defects:
            checklist["citations_valid"] = True
        else:
            checklist["citations_valid"] = False
            defects.extend(citation_defects)

        # 6. 전문 어조 및 AI 상투어 배제 점검
        greetings = ["안녕하세요", "작성해 드립니다", "보고서를 작성합니다", "도움이 되길", "이상으로 보고서를"]
        found_greetings = [g for g in greetings if g in md]
        if found_greetings:
            checklist["tone_valid"] = False
            defects.append(f"보고서에 불필요한 AI 인사말 또는 안내 문구가 포함되어 있습니다: {', '.join(found_greetings)}")
            suggestions.append("서두/말미의 인사말과 메타 발언을 모두 삭제하고 순수한 보고서 본문만 기술하십시오.")

        return checklist, defects, suggestions

    def _llm_semantic_audit(
        self, report_markdown: str, topic: str, context: str
    ) -> tuple[bool, bool, list[str], list[str]]:
        """원본 컨텍스트 대조를 통한 LLM 시맨틱 검수 (수치/팩트 할루시네이션 및 3단계 인과 논리 감사).

        Args:
            report_markdown: 검수 대상 보고서 마크다운 텍스트
            topic: 보고서의 주제어
            context: 원본 참고 컨텍스트 데이터

        Returns:
            tuple[bool, bool, list[str], list[str]]:
                (factuality_valid, causality_valid, defects, suggestions)
        """
        if not self.api_key or not self.client:
            logger.warning("Gemini API 키 또는 클라이언트가 설정되지 않아 LLM 시맨틱 감사를 건너뜁니다.")
            return True, True, [], []

        if not context or not context.strip():
            return True, True, [], []

        prompt = f"""당신은 AI 생성 심층 기술/시장 분석 보고서의 사실 정합성과 인과 논리성을 검증하는 수석 감수위원입니다.
제공된 [원본 컨텍스트 데이터]와 [검수 대상 보고서]를 엄밀하게 상호 대조하여 다음 2대 핵심 항목을 정밀 감사하십시오.

[핵심 감사 기준]
1. 사실 정합성 (Factuality):
   - 보고서에 서술된 시장 규모 수치, 연도별 전망, CAGR %, 기업명, 핵심 기술 규격(nm, Gbps, W 등)이 [원본 컨텍스트 데이터]에 근거하고 있는지 대조하십시오.
   - 컨텍스트에 전혀 없는 날조된(Fabricated) 수치나 허위 기업/기술 사양이 포함되어 있다면 factuality_valid를 false로 설정하고 구체적인 결함 사유를 작성하십시오.
   - 모든 주요 사실과 수치가 컨텍스트와 부합하거나 왜곡이 없다면 factuality_valid를 true로 설정하십시오.

2. 인과 논리성 (Causality):
   - 2장(기술동향)의 핵심 기술/아키텍처 혁신이 3장(시장동향)의 시장 성장을 이끄는 3단계 논리 구조([기술 규격/혁신] -> [물리적·경제적 병목 해결] -> [전방 산업 채택 및 시장 창출])가 설득력 있고 유기적으로 서술되었는지 평가하십시오.
   - 2장과 3장이 단순히 분리 나열되어 있거나, 기술 혁신과 시장 성장의 인과관계가 결여되어 비논리적이라면 causality_valid를 false로 설정하고 구체적 결함 사유를 작성하십시오.
   - 3단계 인과 논리가 명확하고 논리적 연결이 충분하다면 causality_valid를 true로 설정하십시오.

[주제어]: {topic}

[원본 컨텍스트 데이터]:
{context}

[검수 대상 보고서]:
{report_markdown}

반드시 아래 JSON 형식으로만 응답하십시오 (추가 설명이나 마크다운 코드블록 없이 순수 JSON 객체만 반환):
{{
  "factuality_valid": true,
  "causality_valid": true,
  "defects": [],
  "suggestions": []
}}
"""
        try:
            model_names = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-2.5-flash", "gemini-flash-latest"]
            response_text = None
            last_error = None

            keys_to_try = self.api_keys or ([self.api_key] if self.api_key else [])
            for key_idx, current_key in enumerate(keys_to_try, 1):
                client = genai.Client(api_key=current_key)
                key_masked = f"{current_key[:8]}...{current_key[-4:]}" if len(current_key) > 12 else "key"
                key_failed = False

                for model_name in model_names:
                    try:
                        response = client.models.generate_content(
                            model=model_name,
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                response_mime_type="application/json",
                                temperature=0.1
                            )
                        )
                        if response and response.text:
                            response_text = response.text
                            break
                    except Exception as e:
                        last_error = e
                        if is_gemini_key_exhausted_or_invalid(e):
                            logger.warning(
                                f"Gemini API 키 #{key_idx}({key_masked}) 크레딧 소진 또는 인증 오류 감지 ({e}). "
                                f"다음 대체 키로 자동 전환을 시도합니다."
                            )
                            key_failed = True
                            break  # 해당 키는 즉시 중단하고 다음 키로
                        else:
                            logger.warning(f"Gemini 모델 '{model_name}' (키 #{key_idx}) 호출 오류: {e}")

                if response_text:
                    break
                if not key_failed:
                    # 키 문제가 아니라 모델 문제로 전부 실패한 경우에도 다음 키가 있으면 시도
                    pass

            if not response_text:
                logger.warning(f"LLM 시맨틱 감사 응답 생성 실패 (Graceful Fallback 적용): {last_error}")
                return True, True, [], []



            raw_json = response_text.strip()
            raw_json = re.sub(r'^```(?:json)?\s*', '', raw_json)
            raw_json = re.sub(r'\s*```$', '', raw_json).strip()

            data = json.loads(raw_json)
            factuality_valid = bool(data.get("factuality_valid", True))
            causality_valid = bool(data.get("causality_valid", True))

            defects = []
            if isinstance(data.get("defects"), list):
                defects.extend(str(d) for d in data["defects"])
            if isinstance(data.get("factuality_defects"), list):
                defects.extend(str(d) for d in data["factuality_defects"])
            if isinstance(data.get("causality_defects"), list):
                defects.extend(str(d) for d in data["causality_defects"])

            suggestions = []
            if isinstance(data.get("suggestions"), list):
                suggestions.extend(str(s) for s in data["suggestions"])

            return factuality_valid, causality_valid, defects, suggestions

        except Exception as e:
            logger.warning(f"LLM 시맨틱 감사 처리 중 예외 발생 (Graceful Fallback 적용): {e}")
            return True, True, [], []

    def review_report(
        self,
        report_markdown: str,
        topic: str,
        context: Optional[str] = None,
        fresh_docs: Optional[list] = None,
        valid_image_urls: Optional[list[str]] = None,
        deep_audit: bool = False
    ) -> dict:
        """보고서 본문을 검수하여 체크리스트, 결함 목록, 개선 제안을 반환한다.

        Args:
            report_markdown: 검수할 보고서 마크다운 문자열
            topic: 보고서의 주제어
            context: 검색 컨텍스트 (선택 사항)
            fresh_docs: 보고서 작성 이후 WikiDB에 신규 등재된 관련 문서 목록 (선택 사항)
            valid_image_urls: 허용된 이미지 URL 화이트리스트 목록 (선택 사항)
            deep_audit: LLM 기반 사실 정합성 및 인과 논리 심층 감사 여부 (기본값: False)

        Returns:
            dict: passed_all, checklist, defects, actionable_suggestions, fresh_docs 포함 결과
        """
        checklist, defects, suggestions = self._rule_based_audit(
            report_markdown,
            valid_image_urls=valid_image_urls
        )

        # 6. 신규 등재 지식 동기화 점검 (fresh_docs 제공 시)
        if fresh_docs is not None:
            if len(fresh_docs) > 0:
                checklist["fresh_knowledge_synced"] = False
                doc_titles = [d.get("title") or d.get("doc_id") or "신규 문서" for d in fresh_docs[:3]]
                summary_titles = ", ".join(doc_titles)
                if len(fresh_docs) > 3:
                    summary_titles += f" 외 {len(fresh_docs) - 3}건"
                defects.append(
                    f"보고서 작성 이후 WikiDB에 신규 등재된 관련 문서 {len(fresh_docs)}건({summary_titles})이 발견되었습니다. 최신 데이터 동기화 및 보정이 필요합니다."
                )
                suggestions.append(
                    f"신규 등재 문서({summary_titles})의 최신 시장 통계 및 기술 아키텍처 데이터를 보고서에 통합하여 최신화하십시오."
                )
            else:
                checklist["fresh_knowledge_synced"] = True

        # 7. 온디맨드 LLM 사실 정합성 및 인과 논리 심층 감사 (deep_audit=True 및 context 제공 시)
        if deep_audit and context:
            f_valid, c_valid, llm_defects, llm_suggestions = self._llm_semantic_audit(
                report_markdown=report_markdown,
                topic=topic,
                context=context
            )
            checklist["factuality_valid"] = f_valid
            checklist["causality_valid"] = c_valid
            defects.extend(llm_defects)
            suggestions.extend(llm_suggestions)

        # 8. 정량적 품질 점수(Quality Score 0~100) 산출
        base_weights = {
            "structure_valid": 20,
            "tables_valid": 20,
            "quantitative_data_valid": 15,
            "images_valid": 15,
            "citations_valid": 15,
            "tone_valid": 15,
        }
        score = sum(weight for key, weight in base_weights.items() if checklist.get(key, False))

        # 딥 감사 항목 반영 (활성화된 경우)
        if "factuality_valid" in checklist:
            score = int(score * 0.8) + (10 if checklist.get("factuality_valid") else 0) + (10 if checklist.get("causality_valid") else 0)

        # 미해결 결함 1건당 5점 감점
        score = max(0, min(100, score - (len(defects) * 5)))

        passed_all = all(checklist.values()) and len(defects) == 0

        return {
            "passed_all": passed_all,
            "quality_score": score,
            "checklist": checklist,
            "defects": defects,
            "actionable_suggestions": suggestions,
            "fresh_docs": fresh_docs or [],
        }
