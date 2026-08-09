from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .dependencies import invalidate_model_cache, nodes

router = APIRouter(prefix="/api/nodes")


@router.get("")
async def list_nodes() -> list[dict]:
    return await nodes().list()


@router.post("/{node_id}/wake")
async def wake_node(node_id: str) -> dict:
    try:
        result = await nodes().wake(node_id)
        # A waking node is about to offer models it could not a moment ago.
        invalidate_model_cache()
        return result
    except KeyError as exc:
        raise HTTPException(404, "Node not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
