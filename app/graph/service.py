import networkx as nx
from sqlalchemy.orm import Session

from app.graph.builder import build_graph
from app.graph.patterns import shortest_hops_to_offramp
from app.models import User
from app.schemas.graph import GraphClusterResponse, GraphEdge, GraphNode


_layout_cache: dict[str, dict[str, tuple[float, float]]] = {}


def get_cluster(cluster_id: str, db: Session) -> GraphClusterResponse | None:
    focus = (
        db.query(User)
        .filter(User.mule_pattern_tag == cluster_id)
        .order_by(User.mule_likelihood.desc())
        .first()
    )
    if focus is None:
        return None

    G = build_graph(db)

    cluster_ids = {u.id for u in db.query(User).filter(User.mule_pattern_tag == cluster_id).all()}
    extended_ids: set[str] = set(cluster_ids)
    for node in cluster_ids:
        if node in G:
            extended_ids.update(list(G.predecessors(node))[:5])
            extended_ids.update(list(G.successors(node))[:5])

    offramps = [n for n, attrs in G.nodes(data=True) if attrs.get("layer") == "offramp"]
    extended_ids.update(offramps[:2])

    subgraph = G.subgraph(extended_ids).copy()
    layout = _get_or_compute_layout(cluster_id, subgraph)

    nodes = [
        GraphNode(
            id=node,
            label=attrs.get("label") or node,
            layer=attrs.get("layer", "victim"),
            mule_likelihood=float(attrs.get("mule_likelihood") or 0.0),
            x=float(layout.get(node, (0.0, 0.0))[0]),
            y=float(layout.get(node, (0.0, 0.0))[1]),
        )
        for node, attrs in subgraph.nodes(data=True)
    ]

    edges = [
        GraphEdge(source=u, target=v, amount=float(subgraph[u][v].get("amount") or 0.0))
        for u, v in subgraph.edges()
    ]

    hops = shortest_hops_to_offramp(G, focus.id)

    return GraphClusterResponse(
        cluster_id=cluster_id,
        focus_node_id=focus.id,
        nodes=nodes,
        edges=edges,
        hops_to_offramp=hops,
    )


def _get_or_compute_layout(cluster_id: str, G: nx.Graph) -> dict[str, tuple[float, float]]:
    cached = _layout_cache.get(cluster_id)
    if cached is not None and all(n in cached for n in G.nodes()):
        return cached
    positions = nx.spring_layout(G, seed=7, k=0.9, iterations=60)
    layout = {n: (float(p[0]), float(p[1])) for n, p in positions.items()}
    _layout_cache[cluster_id] = layout
    return layout
