from app.auth.dependencies import get_required_user
from app.schemas.user import CurrentUser
from dotenv import load_dotenv
from fastapi import APIRouter, Depends

load_dotenv()

# Create API router with prefix
router = APIRouter()


@router.get("/me", response_model=CurrentUser)
async def get_me(
    current_user: CurrentUser = Depends(get_required_user),
) -> CurrentUser:
    return current_user


@router.get("/health")
async def health_check() -> dict[str, str]:
    """
    Health check endpoint to verify the API is running
    """
    return {"status": "healthy", "message": "Service is running"}
