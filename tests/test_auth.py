from werkzeug.security import generate_password_hash
from app import db, User

def test_signup_creates_unverified_customer_and_verification_session(client, app, monkeypatch):
    import app as module
    sent = {}
    monkeypatch.setattr(module, "deliver_otp", lambda user, code: sent.update(email=user.email, code=code) or "email")
    response = client.post("/signup", data={
        "name": "Test Player", "email": "player@example.com", "phone": "9876543210",
        "password": "StrongPass123", "confirm_password": "StrongPass123"
    }, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        user = User.query.filter_by(email="player@example.com").one()
        assert user.role == "customer"
        assert user.verified is False
        assert user.otp_hash
        assert sent["email"] == user.email
    assert b"Verify your email" in response.data

def test_verify_email_accepts_correct_code(client, app, monkeypatch):
    import app as module
    captured = {}
    monkeypatch.setattr(module, "deliver_otp", lambda user, code: captured.update(code=code) or "email")
    client.post("/signup", data={"name":"Player", "email":"verify@example.com", "password":"StrongPass123", "confirm_password":"StrongPass123"})
    response = client.post("/verify-email", data={"otp":captured["code"]}, follow_redirects=True)
    assert response.status_code == 200
    assert b"Email verified successfully" in response.data
    with app.app_context():
        user = User.query.filter_by(email="verify@example.com").one()
        assert user.verified is True
        assert user.otp_hash is None

def test_unverified_user_cannot_enter_dashboard(client, app):
    with app.app_context():
        user = User(name="Unverified", email="u@example.com", password_hash=generate_password_hash("StrongPass123"), role="customer", verified=False)
        db.session.add(user); db.session.commit()
    response = client.post("/login", data={"email":"u@example.com", "password":"StrongPass123"}, follow_redirects=True)
    assert response.status_code == 200
    assert b"Verify your email" in response.data
