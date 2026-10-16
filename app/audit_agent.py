"""kordoc-wiki-ingest 스킬 규격 기반 원문 대조 AI 검수 및 외과적 자율 보정(Audit & Surgical Self-Healing) 모듈."""

import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pymupdf

from app.utils import (
    generate_toc_and_anchors,
    run_kordoc_lint,
    validate_red_flags,
    clean_markdown_typography,
)

logger = logging.getLogger("AuditAgent")


# ============================================================================
# 1. 데이터 모델 및 이슈 구조화
# ============================================================================

@dataclass
class AuditIssue:
    """검수 과정에서 발견된 개별 결함 항목."""
    category: str           # MISSING_TEXT, MISSING_TABLE, MISSING_FORMULA, MISSING_CHART, RED_FLAG
    page_no: Optional[int]  # 1-based 페이지 번호
    description: str        # 이슈 설명
    suspect_content: str    # 누락 의심 원문 단락/키워드
    location_hint: str      # 마크다운 내 삽입 위치 힌트 (섹션 헤딩 등)


@dataclass
class AuditReport:
    """문서 원문 대조 검수 결과 리포트."""
    doc_id: str
    is_healthy: bool
    issues: list[AuditIssue] = field(default_factory=list)
    missing_sections: list[str] = field(default_factory=list)
    missing_tables: list[str] = field(default_factory=list)
    missing_formulas: list[str] = field(default_factory=list)
    missing_charts: list[str] = field(default_factory=list)
    red_flags: list[str] = field(default_factory=list)
    inspected_pages: int = 0
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    )

    def to_dict(self) -> dict:
        """JSON 직렬화 가능한 딕셔너리로 변환."""
        return {
            "doc_id": self.doc_id,
            "is_healthy": self.is_healthy,
            "total_issues": len(self.issues),
            "missing_sections": self.missing_sections,
            "missing_tables": self.missing_tables,
            "missing_formulas": self.missing_formulas,
            "missing_charts": self.missing_charts,
            "red_flags": self.red_flags,
            "inspected_pages": self.inspected_pages,
            "generated_at": self.generated_at,
            "issues": [
                {
                    "category": iss.category,
                    "page_no": iss.page_no,
                    "description": iss.description,
                    "suspect_content": iss.suspect_content[:200],
                    "location_hint": iss.location_hint,
                }
                for iss in self.issues
            ]
        }


# ============================================================================
# 2. 안전장치: 백업 관리자 (BackupManager)
# ============================================================================

class BackupManager:
    """수정 전 자동 스냅샷 백업 및 1초 롤백 지원 관리자."""

    def __init__(self, backup_dir: Optional[Path] = None):
        # backup_dir은 AuditAgent에서 절대 경로로 주입받는다.
        # 직접 생성 시에는 현재 디렉토리 기준 경로를 절대화한다.
        self.backup_dir = (backup_dir or Path("WikiDB/docs/.backup")).resolve()
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(self, doc_file: Path) -> Path:
        """문서 수정 직전 타임스탬프 백업 파일 생성."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{doc_file.stem}_{timestamp}.bak.md"
        backup_path = self.backup_dir / backup_name
        shutil.copy2(doc_file, backup_path)
        logger.info(f"🛡️ 안전 백업 생성 완료: {backup_path.name}")
        return backup_path

    def rollback(self, doc_file: Path, backup_file: Path) -> bool:
        """백업 파일로부터 원본 마크다운 100% 원상 복구."""
        try:
            if backup_file.exists():
                shutil.copy2(backup_file, doc_file)
                logger.info(f"🔄 롤백 복구 완료: {doc_file.name} <- {backup_file.name}")
                return True
        except Exception as e:
            logger.error(f"롤백 복구 실패 ({doc_file.name}): {e}")
        return False

    def find_best_backup(self, doc_file: Path) -> Optional[Path]:
        """특정 문서의 기존 백업 스냅샷 중 가장 본문 용량이 크고 온전한 완본 백업을 탐색한다."""
        if not self.backup_dir.exists():
            return None
        candidates = list(self.backup_dir.glob(f"{doc_file.stem}_*.bak.md"))
        if not candidates:
            return None
        return max(candidates, key=lambda p: (p.stat().st_size, p.stat().st_mtime))


# ============================================================================
# 3. 품질 게이트 (QualityGate)
# ============================================================================

class QualityGate:
    """kordoc-wiki-ingest 규격 준수 여부를 판별하는 품질 검증 게이트."""

    @staticmethod
    def validate(
        markdown_content: str,
        doc_file: Optional[Path] = None,
        require_metadata: bool = False,
    ) -> tuple[bool, list[str]]:
        """Red Flag 및 kordoc lint 규칙 위반 여부를 검증.
        
        require_metadata=False(기본값): 본문 조각 또는 콘텐츠 단위 검증 시 메타데이터 헤더 누락을 허용한다.
        전체 문서 검증 시 require_metadata=True로 호출한다.
        """
        violations = []

        # 1. Red Flag 검사 (~등, ...(중략)... 등 축약/생략 표현 감지)
        red_flags = validate_red_flags(markdown_content, check_metadata=require_metadata)
        if red_flags:
            violations.extend(red_flags)

        # 2. kordoc lint 검사 (파일 경로가 전달된 경우에만 실행)
        if doc_file and doc_file.exists():
            lint_ok, lint_msg = run_kordoc_lint(doc_file)
            if not lint_ok and "오류" in lint_msg:
                violations.append(f"kordoc lint 결함: {lint_msg}")

        return (len(violations) == 0, violations)


# ============================================================================
# 4. 검수 및 자율 보정 에이전트 (AuditAgent)
# ============================================================================

class AuditAgent:
    """원문 대조 검수(Audit) 및 외과적 보정(Heal)을 수행하는 통합 에이전트."""

    def __init__(
        self,
        docs_dir: Optional[Path] = None,
        backup_dir: Optional[Path] = None,
        api_key: Optional[str] = None,
        model_name: str = "gemini-3.8-flash",
    ):

        self.docs_dir = docs_dir or Path("WikiDB/docs")
        # backup_dir 기본값: docs_dir 기반 절대 경로로 결정하여 CWD 의존 제거
        resolved_docs = Path(self.docs_dir).resolve()
        default_backup = resolved_docs / ".backup"
        self.backup_mgr = BackupManager(backup_dir=backup_dir or default_backup)
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.model_name = model_name

    def audit_document(
        self,
        doc_id: str,
        source_path: Path,
        md_path: Path,
        assets_dir: Optional[Path] = None,
    ) -> AuditReport:
        """원문과 변환된 마크다운을 대조하여 누락 항목 리포트를 생성 (Dry-Run)."""
        issues: list[AuditIssue] = []
        missing_sections: list[str] = []
        missing_tables: list[str] = []
        missing_formulas: list[str] = []
        missing_charts: list[str] = []

        if not md_path.exists():
            return AuditReport(doc_id=doc_id, is_healthy=False, red_flags=["마크다운 파일이 존재하지 않음"])

        md_content = md_path.read_text(encoding="utf-8")
        nospace_md_content = re.sub(r'[\s\W_]+', '', md_content)

        # 1. 마크다운 자체 Red Flag 검사
        current_red_flags = validate_red_flags(md_content)

        # 2. 원문이 PDF인 경우 페이지별 정밀 대조
        inspected_pages = 0
        if source_path.exists() and source_path.suffix.lower() == ".pdf":
            try:
                doc = pymupdf.open(str(source_path))
                inspected_pages = len(doc)

                table_keywords = [
                    "후방 산업", "기준 산업", "전방 산업", "촉진 요인", "저해 요인",
                    "구분 | 내용", "주요 지표", "Upstream", "Downstream", "Category",
                    "Supply Chain", "Market Share", "실적 추이"
                ]

                for p_no in range(len(doc)):
                    page = doc[p_no]
                    p_text = page.get_text("text").strip()
                    if not p_text:
                        continue

                    # PyMuPDF 시각적 텍스트 블록 단위 분할 (block_type == 0: 텍스트 블록)
                    # get_text("text")가 빈 줄 없이 단일 스트림으로 반환하는 경우에도
                    # 블록 기반으로 분할하면 각 시각적 단락을 독립적으로 검사할 수 있다.
                    raw_blocks = page.get_text("blocks")
                    paragraphs = []
                    for blk in raw_blocks:
                        if blk[6] != 0:   # 텍스트 블록(0)만 처리, 이미지 블록(1) 제외
                            continue
                        blk_text = blk[4].strip()
                        if not blk_text:
                            continue
                        sub_paras = [p.strip() for p in re.split(r'\n\s*\n', blk_text) if len(p.strip()) >= 10]
                        if sub_paras:
                            paragraphs.extend(sub_paras)
                        elif len(blk_text) >= 10:
                            paragraphs.append(blk_text)

                    for para in paragraphs:
                        words = [w.strip() for w in re.findall(r'[가-힣A-Za-z0-9]{2,}', para)]
                        if len(words) < 3:
                            continue

                        # 마크다운 본문에 해당 단어들이 존재하는지 검사 (공백 누락 텍스트 레이어 정규화 대응)
                        def is_word_in_md(w: str) -> bool:
                            if w in md_content:
                                return True
                            clean_w = re.sub(r'[\s\W_]+', '', w)
                            return bool(clean_w and clean_w in nospace_md_content)

                        missing_words_in_para = [w for w in words if not is_word_in_md(w)]
                        missing_ratio = len(missing_words_in_para) / len(words)

                        # 해당 단락의 단어 중 60% 이상이 마크다운에 전혀 없는 경우 누락으로 감지
                        if missing_ratio >= 0.6 and len(missing_words_in_para) >= 4:
                            is_table_candidate = (
                                any(kw.lower() in para.lower() for kw in table_keywords)
                                or ((":" in para or "|" in para) and len(para.split('\n')) >= 2 and any(hdr in para for hdr in ["구분", "항목", "지표", "수치", "단위", "비중", "Upstream", "Downstream", "Category"]))
                            )
                            first_line = para.split('\n')[0][:40]

                            if is_table_candidate:
                                desc = f"페이지 {p_no + 1} 원본 표/구조화 데이터가 마크다운에서 누락됨 ('{first_line}...')"
                                issue = AuditIssue(
                                    category="MISSING_TABLE",
                                    page_no=p_no + 1,
                                    description=desc,
                                    suspect_content=para[:250],
                                    location_hint=f"p.{p_no + 1} {first_line}",
                                )
                                issues.append(issue)
                                missing_tables.append(f"p.{p_no + 1} ({first_line})")
                            else:
                                desc = f"페이지 {p_no + 1} 원본 텍스트 단락 누락 ('{first_line}...')"
                                issue = AuditIssue(
                                    category="MISSING_TEXT",
                                    page_no=p_no + 1,
                                    description=desc,
                                    suspect_content=para[:300],
                                    location_hint=f"p.{p_no + 1} {first_line}",
                                )
                                issues.append(issue)
                                missing_sections.append(f"p.{p_no + 1} ({first_line})")

                    # 수식(Math) 누락 검사
                    math_symbols = ["∑", "∫", "±", "×", "÷", "√", "∝", "∂"]
                    found_math = [sym for sym in math_symbols if sym in p_text]
                    if found_math and "$" not in md_content:
                        desc = f"페이지 {p_no + 1} 수식 기호({', '.join(found_math)})가 포함되었으나 LaTeX 수식이 누락됨"
                        issue = AuditIssue(
                            category="MISSING_FORMULA",
                            page_no=p_no + 1,
                            description=desc,
                            suspect_content=p_text[:200],
                            location_hint=f"페이지 {p_no + 1} 수식 섹션",
                        )
                        issues.append(issue)
                        missing_formulas.append(f"p.{p_no + 1} 수식")

                doc.close()
            except Exception as e:
                logger.warning(f"PDF 대조 검수 중 오류: {e}")

        # 3. 에셋 이미지 누락 및 Dual-Mode 수치 표 검사
        if assets_dir and assets_dir.exists():
            for img_path in assets_dir.glob("*.png"):
                if "diagram" in img_path.name or "crop" in img_path.name:
                    continue
                if img_path.name not in md_content:
                    desc = f"에셋 이미지 누락: {img_path.name}"
                    issues.append(
                        AuditIssue(
                            category="MISSING_CHART",
                            page_no=None,
                            description=desc,
                            suspect_content=img_path.name,
                            location_hint="관련 설명 본문 아래",
                        )
                    )
                    missing_charts.append(img_path.name)

        is_healthy = (len(issues) == 0 and len(current_red_flags) == 0)

        return AuditReport(
            doc_id=doc_id,
            is_healthy=is_healthy,
            issues=issues,
            missing_sections=missing_sections,
            missing_tables=missing_tables,
            missing_formulas=missing_formulas,
            missing_charts=missing_charts,
            red_flags=current_red_flags,
            inspected_pages=inspected_pages,
        )

    def heal_document(
        self,
        doc_id: str,
        source_path: Path,
        md_path: Path,
        assets_dir: Optional[Path] = None,
        report: Optional[AuditReport] = None,
    ) -> tuple[bool, str, Optional[Path]]:
        """원문 대조 검수 결과 결함을 외과적으로 정밀 보정하고 안전하게 저장."""
        if not report:
            report = self.audit_document(doc_id, source_path, md_path, assets_dir)

        if report.is_healthy:
            return True, "문서가 이미 kordoc 규격에 완전히 부합하며 누락이 없습니다.", None

        # 1. 안전 백업 생성
        backup_file = self.backup_mgr.create_backup(md_path)
        current_md = md_path.read_text(encoding="utf-8")
        updated_md = current_md

        # 2. AI 멀티모달 외과적 보정 실행
        if self.api_key and source_path.exists() and source_path.suffix.lower() == ".pdf":
            try:
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=self.api_key)
                doc = pymupdf.open(str(source_path))

                for issue in report.issues:
                    if issue.category in ("MISSING_TABLE", "MISSING_TEXT", "MISSING_FORMULA") and issue.page_no:
                        p_no = issue.page_no - 1
                        if p_no < len(doc):
                            page = doc[p_no]
                            pix = page.get_pixmap(dpi=150)
                            img_bytes = pix.tobytes("png")

                            prompt = (
                                f"당신은 대한민국 최고 수준의 공문서/리서치 보고서 전수 복원 전문가입니다.\n"
                                f"원문 {issue.page_no}페이지에서 다음 항목이 마크다운 본문에서 누락되었습니다:\n"
                                f"결함 내용: {issue.description}\n\n"
                                f"[kordoc-wiki-ingest 5대 불변 원칙]\n"
                                f"1. Zero Information Loss: 단 하나의 단어, 수치, 각주, 셀도 생략하지 마십시오. (~등, ... 생략 절대 금지)\n"
                                f"2. 표(Table)는 완전한 다열 마크다운 표(|---|)로 전수 복원하십시오.\n"
                                f"3. 수식은 KaTeX LaTeX 포맷($...$ 또는 $$...$$)으로 작성하십시오.\n\n"
                                f"첨부된 원본 페이지 이미지를 정밀 분석하여, 마크다운의 '{issue.location_hint}' 뒤에 삽입될 "
                                f"**누락된 본문/표/수식 마크다운 조각만을 완전하게 작성**하여 출력하십시오. (인사말/사족 절대 금지)"
                            )

                            resp = client.models.generate_content(
                                model=self.model_name,
                                contents=[
                                    types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                                    prompt,
                                ],
                                config=types.GenerateContentConfig(temperature=0.1),
                            )

                            patch_text = resp.text.strip()
                            patch_text = re.sub(r'^```(?:markdown)?\r?\n', '', patch_text)
                            patch_text = re.sub(r'\r?\n```$', '', patch_text).strip()

                            hint_match = re.search(rf'(###?\s+[^\n]*{re.escape(issue.location_hint[:10])}[^\n]*)', updated_md)
                            if hint_match:
                                insert_pos = hint_match.end()
                                updated_md = updated_md[:insert_pos] + "\n\n" + patch_text + updated_md[insert_pos:]
                                logger.info(f"💉 외과적 패치 삽입 성공: {issue.description}")
                            else:
                                updated_md = updated_md.strip() + "\n\n" + patch_text + "\n"
                                logger.info(f"💉 외과적 패치 본문 말미 결합: {issue.description}")

                doc.close()
            except Exception as e:
                logger.error(f"AI 외과적 보정 생성 중 오류: {e}")

        # 3. 목차(TOC) 재구성
        updated_md = generate_toc_and_anchors(updated_md)

        # 4. 품질 게이트 검증
        is_valid, violations = QualityGate.validate(updated_md, doc_file=md_path, require_metadata=True)
        if not is_valid:
            logger.warning(f"🚨 품질 게이트 불합격으로 롤백 수행: {violations}")
            self.backup_mgr.rollback(md_path, backup_file)
            return False, f"품질 게이트 검증 실패로 롤백되었습니다: {', '.join(violations)}", backup_file

        # 5. 최종 안전 저장
        md_path.write_text(updated_md, encoding="utf-8")
        logger.info(f"✅ 외과적 자율 보정 완료 및 저장: {md_path.name}")
        return True, "kordoc 규격에 따른 원문 대조 외과적 보정이 성공적으로 완료되었습니다.", backup_file

    def audit_and_heal_single(
        self,
        doc_id: str,
        manifest_mgr,
        engine,
        source_dir: Path,
        docs_dir: Optional[Path] = None,
        assets_dir: Optional[Path] = None,
    ) -> tuple[bool, str, AuditReport]:
        """개별 문서에 대해 원문 대조 감사를 실행하고, 결함 발견 시 Tier 1/Tier 2 자율 치유를 수행한다.
        
        반환값: (성공 여부, 결과 메시지, 감사 리포트)
        """
        target_docs_dir = docs_dir or self.docs_dir
        # "WikiDB/assets" 하드코딩 제거: docs_dir 기반으로 추론
        target_assets_dir = assets_dir or (Path(self.docs_dir).resolve().parent / "assets")

        doc = manifest_mgr.get_document(doc_id)
        if not doc:
            report = AuditReport(doc_id=doc_id, is_healthy=False, red_flags=["매니페스트에 등록되지 않은 문서입니다."])
            return False, "매니페스트에서 문서를 찾을 수 없습니다.", report

        md_path = Path(doc.target_md_path) if doc.target_md_path else target_docs_dir / f"{doc.id}.md"
        if not md_path.exists():
            report = AuditReport(doc_id=doc_id, is_healthy=False, red_flags=["마크다운 파일이 디스크에 존재하지 않습니다."])
            return False, "마크다운 파일이 존재하지 않습니다.", report

        source_path = Path(doc.source_path)
        if not source_path.exists():
            alt_source = source_dir / doc.original_filename
            if alt_source.exists():
                source_path = alt_source

        doc_asset_dir = target_assets_dir / doc.id
        report = self.audit_document(
            doc_id=doc.id,
            source_path=source_path,
            md_path=md_path,
            assets_dir=doc_asset_dir if doc_asset_dir.exists() else None,
        )

        if report.is_healthy:
            return True, "문서가 이미 kordoc 규격에 완전히 부합하며 누락 및 결함이 없습니다.", report

        # 결함 유형 및 심각도 분석
        md_content = md_path.read_text(encoding="utf-8", errors="replace")

        # 0. 현재 문서가 절단되었거나 단락 누락이 있을 때, 기존 완본 백업 스냅샷이 존재하면 우선 복원 및 서식 치유 시도
        best_bak = self.backup_mgr.find_best_backup(md_path)
        repaired_bak_content: Optional[str] = None
        if best_bak and best_bak.exists() and best_bak.stat().st_size > len(md_content.encode("utf-8")) * 1.3:
            bak_raw = best_bak.read_text(encoding="utf-8", errors="replace")
            repaired_bak = generate_toc_and_anchors(clean_markdown_typography(bak_raw))
            self.backup_mgr.create_backup(md_path)
            md_path.write_text(repaired_bak, encoding="utf-8")
            bak_report = self.audit_document(
                doc_id=doc.id,
                source_path=source_path,
                md_path=md_path,
                assets_dir=doc_asset_dir if doc_asset_dir.exists() else None,
            )
            if bak_report.is_healthy:
                logger.info(f"✅ 완본 백업 스냅샷 복원 및 서식 치유 완료: {doc.title} ({best_bak.name})")
                return True, f"완본 스냅샷 복원 및 표/서식 자율 치유 완료 ({best_bak.name})", bak_report
            repaired_bak_content = repaired_bak
            md_content = repaired_bak
            report = bak_report

        # 1. 본문 누락 없이 표/서식 결함만 존재하는 경우 Tier 1 로컬 무손실 치유 우선 시도
        has_content_loss = (
            len(report.missing_sections) > 0
            or len(report.missing_tables) > 0
            or (source_path.suffix.lower() == ".pdf" and report.inspected_pages >= 2 and len(md_content.strip()) < 1000)
        )
        if not has_content_loss:
            fixed_try = generate_toc_and_anchors(clean_markdown_typography(md_content))
            if len(validate_red_flags(fixed_try)) == 0:
                self.backup_mgr.create_backup(md_path)
                md_path.write_text(fixed_try, encoding="utf-8")
                logger.info(f"✅ Tier 1 표/서식 무손실 정돈 완료: {doc.title}")
                return True, f"Tier 1 표/서식 정돈 완료 ({len(report.red_flags)}개 서식 결함 보정)", report

        is_pdf_truncated = (
            source_path.suffix.lower() == ".pdf"
            and report.inspected_pages >= 2
            and len(md_content.strip()) < 1000
        )
        is_fatal = (
            len(report.missing_sections) >= 10
            or len(report.missing_tables) >= 3
            or is_pdf_truncated
            or any("표 문법 파손" in flag for flag in report.red_flags)
            or any("이미지 연속 덤프" in flag for flag in report.red_flags)
            or any("무삭제 원칙 위반" in flag for flag in report.red_flags)
        )

        try:
            if is_fatal and source_path.exists() and hasattr(engine, "execute_ingest"):
                logger.warning(
                    f"🚨 [치명적 무결성 결함 감지] '{doc.original_filename}' "
                    f"(누락단락: {len(report.missing_sections)}, 표누락: {len(report.missing_tables)}) "
                    f"→ Tier 2 최신 파이프라인 전면 재인제스트 가동"
                )
                backup_before_ingest = self.backup_mgr.create_backup(md_path)
                new_md_path, new_images, new_title = engine.execute_ingest(
                    source_path=source_path,
                    doc_id=doc.id,
                    file_hash=doc.file_hash,
                    skip_lint=False
                )
                doc.target_md_path = str(new_md_path)
                doc.title = new_title

                # Tier 2 사후 무결성 검증: 재인제스트 결과물이 절단되었거나 기존 완본 백업보다 악화된 경우 즉시 롤백
                new_content = new_md_path.read_text(encoding="utf-8", errors="replace") if new_md_path.exists() else ""
                fallback_content = repaired_bak_content or backup_before_ingest.read_text(encoding="utf-8", errors="replace")
                if len(new_content.strip()) < max(600, int(len(fallback_content.strip()) * 0.5)):
                    logger.warning(
                        f"⚠️ Tier 2 재인제스트 결과 조기 절단 감지 ({len(new_content)}자 < 백업 {len(fallback_content)}자) → 완본 백업 복구"
                    )
                    healed_fallback = generate_toc_and_anchors(clean_markdown_typography(fallback_content))
                    new_md_path.write_text(healed_fallback, encoding="utf-8")

                manifest_mgr.add_or_update_document(doc)
                logger.info(f"✅ Tier 2 완본 재인제스트 완료: {doc.title}")
                return True, f"Tier 2 완본 재인제스트 성공 (누락 {len(report.missing_sections)}개 섹션, {len(report.missing_tables)}개 표 복구)", report
            else:
                logger.info(
                    f"🩹 [서식/들여쓰기 결함 감지] '{doc.original_filename}' "
                    f"({', '.join(report.red_flags[:2])}) → Tier 1 서식 자율 보정"
                )
                self.backup_mgr.create_backup(md_path)
                fixed_md = clean_markdown_typography(md_content)
                fixed_md = generate_toc_and_anchors(fixed_md)
                md_path.write_text(fixed_md, encoding="utf-8")
                logger.info(f"✅ Tier 1 서식 정돈 완료: {doc.title}")
                return True, f"Tier 1 서식 정돈 완료 ({len(report.red_flags)}개 서식 결함 보정)", report
        except Exception as heal_err:
            logger.error(f"❌ 문서 자율 치유 실패 ({doc.original_filename}): {heal_err}")
            return False, f"자율 치유 실패: {heal_err}", report

    def audit_and_heal_all(
        self,
        manifest_mgr,
        engine,
        source_dir: Path,
        docs_dir: Optional[Path] = None,
        assets_dir: Optional[Path] = None,
    ) -> dict[str, int]:
        """WikiDB 내의 모든 완료 문서를 전수 감사하고, 최신 프롬프트/서식 기준에 미달하는 문서를 자동 치유한다.
        
        - Tier 1: 불릿 계층별 들여쓰기 누락, 이중 불릿, 각주 인라인 미분리 등 서식 결함 -> 로컬 무손실 정돈
        - Tier 2: 본문 대량 누락, 깨진 표, 이미지 연속 덤프 등 구조적 결함 -> 최신 파이프라인으로 전면 재인제스트
        """
        target_docs_dir = docs_dir or self.docs_dir
        target_assets_dir = assets_dir or Path("WikiDB/assets")
        all_docs = manifest_mgr.get_all_documents()
        completed_docs = [d for d in all_docs if d.status == "completed"]

        stats = {
            "audited": len(completed_docs),
            "healthy": 0,
            "tier1_healed": 0,
            "tier2_healed": 0,
            "failed": 0,
        }

        logger.info(f"🛡️ [무결성 전수 감사 시작] 총 {len(completed_docs)}개 문서 대상 검증 및 자율 치유...")

        for doc in completed_docs:
            md_path = Path(doc.target_md_path) if doc.target_md_path else target_docs_dir / f"{doc.id}.md"
            if not md_path.exists():
                logger.warning(f"마크다운 파일 부재로 감사 건너뜀: {doc.title} ({doc.id})")
                continue

            source_path = Path(doc.source_path)
            if not source_path.exists():
                alt_source = source_dir / doc.original_filename
                if alt_source.exists():
                    source_path = alt_source

            doc_asset_dir = target_assets_dir / doc.id
            report = self.audit_document(
                doc_id=doc.id,
                source_path=source_path,
                md_path=md_path,
                assets_dir=doc_asset_dir if doc_asset_dir.exists() else None,
            )

            if report.is_healthy:
                stats["healthy"] += 1
                continue

            # 결함 유형 및 심각도 분석 (Tier 2 치명적 결함 판정)
            md_content = md_path.read_text(encoding="utf-8", errors="replace")
            is_pdf_truncated = (
                source_path.suffix.lower() == ".pdf"
                and report.inspected_pages >= 3
                and len(md_content.strip()) < 1000
            )
            is_fatal = (
                len(report.missing_sections) >= 10
                or len(report.missing_tables) >= 3
                or is_pdf_truncated
                or any("표 문법 파손" in flag for flag in report.red_flags)
                or any("이미지 연속 덤프" in flag for flag in report.red_flags)
                or any("무삭제 원칙 위반" in flag for flag in report.red_flags)
            )

            try:
                if is_fatal and source_path.exists() and hasattr(engine, "execute_ingest"):
                    logger.warning(
                        f"🚨 [치명적 무결성 결함 감지] '{doc.original_filename}' "
                        f"(누락단락: {len(report.missing_sections)}, 표누락: {len(report.missing_tables)}) "
                        f"→ Tier 2 최신 파이프라인 전면 재인제스트 가동"
                    )
                    self.backup_mgr.create_backup(md_path)
                    new_md_path, new_images, new_title = engine.execute_ingest(
                        source_path=source_path,
                        doc_id=doc.id,
                        file_hash=doc.file_hash,
                        skip_lint=False
                    )
                    doc.target_md_path = str(new_md_path)
                    doc.title = new_title
                    manifest_mgr.add_or_update_document(doc)
                    stats["tier2_healed"] += 1
                    logger.info(f"✅ Tier 2 완본 재인제스트 완료: {doc.title}")
                else:
                    logger.info(
                        f"🩹 [서식/들여쓰기 결함 감지] '{doc.original_filename}' "
                        f"({', '.join(report.red_flags[:2])}) → Tier 1 서식 자율 보정"
                    )
                    self.backup_mgr.create_backup(md_path)
                    fixed_md = clean_markdown_typography(md_content)
                    fixed_md = generate_toc_and_anchors(fixed_md)
                    md_path.write_text(fixed_md, encoding="utf-8")
                    stats["tier1_healed"] += 1
                    logger.info(f"✅ Tier 1 서식 정돈 완료: {doc.title}")
            except Exception as heal_err:
                logger.error(f"❌ 문서 자율 치유 실패 ({doc.original_filename}): {heal_err}")
                stats["failed"] += 1

        logger.info(
            f"🛡️ [무결성 전수 감사 완료] 정상: {stats['healthy']}, "
            f"Tier 1 서식 보정: {stats['tier1_healed']}, Tier 2 완본 재인제스트: {stats['tier2_healed']}, 실패: {stats['failed']}"
        )
        return stats
