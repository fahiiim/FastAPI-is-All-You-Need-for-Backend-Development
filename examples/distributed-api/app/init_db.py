from .database import Base, engine


def main() -> None:
    Base.metadata.create_all(engine)


if __name__ == "__main__":
    main()
