from typing import Literal

from pydantic import BaseModel, Field


class DAFProfile(BaseModel):
    hobbies: list[str] = Field(default_factory=list)
    optional_subject: str = ""
    work_experience: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    service_preferences: list[str] = Field(default_factory=list)
    hometown: str = ""


class ChatTurn(BaseModel):
    role: Literal["panel", "candidate"]
    content: str


class AnswerEvaluation(BaseModel):
    clarity: Literal["clear", "vague", "off_topic"] = "vague"
    factual_consistency: Literal["consistent", "contradicts_daf", "unknown"] = "unknown"
    notes: str = ""


class DAFFlag(BaseModel):
    field: str
    daf_says: str
    candidate_said: str
    message: str


class RetrievedChunk(BaseModel):
    doc_type: str
    text: str
    preview: str = ""
    source_title: str = ""


class CASource(BaseModel):
    title: str
    daf_anchor: str = ""
    source: str = ""
    grounded: bool = False
    grounding_score: float = 0.0


class EnrichedArticle(BaseModel):
    title: str
    source: str = ""
    published_at: str = ""
    url: str = ""
    daf_anchor: str = ""
    key_highlights: list[str] = Field(default_factory=list)
    detailed_insights: str = ""
    key_concepts: dict[str, str] = Field(default_factory=dict)
    gs_tags: list[str] = Field(default_factory=list)
    is_prelims_relevant: bool = False
