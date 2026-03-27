"""Pytest fixtures shared across all test modules."""

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


@pytest.fixture(scope="session")
def app():
    application = create_app(TestConfig)
    with application.app_context():
        _db.create_all()
        import seed
        seed.run(application)
        yield application


@pytest.fixture(scope="session")
def client(app):
    return app.test_client()


@pytest.fixture(scope="session")
def db(app):
    return _db
