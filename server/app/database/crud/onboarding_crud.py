from app.database.models import Onboarding
from app.schemas.user import CurrentUser
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session


class OnboardingBase(BaseModel):
    name: str | None = None
    email: str | None = None
    company: str | None = None
    research_fields: str | None = None
    research_fields_other: str | None = None
    job_titles: str | None = None
    job_titles_other: str | None = None
    reading_frequency: str | None = None


class OnboardingCreate(OnboardingBase):
    user_id: int


class OnboardingUpdate(OnboardingBase):
    pass


class OnboardingCrud:
    def get_by(self, db: Session, *, user: CurrentUser) -> Onboarding | None:
        return db.scalar(select(Onboarding).where(Onboarding.user_id == user.id))

    def create(self, db: Session, *, obj_in: OnboardingCreate) -> Onboarding:
        onboarding = Onboarding(**obj_in.model_dump())
        db.add(onboarding)
        db.commit()
        db.refresh(onboarding)
        return onboarding

    def update(
        self,
        db: Session,
        *,
        db_obj: Onboarding,
        obj_in: dict[str, object] | OnboardingUpdate,
    ) -> Onboarding:
        changes = (
            obj_in
            if isinstance(obj_in, dict)
            else obj_in.model_dump(exclude_unset=True)
        )
        for field, value in changes.items():
            setattr(db_obj, field, value)
        db.commit()
        db.refresh(db_obj)
        return db_obj


# Create a single instance to use throughout the application
onboarding_crud = OnboardingCrud()
