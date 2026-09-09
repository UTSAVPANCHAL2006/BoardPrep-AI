from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import InterviewState
from app.common.custom_exception import CustomException
from app.common.logger import get_logger
from app.common.utils import (
    build_daf_topic_stack,
    ca_grounding_score,
    format_ca_article_for_prompt,
    history_text,
    is_ca_grounded,
    parse_json_response,
    profile_summary,
    sanitize_board_question,
)
from app.prompts.question_prompt import (
    CA_QUESTION_USER_TEMPLATE,
    CA_RETRY_SUFFIX,
    DAF_QUESTION_TEMPLATE,
    PANEL_PERSONA,
    ROUTER_HINTS,
    SUBJECT_QUESTION_TEMPLATE,
)
from app.schema.interview import CASource, ChatTurn, EnrichedArticle, RetrievedChunk
from app.tools.ca_briefing_tool import CaBriefingTool

logger = get_logger(__name__)


class GenerateQuestionNode:
    def __init__(self, llm, retriever):
        self.llm = llm
        self.retriever = retriever
        self.ca_briefing = CaBriefingTool(llm)

    def chunk_preview(self, text: str, limit: int = 200) -> str:
        cleaned = " ".join(text.split())
        return cleaned[:limit] + ("..." if len(cleaned) > limit else "")

    def pick_focus_anchor(self, state: InterviewState, profile) -> tuple[str, list[str]]:
        router_action = state.get("router_action", "pivot")
        topic_stack = list(state.get("topic_stack", []))

        if router_action in ("probe", "daf_probe"):
            anchor = state.get("current_focus_anchor") or (topic_stack[0] if topic_stack else "your background")
            return anchor, topic_stack

        if not topic_stack:
            topic_stack = build_daf_topic_stack(profile)

        anchor = topic_stack.pop(0)
        topic_stack.append(anchor)
        return anchor, topic_stack

    def pick_ca_article(self, state: InterviewState) -> tuple[EnrichedArticle, int]:
        articles = list(state.get("ca_articles", []))
        if not articles:
            return EnrichedArticle(
                title="India governance and policy developments",
                daf_anchor="general",
                detailed_insights="Recent national policy developments.",
            ), 0
        cursor = state.get("ca_article_cursor", 0) % len(articles)
        return articles[cursor], (cursor + 1) % len(articles)

    async def invoke_llm(self, user_prompt: str, session_id: str = "", run_name: str = "generate_question") -> dict:
        from app.observability.langfuse_client import langchain_invoke_config

        llm = self.llm.get_llm(temperature=0.3, max_tokens=320)
        config = langchain_invoke_config(
            session_id,
            run_name=run_name,
            tags=["upsc-interview", "question"],
        )
        response = await llm.ainvoke(
            [SystemMessage(content=PANEL_PERSONA), HumanMessage(content=user_prompt)],
            config=config,
        )
        return parse_json_response(str(response.content))

    async def generate_question_node(self, state: InterviewState):
        try:
            logger.info("GenerateQuestionNode started")
            phase = state.get("current_phase", "daf_opening")
            profile = state["daf_profile"]
            session_id = state["session_id"]
            router_action = state.get("router_action", "pivot")
            router_hint = ROUTER_HINTS.get(router_action, ROUTER_HINTS["pivot"])
            focus_anchor, topic_stack = self.pick_focus_anchor(state, profile)

            retrieved_chunks: list[RetrievedChunk] = []
            ca_source: CASource | None = None
            ca_briefing: dict | None = None
            ca_article_cursor = state.get("ca_article_cursor", 0)
            question = ""
            question_voice = ""

            if phase == "subject_probe":
                optional = profile.optional_subject or "public administration"
                focus_anchor = f"optional subject: {optional}"
                chunks = await self.retriever.hybrid_retrieve_async(optional, session_id, doc_type="syllabus")
                retrieved_chunks = [
                    RetrievedChunk(doc_type="syllabus", text=c, preview=self.chunk_preview(c))
                    for c in chunks
                ]
                prompt = SUBJECT_QUESTION_TEMPLATE.format(
                    router_hint=router_hint,
                    optional_subject=optional,
                    profile=profile_summary(profile),
                    history=history_text(state.get("chat_history", [])),
                    context="\n\n".join(chunks) if chunks else "Use standard UPSC syllabus concepts.",
                )
                data = await self.invoke_llm(prompt, session_id)
                question = sanitize_board_question(data.get("question", ""), max_words=28)
                question_voice = sanitize_board_question(data.get("question_voice") or question, max_words=32)
                if not question_voice.strip():
                    question_voice = question

            elif phase == "current_affairs":
                featured, ca_article_cursor = self.pick_ca_article(state)
                focus_anchor = featured.daf_anchor or featured.title
                query = f"{featured.title} {featured.daf_anchor}"
                chunks = await self.retriever.hybrid_retrieve_async(query, session_id, doc_type="current_affairs")
                retrieved_chunks = [
                    RetrievedChunk(
                        doc_type="current_affairs",
                        text=c,
                        preview=self.chunk_preview(c),
                        source_title=featured.title,
                    )
                    for c in chunks
                ]
                prompt = CA_QUESTION_USER_TEMPLATE.format(
                    router_hint=router_hint,
                    featured_article=format_ca_article_for_prompt(featured),
                    profile=profile_summary(profile),
                    history=history_text(state.get("chat_history", [])),
                    context="\n\n".join(chunks) if chunks else "None",
                    daf_anchor=featured.daf_anchor or "candidate profile",
                )
                data = await self.invoke_llm(prompt, session_id)
                question = sanitize_board_question(data.get("question", ""), max_words=30)
                question_voice = sanitize_board_question(data.get("question_voice") or question, max_words=35)

                score = ca_grounding_score(question, featured)
                grounded = is_ca_grounded(question, featured)
                if not grounded:
                    data = await self.invoke_llm(
                        prompt + CA_RETRY_SUFFIX.format(article_title=featured.title),
                        session_id,
                        run_name="generate_question_ca_retry",
                    )
                    question = sanitize_board_question(data.get("question", ""), max_words=30)
                    question_voice = sanitize_board_question(
                        data.get("question_voice") or question, max_words=35
                    )
                    score = ca_grounding_score(question, featured)
                    grounded = is_ca_grounded(question, featured)

                ca_source = CASource(
                    title=featured.title,
                    daf_anchor=featured.daf_anchor,
                    source=featured.source,
                    grounded=grounded,
                    grounding_score=round(score, 3),
                )
                ca_briefing = await self.ca_briefing.generate_briefing(featured, session_id, use_llm=True)

            else:
                prompt = DAF_QUESTION_TEMPLATE.format(
                    phase=phase,
                    router_hint=router_hint,
                    focus_anchor=focus_anchor,
                    profile=profile_summary(profile),
                    history=history_text(state.get("chat_history", [])),
                )
                data = await self.invoke_llm(prompt, session_id)
                question = sanitize_board_question(
                    data.get("question", "Tell us briefly about yourself."), max_words=25
                )
                question_voice = sanitize_board_question(
                    data.get("question_voice") or question, max_words=30
                )
                if not question_voice.strip():
                    question_voice = question

            history = list(state.get("chat_history", []))
            history.append(ChatTurn(role="panel", content=question))

            result = {
                "current_question": question,
                "current_question_voice": question_voice,
                "current_focus_anchor": focus_anchor,
                "topic_stack": topic_stack,
                "chat_history": history,
                "last_retrieved_chunks": retrieved_chunks,
                "ca_article_cursor": ca_article_cursor,
            }
            if ca_source:
                result["last_ca_source"] = ca_source
            if ca_briefing:
                result["last_ca_briefing"] = ca_briefing
            else:
                result["last_ca_briefing"] = {}

            logger.info(f"GenerateQuestionNode done: phase={phase} anchor={focus_anchor[:50]}")
            return result

        except Exception as e:
            logger.error(f"Error in GenerateQuestionNode: {str(e)}")
            raise CustomException("GenerateQuestionNode Failed", e)
