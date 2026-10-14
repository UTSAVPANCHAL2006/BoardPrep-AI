"""Step 3 of every turn: ask the next question for the current phase (DAF, subject, current affairs, closing),
with a fixed fallback question if the model is unavailable."""

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import InterviewState
from app.common.custom_exception import CustomException
from app.common.logger import getLogger
from app.common.utils import (
    buildClosingAngles,
    buildDafTopicStack,
    caBoardQuestionWordLimits,
    caGroundingScore,
    formatCaArticleForPrompt,
    historyText,
    isAboutAnswer,
    isCaGrounded,
    llmMessageText,
    parseJsonResponse,
    pickAnswerQuote,
    profileSummary,
    sanitizeBoardQuestion,
    sanitizeCaBoardQuestion,
)
from app.config.config import INTERVIEW_JSON_MODEL
from app.prompts.question_prompt import (
    CA_QUESTION_USER_TEMPLATE,
    CA_RETRY_SUFFIX,
    CLOSING_QUESTION_TEMPLATE,
    DAF_QUESTION_TEMPLATE,
    FOLLOW_UP_QUESTION_TEMPLATE,
    PANEL_PERSONA,
    ROUTER_HINTS,
    SUBJECT_QUESTION_TEMPLATE,
)
from app.schema.interview import CASource, ChatTurn, EnrichedArticle, RetrievedChunk
from app.tools.ca_briefing_tool import CaBriefingTool

logger = getLogger(__name__)


class GenerateQuestionNode:
    def __init__(self, llm, retriever):
        self.llm = llm
        self.retriever = retriever
        self.ca_briefing = CaBriefingTool(llm)

    def chunkPreview(self, text: str, limit: int = 200) -> str:
        cleaned = " ".join(text.split())
        return cleaned[:limit] + ("..." if len(cleaned) > limit else "")

    def pickFocusAnchor(self, state: InterviewState, profile) -> tuple[str, list[str]]:
        router_action = state.get("router_action", "pivot")
        topic_stack = list(state.get("topic_stack", []))

        if router_action in ("probe", "daf_probe", "deepen"):
            anchor = state.get("current_focus_anchor") or (topic_stack[0] if topic_stack else "your background")
            return anchor, topic_stack

        if not topic_stack:
            topic_stack = buildDafTopicStack(profile)

        anchor = topic_stack.pop(0)
        topic_stack.append(anchor)
        return anchor, topic_stack

    def pickCaArticle(self, state: InterviewState) -> tuple[EnrichedArticle, int]:
        articles = list(state.get("ca_articles", []))
        if not articles:
            return EnrichedArticle(
                title="India governance and policy developments",
                daf_anchor="general",
                detailed_insights="Recent national policy developments.",
            ), 0
        cursor = state.get("ca_article_cursor", 0) % len(articles)
        return articles[cursor], (cursor + 1) % len(articles)

    def fallbackQuestion(self, phase: str, focus_anchor: str, closing_angle: str = "") -> dict:
        anchor = focus_anchor or "your background"
        if phase == "daf_opening":
            q = f"Good morning. You mentioned {anchor} in your DAF — please introduce yourself briefly."
            voice = f"नमस्ते। आपने अपने DAF में {anchor} के बारे में लिखा है — कृपया संक्षेप में अपना परिचय दीजिए।"
        elif phase == "closing":
            theme = (closing_angle or focus_anchor or "motivation").lower()
            if "ethical" in theme:
                q = "Describe an ethical dilemma you faced and how you resolved it."
                voice = "कोई ethical dilemma बताइए जिसका सामना आपने किया और उसे आपने कैसे handle किया?"
            elif "failure" in theme or "setback" in theme:
                q = "Tell us about a failure or setback and what you learned from it."
                voice = "कोई failure या setback बताइए और उससे आपने क्या सीखा?"
            elif "not selected" in theme:
                q = "If you are not selected this time, what will be your next step?"
                voice = "अगर इस बार selection नहीं हुआ, तो आपका अगला step क्या होगा?"
            elif "service preference" in theme or "preference" in theme:
                q = "Why is your first service preference at the top of your list?"
                voice = "आपकी पहली service preference सबसे ऊपर क्यों है?"
            elif "hometown" in theme or "public service can improve" in theme:
                q = "How would you use public service to improve your hometown?"
                voice = "Public service से आप अपने hometown को कैसे बेहतर बना सकते हैं?"
            else:
                q = "Why do you want to join the civil services?"
                voice = "आप civil services क्यों join करना चाहते हैं?"
        else:
            q = f"Please elaborate on {anchor}."
            voice = f"कृपया {anchor} पर थोड़ा विस्तार से बताइए।"
        return {"question": q, "question_voice": voice}

    async def invokeLlm(self, user_prompt: str, session_id: str = "", run_name: str = "generate_question") -> dict:
        from app.observability.langfuse_client import langchainInvokeConfig

        llm = self.llm.getLlm(temperature=0.3, max_tokens=480, model=INTERVIEW_JSON_MODEL)
        try:
            llm = llm.bind(response_format={"type": "json_object"})
        except Exception:
            pass
        config = langchainInvokeConfig(
            session_id,
            run_name=run_name,
            tags=["upsc-interview", "question"],
        )
        messages = [SystemMessage(content=PANEL_PERSONA), HumanMessage(content=user_prompt)]
        last_err: Exception | None = None
        for attempt in range(2):
            try:
                response = await llm.ainvoke(messages, config=config)
                raw = llmMessageText(response)
                if not raw.strip():
                    logger.warning(f"GenerateQuestionNode empty LLM text (attempt {attempt + 1})")
                return parseJsonResponse(raw)
            except Exception as e:
                last_err = e
                logger.warning(f"GenerateQuestionNode LLM parse failed (attempt {attempt + 1}): {e}")
        if last_err:
            raise last_err
        raise RuntimeError("GenerateQuestionNode LLM failed")

    async def questionFromLlm(
        self,
        prompt: str,
        session_id: str,
        phase: str,
        focus_anchor: str,
        *,
        run_name: str = "generate_question",
        closing_angle: str = "",
    ) -> dict:
        try:
            return await self.invokeLlm(prompt, session_id, run_name=run_name)
        except Exception as e:
            logger.warning(f"GenerateQuestionNode using fallback question ({phase}): {e}")
            return self.fallbackQuestion(phase, focus_anchor, closing_angle)

    async def followUpQuestion(self, state: InterviewState, session_id: str) -> dict:
        """A question that builds on the candidate's last answer, checked by code to use their words. If the model
        fails or drifts to a new topic twice, a fixed question quotes their own words back."""
        answer = state.get("last_answer", "")
        prompt = FOLLOW_UP_QUESTION_TEMPLATE.format(
            phase=state.get("current_phase", "daf_opening"),
            question=state.get("current_question", ""),
            answer=answer,
            profile=profileSummary(state["daf_profile"]),
        )
        for attempt in range(2):
            try:
                data = await self.invokeLlm(prompt, session_id, run_name="generate_follow_up")
            except Exception as e:
                logger.warning(f"GenerateQuestionNode follow-up failed: {e}")
                break
            question = sanitizeBoardQuestion(data.get("question", ""), max_words=30)
            if question and isAboutAnswer(question, answer):
                voice = sanitizeBoardQuestion(data.get("question_voice") or question, max_words=34)
                return {"question": question, "question_voice": voice or question}
            prompt += "\nCRITICAL: your question did not use the candidate's own words. Quote them."
        quote = pickAnswerQuote(answer)
        return {
            "question": f'You said "{quote}". Why do you think so, and what would you do about it as an officer?',
            "question_voice": f'आपने कहा "{quote}"। आप ऐसा क्यों मानते हैं, और एक अधिकारी के रूप में आप इस पर क्या करेंगे?',
        }

    async def generateQuestionNode(self, state: InterviewState):
        try:
            logger.info("GenerateQuestionNode started")
            phase = state.get("current_phase", "daf_opening")
            profile = state["daf_profile"]
            session_id = state["session_id"]
            interview_mode = state.get("interview_mode", "full")
            router_action = state.get("router_action", "pivot")
            router_hint = ROUTER_HINTS.get(router_action, ROUTER_HINTS["pivot"])
            focus_anchor, topic_stack = self.pickFocusAnchor(state, profile)

            retrieved_chunks: list[RetrievedChunk] = []
            ca_source: CASource | None = None
            ca_briefing: dict | None = None
            ca_article_cursor = state.get("ca_article_cursor", 0)
            question = ""
            question_voice = ""

            if router_action == "deepen":
                data = await self.followUpQuestion(state, session_id)
                question, question_voice = data["question"], data["question_voice"]

            elif phase == "subject_probe":
                optional = profile.optional_subject or "public administration"
                focus_anchor = f"optional subject: {optional}"
                chunks = await self.retriever.hybridRetrieveAsync(optional, session_id, doc_type="syllabus")
                retrieved_chunks = [
                    RetrievedChunk(doc_type="syllabus", text=c, preview=self.chunkPreview(c))
                    for c in chunks
                ]
                prompt = SUBJECT_QUESTION_TEMPLATE.format(
                    router_hint=router_hint,
                    optional_subject=optional,
                    profile=profileSummary(profile),
                    history=historyText(state.get("chat_history", [])),
                    context="\n\n".join(chunks) if chunks else "Use standard UPSC syllabus concepts.",
                )
                data = await self.questionFromLlm(prompt, session_id, phase, focus_anchor)
                question = sanitizeBoardQuestion(data.get("question", ""), max_words=28)
                question_voice = sanitizeBoardQuestion(data.get("question_voice") or question, max_words=32)
                if not question_voice.strip():
                    question_voice = question

            elif phase == "current_affairs":
                ca_q_max = caBoardQuestionWordLimits(interview_mode)
                ca_v_max = caBoardQuestionWordLimits(interview_mode, for_voice=True)
                featured, ca_article_cursor = self.pickCaArticle(state)
                focus_anchor = featured.daf_anchor or featured.title
                query = f"{featured.title} {featured.daf_anchor}"
                chunks = await self.retriever.hybridRetrieveAsync(query, session_id, doc_type="current_affairs")
                retrieved_chunks = [
                    RetrievedChunk(
                        doc_type="current_affairs",
                        text=c,
                        preview=self.chunkPreview(c),
                        source_title=featured.title,
                    )
                    for c in chunks
                ]
                prompt = CA_QUESTION_USER_TEMPLATE.format(
                    router_hint=router_hint,
                    featured_article=formatCaArticleForPrompt(featured),
                    profile=profileSummary(profile),
                    history=historyText(state.get("chat_history", [])),
                    context="\n\n".join(chunks) if chunks else "None",
                    daf_anchor=featured.daf_anchor or "candidate profile",
                )
                data = await self.questionFromLlm(prompt, session_id, phase, focus_anchor)
                question = sanitizeCaBoardQuestion(data.get("question", ""), max_words=ca_q_max)
                question_voice = sanitizeCaBoardQuestion(
                    data.get("question_voice") or question, max_words=ca_v_max
                )

                score = caGroundingScore(question, featured)
                grounded = isCaGrounded(question, featured)
                if not grounded:
                    data = await self.questionFromLlm(
                        prompt + CA_RETRY_SUFFIX.format(article_title=featured.title),
                        session_id,
                        phase,
                        focus_anchor,
                        run_name="generate_question_ca_retry",
                    )
                    question = sanitizeCaBoardQuestion(data.get("question", ""), max_words=ca_q_max)
                    question_voice = sanitizeCaBoardQuestion(
                        data.get("question_voice") or question, max_words=ca_v_max
                    )
                    score = caGroundingScore(question, featured)
                    grounded = isCaGrounded(question, featured)

                ca_source = CASource(
                    title=featured.title,
                    daf_anchor=featured.daf_anchor,
                    source=featured.source,
                    grounded=grounded,
                    grounding_score=round(score, 3),
                )
                ca_briefing = await self.ca_briefing.generateBriefing(featured, session_id, use_llm=True)

            elif phase == "closing":
                closing_angles = buildClosingAngles(profile)
                idx = state.get("closing_angle_index", 0) % len(closing_angles)
                closing_angle = closing_angles[idx]
                focus_anchor = closing_angle
                prompt = CLOSING_QUESTION_TEMPLATE.format(
                    router_hint=router_hint,
                    closing_angle=closing_angle,
                    profile=profileSummary(profile),
                    history=historyText(state.get("chat_history", [])),
                )
                data = await self.questionFromLlm(
                    prompt, session_id, phase, focus_anchor, closing_angle=closing_angle
                )
                question = sanitizeBoardQuestion(
                    data.get("question", "Why do you want to join the civil services?"), max_words=25
                )
                question_voice = sanitizeBoardQuestion(
                    data.get("question_voice") or question, max_words=30
                )
                if not question_voice.strip():
                    question_voice = question

            else:
                prompt = DAF_QUESTION_TEMPLATE.format(
                    phase=phase,
                    router_hint=router_hint,
                    focus_anchor=focus_anchor,
                    profile=profileSummary(profile),
                    history=historyText(state.get("chat_history", [])),
                )
                data = await self.questionFromLlm(prompt, session_id, phase, focus_anchor)
                question = sanitizeBoardQuestion(
                    data.get("question", "Tell us briefly about yourself."), max_words=25
                )
                question_voice = sanitizeBoardQuestion(
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
