from app.agents.state import InterviewState
from app.common.custom_exception import CustomException
from app.common.logger import get_logger
from app.schema.interview import AnswerEvaluation

logger = get_logger(__name__)

PHASE_ORDER = ["daf_opening", "subject_probe", "current_affairs", "closing"]


def phase_exchange_limit(state: InterviewState, phase: str) -> int:
    phase_limits = state.get("phase_exchanges") or {}
    return phase_limits.get(phase, state.get("exchanges_per_phase", 3))


class FollowUpRouterNode:
    def follow_up_router_node(self, state: InterviewState):
        try:
            logger.info("FollowUpRouterNode started")
            phase = state.get("current_phase", "daf_opening")
            phase_count = state.get("phase_exchange_count", 0)
            total_count = state.get("follow_up_count", 0)
            exchange_limit = phase_exchange_limit(state, phase)
            max_questions = state.get("max_questions", 12)
            evaluation = state.get("last_evaluation", AnswerEvaluation())

            interview_complete = False
            next_phase = phase
            router_action = "pivot"

            if evaluation.factual_consistency == "contradicts_daf":
                router_action = "daf_probe"
            elif evaluation.clarity in ("vague", "off_topic"):
                router_action = "probe"
            elif evaluation.clarity == "clear":
                router_action = "pivot"

            if router_action == "probe" and phase_count >= 1:
                router_action = "pivot"

            if phase_count >= exchange_limit:
                idx = PHASE_ORDER.index(phase) if phase in PHASE_ORDER else 0
                if idx < len(PHASE_ORDER) - 1:
                    next_phase = PHASE_ORDER[idx + 1]
                    router_action = "advance_phase"
                else:
                    interview_complete = True

            if total_count >= max_questions:
                interview_complete = True

            logger.info(
                f"FollowUpRouterNode: phase={next_phase}, action={router_action}, complete={interview_complete}"
            )
            return {
                "current_phase": next_phase,
                "phase_exchange_count": 0 if next_phase != phase else phase_count,
                "interview_complete": interview_complete,
                "route": "generate_question",
                "router_action": router_action,
            }

        except Exception as e:
            logger.error(f"Error in FollowUpRouterNode: {str(e)}")
            raise CustomException("FollowUpRouterNode Failed", e)
