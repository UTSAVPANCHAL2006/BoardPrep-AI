from typing import Literal

from typing_extensions import TypedDict

from app.schema.interview import (
    AnswerEvaluation,
    ChatTurn,
    CASource,
    DAFProfile,
    DAFFlag,
    EnrichedArticle,
    RetrievedChunk,
)

InterviewPhase = Literal[
    "daf_opening",
    "subject_probe",
    "current_affairs",
    "closing",
]


class InterviewState(TypedDict, total=False):
    session_id: str
    candidate_daf: str
    daf_profile: DAFProfile
    chat_history: list[ChatTurn]
    current_question: str
    current_question_voice: str
    current_focus_anchor: str
    last_answer: str
    current_phase: InterviewPhase
    topic_stack: list[str]
    panel_persona: str
    follow_up_count: int
    phase_exchange_count: int
    last_evaluation: AnswerEvaluation
    feedback_report: dict
    interview_complete: bool
    route: str
    router_action: str
    daf_flags: list[DAFFlag]
    last_retrieved_chunks: list[RetrievedChunk]
    ca_articles: list[EnrichedArticle]
    ca_article_cursor: int
    last_ca_source: CASource
    last_ca_briefing: dict
    interview_mode: str
    max_questions: int
    exchanges_per_phase: int
