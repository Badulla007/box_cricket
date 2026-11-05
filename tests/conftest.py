import os
import tempfile
import pytest
from app import create_app, db

@pytest.fixture()
def app():
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    test_app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///" + path.replace('\\', '/'),
        "SECRET_KEY": "test-secret-key",
        "ALLOW_DEMO_DATA": False,
        "CONSOLE_OTP_FALLBACK": False,
        "MAIL_SUPPRESS_SEND": True,
    })
    with test_app.app_context():
        db.drop_all()
        db.create_all()
    yield test_app
    with test_app.app_context():
        db.session.remove()
        db.drop_all()
    os.unlink(path)

@pytest.fixture()
def client(app):
    return app.test_client()
