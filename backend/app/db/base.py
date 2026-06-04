from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for future SQLAlchemy models."""


from app.domains.governance import models as governance_models  # noqa: E402,F401
from app.domains.identity import models as identity_models  # noqa: E402,F401
