from datetime import datetime, timedelta

import networkx as nx


def fan_in_distinct_senders(G: nx.DiGraph, node_id: str, window_hours: int = 2) -> int:
    if node_id not in G:
        return 0
    cutoff = datetime.utcnow() - timedelta(hours=window_hours)
    senders: set[str] = set()
    for predecessor in G.predecessors(node_id):
        data = G.get_edge_data(predecessor, node_id) or {}
        ts = data.get("timestamp")
        if ts is None or ts >= cutoff:
            senders.add(predecessor)
    return len(senders)


def velocity_in_out(G: nx.DiGraph, node_id: str, window_hours: int = 1) -> tuple[int, int]:
    if node_id not in G:
        return (0, 0)
    cutoff = datetime.utcnow() - timedelta(hours=window_hours)

    in_count = sum(
        1
        for p in G.predecessors(node_id)
        if (data := G.get_edge_data(p, node_id)) and (data.get("timestamp") is None or data["timestamp"] >= cutoff)
    )
    out_count = sum(
        1
        for s in G.successors(node_id)
        if (data := G.get_edge_data(node_id, s)) and (data.get("timestamp") is None or data["timestamp"] >= cutoff)
    )
    return (in_count, out_count)


def shortest_hops_to_offramp(G: nx.DiGraph, node_id: str) -> int | None:
    if node_id not in G:
        return None

    offramps = [n for n, attrs in G.nodes(data=True) if attrs.get("layer") == "offramp"]
    best: int | None = None
    for off in offramps:
        try:
            path_len = nx.shortest_path_length(G, source=node_id, target=off)
            if best is None or path_len < best:
                best = path_len
        except nx.NetworkXNoPath:
            continue
    return best
