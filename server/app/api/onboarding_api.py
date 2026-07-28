from app.auth.dependencies import get_required_user
from app.auth.runtime import auth_manager
from app.database.crud.onboarding_crud import OnboardingCreate, onboarding_crud
from app.database.database import get_db
from app.database.telemetry import track_event
from app.helpers.email import send_profile_email
from app.schemas.onboarding import CreateOnboardingRequest, OnboardingResponse
from app.schemas.user import CurrentUser
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

# Create API router
onboarding_router = APIRouter()


@onboarding_router.post("", response_model=OnboardingResponse, status_code=201)
async def create_onboarding(
    request: CreateOnboardingRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> OnboardingResponse:
    """Create or update onboarding data for a user"""
    existing_onboarding = onboarding_crud.get_by(db, user=current_user)
    if existing_onboarding:
        onboarding = onboarding_crud.update(
            db,
            db_obj=existing_onboarding,
            obj_in=request.model_dump(exclude_unset=True, mode="json"),
        )
    else:
        onboarding = onboarding_crud.create(
            db,
            obj_in=OnboardingCreate(
                user_id=current_user.id,
                **request.model_dump(exclude_unset=True, mode="json"),
            ),
        )
    if onboarding is None:
        raise RuntimeError("onboarding_write_failed")
    prepared_onboarding: dict[str, object] = {
        "name": request.name,
        "email": str(request.email),
        "company": request.company,
        "job_titles_other": request.job_titles_other,
        "research_fields_other": request.research_fields_other,
        "reading_frequency": request.reading_frequency,
        "job_titles": [
            value.strip()
            for value in (request.job_titles or "").lower().split(",")
            if value.strip()
        ],
        "research_fields": [
            value.strip()
            for value in (request.research_fields or "").lower().split(",")
            if value.strip()
        ],
    }
    if not current_user.display_name and request.name:
        await auth_manager.update_profile(current_user.id, request.name)
    track_event(
        "onboarding_completed",
        user_id=str(current_user.id),
        properties=prepared_onboarding,
        db=db,
    )
    send_profile_email(onboarding)
    return OnboardingResponse.model_validate(onboarding)
