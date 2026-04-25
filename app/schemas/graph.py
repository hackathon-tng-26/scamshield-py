from pydantic import BaseModel, ConfigDict


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    layer: str
    mule_likelihood: float = 0.0
    x: float = 0.0
    y: float = 0.0


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    amount: float = 0.0


class GraphClusterResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster_id: str
    focus_node_id: str | None
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    hops_to_offramp: int | None = None
