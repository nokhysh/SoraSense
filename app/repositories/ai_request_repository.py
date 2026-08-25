"""AI質問の状態遷移を永続化する。"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.models.ai_request import AIRequest


class AIRequestRepository:
    """RUNNINGから終端状態への一方向の更新を提供する。"""

    def start(self, session: Session, question: str, model: str) -> AIRequest:
        """外部AI呼出し前にRUNNING行を作成する。"""

        request = AIRequest(
            id=uuid4(),
            question=question,
            status="RUNNING",
            model=model,
            tool_calls=0,
        )
        session.add(request)
        session.commit()
        return request

    def succeed(
        self,
        session: Session,
        request_id: UUID,
        *,
        answer: str,
        tool_calls: int,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> None:
        """検証済み回答と利用量だけを成功として保存する。"""

        request = session.get(AIRequest, request_id)
        if request is None:
            raise RuntimeError("AI request disappeared")
        request.status = "SUCCEEDED"
        request.answer = answer
        request.tool_calls = tool_calls
        request.input_tokens = input_tokens
        request.output_tokens = output_tokens
        request.completed_at = datetime.now(UTC)
        session.commit()

    def fail(
        self,
        session: Session,
        request_id: UUID,
        *,
        error_code: str,
        tool_calls: int,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> None:
        """未検証回答を保存せず安全な失敗分類だけを記録する。"""

        request = session.get(AIRequest, request_id)
        if request is None:
            raise RuntimeError("AI request disappeared")
        request.status = "FAILED"
        request.error_code = error_code
        request.tool_calls = tool_calls
        request.input_tokens = input_tokens
        request.output_tokens = output_tokens
        request.completed_at = datetime.now(UTC)
        session.commit()
