import warnings
from io import BytesIO

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.v1.admin import require_admin
from app.api.v1.dependencies import require_owner
from app.core.config import settings
from app.db.database import get_db
from app.integrations.photo_storage import LocalPrivatePhotoStorage, PhotoStorage
from app.models import Amenity, Owner, PG, PGPhoto
from app.services.listing_visibility import public_owner_eligibility
from app.schemas.photo import (
    AmenityIdsRequest,
    AmenityOut,
    AdminPhotoOut,
    OwnerPhotoOut,
    PGMediaOut,
    PhotoCaptionUpdate,
    PhotoOrderRequest,
    PhotoReviewRequest,
    PhotoOut,
    PendingPhotoOut,
)


router = APIRouter(tags=["PG Media"])
photo_storage: PhotoStorage = LocalPrivatePhotoStorage(settings.photo_storage_dir)
_SUPPORTED_IMAGES = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
}
_MAX_IMAGE_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = _MAX_IMAGE_PIXELS


def _owned_pg(db: Session, owner: Owner, pg_id: int, *, lock: bool = False) -> PG:
    statement = select(PG).where(PG.id == pg_id, PG.owner_id == owner.id)
    if lock:
        statement = statement.with_for_update()
    pg = db.scalar(statement)
    if pg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PG listing not found",
        )
    return pg


def _public_photo_url(photo_id: int) -> str:
    return f"{settings.api_v1_prefix}/photos/{photo_id}/content"


def _owner_photo_url(photo_id: int) -> str:
    return f"{settings.api_v1_prefix}/owners/me/photos/{photo_id}/content"


def _photo_out(photo: PGPhoto) -> PhotoOut:
    return PhotoOut(
        id=photo.id,
        pg_id=photo.pg_id,
        url=_public_photo_url(photo.id),
        caption=photo.caption,
        display_order=photo.display_order,
        is_cover=photo.is_cover,
        created_at=photo.created_at,
    )


def _owner_photo_out(photo: PGPhoto) -> OwnerPhotoOut:
    return OwnerPhotoOut(
        id=photo.id,
        pg_id=photo.pg_id,
        url=_owner_photo_url(photo.id),
        caption=photo.caption,
        display_order=photo.display_order,
        is_cover=photo.is_cover,
        created_at=photo.created_at,
        review_status=photo.review_status,
    )


async def _read_valid_image(upload: UploadFile) -> tuple[bytes, str, str]:
    content = bytearray()
    while True:
        chunk = await upload.read(64 * 1024)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > settings.photo_max_upload_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Image exceeds the configured upload size limit",
            )
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Uploaded image is empty",
        )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                image_format = image.format
                if image_format not in _SUPPORTED_IMAGES:
                    raise HTTPException(
                        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                        detail="Only JPEG, PNG, and WebP images are supported",
                    )
                if image.width * image.height > _MAX_IMAGE_PIXELS:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail="Image dimensions exceed the supported limit",
                    )
                image.verify()
            with Image.open(BytesIO(content)) as image:
                image.load()
    except HTTPException:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Uploaded file is not a valid supported image",
        ) from None

    extension, media_type = _SUPPORTED_IMAGES[image_format]
    return bytes(content), extension, media_type


def _photo_file_response(photo: PGPhoto, *, private: bool) -> FileResponse:
    try:
        path = photo_storage.get_path(photo.storage_key)
    except (FileNotFoundError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Photo file not found",
        ) from None
    headers = {"Cache-Control": "private, no-store"} if private else {
        "Cache-Control": "public, max-age=300"
    }
    return FileResponse(
        path,
        media_type=photo.media_type,
        headers=headers,
    )


@router.get("/amenities", response_model=list[AmenityOut])
def list_amenities(db: Session = Depends(get_db)):
    return db.scalars(
        select(Amenity).where(Amenity.is_active.is_(True)).order_by(Amenity.id)
    ).all()


@router.get("/pgs/{pg_id}/media", response_model=PGMediaOut)
def get_public_pg_media(pg_id: int, db: Session = Depends(get_db)):
    pg = db.scalar(
        select(PG)
        .where(
            PG.id == pg_id,
            PG.is_active.is_(True),
            PG.verification_status == "verified",
            public_owner_eligibility(),
        )
        .options(selectinload(PG.photos), selectinload(PG.amenities))
    )
    if pg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PG listing not found",
        )

    photos = sorted(
        (
            photo
            for photo in pg.photos
            if photo.review_status == "approved"
        ),
        key=lambda photo: (photo.display_order, photo.id),
    )
    public_photos = [_photo_out(photo) for photo in photos]
    cover = next((photo for photo in public_photos if photo.is_cover), None)
    return PGMediaOut(
        pg_id=pg.id,
        photos=public_photos,
        cover_photo=cover,
        amenities=[
            AmenityOut.model_validate(amenity)
            for amenity in sorted(
                (amenity for amenity in pg.amenities if amenity.is_active),
                key=lambda amenity: amenity.id,
            )
        ],
    )


@router.put(
    "/owners/me/pgs/{pg_id}/amenities",
    response_model=list[AmenityOut],
)
def set_pg_amenities(
    pg_id: int,
    payload: AmenityIdsRequest,
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        pg = _owned_pg(db, owner, pg_id, lock=True)
        amenity_ids = payload.amenity_ids
        if len(set(amenity_ids)) != len(amenity_ids):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Amenity IDs must not contain duplicates",
            )
        amenities = (
            db.scalars(
                select(Amenity)
                .where(
                    Amenity.id.in_(amenity_ids),
                    Amenity.is_active.is_(True),
                )
                .order_by(Amenity.id)
            ).all()
            if amenity_ids
            else []
        )
        if len(amenities) != len(amenity_ids):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="One or more amenity IDs are invalid or inactive",
            )
        pg.amenities = amenities
        db.commit()
        return [AmenityOut.model_validate(item) for item in amenities]
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


@router.delete(
    "/owners/me/pgs/{pg_id}/amenities/{amenity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_pg_amenity(
    pg_id: int,
    amenity_id: int,
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    pg = _owned_pg(db, owner, pg_id)
    amenity = next(
        (item for item in pg.amenities if item.id == amenity_id),
        None,
    )
    if amenity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Amenity association not found",
        )
    pg.amenities.remove(amenity)
    db.commit()


@router.get(
    "/owners/me/pgs/{pg_id}/photos",
    response_model=list[OwnerPhotoOut],
)
def list_owner_photos(
    pg_id: int,
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    _owned_pg(db, owner, pg_id)
    photos = db.scalars(
        select(PGPhoto)
        .where(PGPhoto.pg_id == pg_id)
        .order_by(PGPhoto.display_order, PGPhoto.id)
    ).all()
    return [_owner_photo_out(photo) for photo in photos]


@router.post(
    "/owners/me/pgs/{pg_id}/photos",
    response_model=OwnerPhotoOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_pg_photo(
    pg_id: int,
    file: UploadFile = File(...),
    caption: str | None = Form(default=None, max_length=300),
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    storage_key = None
    try:
        content, extension, media_type = await _read_valid_image(file)
        _owned_pg(db, owner, pg_id, lock=True)
        photo_count = db.scalar(
            select(func.count(PGPhoto.id)).where(PGPhoto.pg_id == pg_id)
        )
        if photo_count >= settings.photo_max_per_pg:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This PG has reached its photo limit",
            )

        try:
            storage_key = photo_storage.store(content, extension)
        except OSError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Photo storage is unavailable",
            ) from None

        current_order = db.scalar(
            select(func.coalesce(func.max(PGPhoto.display_order), -1)).where(
                PGPhoto.pg_id == pg_id
            )
        )
        photo = PGPhoto(
            pg_id=pg_id,
            storage_key=storage_key,
            media_type=media_type,
            caption=caption.strip() if caption and caption.strip() else None,
            display_order=current_order + 1,
            is_cover=False,
            review_status="pending",
        )
        db.add(photo)
        db.commit()
        db.refresh(photo)
        return _owner_photo_out(photo)
    except HTTPException:
        db.rollback()
        if storage_key is not None:
            try:
                photo_storage.delete(storage_key)
            except OSError:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Photo upload failed and stored file cleanup is pending",
                ) from None
        raise
    except Exception:
        db.rollback()
        if storage_key is not None:
            try:
                photo_storage.delete(storage_key)
            except OSError:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Photo upload failed and stored file cleanup is pending",
                ) from None
        raise
    finally:
        await file.close()


@router.get(
    "/owners/me/photos/{photo_id}/content",
    response_class=FileResponse,
)
def get_owner_photo_content(
    photo_id: int,
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    photo = db.scalar(
        select(PGPhoto)
        .join(PG, PG.id == PGPhoto.pg_id)
        .where(PGPhoto.id == photo_id, PG.owner_id == owner.id)
    )
    if photo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Photo not found",
        )
    return _photo_file_response(photo, private=True)


@router.put(
    "/owners/me/pgs/{pg_id}/photos/order",
    response_model=list[OwnerPhotoOut],
)
def reorder_pg_photos(
    pg_id: int,
    payload: PhotoOrderRequest,
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        _owned_pg(db, owner, pg_id, lock=True)
        if len(set(payload.photo_ids)) != len(payload.photo_ids):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Photo IDs must not contain duplicates",
            )
        photos = db.scalars(
            select(PGPhoto)
            .where(PGPhoto.pg_id == pg_id)
            .with_for_update()
        ).all()
        if {photo.id for photo in photos} != set(payload.photo_ids):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Photo IDs must match this PG's complete photo gallery",
            )
        by_id = {photo.id: photo for photo in photos}
        for order, photo_id in enumerate(payload.photo_ids):
            by_id[photo_id].display_order = order
        db.commit()
        return [
            _owner_photo_out(by_id[photo_id])
            for photo_id in payload.photo_ids
        ]
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


@router.patch(
    "/owners/me/photos/{photo_id}",
    response_model=OwnerPhotoOut,
)
def update_photo_caption(
    photo_id: int,
    payload: PhotoCaptionUpdate,
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    photo = db.scalar(
        select(PGPhoto)
        .join(PG, PG.id == PGPhoto.pg_id)
        .where(PGPhoto.id == photo_id, PG.owner_id == owner.id)
        .with_for_update()
    )
    if photo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Photo not found",
        )
    photo.caption = payload.caption.strip() if payload.caption else None
    db.commit()
    db.refresh(photo)
    return _owner_photo_out(photo)


@router.put(
    "/owners/me/photos/{photo_id}/cover",
    response_model=OwnerPhotoOut,
)
def select_cover_photo(
    photo_id: int,
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        photo_reference = db.scalar(
            select(PGPhoto)
            .where(PGPhoto.id == photo_id)
        )
        if photo_reference is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Photo not found",
            )
        pg = _owned_pg(db, owner, photo_reference.pg_id, lock=True)
        photo = db.scalar(
            select(PGPhoto)
            .where(PGPhoto.id == photo_id, PGPhoto.pg_id == pg.id)
            .with_for_update()
        )
        if photo is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Photo not found",
            )
        if photo.review_status != "approved":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only an approved photo can be selected as cover",
            )
        db.execute(
            update(PGPhoto)
            .where(PGPhoto.pg_id == pg.id)
            .values(is_cover=False)
        )
        db.flush()
        photo.is_cover = True
        db.commit()
        db.refresh(photo)
        return _owner_photo_out(photo)
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cover photo changed concurrently; retry the request",
        ) from None
    except Exception:
        db.rollback()
        raise


@router.delete(
    "/owners/me/photos/{photo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_owner_photo(
    photo_id: int,
    owner: Owner = Depends(require_owner),
    db: Session = Depends(get_db),
):
    photo = db.scalar(
        select(PGPhoto)
        .join(PG, PG.id == PGPhoto.pg_id)
        .where(PGPhoto.id == photo_id, PG.owner_id == owner.id)
        .with_for_update()
    )
    if photo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Photo not found",
        )
    storage_key = photo.storage_key
    db.delete(photo)
    db.commit()
    try:
        photo_storage.delete(storage_key)
    except OSError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Photo record was removed; storage cleanup is pending",
        ) from None


@router.get(
    "/photos/{photo_id}/content",
    response_class=FileResponse,
)
def get_public_photo_content(
    photo_id: int,
    db: Session = Depends(get_db),
):
    photo = db.scalar(
        select(PGPhoto)
        .join(PG, PG.id == PGPhoto.pg_id)
        .where(
            PGPhoto.id == photo_id,
            PGPhoto.review_status == "approved",
            PG.is_active.is_(True),
            PG.verification_status == "verified",
            public_owner_eligibility(),
        )
    )
    if photo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Photo not found",
        )
    return _photo_file_response(photo, private=False)


admin_router = APIRouter(
    prefix="/admin",
    tags=["Admin Photo Review"],
    dependencies=[Depends(require_admin)],
)


@admin_router.get("/photos/pending", response_model=list[PendingPhotoOut])
def list_pending_photos(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    if limit < 1 or limit > 100 or offset < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="limit must be 1-100 and offset must be non-negative",
        )
    photos = db.scalars(
        select(PGPhoto)
        .where(PGPhoto.review_status == "pending")
        .order_by(PGPhoto.created_at, PGPhoto.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [
        PendingPhotoOut(
            id=photo.id,
            pg_id=photo.pg_id,
            url=f"{settings.api_v1_prefix}/admin/photos/{photo.id}/content",
            caption=photo.caption,
            display_order=photo.display_order,
            created_at=photo.created_at,
            review_status=photo.review_status,
        )
        for photo in photos
    ]


@admin_router.get(
    "/photos/{photo_id}/content",
    response_class=FileResponse,
)
def get_admin_photo_content(
    photo_id: int,
    db: Session = Depends(get_db),
):
    photo = db.get(PGPhoto, photo_id)
    if photo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Photo not found",
        )
    return _photo_file_response(photo, private=True)


@admin_router.patch(
    "/photos/{photo_id}/review",
    response_model=AdminPhotoOut,
)
def review_photo(
    photo_id: int,
    payload: PhotoReviewRequest,
    db: Session = Depends(get_db),
):
    try:
        photo = db.scalar(
            select(PGPhoto)
            .where(PGPhoto.id == photo_id)
            .with_for_update()
        )
        if photo is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Photo not found",
            )
        if photo.review_status != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Photo is no longer pending review",
            )
        photo.review_status = (
            "approved" if payload.action == "approve" else "rejected"
        )
        photo.moderation_notes = payload.moderation_notes
        db.commit()
        db.refresh(photo)
        return AdminPhotoOut(
            id=photo.id,
            pg_id=photo.pg_id,
            url=f"{settings.api_v1_prefix}/admin/photos/{photo.id}/content",
            caption=photo.caption,
            display_order=photo.display_order,
            is_cover=photo.is_cover,
            review_status=photo.review_status,
            created_at=photo.created_at,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
