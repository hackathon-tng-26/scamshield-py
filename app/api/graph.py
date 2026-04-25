from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.graph.service import get_cluster
from app.schemas.graph import GraphClusterResponse

router = APIRouter()


@router.get("/cluster/{cluster_id}", response_model=GraphClusterResponse)
def cluster(cluster_id: str, db: Session = Depends(get_db)) -> GraphClusterResponse:
    result = get_cluster(cluster_id, db)
    if result is None:
        raise HTTPException(status_code=404, detail=f"cluster {cluster_id} not found")
    return result
