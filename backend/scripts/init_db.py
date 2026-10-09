from app.db import engine
from app.models import Base


def main():
    Base.metadata.create_all(bind=engine)
    print("Database tables created")


if __name__ == "__main__":
    main()
