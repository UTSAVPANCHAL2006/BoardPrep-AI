from app.agents.state import InterviewState


def interview_router(state: InterviewState) -> str:
    if state.get("interview_complete"):
        return "feedback"
    return "generate_question"
