from sqlalchemy import exists, or_, select

from app.models import Owner, OwnerVerification, PG


def public_owner_eligibility():
    approved_account = exists(
        select(1)
        .select_from(OwnerVerification)
        .join(Owner, Owner.id == OwnerVerification.owner_id)
        .where(
            OwnerVerification.owner_id == PG.owner_id,
            OwnerVerification.verification_status == "approved",
            OwnerVerification.management_authority_status == "approved",
            Owner.account_status == "active",
            Owner.is_active.is_(True),
            Owner.role == "owner",
        )
    )
    return or_(PG.owner_id.is_(None), approved_account)
