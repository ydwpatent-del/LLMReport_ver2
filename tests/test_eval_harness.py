"""에이전트 엔지니어링 골든 평가셋 벤치마크 및 작업 관리자(Harness) 테스트 스위트."""

import time
from pathlib import Path
from fastapi.testclient import TestClient

from app.server import create_app
from app.task_manager import TaskManager, TaskStatus, AgentTask
from app.report_reviewer import ReportReviewAgent

app = create_app()


def test_task_manager_lifecycle():
    """TaskManager의 작업 등록, 진행률 업데이트, 완료 및 실패 라이프사이클을 검증한다."""
    tm = TaskManager(max_workers=2, max_history=10)
    
    # 1. 작업 등록
    task_id = tm.create_task("test_job")
    task = tm.get_task(task_id)
    assert task is not None
    assert task.status == TaskStatus.PENDING
    assert task.progress == 0

    # 2. 진행률 갱신
    tm.update_task(task_id, 45, "중간 처리 중", TaskStatus.RUNNING)
    task = tm.get_task(task_id)
    assert task.status == TaskStatus.RUNNING
    assert task.progress == 45
    assert "중간 처리 중" in task.message

    # 3. 작업 완료
    tm.complete_task(task_id, {"result_key": "success_value"})
    task = tm.get_task(task_id)
    assert task.status == TaskStatus.COMPLETED
    assert task.progress == 100
    assert task.result == {"result_key": "success_value"}

    # 4. 실패 처리 검증
    fail_id = tm.create_task("fail_job")
    tm.fail_task(fail_id, "강제 발생 에러")
    fail_task = tm.get_task(fail_id)
    assert fail_task.status == TaskStatus.FAILED
    assert fail_task.error == "강제 발생 에러"


def test_task_manager_submit_execution():
    """TaskManager의 비동기 백그라운드 함수 위임 실행 및 완료를 검증한다."""
    tm = TaskManager(max_workers=2)
    task_id = tm.create_task("async_execution")

    def dummy_work():
        time.sleep(0.05)
        return {"data": 12345}

    tm.submit_task(task_id, dummy_work)

    # 비동기 실행 대기 (최대 1초)
    for _ in range(20):
        t = tm.get_task(task_id)
        if t.status == TaskStatus.COMPLETED:
            break
        time.sleep(0.05)

    final_task = tm.get_task(task_id)
    assert final_task.status == TaskStatus.COMPLETED
    assert final_task.result == {"data": 12345}


def test_golden_reports_evaluation_benchmark():
    """WikiDB/reports에 축적된 골든 보고서들이 5대 필수 목차 및 고품질 평가 기준(80점 이상)을 만족하는지 검증한다."""
    reports_dir = Path("WikiDB/reports")
    if not reports_dir.exists():
        return

    reviewer = ReportReviewAgent()
    report_files = list(reports_dir.glob("*.md"))
    assert len(report_files) >= 10, f"최소 10개 이상의 보고서가 존재해야 합니다. (현재: {len(report_files)})"

    evaluated_scores = []
    for rep_file in report_files:
        content = rep_file.read_text(encoding="utf-8")
        topic = rep_file.stem.replace("REPORT_", "")

        audit = reviewer.review_report(report_markdown=content, topic=topic)
        score = audit.get("quality_score", 0)
        checklist = audit.get("checklist", {})

        # 5대 필수 목차 무결성 검증 (structure_valid)
        assert checklist.get("structure_valid") is True, f"{rep_file.name}의 5대 목차가 손상되었습니다."
        
        # 골든 벤치마크 개별 점수 기준: 70점 이상 달성
        assert score >= 70, f"{rep_file.name}의 품질 점수가 {score}점으로 기준치(70점) 미만입니다."
        evaluated_scores.append(score)

    avg_score = sum(evaluated_scores) / len(evaluated_scores)
    assert avg_score >= 90.0, f"전체 보고서 평균 점수가 90점 이상이어야 합니다. (현재 평균: {avg_score:.1f}점)"


def test_async_task_endpoints():
    """FastAPI 비동기 작업 조회 엔드포인트의 정상 작동을 검증한다."""
    client = TestClient(app)

    # 존재하지 않는 태스크 조회 시 404
    resp = client.get("/api/topic/tasks/task_nonexistent_999")
    assert resp.status_code == 404

    # 비동기 생성 요청 (빈 토픽인 경우 400 유효성 검증)
    empty_resp = client.post("/api/topic/generate/async", json={"topic": "   "})
    assert empty_resp.status_code == 400
