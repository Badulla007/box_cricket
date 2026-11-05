# BOUNDARY — Box Cricket Turf Booking & Management

BOUNDARY is an hourly booking platform for **local box cricket turfs only**. It is not a professional cricket stadium, spectator seat, or match-ticket booking system.

## Main features

- Customer signup, email OTP verification and resend flow (10-minute OTP expiry, hashed OTP storage, resend cooldown, attempt limit).
- Local-development-only OTP console fallback. When SMTP is unavailable, the UI says so and the code is logged to the Flask terminal only if `FLASK_DEBUG=true` and `CONSOLE_OTP_FALLBACK=true`.
- Three protected roles: Admin, Employee and Customer.
- Admin turf directory management, user role management, booking status and payment record management.
- Employee customer lookup and booking status management (no role or system settings access).
- Customer turf discovery, date-specific hourly slot availability, booking requests, booking history and cancellation.
- Overlap prevention on the server and within a serialized booking transaction.
- Local BOUNDARY turf directory plus optional informational OpenStreetMap discovery. External results are not bookable until an Admin verifies and adds the facility.
- SQLite by default; set `DATABASE_URL` for MySQL/AWS RDS.
- Existing `user`, `venue`, and `booking` table names are retained; startup adds new columns without dropping old data. Old stadium/general ground entries are deactivated from the bookable directory, not deleted. Legacy match-ticket rows remain stored but are not displayed or bookable in this application.

## Windows setup

Open PowerShell in the extracted `boundary_cricket_app` folder:

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

Edit `.env` before testing email. For Gmail:

1. Enable Google 2-Step Verification.
2. Create an App Password in your Google Account security settings.
3. Put the Gmail address in `MAIL_USERNAME` and `MAIL_DEFAULT_SENDER`.
4. Put the 16-character App Password in `MAIL_PASSWORD` (spaces are removed by the app).
5. Keep `MAIL_PORT=587`, `MAIL_USE_TLS=true`, `MAIL_USE_SSL=false` for Gmail STARTTLS.
6. Save `.env` in the same directory as `app.py`.

Run the SMTP test before signup:

```powershell
python test_email.py your-receiving-email@gmail.com
```

Only proceed when the test script reports that SMTP accepted the message. Also check Spam. If the SMTP test fails, the script prints the provider exception so you can correct the actual credential/network issue.

Start the app:

```powershell
python app.py
```

Open <http://127.0.0.1:5000>.

## Default local Admin

If no admin already exists, first startup seeds:

```text
Email: admin@boundary.local
Password: Boundary@123
```

The supplied `.env.example` sets `BOUNDARY_ADMIN_PASSWORD=Boundary@123`; use that for the first local login, or change it before first startup. Change this default immediately and do not expose the local demo admin on a public deployment. Existing Admin accounts are not overwritten.

## Email troubleshooting

- `SMTP is not configured`: the app did not find all required mail settings in `.env`. Confirm `.env` is beside `app.py`, values are not still placeholders, and restart the server after edits.
- `Username and Password not accepted`: use a Google App Password, not your regular Gmail password. Confirm 2-Step Verification and account policy allow App Passwords.
- Timeout / connection refused: verify network access to `smtp.gmail.com:587`; some networks block outbound SMTP.
- During local development only, if SMTP fails and console fallback is enabled, read the six-digit `DEVELOPMENT-ONLY OTP` in the terminal running `python app.py`. It is not an email. On production, set `FLASK_DEBUG=false` and `CONSOLE_OTP_FALLBACK=false`.
- Resend is rate-limited by `OTP_RESEND_COOLDOWN_SECONDS` (default 60 seconds). A resend invalidates the earlier code.

## Box turf directory and external discovery

The database is the bookable source of truth. Admin-added and activated Box Turf records can be booked. Seeded entries have a visible **Demo listing** label and sample data; replace/deactivate them before public launch. External OpenStreetMap results are informational only and cannot be booked until verified and added by Admin. OSM coverage may be incomplete; no external provider can guarantee every local indoor box turf is listed.

## Booking rules

- Slots are generated from a turf's operating hours and slot interval.
- Customers may choose 1, 2 or 3 hours.
- Pending and Confirmed reservations block overlapping time ranges.
- Backend availability is checked again when creating a booking.
- Customer cancellations are allowed at least four hours before the start time.
- Booking starts as Pending; Employee/Admin may confirm, reject, cancel or complete it.
- Payment remains Pending unless an Admin records a verified offline payment. This build does not process card/UPI transactions. Do not mark Paid without receipt confirmation.

## Existing database safety

Back up `instance/boundary.db` before upgrading. The application preserves legacy user/turf/booking rows and adds columns. Stadium and generic `Cricket Ground` records are set inactive for the box-cricket directory instead of being deleted. Old match-ticket rows are kept in the DB but are not part of this app's routes or customer screens. If your legacy database uses a customized schema, test on a copy first.

## Tests

```powershell
pytest -q
```

Automated tests cover OTP verification flow with a mocked mail sender, role restrictions, slot availability, overlapping booking prevention and filtering out stadium-type records. Live SMTP delivery and OpenStreetMap discovery require internet access and valid runtime configuration, so they are tested separately.

## MySQL / AWS RDS configuration

Installations include `PyMySQL`. Set `DATABASE_URL` in `.env` using a SQLAlchemy URL such as:

```env
DATABASE_URL=mysql+pymysql://db_user:URL_ENCODED_PASSWORD@your-rds-endpoint:3306/boundary
```

URL-encode special characters in the password. Configure the RDS security group to allow MySQL (3306) only from the application server security group, and do not expose the database publicly.

## Production checklist

- Set a unique, long `SECRET_KEY`.
- Set `FLASK_DEBUG=false` and `CONSOLE_OTP_FALLBACK=false`.
- Use HTTPS and set `SESSION_COOKIE_SECURE=true`.
- Use a production WSGI server (e.g. Waitress on Windows or Gunicorn on Linux), not Flask's development server.
- Use MySQL/AWS RDS and configure backups.
- Replace sample demo turfs and images with facilities you have verified and permission to list.
- Set an OSM User-Agent containing a real contact method and follow the provider usage policy.
- Add a payment provider only with server-side payment verification/webhooks before enabling online payments.
