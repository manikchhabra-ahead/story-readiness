from langgraph.graph import StateGraph

from app.graph.nodes import (
    determine_category,
    evaluate_story,
    generate_output,
    jira_write,
)
from app.graph.state import StoryState


def build_graph() -> StateGraph:
    graph = StateGraph(StoryState)

    graph.add_node("evaluate_story", evaluate_story)
    graph.add_node("generate_output", generate_output)
    graph.add_node("determine_category", determine_category)
    graph.add_node("jira_write", jira_write)

    graph.set_entry_point("evaluate_story")
    graph.add_edge("evaluate_story", "generate_output")
    graph.add_edge("generate_output", "determine_category")
    graph.add_edge("determine_category", "jira_write")
    graph.set_finish_point("jira_write")

    return graph.compile()
