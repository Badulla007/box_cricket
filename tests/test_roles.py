from werkzeug.security import generate_password_hash
from app import db, User

def add_user(app, role, email):
    with app.app_context():
        user = User(name=role.title(), email=email, password_hash=generate_password_hash("StrongPass123"), role=role, verified=True)
        db.session.add(user); db.session.commit(); return user.id

def test_customer_cannot_access_admin_or_employee(client, app):
    uid = add_user(app, "customer", "customer@example.com")
    with client.session_transaction() as sess: sess["_user_id"] = str(uid); sess["_fresh"] = True
    assert client.get("/admin").status_code == 403
    assert client.get("/employee").status_code == 403

def test_employee_cannot_access_admin(client, app):
    uid = add_user(app, "employee", "employee@example.com")
    with client.session_transaction() as sess: sess["_user_id"] = str(uid); sess["_fresh"] = True
    assert client.get("/employee").status_code == 200
    assert client.get("/admin").status_code == 403
