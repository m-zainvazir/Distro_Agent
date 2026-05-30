from langgraph.graph.state import CompiledStateGraph

from app.agents.analyst_agent import analyst_graph
from app.agents.brand_extractor import brand_extractor_graph

AGENT_REGISTRY: dict[str, CompiledStateGraph] = {
    "brand_extractor": brand_extractor_graph,
    "analyst": analyst_graph,
}
