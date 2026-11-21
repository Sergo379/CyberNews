from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, URL
from sqlalchemy.orm import sessionmaker


class Database:
    def __init__(self, url: URL):
        self.engine: Engine = create_engine(
            url,
            pool_pre_ping=True,
            pool_timeout=3,
            connect_args={"connect_timeout": 3, "options": "-c statement_timeout=3000"},
        )
        self.sessions = sessionmaker(bind=self.engine)

    def check(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
