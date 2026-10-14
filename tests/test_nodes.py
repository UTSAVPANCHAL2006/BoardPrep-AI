"""The real interview nodes on the CTO's test (skip every question), with a fake model. No network calls."""

import asyncio
import json

import pytest

pytest.importorskip("langchain_core")

from app.agents.nodes.evaluate_answer_node import EvaluateAnswerNode  # noqa: E402
from app.agents.nodes.feedback_report_node import FeedbackReportNode  # noqa: E402
from app.schema.interview import DAFProfile  # noqa: E402


class FakeReply:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeChat:
    def __init__(self, owner: "FakeLlm") -> None:
        self.owner = owner

    def bind(self, **_: object) -> "FakeChat":
        return self

    async def ainvoke(self, *_: object, **__: object) -> FakeReply:
        self.owner.calls += 1
        return FakeReply(json.dumps(self.owner.reply))


class FakeLlm:
    """Generous on purpose: if any of its 8s reach a skipped interview, the test fails."""

    def __init__(self) -> None:
        self.calls = 0
        self.reply = {
            "overall_summary": "Strong, confident candidate.",
            "strengths": ['"skip" shows clarity'],
            "improvements": ["Answer every question, even briefly."],
            "priority_actions": ["Practise answering about your hometown."],
            "question_feedback": [{"turn": 1, "improve": "Share what you know.", "better_answer": "Two key points."}],
            "scores": {"clarity": 8, "structure": 8, "daf_consistency": 8, "subject_depth": 8, "current_affairs": 8, "confidence": 8},
        }

    def getLlm(self, **_: object) -> FakeChat:
        return FakeChat(self)


def testSkippingEveryQuestionEndToEndScoresZeroWithCoaching() -> None:
    llm = FakeLlm()
    evaluate = EvaluateAnswerNode(llm)
    state: dict = {"daf_profile": DAFProfile(hometown="Jaipur"), "session_id": "test", "evaluation_log": [], "chat_history": []}
    for phase in ("daf_opening", "daf_opening", "subject_probe", "current_affairs"):
        state.update({"current_phase": phase, "current_question": f"A {phase} question?", "last_answer": "skip"})
        update = asyncio.run(evaluate.evaluateAnswerNode(state))
        assert update["last_evaluation"].answered is False
        state.update(update)
    assert llm.calls == 0  # a skip is judged by rule; the model never grades it
    assert state["follow_up_count"] == 4  # the interview moves on after each skip

    report = asyncio.run(FeedbackReportNode(llm).feedbackReportNode(state))["feedback_report"]
    assert all(score in (0, None) for score in report["scores"].values())
    assert report["strengths"] == []
    assert report["question_feedback"][0]["better_answer"] == "Two key points."  # still coached


class BrokenLlm:
    """Every call fails, like a timeout or a rate limit."""

    calls = 0

    def getLlm(self, **_: object) -> "BrokenLlm":
        return self

    def bind(self, **_: object) -> "BrokenLlm":
        return self

    async def ainvoke(self, *_: object, **__: object) -> None:
        BrokenLlm.calls += 1
        raise TimeoutError("model timed out")


def testAFailingModelNeverEndsTheInterviewOrLosesTheReport() -> None:
    llm = BrokenLlm()
    evaluate = EvaluateAnswerNode(llm)
    state: dict = {"daf_profile": DAFProfile(hometown="Panchkula", hobbies=["badminton"]), "session_id": "t",
                   "evaluation_log": [], "chat_history": []}  # fmt: skip
    answers = [
        "Growing up in Panchkula, I saw planned sectors work because zoning kept traffic away from homes. "
        "For example, Sector 5 has green belts. However, rents rose. So planning must include affordable housing.",
        "skip",
        "Badminton taught me discipline.",
    ]
    for number, answer in enumerate(answers, 1):
        state.update({"current_phase": "daf_opening", "current_question": f"Question {number}: how has it shaped you?", "last_answer": answer})
        state.update(asyncio.run(evaluate.evaluateAnswerNode(state)))
    log = state["evaluation_log"]
    assert [entry["clarity"] for entry in log] == ["clear", "off_topic", "vague"]  # code judged both real answers
    assert state["follow_up_count"] == 3

    report = asyncio.run(FeedbackReportNode(llm).feedbackReportNode(state))["feedback_report"]
    assert report["coverage"] == {"answered": 2, "asked": 3, "max_score": 7}
    assert report["scores"]["clarity"] > 0 and report["question_feedback"][1]["status"] == "skipped"
    built = {row["item"]: row["ok"] for row in report["question_feedback"][0]["checklist"]}
    assert built["reason"] and built["example"] and built["balance"] and built["conclusion"]


# ---------- follow-ups: a real board digs into a good answer once, using the candidate's own words ----------

from app.agents.nodes.follow_up_router_node import FollowUpRouterNode  # noqa: E402
from app.agents.nodes.generate_question_node import GenerateQuestionNode  # noqa: E402
from app.schema.interview import AnswerEvaluation  # noqa: E402

PANCHKULA = (
    "Growing up in Panchkula showed me that planned sectors and green belts make services easy to reach, "
    "but informal settlements on the edges still lack water."
)


def routeAfter(clarity: str, previous: str, phase: str = "daf_opening", answered: bool = True) -> str:
    state = {"current_phase": phase, "phase_exchange_count": 1, "follow_up_count": 1, "exchanges_per_phase": 3,
             "router_action": previous, "last_evaluation": AnswerEvaluation(answered=answered, clarity=clarity)}  # fmt: skip
    return FollowUpRouterNode().followUpRouterNode(state)["router_action"]


def testAGoodAnswerIsFollowedUpOnceThenTheBoardMovesOn() -> None:
    assert routeAfter("clear", "pivot") == "deepen"
    assert routeAfter("clear", "deepen") == "pivot"  # never a follow-up of a follow-up
    assert routeAfter("clear", "pivot", phase="closing") == "pivot"  # the closing round keeps its themes
    assert routeAfter("off_topic", "pivot", answered=False) == "pivot"  # a skip is never dug into


class QuestionLlm(FakeLlm):
    def __init__(self, question: str) -> None:
        super().__init__()
        self.reply = {"question": question, "question_voice": "आपने कहा..."}


def followUp(llm: object) -> str:
    node = GenerateQuestionNode(llm, retriever=None)
    state = {"current_phase": "daf_opening", "current_question": "How did Panchkula shape you?", "last_answer": PANCHKULA,
             "daf_profile": DAFProfile(hometown="Panchkula"), "session_id": "t", "router_action": "deepen",
             "chat_history": [], "topic_stack": ["hometown: Panchkula"], "current_focus_anchor": "hometown: Panchkula"}  # fmt: skip
    return asyncio.run(node.generateQuestionNode(state))["current_question"]


def testAFollowUpBuildsOnTheCandidatesOwnWords() -> None:
    asked = 'You said "informal settlements on the edges still lack water". As a DM, what would you do first?'
    assert followUp(QuestionLlm(asked)) == asked


def testAFollowUpThatChangesTopicIsReplacedByTheirOwnWords() -> None:
    llm = QuestionLlm("What is your view on India's foreign policy towards China?")  # a new topic, not a follow-up
    question = followUp(llm)
    assert llm.calls == 2 and question.startswith('You said "Growing up in Panchkula showed me that')
    assert followUp(BrokenLlm()).startswith('You said "')  # no model at all: the board still follows up
