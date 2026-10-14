"""Step 1 of every turn: judge the candidate's answer. Non-answers (skip, gibberish, 'give me 10') score 0 by
code; real answers are judged by the model, and DAF contradictions are checked by code."""

from langchain_core.messages import HumanMessage

from app.agents.scoring import (
    NON_ANSWER_REASONS,
    capClarityForLength,
    classifyNonAnswer,
    fallbackEvaluation,
    findDafContradictions,
)
from app.agents.state import InterviewState
from app.common.custom_exception import CustomException
from app.common.logger import getLogger
from app.common.utils import parseJsonResponse, profileSummary, llmMessageText
from app.config.config import INTERVIEW_JSON_MODEL
from app.prompts.evaluate_prompt import EVALUATE_USER_TEMPLATE
from app.schema.interview import AnswerEvaluation, ChatTurn, DAFFlag

logger = getLogger(__name__)


class EvaluateAnswerNode:
    def __init__(self, llm):
        self.llm = llm

    async def evaluateAnswerNode(self, state: InterviewState):
        try:
            logger.info("EvaluateAnswerNode started")
            answer = state.get("last_answer", "").strip()
            profile = state["daf_profile"]

            non_answer = classifyNonAnswer(answer, state.get("current_question", ""))
            if non_answer:
                # Silence or "skip" scores 0 by rule, before any model sees it, and the interview moves on.
                evaluation = AnswerEvaluation(
                    answered=False,
                    clarity="off_topic",
                    factual_consistency="unknown",
                    notes=NON_ANSWER_REASONS[non_answer],
                )
                history = list(state.get("chat_history", []))
                if answer:
                    history.append(ChatTurn(role="candidate", content=answer))
                eval_log = list(state.get("evaluation_log", []))
                eval_log.append(
                    {
                        "phase": state.get("current_phase", ""),
                        "question": state.get("current_question", ""),
                        "answer": answer[:6000],  # the whole answer: length, quotes and checks need all of it
                        "non_answer": non_answer,
                        "clarity": evaluation.clarity,
                        "factual_consistency": evaluation.factual_consistency,
                        "notes": evaluation.notes,
                    }
                )
                return {
                    "last_evaluation": evaluation,
                    "chat_history": history,
                    "follow_up_count": state.get("follow_up_count", 0) + 1,
                    "phase_exchange_count": state.get("phase_exchange_count", 0) + 1,
                    "evaluation_log": eval_log,
                }

            prompt = EVALUATE_USER_TEMPLATE.format(
                question=state.get("current_question", ""),
                answer=answer,
                profile=profileSummary(profile),
            )

            llm = self.llm.getLlm(temperature=0.2, max_tokens=280, model=INTERVIEW_JSON_MODEL)
            try:
                llm = llm.bind(response_format={"type": "json_object"})
            except Exception:
                pass
            session_id = state.get("session_id", "")
            from app.observability.langfuse_client import langchainInvokeConfig

            config = langchainInvokeConfig(
                session_id,
                run_name="evaluate_answer",
                tags=["upsc-interview", "evaluation"],
            )
            try:
                response = await llm.ainvoke([HumanMessage(content=prompt)], config=config)
                evaluation = AnswerEvaluation.model_validate(parseJsonResponse(llmMessageText(response)))
            except Exception as error:
                # A timeout, rate limit or broken JSON must never end the interview: code judges this answer.
                logger.warning(f"EvaluateAnswerNode: model unavailable ({error}); code evaluation used")
                evaluation = AnswerEvaluation.model_validate(fallbackEvaluation(answer))
            evaluation.clarity = capClarityForLength(evaluation.clarity, answer)

            history = list(state.get("chat_history", []))
            history.append(ChatTurn(role="candidate", content=answer))

            daf_flags = list(state.get("daf_flags", []))
            code_flags = findDafContradictions(answer, profile.model_dump())
            if code_flags:
                # Proven by reading the answer against the DAF: specific flags, whatever the model concluded.
                evaluation.factual_consistency = "contradicts_daf"
                seen = {(flag.field, flag.candidate_said.lower()) for flag in daf_flags}
                for flag in code_flags:
                    if (flag["field"], flag["candidate_said"].lower()) not in seen:  # one flag per contradiction
                        daf_flags.append(DAFFlag(**flag))
                        seen.add((flag["field"], flag["candidate_said"].lower()))
            elif evaluation.factual_consistency == "contradicts_daf":
                daf_flags.append(
                    DAFFlag(
                        field="daf_profile",
                        daf_says=profileSummary(profile),
                        candidate_said=answer[:300],
                        message=evaluation.notes or "Candidate answer may contradict DAF details.",
                    )
                )

            eval_log = list(state.get("evaluation_log", []))
            eval_log.append(
                {
                    "phase": state.get("current_phase", ""),
                    "question": state.get("current_question", ""),
                    "answer": answer[:6000],  # the whole answer: length, quotes and checks need all of it
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
