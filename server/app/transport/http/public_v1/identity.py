from app.shared.application import Actor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends

router = APIRouter()


@router.get("/me", response_model=Actor)
async def get_me(
    actor: Actor = Depends(get_required_user),
) -> Actor:
    return actor
