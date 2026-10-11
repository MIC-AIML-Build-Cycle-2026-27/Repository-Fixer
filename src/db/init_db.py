"""Create all tables.  Run with:  python -m src.db.init_db"""

from src.db.models import Base
from src.db.session import get_engine


def main() -> None:
    Base.metadata.create_all(get_engine())
    print("Tables created.")


if __name__ == "__main__":
    main()
