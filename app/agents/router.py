"""Picks the graph's next node: the feedback report once the interview is complete, otherwise the next question."""

from app.agents.state import InterviewState


def interviewRouter(state: InterviewState) -> str:
    if state.get("interview_complete"):
        return "feedback"
    return "generate_question"
