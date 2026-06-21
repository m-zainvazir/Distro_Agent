from langgraph.graph.state import CompiledStateGraph

from app.agents.analyst_agent import analyst_graph
from app.agents.brand_extractor import brand_extractor_graph
from app.agents.retention_agent import build_retention_graph
from app.workflows.phase1_workflow import phase1_graph
from app.workflows.phase2_workflow import build_phase2_graph

AGENT_REGISTRY: dict[str, CompiledStateGraph] = {
    "brand_extractor": brand_extractor_graph,
    "analyst": analyst_graph,
    "phase1": phase1_graph,
}

# HITL graphs that require a checkpointer are exposed as factories, not compiled
# singletons (same pattern as phase2).
__all__ = ["AGENT_REGISTRY", "build_phase2_graph", "build_retention_graph"]
