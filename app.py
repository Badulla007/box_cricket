import os
import re
import json
import secrets
import hashlib
from datetime import datetime, date, time, timedelta
from functools import wraps
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, redirect, url_for, flash, jsonify,
    session, abort, current_app
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user, login_required, current_user
)
from flask_mail import Mail, Message
from flask_wtf.csrf import CSRFProtect
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy import text, or_, Index, inspect
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"), override=False)


def env_bool(name, default=False):
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, "static", "uploads"), exist_ok=True)

    default_db = "sqlite:///boundary.db"
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY", "dev-only-change-this-secret-before-deployment"),
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", default_db),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        MAIL_SERVER=os.getenv("MAIL_SERVER", "smtp.gmail.com"),
        MAIL_PORT=int(os.getenv("MAIL_PORT", "587")),
        MAIL_USE_TLS=env_bool("MAIL_USE_TLS", True),
        MAIL_USE_SSL=env_bool("MAIL_USE_SSL", False),
        MAIL_USERNAME=os.getenv("MAIL_USERNAME", "").strip(),
        MAIL_PASSWORD=os.getenv("MAIL_PASSWORD", "").strip().replace(" ", ""),
        MAIL_DEFAULT_SENDER=(os.getenv("MAIL_DEFAULT_SENDER", "").strip() or os.getenv("MAIL_USERNAME", "").strip()),
        MAIL_TIMEOUT=int(os.getenv("MAIL_TIMEOUT", "20")),
        CONSOLE_OTP_FALLBACK=env_bool("CONSOLE_OTP_FALLBACK", True),
        APP_TIMEZONE=os.getenv("APP_TIMEZONE", "Asia/Kolkata"),
        OTP_TTL_MINUTES=int(os.getenv("OTP_TTL_MINUTES", "10")),
        OTP_RESEND_COOLDOWN_SECONDS=int(os.getenv("OTP_RESEND_COOLDOWN_SECONDS", "60")),
        OTP_MAX_ATTEMPTS=int(os.getenv("OTP_MAX_ATTEMPTS", "5")),
        UPLOAD_FOLDER=os.path.join(BASE_DIR, "static", "uploads"),
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=env_bool("SESSION_COOKIE_SECURE", False),
        WTF_CSRF_TIME_LIMIT=3600,
        ALLOW_DEMO_DATA=env_bool("ALLOW_DEMO_DATA", True),
        NOMINATIM_USER_AGENT=os.getenv("NOMINATIM_USER_AGENT", "BOUNDARYBoxCricket/1.0 (local development)"),
    )
    if test_config:
        app.config.update(test_config)

    if app.config["MAIL_USE_TLS"] and app.config["MAIL_USE_SSL"]:
        raise RuntimeError("Use either MAIL_USE_TLS or MAIL_USE_SSL, not both.")

    db.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "warning"

    register_template_helpers(app)
    register_routes(app)
    register_error_handlers(app)

    with app.app_context():
        db.create_all()
        migrate_legacy_schema()
        if app.config.get("ALLOW_DEMO_DATA"):
            seed_demo_data()

    return app


db = SQLAlchemy()
mail = Mail()
csrf = CSRFProtect()
login_manager = LoginManager()


# -----------------------------------------------------------------------------
# Models. The `venue` and `booking` table names intentionally preserve the
# original BOUNDARY SQLite schema where possible. Match-ticket records remain
# in the database but are not used or displayed by this box-cricket application.
# -----------------------------------------------------------------------------
class User(UserMixin, db.Model):
    __tablename__ = "user"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(30))
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="customer", index=True)
    verified = db.Column(db.Boolean, nullable=False, default=False)
    # otp is retained for compatibility with older BOUNDARY databases; new codes
    # are stored only as hashes in otp_hash.
    otp = db.Column(db.String(6))
    otp_hash = db.Column(db.String(255))
    otp_expires = db.Column(db.DateTime)
    otp_last_sent_at = db.Column(db.DateTime)
    otp_attempts = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    bookings = db.relationship("Booking", back_populates="customer", lazy=True)

    @property
    def is_verified(self):
        return bool(self.verified)

    @property
    def is_active(self):
        return True


class Turf(db.Model):
    __tablename__ = "venue"  # legacy-compatible table name
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), nullable=False)
    venue_type = db.Column(db.String(30), nullable=False, default="Box Turf")
    address = db.Column(db.String(250), nullable=False)
    locality = db.Column(db.String(120))
    city = db.Column(db.String(100), nullable=False, default="Hyderabad", index=True)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    price_per_hour = db.Column(db.Float, nullable=False, default=800)
    capacity = db.Column(db.Integer, nullable=False, default=14)
    surface = db.Column(db.String(80), default="Artificial turf")
    turf_kind = db.Column(db.String(20), nullable=False, default="Outdoor")
    description = db.Column(db.Text)
    image_url = db.Column(db.String(500))
    opening_time = db.Column(db.String(5), nullable=False, default="06:00")
    closing_time = db.Column(db.String(5), nullable=False, default="23:00")
    slot_minutes = db.Column(db.Integer, nullable=False, default=60)
    operating_days = db.Column(db.String(80), nullable=False, default="Mon,Tue,Wed,Thu,Fri,Sat,Sun")
    amenities = db.Column(db.String(1000), nullable=False, default="[]")
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    is_demo = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    @property
    def amenity_list(self):
        try:
            value = json.loads(self.amenities or "[]")
            return value if isinstance(value, list) else []
        except (TypeError, ValueError):
            return []

    @property
    def kind_label(self):
        return "Indoor box cricket" if self.turf_kind == "Indoor" else "Outdoor box cricket"


class Booking(db.Model):
    __tablename__ = "booking"  # legacy-compatible table name
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(24), unique=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    venue_id = db.Column(db.Integer, db.ForeignKey("venue.id"), nullable=True, index=True)
    # Kept only so old match-ticket rows can remain intact; never used for new flows.
    match_id = db.Column(db.Integer, nullable=True)
    booking_date = db.Column(db.String(20), nullable=False, index=True)
    slot = db.Column(db.String(30), nullable=False)
    start_time = db.Column(db.Time)
    end_time = db.Column(db.Time)
    duration_minutes = db.Column(db.Integer, nullable=False, default=60)
    hourly_price = db.Column(db.Float, nullable=False, default=0)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    total_amount = db.Column(db.Float, nullable=False, default=0)
    status = db.Column(db.String(30), nullable=False, default="Pending", index=True)
    payment_status = db.Column(db.String(20), nullable=False, default="Pending")
    payment_method = db.Column(db.String(40), nullable=False, default="Pay at venue")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    customer = db.relationship("User", back_populates="bookings")
    turf = db.relationship("Turf", foreign_keys=[venue_id])
    payments = db.relationship("Payment", back_populates="booking", cascade="all, delete-orphan", lazy=True)


class Payment(db.Model):
    __tablename__ = "payment"
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("booking.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="Pending")
    method = db.Column(db.String(40), nullable=False, default="Pay at venue")
    provider_reference = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    booking = db.relationship("Booking", back_populates="payments")


Index("ix_booking_turf_date_status", Booking.venue_id, Booking.booking_date, Booking.status)


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


def local_now():
    try:
        return datetime.now(ZoneInfo(current_app.config["APP_TIMEZONE"])).replace(tzinfo=None)
    except Exception:
        return datetime.now()


def smtp_is_configured():
    keys = ("MAIL_SERVER", "MAIL_PORT", "MAIL_USERNAME", "MAIL_PASSWORD", "MAIL_DEFAULT_SENDER")
    if not all(str(current_app.config.get(key, "")).strip() for key in keys):
        return False
    sender = current_app.config["MAIL_DEFAULT_SENDER"]
    username = current_app.config["MAIL_USERNAME"]
    return "@" in sender and "@" in username and not any(
        x in (sender + username).lower() for x in ("your_email", "example.com", "replace_me")
    )


def email_send(recipient, subject, body, html=None):
    if not smtp_is_configured():
        raise RuntimeError("Email is not configured. Add valid SMTP settings to .env.")
    message = Message(subject=subject, recipients=[recipient], sender=current_app.config["MAIL_DEFAULT_SENDER"])
    message.body = body
    if html:
        message.html = html
    mail.send(message)


def create_otp(user):
    code = f"{secrets.randbelow(1_000_000):06d}"
    user.otp_hash = generate_password_hash(code)
    user.otp = None
    user.otp_expires = local_now() + timedelta(minutes=current_app.config["OTP_TTL_MINUTES"])
    user.otp_last_sent_at = local_now()
    user.otp_attempts = 0
    db.session.commit()
    return code


def deliver_otp(user, code):
    html = f"""<div style='font-family:Arial,sans-serif;max-width:520px;margin:auto;padding:32px;color:#173b2c'>
    <div style='font-size:25px;font-weight:800;color:#13834d'>BOUNDARY<span style='color:#8fbd9f'>.</span></div>
    <h2>Verify your email</h2><p>Use this one-time code to verify your BOUNDARY account.</p>
    <div style='padding:18px;background:#eff8f2;border:1px solid #d5eadb;border-radius:14px;text-align:center;font-size:32px;font-weight:800;letter-spacing:9px;color:#12643c'>{code}</div>
    <p>This code expires in {current_app.config['OTP_TTL_MINUTES']} minutes and can be used once.</p><p style='color:#617568;font-size:12px'>If you did not create this account, ignore this email.</p></div>"""
    try:
        email_send(user.email, "Your BOUNDARY verification code", f"Your BOUNDARY verification code is {code}. It expires in {current_app.config['OTP_TTL_MINUTES']} minutes.", html)
        current_app.logger.info("Verification email submitted to SMTP for %s", user.email)
        return "email"
    except Exception as exc:
        current_app.logger.warning("Verification email delivery failed for %s: %s", user.email, exc)
        if current_app.debug and current_app.config.get("CONSOLE_OTP_FALLBACK"):
            current_app.logger.warning("DEVELOPMENT-ONLY OTP for %s: %s", user.email, code)
            return "console"
        return "failed"


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            if not current_user.verified:
                logout_user()
                flash("Verify your email before continuing.", "warning")
                return redirect(url_for("login"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def is_safe_redirect(target):
    if not target:
        return False
    parsed = urlparse(target)
    return not parsed.netloc and target.startswith("/") and not target.startswith("//")


def parse_time(value):
    try:
        return datetime.strptime(value, "%H:%M").time()
    except (TypeError, ValueError):
        return None


def time_minutes(value):
    return value.hour * 60 + value.minute


def slot_rows(turf, duration_hours=1, selected_date=None):
    duration = int(duration_hours) * 60
    start = parse_time(turf.opening_time) or time(6, 0)
    close = parse_time(turf.closing_time) or time(23, 0)
    step = max(15, min(int(turf.slot_minutes or 60), 120))
    current = time_minutes(start)
    end_limit = time_minutes(close)
    slots = []
    while current + duration <= end_limit:
        start_t = time(current // 60, current % 60)
        end_val = current + duration
        end_t = time(end_val // 60, end_val % 60)
        if selected_date and selected_date == local_now().date() and datetime.combine(selected_date, start_t) <= local_now():
            available = False
            reason = "In the past"
        else:
            available = True
            reason = "Available"
        slots.append({"start": start_t.strftime("%H:%M"), "end": end_t.strftime("%H:%M"), "label": f"{start_t.strftime('%I:%M %p')} – {end_t.strftime('%I:%M %p')}", "available": available, "reason": reason})
        current += step
    if selected_date:
        existing = Booking.query.filter(
            Booking.venue_id == turf.id,
            Booking.booking_date == selected_date.isoformat(),
            Booking.status.in_(["Pending", "Confirmed"]),
        ).all()
        for slot in slots:
            requested_start = time_minutes(parse_time(slot["start"]))
            requested_end = time_minutes(parse_time(slot["end"]))
            for booking in existing:
                old_start, old_end = booking_times(booking)
                if old_start is None or old_end is None:
                    continue
                if requested_start < time_minutes(old_end) and requested_end > time_minutes(old_start):
                    slot["available"] = False
                    slot["reason"] = "Already reserved"
                    break
    return slots


def booking_times(booking):
    if booking.start_time and booking.end_time:
        return booking.start_time, booking.end_time
    # Legacy rows stored the slot as "18:00 - 19:00".
    match = re.match(r"\s*(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*", booking.slot or "")
    if match:
        return parse_time(match.group(1)), parse_time(match.group(2))
    return None, None


def booking_overlaps(turf_id, day, start_t, end_t, exclude_id=None):
    bookings = Booking.query.filter(
        Booking.venue_id == turf_id,
        Booking.booking_date == day,
        Booking.status.in_(["Pending", "Confirmed"]),
    ).all()
    if not start_t or not end_t:
        return False
    new_start, new_end = time_minutes(start_t), time_minutes(end_t)
    for booking in bookings:
        if exclude_id and booking.id == exclude_id:
            continue
        old_start, old_end = booking_times(booking)
        if old_start and old_end and new_start < time_minutes(old_end) and new_end > time_minutes(old_start):
            return True
    return False


def register_template_helpers(app):
    @app.context_processor
    def inject_globals():
        return {"now_date": local_now().date().isoformat(), "smtp_configured": smtp_is_configured()}

    @app.template_filter("currency")
    def currency(value):
        try:
            return f"₹{float(value):,.0f}"
        except (TypeError, ValueError):
            return "₹0"


def migrate_legacy_schema():
    """Add new columns to pre-existing BOUNDARY tables without dropping rows."""
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    additions = {
        "user": {
            "phone": "VARCHAR(30)", "otp_hash": "VARCHAR(255)",
            "otp_last_sent_at": "DATETIME", "otp_attempts": "INTEGER NOT NULL DEFAULT 0",
            "created_at": "DATETIME",
        },
        "venue": {
            "locality": "VARCHAR(120)", "turf_kind": "VARCHAR(20) NOT NULL DEFAULT 'Outdoor'",
            "opening_time": "VARCHAR(5) NOT NULL DEFAULT '06:00'",
            "closing_time": "VARCHAR(5) NOT NULL DEFAULT '23:00'",
            "slot_minutes": "INTEGER NOT NULL DEFAULT 60",
            "operating_days": "VARCHAR(80) NOT NULL DEFAULT 'Mon,Tue,Wed,Thu,Fri,Sat,Sun'",
            "amenities": "VARCHAR(1000) NOT NULL DEFAULT '[]'", "is_demo": "BOOLEAN NOT NULL DEFAULT 0",
            "created_at": "DATETIME",
        },
        "booking": {
            "reference": "VARCHAR(24)", "start_time": "TIME", "end_time": "TIME",
            "duration_minutes": "INTEGER NOT NULL DEFAULT 60", "hourly_price": "FLOAT NOT NULL DEFAULT 0",
            "payment_status": "VARCHAR(20) NOT NULL DEFAULT 'Pending'",
            "payment_method": "VARCHAR(40) NOT NULL DEFAULT 'Pay at venue'",
        },
    }
    for table, cols in additions.items():
        if table not in tables:
            continue
        existing = {col["name"] for col in inspector.get_columns(table)}
        for column, definition in cols.items():
            if column not in existing:
                db.session.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}'))
    db.session.commit()
    if "booking" in tables:
        try:
            indexes = inspect(db.engine).get_indexes("booking")
            if not any("reference" in index.get("column_names", []) for index in indexes):
                if db.engine.dialect.name == "sqlite":
                    db.session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_booking_reference ON booking (reference)"))
                else:
                    db.session.execute(text("CREATE UNIQUE INDEX ix_booking_reference ON booking (reference)"))
            indexes = inspect(db.engine).get_indexes("booking")
            if not any(index.get("column_names") == ["venue_id", "booking_date", "status"] for index in indexes):
                if db.engine.dialect.name == "sqlite":
                    db.session.execute(text("CREATE INDEX IF NOT EXISTS ix_booking_turf_date_status ON booking (venue_id, booking_date, status)"))
                else:
                    db.session.execute(text("CREATE INDEX ix_booking_turf_date_status ON booking (venue_id, booking_date, status)"))
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Could not create legacy booking indexes")

    # Retain old rows but do not expose professional stadium / general cricket-ground
    # entries as bookable box-cricket turfs.
    if "venue" in tables:
        db.session.execute(text("UPDATE venue SET active = 0 WHERE lower(coalesce(venue_type,'')) IN ('stadium','cricket ground')"))
        db.session.commit()
    # Backfill stable references and booking times for legacy turf reservations.
    for booking in Booking.query.filter(Booking.venue_id.isnot(None), Booking.reference.is_(None)).all():
        booking.reference = "BND" + secrets.token_hex(5).upper()
        a, b = booking_times(booking)
        if a and b:
            booking.start_time, booking.end_time = a, b
            booking.duration_minutes = max(1, time_minutes(b) - time_minutes(a))
    for user in User.query.filter(User.created_at.is_(None)).all():
        user.created_at = datetime.utcnow()
    for turf in Turf.query.filter(Turf.created_at.is_(None)).all():
        turf.created_at = datetime.utcnow()
    db.session.commit()


def seed_demo_data():
    if not User.query.filter_by(email="admin@boundary.local").first():
        admin_password = os.getenv("BOUNDARY_ADMIN_PASSWORD", "Boundary@123")
        db.session.add(User(
            name="BOUNDARY Administrator", email="admin@boundary.local",
            password_hash=generate_password_hash(admin_password), role="admin", verified=True,
        ))
        db.session.commit()
    if Turf.query.filter_by(venue_type="Box Turf").count() == 0:
        demo = [
            Turf(name="Boundary Box Arena", venue_type="Box Turf", address="Madhapur, Hyderabad", locality="Madhapur", city="Hyderabad", latitude=17.4483, longitude=78.3915, price_per_hour=900, capacity=14, surface="Premium synthetic grass", turf_kind="Indoor", description="A sample indoor box cricket setup with enclosed nets, floodlights and changing facilities. This is demo data; replace it with a verified local turf before accepting real bookings.", image_url="/static/images/cricket-hero.png", amenities=json.dumps(["Floodlights", "Parking", "Changing room", "Drinking water"]), is_demo=True),
            Turf(name="PowerPlay Box Turf", venue_type="Box Turf", address="Kukatpally, Hyderabad", locality="Kukatpally", city="Hyderabad", latitude=17.4849, longitude=78.4138, price_per_hour=750, capacity=12, surface="Artificial turf", turf_kind="Outdoor", description="A sample outdoor box cricket turf for friendly games and practice. This is demo data; verify the facility before using it for real bookings.", image_url="/static/images/cricket-hero.png", amenities=json.dumps(["Floodlights", "Equipment rental", "Parking"]), is_demo=True),
            Turf(name="WicketBox Sports Hub", venue_type="Box Turf", address="Gachibowli, Hyderabad", locality="Gachibowli", city="Hyderabad", latitude=17.4401, longitude=78.3489, price_per_hour=1100, capacity=16, surface="Premium artificial turf", turf_kind="Indoor", description="A sample indoor box cricket facility. Demo listing only; confirm real-world details before enabling live reservations.", image_url="/static/images/cricket-hero.png", amenities=json.dumps(["Air circulation", "Washroom", "Seating", "Parking"]), is_demo=True),
        ]
        db.session.add_all(demo)
        db.session.commit()


def register_routes(app):
    @app.get("/")
    def index():
        search = request.args.get("q", "").strip()
        query = Turf.query.filter_by(active=True).filter(Turf.venue_type == "Box Turf")
        if search:
            like = f"%{search}%"
            query = query.filter(or_(Turf.city.ilike(like), Turf.locality.ilike(like), Turf.name.ilike(like), Turf.address.ilike(like)))
        turfs = query.order_by(Turf.is_demo.asc(), Turf.id.desc()).limit(6).all()
        return render_template("index.html", turfs=turfs, search=search)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "application": "BOUNDARY Box Cricket Turf Booking", "email_configured": smtp_is_configured(), "roles": ["admin", "employee", "customer"]})

    # ------------------------------- Auth ------------------------------------
    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            phone = request.form.get("phone", "").strip()
            password = request.form.get("password", "")
            confirm = request.form.get("confirm_password", "")
            if not name or len(name) > 100 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
                flash("Enter your name and a valid email address.", "danger")
                return render_template("auth.html", mode="signup", form_data=request.form)
            if phone and not re.fullmatch(r"[0-9+()\-\s]{7,20}", phone):
                flash("Enter a valid mobile number.", "danger")
                return render_template("auth.html", mode="signup", form_data=request.form)
            if len(password) < 8 or password != confirm:
                flash("Passwords must match and contain at least 8 characters.", "danger")
                return render_template("auth.html", mode="signup", form_data=request.form)
            user = User.query.filter_by(email=email).first()
            if user and user.verified:
                flash("That email already has a verified account. Please log in.", "warning")
                return redirect(url_for("login"))
            if user and user.otp_last_sent_at:
                elapsed = (local_now() - user.otp_last_sent_at).total_seconds()
                if elapsed < current_app.config["OTP_RESEND_COOLDOWN_SECONDS"]:
                    session["pending_verification_email"] = email
                    flash("An account already exists but is not verified. Use the Verify Email page and wait for the resend timer.", "warning")
                    return redirect(url_for("verify_email"))
            if user is None:
                user = User(name=name, email=email, role="customer", verified=False)
                db.session.add(user)
            user.name, user.phone = name, phone
            user.password_hash = generate_password_hash(password)
            user.role = "customer"  # never accept a role from a public signup form
            user.verified = False
            try:
                code = create_otp(user)
            except Exception:
                db.session.rollback()
                current_app.logger.exception("Could not create verification code")
                flash("We couldn't create your account. Please try again.", "danger")
                return render_template("auth.html", mode="signup")
            session["pending_verification_email"] = email
            result = deliver_otp(user, code)
            if result == "email":
                flash("Verification code sent. Check your inbox and spam folder.", "success")
            elif result == "console":
                flash("Email settings are not ready. A development-only code was written to the Flask terminal.", "warning")
            else:
                flash("Your account is saved, but email delivery failed. Fix SMTP settings and use Resend Verification Code.", "danger")
            return redirect(url_for("verify_email"))
        return render_template("auth.html", mode="signup")

    @app.route("/verify-email", methods=["GET", "POST"])
    def verify_email():
        email = session.get("pending_verification_email")
        if not email:
            flash("Start by creating an account or sign in to resume verification.", "warning")
            return redirect(url_for("signup"))
        user = User.query.filter_by(email=email).first_or_404()
        if user.verified:
            session.pop("pending_verification_email", None)
            flash("Your email is already verified. Please log in.", "success")
            return redirect(url_for("login"))
        if request.method == "POST":
            code = re.sub(r"\D", "", request.form.get("otp", ""))
            if not re.fullmatch(r"\d{6}", code):
                flash("Enter all six digits of your verification code.", "danger")
            elif user.otp_attempts >= current_app.config["OTP_MAX_ATTEMPTS"]:
                flash("Too many incorrect attempts. Request a new verification code.", "danger")
            elif not user.otp_hash or not user.otp_expires or user.otp_expires < local_now():
                flash("Your code is missing or expired. Request a new code.", "warning")
            elif check_password_hash(user.otp_hash, code):
                user.verified = True
                user.otp_hash = None
                user.otp = None
                user.otp_expires = None
                user.otp_attempts = 0
                db.session.commit()
                session.pop("pending_verification_email", None)
                flash("Email verified successfully. You can now log in.", "success")
                return redirect(url_for("login"))
            else:
                user.otp_attempts += 1
                db.session.commit()
                flash(f"That code is incorrect. {max(0, current_app.config['OTP_MAX_ATTEMPTS'] - user.otp_attempts)} attempts remaining.", "danger")
        remaining = 0
        if user.otp_last_sent_at:
            elapsed = (local_now() - user.otp_last_sent_at).total_seconds()
            remaining = max(0, int(current_app.config["OTP_RESEND_COOLDOWN_SECONDS"] - elapsed))
        return render_template("verify.html", email=email, resend_wait=remaining)

    @app.post("/resend-verification")
    def resend_verification():
        email = session.get("pending_verification_email")
        if not email:
            flash("Your verification session expired. Please sign up again.", "warning")
            return redirect(url_for("signup"))
        user = User.query.filter_by(email=email).first()
        if not user or user.verified:
            session.pop("pending_verification_email", None)
            flash("This account does not need verification.", "info")
            return redirect(url_for("login"))
        if user.otp_last_sent_at:
            elapsed = (local_now() - user.otp_last_sent_at).total_seconds()
            wait = current_app.config["OTP_RESEND_COOLDOWN_SECONDS"] - elapsed
            if wait > 0:
                flash(f"Please wait {int(wait) + 1} seconds before requesting another code.", "warning")
                return redirect(url_for("verify_email"))
        try:
            code = create_otp(user)
            result = deliver_otp(user, code)
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Resend OTP failed")
            flash("A new code could not be generated. Try again.", "danger")
            return redirect(url_for("verify_email"))
        if result == "email":
            flash("A new verification code has been sent. The previous code is no longer valid.", "success")
        elif result == "console":
            flash("Development mode: the new code is in the Flask terminal. The previous code is invalid.", "warning")
        else:
            flash("SMTP delivery failed. Check the .env settings and try again after the resend cooldown.", "danger")
        return redirect(url_for("verify_email"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            user = User.query.filter_by(email=email).first()
            if user and check_password_hash(user.password_hash, password):
                if not user.verified:
                    session["pending_verification_email"] = user.email
                    flash("Verify your email before logging in.", "warning")
                    return redirect(url_for("verify_email"))
                login_user(user, remember=bool(request.form.get("remember")))
                flash(f"Welcome back, {user.name.split()[0]}.", "success")
                target = request.args.get("next", "")
                return redirect(target if is_safe_redirect(target) else url_for("dashboard"))
            flash("Email or password is incorrect.", "danger")
        return render_template("auth.html", mode="login")

    @app.post("/logout")
    @login_required
    def logout():
        logout_user()
        flash("You have been signed out.", "info")
        return redirect(url_for("index"))

    @app.route("/forgot-password", methods=["GET", "POST"])
    def forgot_password():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            user = User.query.filter_by(email=email, verified=True).first()
            # Generic response avoids account enumeration.
            if user:
                token = URLSafeTimedSerializer(current_app.config["SECRET_KEY"]).dumps(user.email, salt="boundary-password-reset")
                link = url_for("reset_password", token=token, _external=True)
                try:
                    email_send(user.email, "Reset your BOUNDARY password", f"Reset your password using this link (valid for 30 minutes): {link}", f"<p>Reset your BOUNDARY password:</p><p><a href='{link}'>Reset password</a></p><p>Link expires in 30 minutes.</p>")
                except Exception:
                    current_app.logger.exception("Password reset email failed")
                    if current_app.debug:
                        current_app.logger.warning("Development password reset link for %s: %s", user.email, link)
            flash("When the address belongs to a verified account, password reset instructions will be sent.", "info")
            return redirect(url_for("login"))
        return render_template("forgot_password.html")

    @app.route("/reset-password/<token>", methods=["GET", "POST"])
    def reset_password(token):
        serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
        try:
            email = serializer.loads(token, salt="boundary-password-reset", max_age=1800)
        except (BadSignature, SignatureExpired):
            flash("That password reset link is invalid or expired.", "danger")
            return redirect(url_for("forgot_password"))
        user = User.query.filter_by(email=email, verified=True).first_or_404()
        if request.method == "POST":
            password = request.form.get("password", "")
            confirm = request.form.get("confirm_password", "")
            if len(password) < 8 or password != confirm:
                flash("Passwords must match and contain at least eight characters.", "danger")
            else:
                user.password_hash = generate_password_hash(password)
                db.session.commit()
                flash("Password updated. Please log in.", "success")
                return redirect(url_for("login"))
        return render_template("reset_password.html")

    # --------------------------- Customer dashboard -------------------------
    @app.get("/dashboard")
    @login_required
    def dashboard():
        if current_user.role == "admin":
            return redirect(url_for("admin_dashboard"))
        if current_user.role == "employee":
            return redirect(url_for("employee_dashboard"))
        bookings = Booking.query.filter_by(user_id=current_user.id).filter(Booking.venue_id.isnot(None)).order_by(Booking.created_at.desc()).limit(8).all()
        return render_template("customer_dashboard.html", bookings=bookings)

    @app.get("/profile")
    @login_required
    def profile():
        return render_template("profile.html")

    @app.post("/profile")
    @login_required
    def update_profile():
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        if not name:
            flash("Name is required.", "danger")
        elif phone and not re.fullmatch(r"[0-9+()\-\s]{7,20}", phone):
            flash("Enter a valid mobile number.", "danger")
        else:
            current_user.name = name[:100]
            current_user.phone = phone
            db.session.commit()
            flash("Profile updated.", "success")
        return redirect(url_for("profile"))

    # ------------------------------- Turf listing ---------------------------
    @app.get("/turfs")
    def turfs():
        search = request.args.get("q", "").strip()
        kind = request.args.get("kind", "all")
        min_price = request.args.get("min_price", "").strip()
        max_price = request.args.get("max_price", "").strip()
        query = Turf.query.filter_by(active=True, venue_type="Box Turf")
        if search:
            like = f"%{search}%"
            query = query.filter(or_(Turf.name.ilike(like), Turf.locality.ilike(like), Turf.city.ilike(like), Turf.address.ilike(like)))
        if kind in ("Indoor", "Outdoor"):
            query = query.filter_by(turf_kind=kind)
        try:
            if min_price:
                query = query.filter(Turf.price_per_hour >= float(min_price))
            if max_price:
                query = query.filter(Turf.price_per_hour <= float(max_price))
        except ValueError:
            flash("Price filters must be valid numbers.", "warning")
        all_turfs = query.order_by(Turf.is_demo.asc(), Turf.price_per_hour.asc()).all()
        return render_template("turfs.html", turfs=all_turfs, search=search, kind=kind, min_price=min_price, max_price=max_price)

    @app.get("/api/turfs")
    def api_turfs():
        items = []
        for turf in Turf.query.filter_by(active=True, venue_type="Box Turf").all():
            items.append({"id": turf.id, "name": turf.name, "city": turf.city, "locality": turf.locality, "address": turf.address, "lat": turf.latitude, "lng": turf.longitude, "price": turf.price_per_hour, "kind": turf.turf_kind, "image": turf.image_url, "url": url_for("turf_detail", turf_id=turf.id)})
        return jsonify(items)

    @app.get("/api/discover-turfs")
    def discover_turfs():
        place = request.args.get("q", "").strip()
        if len(place) < 2:
            return jsonify({"error": "Enter a city or locality to search."}), 400
        cache = current_app.extensions.setdefault("boundary_osm_cache", {})
        cache_key = place.casefold()
        now_stamp = local_now().timestamp()
        cached = cache.get(cache_key)
        if cached and cached[0] > now_stamp:
            return jsonify(cached[1])
        last_request = current_app.extensions.get("boundary_osm_last_request", 0)
        if now_stamp - last_request < 1.1:
            return jsonify({"error": "Please wait a moment before searching external listings again."}), 429
        current_app.extensions["boundary_osm_last_request"] = now_stamp
        try:
            response = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": f"box cricket turf {place}", "format": "jsonv2", "addressdetails": 1, "extratags": 1, "limit": 15},
                headers={"User-Agent": current_app.config["NOMINATIM_USER_AGENT"]}, timeout=8,
            )
            response.raise_for_status()
            raw = response.json()
            results = []
            for item in raw:
                name = item.get("name") or item.get("display_name", "").split(",")[0]
                haystack = (name + " " + item.get("display_name", "")).lower()
                tags = item.get("extratags") or {}
                sport = str(tags.get("sport", "")).lower()
                if not any(word in haystack for word in ("box cricket", "cricket turf", "cricket arena", "cricket net")) and sport != "cricket":
                    continue
                results.append({"name": name, "address": item.get("display_name", ""), "lat": item.get("lat"), "lng": item.get("lon"), "source": "OpenStreetMap", "note": "External listing — verify with the operator before visiting. Not bookable until an Admin adds and verifies it."})
            payload = {"results": results, "message": "No matching box-cricket listings were returned by OpenStreetMap." if not results else "External listings are informational only until verified by BOUNDARY Admin."}
            cache[cache_key] = (now_stamp + 21600, payload)
            return jsonify(payload)
        except requests.RequestException:
            return jsonify({"error": "External location search is temporarily unavailable. You can still search BOUNDARY's verified turf directory."}), 503

    @app.get("/turf/<int:turf_id>")
    def turf_detail(turf_id):
        turf = Turf.query.filter_by(id=turf_id, active=True, venue_type="Box Turf").first_or_404()
        return render_template("turf_detail.html", turf=turf)

    @app.get("/api/turf/<int:turf_id>/slots")
    def turf_slots(turf_id):
        turf = Turf.query.filter_by(id=turf_id, active=True, venue_type="Box Turf").first_or_404()
        try:
            selected_day = date.fromisoformat(request.args.get("date", ""))
            hours = int(request.args.get("hours", "1"))
        except (ValueError, TypeError):
            return jsonify({"error": "Choose a valid date and duration."}), 400
        if selected_day < local_now().date():
            return jsonify({"error": "Past dates cannot be booked."}), 400
        if hours not in (1, 2, 3):
            return jsonify({"error": "Choose a duration of 1, 2 or 3 hours."}), 400
        weekday = selected_day.strftime("%a")
        days = [x.strip() for x in (turf.operating_days or "").split(",")]
        if weekday not in days:
            return jsonify({"slots": [], "message": "This turf is closed on the selected day."})
        slots = slot_rows(turf, hours, selected_day)
        return jsonify({"slots": slots, "message": f"{sum(1 for slot in slots if slot['available'])} available start times."})

    @app.route("/turf/<int:turf_id>/book", methods=["POST"])
    @role_required("customer", "user")
    def book_turf(turf_id):
        turf = Turf.query.filter_by(id=turf_id, active=True, venue_type="Box Turf").first_or_404()
        try:
            booking_day = date.fromisoformat(request.form.get("booking_date", ""))
            hours = int(request.form.get("duration_hours", "1"))
        except (ValueError, TypeError):
            flash("Choose a valid booking date and duration.", "danger")
            return redirect(url_for("turf_detail", turf_id=turf.id))
        start_t = parse_time(request.form.get("start_time", ""))
        if booking_day < local_now().date() or hours not in (1, 2, 3) or not start_t:
            flash("Check the booking date, time and duration.", "danger")
            return redirect(url_for("turf_detail", turf_id=turf.id))
        duration = hours * 60
        start_minutes = time_minutes(start_t)
        end_minutes = start_minutes + duration
        open_t, close_t = parse_time(turf.opening_time), parse_time(turf.closing_time)
        if not open_t or not close_t or start_minutes < time_minutes(open_t) or end_minutes > time_minutes(close_t):
            flash("That time is outside this turf's operating hours.", "danger")
            return redirect(url_for("turf_detail", turf_id=turf.id))
        if (start_minutes - time_minutes(open_t)) % max(15, int(turf.slot_minutes or 60)) != 0:
            flash("Choose one of the available start times shown on the page.", "danger")
            return redirect(url_for("turf_detail", turf_id=turf.id))
        end_t = time(end_minutes // 60, end_minutes % 60)
        if booking_day == local_now().date() and datetime.combine(booking_day, start_t) <= local_now():
            flash("Choose a future time slot.", "danger")
            return redirect(url_for("turf_detail", turf_id=turf.id))
        weekday = booking_day.strftime("%a")
        if weekday not in [x.strip() for x in (turf.operating_days or "").split(",")]:
            flash("This turf is closed on that day.", "danger")
            return redirect(url_for("turf_detail", turf_id=turf.id))

        # Serialize same-turf booking creation: SQLite uses BEGIN IMMEDIATE; MySQL
        # locks the turf row. Availability is rechecked inside the transaction.
        db.session.rollback()
        try:
            if db.engine.dialect.name == "sqlite":
                db.session.execute(text("BEGIN IMMEDIATE"))
                locked_turf = db.session.get(Turf, turf_id)
            else:
                locked_turf = Turf.query.filter_by(id=turf_id).with_for_update().first()
            if not locked_turf or not locked_turf.active:
                db.session.rollback()
                abort(404)
            if booking_overlaps(turf_id, booking_day.isoformat(), start_t, end_t):
                db.session.rollback()
                flash("That time overlaps another reservation. Please choose another slot.", "danger")
                return redirect(url_for("turf_detail", turf_id=turf.id))
            hourly = float(locked_turf.price_per_hour)
            reference = "BND-" + secrets.token_hex(4).upper()
            booking = Booking(
                reference=reference, user_id=current_user.id, venue_id=locked_turf.id,
                booking_date=booking_day.isoformat(), slot=f"{start_t.strftime('%H:%M')} - {end_t.strftime('%H:%M')}",
                start_time=start_t, end_time=end_t, duration_minutes=duration,
                hourly_price=hourly, quantity=1, total_amount=hourly * hours,
                status="Pending", payment_status="Pending", payment_method="Pay at venue",
            )
            db.session.add(booking)
            db.session.flush()
            db.session.add(Payment(booking_id=booking.id, amount=booking.total_amount, status="Pending", method="Pay at venue"))
            db.session.commit()
            flash(f"Booking request {reference} created. The slot is held while the turf confirms it.", "success")
            return redirect(url_for("my_bookings"))
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Booking transaction failed")
            flash("We could not complete this booking. Refresh availability and try again.", "danger")
            return redirect(url_for("turf_detail", turf_id=turf.id))

    # ------------------------------- My bookings ----------------------------
    @app.get("/my-bookings")
    @role_required("customer", "user")
    def my_bookings():
        bookings = Booking.query.filter_by(user_id=current_user.id).filter(Booking.venue_id.isnot(None)).order_by(Booking.created_at.desc()).all()
        return render_template("my_bookings.html", bookings=bookings)

    @app.post("/booking/<int:booking_id>/cancel")
    @role_required("customer", "user")
    def cancel_booking(booking_id):
        booking = Booking.query.filter_by(id=booking_id, user_id=current_user.id).filter(Booking.venue_id.isnot(None)).first_or_404()
        if booking.status not in ("Pending", "Confirmed"):
            flash("This booking can no longer be cancelled.", "warning")
        else:
            start_t, _ = booking_times(booking)
            try:
                booking_day = date.fromisoformat(booking.booking_date)
            except ValueError:
                booking_day = local_now().date()
            if start_t and datetime.combine(booking_day, start_t) - local_now() < timedelta(hours=4):
                flash("Bookings can be cancelled at least four hours before the start time.", "warning")
            else:
                booking.status = "Cancelled"
                db.session.commit()
                flash("Booking cancelled. The time slot is available again.", "success")
        return redirect(url_for("my_bookings"))

    # ------------------------------- Admin ----------------------------------
    @app.get("/admin")
    @role_required("admin")
    def admin_dashboard():
        customers = User.query.filter(User.role.in_(["customer", "user"])).order_by(User.created_at.desc()).all()
        employees = User.query.filter_by(role="employee").order_by(User.created_at.desc()).all()
        turfs = Turf.query.order_by(Turf.id.desc()).all()
        bookings = Booking.query.filter(Booking.venue_id.isnot(None)).order_by(Booking.created_at.desc()).all()
        today = local_now().date().isoformat()
        confirmed_revenue = sum(float(b.total_amount or 0) for b in bookings if b.payment_status == "Paid")
        stats = {
            "customers": len(customers), "employees": len(employees), "turfs": len([t for t in turfs if t.active]),
            "bookings": len(bookings), "today": sum(1 for b in bookings if b.booking_date == today),
            "upcoming": sum(1 for b in bookings if b.booking_date >= today and b.status in ("Pending", "Confirmed")),
            "cancelled": sum(1 for b in bookings if b.status == "Cancelled"), "revenue": confirmed_revenue,
        }
        return render_template("admin_dashboard.html", stats=stats, customers=customers, employees=employees, turfs=turfs, bookings=bookings)

    @app.post("/admin/turf/create")
    @role_required("admin")
    def admin_create_turf():
        try:
            price = float(request.form.get("price_per_hour", "0"))
            capacity = int(request.form.get("capacity", "0"))
            slot_minutes = int(request.form.get("slot_minutes", "60"))
            latitude = float(request.form["latitude"]) if request.form.get("latitude") else None
            longitude = float(request.form["longitude"]) if request.form.get("longitude") else None
        except ValueError:
            flash("Price, capacity and slot interval must be valid numbers.", "danger")
            return redirect(url_for("admin_dashboard") + "#turfs")
        name = request.form.get("name", "").strip()
        address = request.form.get("address", "").strip()
        city = request.form.get("city", "").strip()
        opening = request.form.get("opening_time", "06:00")
        closing = request.form.get("closing_time", "23:00")
        if not name or not address or not city or price <= 0 or capacity < 2 or slot_minutes not in (30, 60):
            flash("Enter valid turf details, price, capacity and a 30/60-minute slot interval.", "danger")
            return redirect(url_for("admin_dashboard") + "#turfs")
        if not parse_time(opening) or not parse_time(closing) or time_minutes(parse_time(opening)) >= time_minutes(parse_time(closing)):
            flash("Opening time must be earlier than closing time.", "danger")
            return redirect(url_for("admin_dashboard") + "#turfs")
        amenities = [x.strip() for x in request.form.getlist("amenities") if x.strip()]
        image_url = request.form.get("image_url", "").strip()
        if image_url and not image_url.startswith(("https://", "http://", "/static/uploads/", "/static/images/")):
            flash("Image URL must use HTTP(S) or a local upload path.", "danger")
            return redirect(url_for("admin_dashboard") + "#turfs")
        turf = Turf(
            name=name[:140], venue_type="Box Turf", address=address[:250], locality=request.form.get("locality", "").strip(),
            city=city[:100], latitude=latitude, longitude=longitude,
            price_per_hour=price, capacity=capacity, surface=request.form.get("surface", "Artificial turf").strip(),
            turf_kind=request.form.get("turf_kind", "Outdoor"), description=request.form.get("description", "").strip(),
            image_url=image_url, opening_time=opening, closing_time=closing, slot_minutes=slot_minutes,
            operating_days=",".join(request.form.getlist("operating_days")) or "Mon,Tue,Wed,Thu,Fri,Sat,Sun",
            amenities=json.dumps(amenities), active=True, is_demo=False,
        )
        db.session.add(turf)
        db.session.commit()
        flash("Box cricket turf added to the bookable directory.", "success")
        return redirect(url_for("admin_dashboard") + "#turfs")

    @app.post("/admin/turf/<int:turf_id>/update")
    @role_required("admin")
    def admin_update_turf(turf_id):
        turf = Turf.query.get_or_404(turf_id)
        try:
            price = float(request.form.get("price_per_hour", "0"))
            capacity = int(request.form.get("capacity", "0"))
            interval = int(request.form.get("slot_minutes", "60"))
            lat = float(request.form["latitude"]) if request.form.get("latitude") else None
            lng = float(request.form["longitude"]) if request.form.get("longitude") else None
        except ValueError:
            flash("Check the turf price, capacity, coordinates and slot interval.", "danger")
            return redirect(url_for("admin_dashboard") + "#turfs")
        opening = request.form.get("opening_time", "06:00")
        closing = request.form.get("closing_time", "23:00")
        if not request.form.get("name", "").strip() or not request.form.get("address", "").strip() or not request.form.get("city", "").strip() or price <= 0 or capacity < 2 or interval not in (30, 60) or not parse_time(opening) or not parse_time(closing) or time_minutes(parse_time(opening)) >= time_minutes(parse_time(closing)):
            flash("The turf details are incomplete or invalid.", "danger")
            return redirect(url_for("admin_dashboard") + "#turfs")
        turf.name = request.form["name"].strip()[:140]
        turf.address = request.form["address"].strip()[:250]
        turf.locality = request.form.get("locality", "").strip()
        turf.city = request.form["city"].strip()[:100]
        turf.turf_kind = request.form.get("turf_kind", "Outdoor") if request.form.get("turf_kind") in ("Indoor", "Outdoor") else "Outdoor"
        turf.price_per_hour, turf.capacity = price, capacity
        turf.surface = request.form.get("surface", "Artificial turf").strip()
        turf.opening_time, turf.closing_time, turf.slot_minutes = opening, closing, interval
        turf.latitude, turf.longitude = lat, lng
        turf.description = request.form.get("description", "").strip()
        turf.operating_days = ",".join(request.form.getlist("operating_days")) or "Mon,Tue,Wed,Thu,Fri,Sat,Sun"
        turf.amenities = json.dumps([x.strip() for x in request.form.getlist("amenities") if x.strip()])
        image_url = request.form.get("image_url", "").strip()
        if image_url:
            if not image_url.startswith(("https://", "http://", "/static/uploads/", "/static/images/")):
                flash("Image URL must use HTTP(S) or a local static path.", "danger")
                return redirect(url_for("admin_dashboard") + "#turfs")
            turf.image_url = image_url
        db.session.commit()
        flash("Turf details updated.", "success")
        return redirect(url_for("admin_dashboard") + "#turfs")

    @app.post("/admin/turf/<int:turf_id>/status")
    @role_required("admin")
    def admin_turf_status(turf_id):
        turf = Turf.query.get_or_404(turf_id)
        turf.active = request.form.get("active") == "1"
        db.session.commit()
        flash(f"{turf.name} is now {'active' if turf.active else 'inactive'}.", "success")
        return redirect(url_for("admin_dashboard") + "#turfs")

    @app.post("/admin/users/<int:user_id>/role")
    @role_required("admin")
    def admin_update_role(user_id):
        user = User.query.get_or_404(user_id)
        role = request.form.get("role")
        if user.id == current_user.id or not user.verified or role not in ("customer", "employee", "admin"):
            flash("Role change is not allowed for this account.", "danger")
        else:
            user.role = role
            db.session.commit()
            flash(f"{user.name}'s role changed to {role.title()}.", "success")
        return redirect(url_for("admin_dashboard") + "#team")

    @app.post("/admin/booking/<int:booking_id>/payment")
    @role_required("admin")
    def admin_update_payment(booking_id):
        booking = Booking.query.filter(Booking.id == booking_id, Booking.venue_id.isnot(None)).first_or_404()
        status = request.form.get("payment_status")
        if status not in ("Pending", "Paid", "Failed", "Refunded"):
            flash("Invalid payment status.", "danger")
        else:
            booking.payment_status = status
            payment = Payment.query.filter_by(booking_id=booking.id).order_by(Payment.id.desc()).first()
            if not payment:
                payment = Payment(booking_id=booking.id, amount=booking.total_amount, method=booking.payment_method)
                db.session.add(payment)
            payment.status = status
            db.session.commit()
            flash("Payment record updated. Mark Paid only after confirming receipt.", "success")
        return redirect(url_for("admin_dashboard") + "#bookings")

    # ------------------------------ Employee --------------------------------
    @app.get("/employee/customer/<int:user_id>")
    @role_required("employee")
    def employee_customer_detail(user_id):
        customer = User.query.filter(User.id == user_id, User.role.in_(["customer", "user"])).first_or_404()
        bookings = Booking.query.filter_by(user_id=customer.id).filter(Booking.venue_id.isnot(None)).order_by(Booking.created_at.desc()).all()
        return render_template("employee_customer.html", customer=customer, bookings=bookings)

    @app.get("/employee")
    @role_required("employee")
    def employee_dashboard():
        search = request.args.get("q", "").strip()
        customers_query = User.query.filter(User.role.in_(["customer", "user"]))
        if search:
            like = f"%{search}%"
            customers_query = customers_query.filter(or_(User.name.ilike(like), User.email.ilike(like), User.phone.ilike(like)))
        customers = customers_query.order_by(User.created_at.desc()).all()
        ids = [u.id for u in customers]
        bookings = Booking.query.filter(Booking.user_id.in_(ids), Booking.venue_id.isnot(None)).order_by(Booking.created_at.desc()).all() if ids else []
        return render_template("employee_dashboard.html", customers=customers, bookings=bookings, search=search)

    @app.post("/employee/booking/<int:booking_id>/status")
    @role_required("employee")
    def employee_booking_status(booking_id):
        booking = Booking.query.filter(Booking.id == booking_id, Booking.venue_id.isnot(None)).first_or_404()
        if booking.customer.role not in ("customer", "user"):
            abort(403)
        status = request.form.get("status")
        if status not in ("Confirmed", "Rejected", "Cancelled", "Completed"):
            flash("Employee cannot apply that booking status.", "danger")
            return redirect(url_for("employee_dashboard"))
        if status == "Confirmed" and booking_overlaps(booking.venue_id, booking.booking_date, *booking_times(booking), exclude_id=booking.id):
            flash("This time now conflicts with another reservation. Please review it.", "danger")
        else:
            booking.status = status
            db.session.commit()
            flash("Customer booking updated.", "success")
        return redirect(url_for("employee_dashboard") + "#bookings")

    @app.post("/admin/booking/<int:booking_id>/status")
    @role_required("admin")
    def admin_booking_status(booking_id):
        booking = Booking.query.filter(Booking.id == booking_id, Booking.venue_id.isnot(None)).first_or_404()
        status = request.form.get("status")
        if status not in ("Pending", "Confirmed", "Rejected", "Cancelled", "Completed"):
            flash("Invalid booking status.", "danger")
        elif status in ("Pending", "Confirmed") and booking_overlaps(booking.venue_id, booking.booking_date, *booking_times(booking), exclude_id=booking.id):
            flash("This time now conflicts with another reservation.", "danger")
        else:
            booking.status = status
            db.session.commit()
            flash("Booking status updated.", "success")
        return redirect(url_for("admin_dashboard") + "#bookings")

    # ------------------------------ Uploads --------------------------------
    @app.post("/admin/turf/<int:turf_id>/image")
    @role_required("admin")
    def upload_turf_image(turf_id):
        turf = Turf.query.get_or_404(turf_id)
        file = request.files.get("image")
        allowed = {"png", "jpg", "jpeg", "webp"}
        if not file or "." not in file.filename or file.filename.rsplit(".", 1)[1].lower() not in allowed:
            flash("Upload a PNG, JPG or WEBP image.", "danger")
        else:
            filename = secrets.token_hex(12) + "_" + secure_filename(file.filename)
            path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
            file.save(path)
            turf.image_url = "/static/uploads/" + filename
            db.session.commit()
            flash("Turf image updated.", "success")
        return redirect(url_for("admin_dashboard") + "#turfs")

    @app.get("/access-denied")
    def access_denied():
        return render_template("errors/403.html"), 403


def register_error_handlers(app):
    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(_error):
        db.session.rollback()
        return render_template("errors/500.html"), 500


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=env_bool("FLASK_DEBUG", True))
