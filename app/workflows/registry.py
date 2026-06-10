from langgraph.graph.state import CompiledStateGraph

from app.agents.analyst_agent import analyst_graph
from app.agents.brand_extractor import brand_extractor_graph
from app.workflows.phase1_workflow import phase1_graph
from app.workflows.phase2_workflow import build_phase2_graph

AGENT_REGISTRY: dict[str, CompiledStateGraph] = {
    "brand_extractor": brand_extractor_graph,
    "analyst": analyst_graph,
    "phase1": phase1_graph,
}

__all__ = ["AGENT_REGISTRY", "build_phase2_graph"]
