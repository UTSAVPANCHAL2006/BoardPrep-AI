from langchain_core.messages import HumanMessage

from app.agents.state import InterviewState
from app.common.custom_exception import CustomException
from app.common.logger import get_logger
from app.common.utils import (
    evaluation_log_text,
    history_text,
    llm_message_text,
    parse_json_response,
    profile_summary,
)
from app.config.config import INTERVIEW_JSON_MODEL
from app.prompts.feedback_prompt import FEEDBACK_USER_TEMPLATE

logger = get_logger(__name__)

SCORE_KEYS = (
    "clarity",
    "structure",
    "daf_consistency",
    "subject_depth",
    "current_affairs",
    "confidence",
)


def calibrate_feedback_scores(report: dict, evaluation_log: list[dict], daf_flags: list) -> dict:
    """Apply fair floors so practice mocks are not scored unrealistically low."""
    scores = dict(report.get("scores") or {})
    if not scores:
        return report

    answered = [e for e in evaluation_log if (e.get("answer") or "").strip()]
    answered_count = len(answered)
    clear_count = sum(1 for e in answered if e.get("clarity") == "clear")
    vague_count = sum(1 for e in answered if e.get("clarity") == "vague")

    if answered_count >= 3:
        floor = 4
        if clear_count >= answered_count // 2:
            floor = 5
        for key in ("clarity", "structure", "confidence"):
            scores[key] = max(int(scores.get(key, 0) or 0), floor)

    if answered_count >= 1 and vague_count <= answered_count:
        scores["clarity"] = max(int(scores.get("clarity", 0) or 0), 3)

    if daf_flags:
        scores["daf_consistency"] = min(int(scores.get("daf_consistency", 10) or 10), 6)
    elif answered_count:
        scores["daf_consistency"] = max(int(scores.get("daf_consistency", 0) or 0), 7)

    phases_seen = {e.get("phase") for e in evaluation_log}
    if "subject_probe" not in phases_seen:
        scores["subject_depth"] = max(int(scores.get("subject_depth", 0) or 0), 5)
    if "current_affairs" not in phases_seen:
        scores["current_affairs"] = max(int(scores.get("current_affairs", 0) or 0), 5)

    for key in SCORE_KEYS:
        val = int(scores.get(key, 0) or 0)
        scores[key] = max(1, min(10, val))

    report["scores"] = scores
    return report


class FeedbackReportNode:
    def __init__(self, llm):
        self.llm = llm

    async def feedback_report_node(self, state: InterviewState):
        try:
            logger.info("FeedbackReportNode started")
            profile = state["daf_profile"]
            daf_flags = state.get("daf_flags", [])
            evaluation_log = state.get("evaluation_log", [])
            flags_text = (
                "\n".join(f"- {flag.message}" for flag in daf_flags)
                if daf_flags
                else "None"
            )
            prompt = FEEDBACK_USER_TEMPLATE.format(
                interview_mode=state.get("interview_mode", "full"),
                question_count=len(evaluation_log),
                profile=profile_summary(profile),
                history=history_text(state.get("chat_history", []), limit=None),
                evaluation_log=evaluation_log_text(evaluation_log),
                daf_flags=flags_text,
            )

            llm = self.llm.get_llm(temperature=0.25, max_tokens=1200, model=INTERVIEW_JSON_MODEL)
            try:
                llm = llm.bind(response_format={"type": "json_object"})
            except Exception:
                pass
            session_id = state.get("session_id", "")
            from app.observability.langfuse_client import langchain_invoke_config

            config = langchain_invoke_config(
                session_id,
                run_name="feedback_report",
                tags=["upsc-interview", "feedback"],
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)], config=config)
            report = parse_json_response(llm_message_text(response))
            report = calibrate_feedback_scores(report, evaluation_log, daf_flags)
            if daf_flags:
                report["daf_flags"] = [
                    flag.model_dump() if hasattr(flag, "model_dump") else flag
                    for flag in daf_flags
                ]

            logger.info("FeedbackReportNode completed")
            return {"feedback_report": report, "interview_complete": True}

        except Exception as e:
            logger.error(f"Error in FeedbackReportNode: {str(e)}")
            raise CustomException("FeedbackReportNode Failed", e)
