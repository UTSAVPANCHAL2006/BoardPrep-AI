"""The end of the interview: writes the feedback report. The model writes the coaching; code decides the scores
and checks every quote (see app/agents/scoring.py)."""

from langchain_core.messages import HumanMessage

from app.agents.state import InterviewState
from app.common.custom_exception import CustomException
from app.common.logger import getLogger
from app.common.utils import (
    evaluationLogText,
    historyText,
    llmMessageText,
    parseJsonResponse,
    profileSummary,
)
from app.agents.scoring import (
    addCoaching,
    buildFallbackReport,
    buildNoAnswerReport,
    calibrateFeedbackScores,
    groundQuestionFeedback,
    isSubstantive,
)
from app.config.config import INTERVIEW_JSON_MODEL
from app.prompts.feedback_prompt import FEEDBACK_USER_TEMPLATE

logger = getLogger(__name__)

class FeedbackReportNode:
    def __init__(self, llm):
        self.llm = llm

    async def feedbackReportNode(self, state: InterviewState):
        try:
            logger.info("FeedbackReportNode started")
            profile = state["daf_profile"]
            daf_flags = state.get("daf_flags", [])
            evaluation_log = state.get("evaluation_log", [])
            nothing_answered = not any(isSubstantive(entry) for entry in evaluation_log)
            flags_text = (
                "\n".join(f"- {flag.message}" for flag in daf_flags)
                if daf_flags
                else "None"
            )
            prompt = FEEDBACK_USER_TEMPLATE.format(
                interview_mode=state.get("interview_mode", "full"),
                question_count=len(evaluation_log),
                profile=profileSummary(profile),
                history=historyText(state.get("chat_history", []), limit=None),
                evaluation_log=evaluationLogText(evaluation_log),
                daf_flags=flags_text,
            )

            llm = self.llm.getLlm(temperature=0.25, max_tokens=3000, model=INTERVIEW_JSON_MODEL)
            try:
                llm = llm.bind(response_format={"type": "json_object"})
            except Exception:
                pass
            session_id = state.get("session_id", "")
            from app.observability.langfuse_client import langchainInvokeConfig

            config = langchainInvokeConfig(
                session_id,
                run_name="feedback_report",
                tags=["upsc-interview", "feedback"],
            )
            if nothing_answered:
                # Scores, summary and strengths come from rules (all 0, none); the model only adds coaching.
                report = buildNoAnswerReport(evaluation_log)
                try:
                    response = await llm.ainvoke([HumanMessage(content=prompt)], config=config)
                    report = addCoaching(report, parseJsonResponse(llmMessageText(response)), evaluation_log)
                except Exception as error:
                    logger.warning(f"FeedbackReportNode: coaching unavailable ({error}); rules report only")
                if daf_flags:  # contradictions are shown even when nothing counted as an answer
                    report["daf_flags"] = [flag.model_dump() if hasattr(flag, "model_dump") else flag for flag in daf_flags]
                return {"feedback_report": report, "interview_complete": True}

            try:
                response = await llm.ainvoke([HumanMessage(content=prompt)], config=config)
                report = parseJsonResponse(llmMessageText(response))
                if not isinstance(report, dict):
                    raise ValueError("report is not a JSON object")
                report = calibrateFeedbackScores(report, evaluation_log, daf_flags)
                report = groundQuestionFeedback(report, evaluation_log, profile.model_dump())
            except Exception as error:
                # The candidate always gets a report: built from the per-answer checks when the coach model fails.
                logger.warning(f"FeedbackReportNode: model unavailable ({error}); rules report used")
                report = buildFallbackReport(evaluation_log, daf_flags, profile.model_dump())
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
