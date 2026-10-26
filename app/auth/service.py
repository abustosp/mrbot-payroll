from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.database.models import Organization, User


def seed_admin(db: Session, email: str, password: str, organization_name: str = "Organización") -> User:
    """Create the first organization admin once; never run implicitly on import."""
    email = email.strip().lower()
    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        return existing
    organization = db.scalar(select(Organization).where(Organization.slug == "default"))
    if organization is None:
        organization = Organization(name=organization_name, slug="default")
        db.add(organization)
        db.flush()
    user = User(
        organization_id=organization.id,
        email=email,
        password_hash=hash_password(password),
        role="admin",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
