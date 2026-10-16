"""AI 에이전트 장기 실행 비동기 작업 큐 및 상태 관리 모듈."""

import enum
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("TaskManager")


class TaskStatus(str, enum.Enum):
    """작업 진행 상태 열거형."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AgentTask(BaseModel):
    """에이전트 백그라운드 작업 상태 모델."""
    task_id: str = Field(description="작업 고유 식별자")
    task_type: str = Field(description="작업 유형 (예: topic_generate, topic_refine)")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="현재 작업 상태")
    progress: int = Field(default=0, ge=0, le=100, description="진행률 (0~100%)")
    message: str = Field(default="작업 대기 중", description="현재 작업 진행 상태 메시지")
    result: Optional[Dict[str, Any]] = Field(default=None, description="작업 성공 시 결과 데이터")
    error: Optional[str] = Field(default=None, description="작업 실패 시 에러 내용")
    created_at: float = Field(default_factory=time.time, description="작업 생성 타임스탬프")
    updated_at: float = Field(default_factory=time.time, description="최종 상태 갱신 타임스탬프")


class TaskManager:
    """스레드 안전한 인메모리 비동기 작업 관리자."""

    def __init__(self, max_workers: int = 4, max_history: int = 100):
        self._tasks: Dict[str, AgentTask] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="AgentTaskWorker")
        self._max_history = max_history

    def create_task(self, task_type: str) -> str:
        """새로운 작업을 생성하고 작업 식별자를 반환한다."""
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        now = time.time()
        new_task = AgentTask(
            task_id=task_id,
            task_type=task_type,
            status=TaskStatus.PENDING,
            progress=0,
            message="작업이 등록되어 대기 중입니다.",
            created_at=now,
            updated_at=now,
        )

        with self._lock:
            # 이력 초과 시 완료/실패된 가장 오래된 작업부터 정리
            if len(self._tasks) >= self._max_history:
                finished_keys = [
                    tid for tid, t in self._tasks.items()
                    if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
                ]
                if finished_keys:
                    oldest_key = min(finished_keys, key=lambda k: self._tasks[k].created_at)
                    del self._tasks[oldest_key]

            self._tasks[task_id] = new_task

        logger.info(f"작업 생성 완료: {task_id} (유형: {task_type})")
        return task_id

    def get_task(self, task_id: str) -> Optional[AgentTask]:
        """특정 작업의 현재 상태를 반환한다."""
        with self._lock:
            task = self._tasks.get(task_id)
            return task.model_copy() if task else None

    def update_task(
        self,
        task_id: str,
        progress: int,
        message: str,
        status: TaskStatus = TaskStatus.RUNNING
    ) -> None:
        """작업의 진행률과 상태 메시지를 갱신한다."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                logger.warning(f"상태를 갱신할 작업을 찾을 수 없음: {task_id}")
                return
            task.progress = max(0, min(100, progress))
            task.message = message
            task.status = status
            task.updated_at = time.time()

        logger.debug(f"작업 진행 상태 [{task_id}]: {progress}% - {message}")

    def complete_task(
        self,
        task_id: str,
        result: Dict[str, Any],
        message: str = "작업이 성공적으로 완료되었습니다."
    ) -> None:
        """작업을 완료 상태로 전환하고 결과 데이터를 기록한다."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                logger.warning(f"완료 처리할 작업을 찾을 수 없음: {task_id}")
                return
            task.status = TaskStatus.COMPLETED
            task.progress = 100
            task.message = message
            task.result = result
            task.updated_at = time.time()

        logger.info(f"작업 완료 처리: {task_id}")

    def fail_task(
        self,
        task_id: str,
        error: str,
        message: str = "작업 처리 중 오류가 발생했습니다."
    ) -> None:
        """작업을 실패 상태로 전환하고 에러 메시지를 기록한다."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                logger.warning(f"실패 처리할 작업을 찾을 수 없음: {task_id}")
                return
            task.status = TaskStatus.FAILED
            task.error = error
            task.message = f"{message} ({error})"
            task.updated_at = time.time()

        logger.warning(f"작업 실패 처리: {task_id} - {error}")

    def submit_task(
        self,
        task_id: str,
        target_fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any
    ) -> None:
        """작업 풀에 함수 실행을 위임하고 비동기 수명주기를 관리한다."""
        def _runner():
            self.update_task(task_id, 10, "작업 실행을 시작합니다.", TaskStatus.RUNNING)
            try:
                # 콜백 함수 주입이 가능한 경우 주입, 아니면 일반 실행
                result = target_fn(
                    *args,
                    progress_callback=lambda p, msg: self.update_task(task_id, p, msg),
                    **kwargs
                )
                self.complete_task(task_id, result if isinstance(result, dict) else {"data": result})
            except TypeError:
                # target_fn이 progress_callback 인자를 받지 않는 일반 함수인 경우
                try:
                    result = target_fn(*args, **kwargs)
                    self.complete_task(task_id, result if isinstance(result, dict) else {"data": result})
                except Exception as inner_err:
                    logger.exception(f"작업 실행 실패 ({task_id}): {inner_err}")
                    self.fail_task(task_id, str(inner_err))
            except Exception as e:
                logger.exception(f"작업 실행 실패 ({task_id}): {e}")
                self.fail_task(task_id, str(e))

        self._executor.submit(_runner)


# 전역 싱글톤 인스턴스 및 의존성 주입 프로바이더
_default_task_manager: Optional[TaskManager] = None


def get_task_manager() -> TaskManager:
    """TaskManager 의존성 주입 프로바이더."""
    global _default_task_manager
    if _default_task_manager is None:
        _default_task_manager = TaskManager()
    return _default_task_manager
