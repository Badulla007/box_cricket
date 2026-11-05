from datetime import time
from werkzeug.security import generate_password_hash
from app import db, User, Turf, Booking

def setup_turf(app):
    with app.app_context():
        user = User(name="Player", email="booker@example.com", password_hash=generate_password_hash("StrongPass123"), role="customer", verified=True)
        turf = Turf(name="Test Box Turf", venue_type="Box Turf", address="Test Road", city="Hyderabad", price_per_hour=500, capacity=12, opening_time="06:00", closing_time="23:00", slot_minutes=60, operating_days="Mon,Tue,Wed,Thu,Fri,Sat,Sun", active=True)
        db.session.add_all([user,turf]); db.session.commit(); return user.id, turf.id

def login(client, user_id):
    with client.session_transaction() as sess: sess["_user_id"] = str(user_id); sess["_fresh"] = True

def test_slots_api_returns_available_slots(client, app):
    _, turf_id = setup_turf(app)
    response = client.get(f"/api/turf/{turf_id}/slots?date=2099-05-05&hours=1")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["slots"]
    assert all("available" in slot for slot in payload["slots"])

def test_duplicate_overlapping_booking_blocked(client, app):
    user_id, turf_id = setup_turf(app)
    login(client, user_id)
    # 2099-05-05 is a Wednesday.
    response = client.post(f"/turf/{turf_id}/book", data={"booking_date":"2099-05-05", "duration_hours":"2", "start_time":"18:00"}, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        first = Booking.query.filter_by(venue_id=turf_id).one()
        assert first.status == "Pending"
        assert first.start_time == time(18, 0)
    response2 = client.post(f"/turf/{turf_id}/book", data={"booking_date":"2099-05-05", "duration_hours":"1", "start_time":"19:00"}, follow_redirects=True)
    assert response2.status_code == 200
    with app.app_context():
        assert Booking.query.filter_by(venue_id=turf_id).count() == 1

def test_general_stadium_type_not_listed_as_turf(client, app):
    with app.app_context():
        stadium = Turf(name="A Stadium", venue_type="Stadium", address="City", city="Hyderabad", active=True)
        db.session.add(stadium); db.session.commit()
    response = client.get("/api/turfs")
    assert response.status_code == 200
    assert all(item["name"] != "A Stadium" for item in response.get_json())
