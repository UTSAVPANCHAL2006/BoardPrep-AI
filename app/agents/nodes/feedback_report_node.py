from langchain_core.messages import HumanMessage

from app.agents.state import InterviewState
from app.common.custom_exception import CustomException
from app.common.logger import get_logger
from app.common.utils import history_text, llm_message_text, parse_json_response, profile_summary
from app.config.config import INTERVIEW_JSON_MODEL
from app.prompts.feedback_prompt import FEEDBACK_USER_TEMPLATE

logger = get_logger(__name__)


class FeedbackReportNode:
    def __init__(self, llm):
        self.llm = llm

    async def feedback_report_node(self, state: InterviewState):
        try:
            logger.info("FeedbackReportNode started")
            profile = state["daf_profile"]
            daf_flags = state.get("daf_flags", [])
            flags_text = (
                "\n".join(f"- {flag.message}" for flag in daf_flags)
                if daf_flags
                else "None"
            )
            prompt = FEEDBACK_USER_TEMPLATE.format(
                profile=profile_summary(profile),
                history=history_text(state.get("chat_history", [])),
                daf_flags=flags_text,
            )

            llm = self.llm.get_llm(model=INTERVIEW_JSON_MODEL)
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
