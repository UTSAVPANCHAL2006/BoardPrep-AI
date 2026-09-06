from langgraph.graph import END, START, StateGraph

from app.agents.nodes.evaluate_answer_node import EvaluateAnswerNode
from app.agents.nodes.feedback_report_node import FeedbackReportNode
from app.agents.nodes.follow_up_router_node import FollowUpRouterNode
from app.agents.nodes.generate_question_node import GenerateQuestionNode
from app.agents.router import interview_router
from app.agents.state import InterviewState
from app.common.logger import get_logger

logger = get_logger(__name__)


class InterviewGraph:
    def __init__(self, llm, retriever):
        self.llm = llm
        self.retriever = retriever
        self.question_graph = self.build_question_graph()
        self.turn_graph = self.build_turn_graph()

    def build_question_graph(self):
        graph_builder = StateGraph(InterviewState)
        gen_node = GenerateQuestionNode(self.llm, self.retriever)
        graph_builder.add_node("generate_question", gen_node.generate_question_node)
        graph_builder.add_edge(START, "generate_question")
        graph_builder.add_edge("generate_question", END)
        return graph_builder.compile()

    def build_turn_graph(self):
        graph_builder = StateGraph(InterviewState)
        eval_node = EvaluateAnswerNode(self.llm)
        router_node = FollowUpRouterNode()
        gen_node = GenerateQuestionNode(self.llm, self.retriever)
        feedback_node = FeedbackReportNode(self.llm)

        graph_builder.add_node("evaluate_answer", eval_node.evaluate_answer_node)
        graph_builder.add_node("follow_up_router", router_node.follow_up_router_node)
        graph_builder.add_node("generate_question", gen_node.generate_question_node)
        graph_builder.add_node("feedback", feedback_node.feedback_report_node)

        graph_builder.add_edge(START, "evaluate_answer")
        graph_builder.add_edge("evaluate_answer", "follow_up_router")
        graph_builder.add_conditional_edges(
            "follow_up_router",
            interview_router,
            {"generate_question": "generate_question", "feedback": "feedback"},
        )
        graph_builder.add_edge("generate_question", END)
        graph_builder.add_edge("feedback", END)

        return graph_builder.compile()

    async def run_first_question(self, state):
        logger.info("InterviewGraph: running first question")
        return await self.question_graph.ainvoke(state)

    async def run_turn(self, state):
        logger.info("InterviewGraph: running turn")
        return await self.turn_graph.ainvoke(state)
