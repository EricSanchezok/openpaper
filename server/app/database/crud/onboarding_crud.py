from app.database.crud.base_crud import CRUDBase
from app.database.models import Onboarding
from pydantic import BaseModel


class OnboardingBase(BaseModel):
    name: str | None = None
    email: str | None = None
    company: str | None = None
    research_fields: str | None = None
    research_fields_other: str | None = None
    job_titles: str | None = None
    job_titles_other: str | None = None
    reading_frequency: str | None = None
    referral_source: str | None = None
    referral_source_other: str | None = None


class OnboardingCreate(OnboardingBase):
    user_id: int


class OnboardingUpdate(OnboardingBase):
    pass


class OnboardingCrud(CRUDBase[Onboarding, OnboardingCreate, OnboardingUpdate]):
    """CRUD operations specifically for Onboarding model"""

    pass


# Create a single instance to use throughout the application
onboarding_crud = OnboardingCrud(Onboarding)
