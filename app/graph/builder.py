from datetime import datetime, timedelta

import networkx as nx
from sqlalchemy.orm import Session

from app.models import Transaction, User


def build_graph(db: Session, within_days: int = 30) -> nx.DiGraph:
    G: nx.DiGraph = nx.DiGraph()
    for user in db.query(User).all():
        G.add_node(
            user.id,
            label=user.name,
            phone=user.phone,
            layer=_layer_for(user),
            mule_likelihood=float(user.mule_likelihood or 0.0),
            mule_pattern_tag=user.mule_pattern_tag,
        )

    cutoff = datetime.utcnow() - timedelta(days=within_days)
    txns = db.query(Transaction).filter(Transaction.timestamp >= cutoff).all()
    for txn in txns:
        if G.has_node(txn.sender_id) and G.has_node(txn.recipient_id):
            G.add_edge(txn.sender_id, txn.recipient_id, amount=txn.amount, timestamp=txn.timestamp)

    return G


def _layer_for(user: User) -> str:
    if user.account_type == "offramp":
        return "offramp"
    if user.account_type != "mule":
        return "victim"
    tag = user.mule_pattern_tag or ""
    if "T1" in user.id or user.mule_likelihood >= 0.85:
        return "t1"
    if "T2" in user.id:
        return "t2"
    if "T3" in user.id:
        return "t3"
    return "t1"
