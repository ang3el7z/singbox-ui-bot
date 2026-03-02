from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from api.database import get_db, FederationNode
from api.services.federation_service import fed_client
from api.deps import require_any_auth, audit

router = APIRouter()


class NodeCreate(BaseModel):
    name: str
    url: str
    secret: str
    role: str = "node"


class NodeResponse(BaseModel):
    id: int
    name: str
    url: str
    role: str
    is_active: bool
    last_ping: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class BridgeCreate(BaseModel):
    node_ids: List[int]  # ordered list of node IDs to chain


@router.get("/", response_model=List[NodeResponse])
async def list_nodes(db: AsyncSession = Depends(get_db), auth: dict = Depends(require_any_auth)):
    result = await db.execute(select(FederationNode).order_by(FederationNode.created_at))
    return result.scalars().all()


@router.post("/", status_code=201, response_model=NodeResponse)
async def add_node(
    body: NodeCreate,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_any_auth),
):
    is_online = await fed_client.ping_node(body.url, body.secret)
    node = FederationNode(
        name=body.name,
        url=body.url.rstrip("/"),
        secret=body.secret,
        role=body.role,
        is_active=is_online,
    )
    db.add(node)
    await db.commit()
    await db.refresh(node)
    await audit(auth["actor"], "add_fed_node", f"name={body.name} url={body.url} online={is_online}")
    return node


@router.get("/{node_id}", response_model=NodeResponse)
async def get_node(node_id: int, db: AsyncSession = Depends(get_db), auth: dict = Depends(require_any_auth)):
    node = await db.get(FederationNode, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


@router.delete("/{node_id}")
async def delete_node(node_id: int, db: AsyncSession = Depends(get_db), auth: dict = Depends(require_any_auth)):
    node = await db.get(FederationNode, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    await db.delete(node)
    await db.commit()
    await audit(auth["actor"], "delete_fed_node", f"id={node_id}")
    return {"detail": "Deleted"}


@router.post("/{node_id}/ping")
async def ping_node(node_id: int, db: AsyncSession = Depends(get_db), auth: dict = Depends(require_any_auth)):
    node = await db.get(FederationNode, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    ok = await fed_client.ping_node(node.url, node.secret)
    node.is_active = ok
    node.last_ping = datetime.utcnow()
    db.add(node)
    await db.commit()
    return {"online": ok, "node": node.name}


@router.post("/ping-all")
async def ping_all(db: AsyncSession = Depends(get_db), auth: dict = Depends(require_any_auth)):
    results = await fed_client.ping_all_nodes()
    return results


@router.post("/bridge")
async def create_bridge(body: BridgeCreate, db: AsyncSession = Depends(get_db), auth: dict = Depends(require_any_auth)):
    if len(body.node_ids) < 1:
        raise HTTPException(status_code=400, detail="Need at least 1 remote node")
    # fed_client.create_bridge requires at least 2 chained nodes; 1 node = simple exit
    nodes = []
    for nid in body.node_ids:
        node = await db.get(FederationNode, nid)
        if not node:
            raise HTTPException(status_code=404, detail=f"Node {nid} not found")
        nodes.append({"id": node.id, "name": node.name, "url": node.url, "secret": node.secret})
    try:
        await fed_client.create_bridge(nodes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    chain = " → ".join(["(this server)"] + [n["name"] for n in nodes] + ["Internet"])
    await audit(auth["actor"], "create_bridge", chain)
    return {"detail": "Bridge created", "chain": chain}


@router.get("/topology")
async def topology(db: AsyncSession = Depends(get_db), auth: dict = Depends(require_any_auth)):
    from api.config import settings
    result = await db.execute(select(FederationNode).order_by(FederationNode.created_at))
    nodes = result.scalars().all()
    return {
        "master": settings.domain or "this server",
        "nodes": [
            {
                "id": n.id, "name": n.name, "url": n.url,
                "role": n.role, "is_active": n.is_active,
                "last_ping": n.last_ping.isoformat() if n.last_ping else None,
            }
            for n in nodes
        ],
    }
