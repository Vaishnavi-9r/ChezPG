from app.db.base import Base
from app.db.database import engine

# Import models so SQLAlchemy registers their tables.
from app.models import City, Area, PG  # noqa: F401


def main():
    Base.metadata.create_all(bind=engine)
    print("ChezPG database tables are ready.")


if __name__ == "__main__":
    main()