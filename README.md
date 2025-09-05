# HJSS Scheduling App

A Flask-based scheduling and booking app with secure auth, 2FA, coach invites, calendar, booking, attendance, and reviews.

## Requirements

- Python 3.10+
- pip
- A `.env` file with:
	- `SECRET_KEY=...`
	- `DATABASE_URL=sqlite:///app.db` (or your DB URI)

Install dependencies:

```sh
pip install -r requirements.txt
```

## Makefile commands
- `make run` – start server in background (http://127.0.0.1:5000)
- `make stop` – stop background server
- `make clean-db` – remove SQLite db (app.db)
- `make new-coach-token` – print a one-time coach invite token value
- `make seed-coaches` – start server (if not running), generate 5 invite tokens and register 5 coaches via `/register/coach`
- `make reset` – stop server, wipe db, start server, and seed 5 coaches
- `make gen-past email=user@example.com weeks=4 count=3` – generate past data

Notes:
- Seeded coaches use emails like `coachN+<epoch>@example.com` with password `Pass1234!`.
- Override defaults: `HOST=0.0.0.0 PORT=8080 PY=python3.11 make run`.

## Run without Makefile

Prepare env vars (or use `.env` with python-dotenv):

```sh
export SECRET_KEY="your-secret"
export DATABASE_URL="sqlite:///app.db"
```

Run the app directly:

```sh
python3 main.py
```

Alternative with Flask runner:

```sh
export FLASK_APP=main.py
export FLASK_ENV=development
flask run --host 0.0.0.0 --port 8080
```

## CLI utilities

Direct flags to `main.py`:

- New coach invite (prints invite link fragment):

```sh
python3 main.py -new_coach
```

- Generate past data for a user:

```sh
python3 main.py -gen_past_for user@example.com -weeks 4 -count 3
```

Arguments:
- `-gen_past_for <email>` – required email of learner or coach
- `-weeks N` – number of weeks back (default 4)
- `-count M` – number of bookings to create for a learner (default 3)
