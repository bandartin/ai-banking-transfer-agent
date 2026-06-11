"""Pytest fixtures shared across all test modules."""

import os

os.environ["LANGCHAIN_TRACING_V2"] = "false"  # 테스트 중 LangSmith 비활성

import pytest
from app import create_app
from src.models.database import db as _db
from config import Config


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    SECRET_KEY = "test-secret"
    LLM_PROVIDER = "deterministic"
    DEMO_USER_ID = 1
    CHECKPOINT_DB_PATH = ":memory:"
    LANGSMITH_ENABLED = False


@pytest.fixture(scope="session")
def app():
    from src.agents.supervisor.graph import reset_graph_singleton
    reset_graph_singleton()  # 다른 프로세스/모듈 상태와 격리

    application = create_app(TestConfig)
    with application.app_context():
        _db.create_all()
        import seed
        seed.run(application)
        yield application

    reset_graph_singleton()


@pytest.fixture(scope="session")
def client(app):
    return app.test_client()


@pytest.fixture(scope="session")
def db(app):
    return _db
