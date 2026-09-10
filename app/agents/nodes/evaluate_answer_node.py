from langchain_core.messages import HumanMessage

from app.agents.state import InterviewState
from app.common.custom_exception import CustomException
from app.common.logger import get_logger
from app.common.utils import parse_json_response, profile_summary, llm_message_text
from app.config.config import INTERVIEW_JSON_MODEL
from app.prompts.evaluate_prompt import EVALUATE_USER_TEMPLATE
from app.schema.interview import AnswerEvaluation, ChatTurn, DAFFlag

logger = get_logger(__name__)


class EvaluateAnswerNode:
    def __init__(self, llm):
        self.llm = llm

    async def evaluate_answer_node(self, state: InterviewState):
        try:
            logger.info("EvaluateAnswerNode started")
            answer = state.get("last_answer", "").strip()
            profile = state["daf_profile"]

            if not answer:
                evaluation = AnswerEvaluation(
                    clarity="off_topic",
                    factual_consistency="unknown",
                    notes="No answer provided.",
                )
                eval_log = list(state.get("evaluation_log", []))
                eval_log.append(
                    {
                        "phase": state.get("current_phase", ""),
                        "question": state.get("current_question", ""),
                        "answer": "",
                        "clarity": evaluation.clarity,
                        "factual_consistency": evaluation.factual_consistency,
                        "notes": evaluation.notes,
                    }
                )
                return {"last_evaluation": evaluation, "evaluation_log": eval_log}

            prompt = EVALUATE_USER_TEMPLATE.format(
                question=state.get("current_question", ""),
                answer=answer,
                profile=profile_summary(profile),
            )

            llm = self.llm.get_llm(temperature=0.2, max_tokens=280, model=INTERVIEW_JSON_MODEL)
            try:
                llm = llm.bind(response_format={"type": "json_object"})
            except Exception:
                pass
            session_id = state.get("session_id", "")
            from app.observability.langfuse_client import langchain_invoke_config

            config = langchain_invoke_config(
                session_id,
                run_name="evaluate_answer",
                tags=["upsc-interview", "evaluation"],
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)], config=config)
            data = parse_json_response(llm_message_text(response))
            evaluation = AnswerEvaluation.model_validate(data)

            history = list(state.get("chat_history", []))
            history.append(ChatTurn(role="candidate", content=answer))

            daf_flags = list(state.get("daf_flags", []))
            if evaluation.factual_consistency == "contradicts_daf":
                daf_flags.append(
                    DAFFlag(
                        field="daf_profile",
                        daf_says=profile_summary(profile),
                        candidate_said=answer[:300],
                        message=evaluation.notes or "Candidate answer may contradict DAF details.",
                    )
                )

            eval_log = list(state.get("evaluation_log", []))
            eval_log.append(
                {
                    "phase": state.get("current_phase", ""),
                    "question": state.get("current_question", ""),
                    "answer": answer[:800],
                    "clarity": evaluation.clarity,
                    "factual_consistency": evaluation.factual_consistency,
                    "notes": evaluation.notes or "",
                }
            )

            logger.info(f"EvaluateAnswerNode completed: clarity={evaluation.clarity}")
            return {
                "last_evaluation": evaluation,
                "chat_history": history,
                "follow_up_count": state.get("follow_up_count", 0) + 1,
                "phase_exchange_count": state.get("phase_exchange_count", 0) + 1,
                "daf_flags": daf_flags,
                "evaluation_log": eval_log,
            }

        except Exception as e:
            logger.error(f"Error in EvaluateAnswerNode: {str(e)}")
            raise CustomException("EvaluateAnswerNode Failed", e)
