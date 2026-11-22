"""Point tests at isolated Postgres and Mongo databases, never the dev ones.

The env vars are set before anything imports app settings, so the app, Alembic
and get_settings() all see the test databases. TEST_DB_SUFFIX lets parallel runs
(e.g. separate worktrees) use their own databases.
"""

import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic_settings import BaseSettings, SettingsConfigDict
from pymongo import MongoClient
from pymongo.database import Database
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


class _Env(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str
    mongo_url: str
    mongo_db: str


_env = _Env()
_suffix = os.environ.get("TEST_DB_SUFFIX", "test")
_dev_db = make_url(_env.database_url)
TEST_DB_NAME = f"{_dev_db.database}_{_suffix}"
TEST_DATABASE_URL = _dev_db.set(database=TEST_DB_NAME).render_as_string(hide_password=False)
TEST_MONGO_DB = f"{_env.mongo_db}_{_suffix}"

os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["MONGO_DB"] = TEST_MONGO_DB
# tests must never reach the network or spend credits: no keys, unroutable hosts, so a
# test that forgets a fake transport fails fast instead of calling the live APIs
os.environ["CRUSTDATA_API_KEY"] = ""
os.environ["CRUSTDATA_BASE_URL"] = "http://crustdata.invalid"
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["OPENROUTER_BASE_URL"] = "http://openrouter.invalid/api/v1"


def _libpq_dsn(database: str) -> str:
    return _dev_db.set(drivername="postgresql", database=database).render_as_string(
        hide_password=False
    )


@pytest.fixture(scope="session", autouse=True)
def _test_databases() -> None:
    # recreated every session: a test DB left at another branch's revision can't block a run
    with psycopg.connect(_libpq_dsn(str(_dev_db.database)), autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    command.upgrade(Config("alembic.ini"), "head")
    MongoClient(_env.mongo_url).drop_database(TEST_MONGO_DB)


@pytest.fixture(autouse=True)
def _clean_state() -> Iterator[None]:
    yield
    from app.models import Base

    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with psycopg.connect(_libpq_dsn(TEST_DB_NAME), autocommit=True) as conn:
        conn.execute(f"TRUNCATE {tables} CASCADE")
    mongo: Database[dict[str, Any]] = MongoClient(_env.mongo_url)[TEST_MONGO_DB]
    for name in mongo.list_collection_names():
        mongo[name].delete_many({})


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db() -> Iterator[Session]:
    from app.db.session import SessionLocal

    with SessionLocal() as session:
        yield session
