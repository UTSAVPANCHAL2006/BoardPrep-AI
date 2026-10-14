"""The interview as a LangGraph flow: evaluate the answer -> pick the next move -> ask the next question,
and write the feedback report when the interview ends."""

from langgraph.graph import END, START, StateGraph

from app.agents.nodes.evaluate_answer_node import EvaluateAnswerNode
from app.agents.nodes.feedback_report_node import FeedbackReportNode
from app.agents.nodes.follow_up_router_node import FollowUpRouterNode
from app.agents.nodes.generate_question_node import GenerateQuestionNode
from app.agents.router import interviewRouter
from app.agents.state import InterviewState
from app.common.logger import getLogger

logger = getLogger(__name__)


class InterviewGraph:
    def __init__(self, llm, retriever):
        self.llm = llm
        self.retriever = retriever
        self.question_graph = self.buildQuestionGraph()
        self.turn_graph = self.buildTurnGraph()

    def buildQuestionGraph(self):
        graph_builder = StateGraph(InterviewState)
        gen_node = GenerateQuestionNode(self.llm, self.retriever)
        graph_builder.add_node("generate_question", gen_node.generateQuestionNode)
        graph_builder.add_edge(START, "generate_question")
        graph_builder.add_edge("generate_question", END)
        return graph_builder.compile()

    def buildTurnGraph(self):
        graph_builder = StateGraph(InterviewState)
        eval_node = EvaluateAnswerNode(self.llm)
        router_node = FollowUpRouterNode()
        gen_node = GenerateQuestionNode(self.llm, self.retriever)
        feedback_node = FeedbackReportNode(self.llm)

        graph_builder.add_node("evaluate_answer", eval_node.evaluateAnswerNode)
        graph_builder.add_node("follow_up_router", router_node.followUpRouterNode)
        graph_builder.add_node("generate_question", gen_node.generateQuestionNode)
        graph_builder.add_node("feedback", feedback_node.feedbackReportNode)

        graph_builder.add_edge(START, "evaluate_answer")
        graph_builder.add_edge("evaluate_answer", "follow_up_router")
        graph_builder.add_conditional_edges(
            "follow_up_router",
            interviewRouter,
            {"generate_question": "generate_question", "feedback": "feedback"},
        )
        graph_builder.add_edge("generate_question", END)
        graph_builder.add_edge("feedback", END)

        return graph_builder.compile()

    async def runFirstQuestion(self, state):
        logger.info("InterviewGraph: running first question")
        return await self.question_graph.ainvoke(state)

    async def runTurn(self, state):
        logger.info("InterviewGraph: running turn")
        return await self.turn_graph.ainvoke(state)
