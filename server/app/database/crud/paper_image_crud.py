import logging
import uuid

from app.database.models import PaperImage
from app.policies.documents import get_document_access
from app.schemas.user import CurrentUser
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# Define Pydantic models for type safety
class PaperImageBase(BaseModel):
    paper_id: uuid.UUID
    s3_object_key: str
    format: str
    size_bytes: int
    width: int
    height: int
    page_number: int
    image_index: int
    placeholder_id: str
    caption: str | None = None


class PaperImageCreate(PaperImageBase):
    pass


class PaperImageUpdate(BaseModel):
    s3_object_key: str | None = None
    format: str | None = None
    size_bytes: int | None = None
    width: int | None = None
    height: int | None = None
    page_number: int | None = None
    image_index: int | None = None
    caption: str | None = None
    placeholder_id: str | None = None


# Document Image CRUD that inherits from the base CRUD
class PaperImageCRUD:
    """CRUD operations specifically for PaperImage model"""

    def create(
        self,
        db: Session,
        *,
        obj_in: PaperImageCreate,
        user: CurrentUser,
    ) -> PaperImage:
        if (
            get_document_access(
                db,
                document_id=obj_in.paper_id,
                user_id=user.id,
            )
            is None
        ):
            raise ValueError("Paper is not accessible")
        image = PaperImage(**obj_in.model_dump())
        db.add(image)
        db.commit()
        db.refresh(image)
        return image

    def get(
        self,
        db: Session,
        *,
        id: object,
        user: CurrentUser,
    ) -> PaperImage | None:
        try:
            image_id = uuid.UUID(str(id))
        except (TypeError, ValueError):
            return None
        image = db.get(PaperImage, image_id)
        if image is None:
            return None
        if (
            get_document_access(
                db,
                document_id=image.paper_id,
                user_id=user.id,
            )
            is None
        ):
            return None
        return image

    def create_with_paper_validation(
        self, db: Session, *, obj_in: PaperImageCreate, user: CurrentUser
    ) -> PaperImage | None:
        """
        Create a paper image with validation that the paper exists and belongs to the user
        """
        # Verify the paper exists and belongs to the user
        if (
            get_document_access(
                db,
                document_id=obj_in.paper_id,
                user_id=user.id,
            )
            is None
        ):
            raise ValueError(
                f"Paper with ID {obj_in.paper_id} not found or doesn't belong to user"
            )

        return self.create(db, obj_in=obj_in, user=user)

    def create_multiple_with_paper_validation(
        self, db: Session, *, images: list[PaperImageCreate], user: CurrentUser
    ) -> list[PaperImage]:
        """
        Create multiple paper images with validation that the papers exist and belong to the user
        """
        if not images:
            return []

        # Get all unique paper IDs
        paper_ids = list(set(img.paper_id for img in images))

        # Verify all papers exist and belong to the user
        existing_paper_ids = {
            paper_id
            for paper_id in paper_ids
            if get_document_access(
                db,
                document_id=paper_id,
                user_id=user.id,
            )
            is not None
        }

        # Check if any paper IDs are missing
        missing_paper_ids = set(paper_ids) - existing_paper_ids
        if missing_paper_ids:
            raise ValueError(
                f"Papers with IDs {missing_paper_ids} not found or don't belong to user"
            )

        # Create all images
        created_images = []
        for image in images:
            created_image = self.create(db, obj_in=image, user=user)
            if created_image:
                created_images.append(created_image)

        return created_images

    def get_by_paper_id(
        self, db: Session, *, paper_id: str, user: CurrentUser
    ) -> list[PaperImage]:
        """
        Get all images for a specific paper
        """
        # First verify the paper belongs to the user
        try:
            document_id = uuid.UUID(paper_id)
        except ValueError as exc:
            raise ValueError("Invalid paper ID") from exc
        if (
            get_document_access(
                db,
                document_id=document_id,
                user_id=user.id,
            )
            is None
        ):
            raise ValueError(
                f"Paper with ID {paper_id} not found or doesn't belong to user"
            )

        return list(
            db.scalars(
                select(PaperImage)
                .where(PaperImage.paper_id == paper_id)
                .order_by(PaperImage.page_number, PaperImage.image_index)
            ).all()
        )


# Create a single instance to use throughout the application
paper_image_crud = PaperImageCRUD()
