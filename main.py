from config import app, db
from flask import Flask, render_template, jsonify, session
from models import Learner, Coach, Lesson, Booking, Review, CoachInvite
from auth import auth_bp
from portal import portal_bp
from scheduler import ensure_schedule
import sys, secrets
from datetime import datetime, timedelta
from datetime import date as _date

@app.context_processor
def inject_user():
    from auth import _get_user
    role = session.get('role')
    uid = session.get('user_id')
    user = _get_user(role, uid) if role and uid else None
    return dict(current_user=user, current_role=role)


@app.route('/')
def home():
    return render_template('home.html')

# Register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(portal_bp)


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        # On startup, mark any past 'booked' bookings as 'missed'
        try:
            today = _date.today()
            past_booked = (Booking.query
                           .join(Lesson, Booking.lesson_id == Lesson.id)
                           .filter(Lesson.lesson_date < today,
                                   Booking.booking_status == 'booked')
                           .all())
            changed = 0
            for b in past_booked:
                b.booking_status = 'missed'
                changed += 1
            if changed:
                db.session.commit()
        except Exception:
            pass
        # CLI: generate one-time coach invite link
        if len(sys.argv) > 1 and sys.argv[1] == "-new_coach":
            token = secrets.token_urlsafe(32)
            invite = CoachInvite(
                token=token,
                created_at=datetime.now(),
                expires_at=datetime.now() + timedelta(days=7),
            )
            db.session.add(invite)
            db.session.commit()
            link = f"/register/coach?token={token}"
            print("One-time coach invite created (valid 7 days):")
            print(link)
            sys.exit(0)

        # CLI: generate past classes/bookings for a given email (learner or coach)
        if "-gen_past_for" in sys.argv:
            try:
                idx = sys.argv.index("-gen_past_for")
                email = sys.argv[idx + 1].strip().lower()
            except Exception:
                print("Usage: main.py -gen_past_for <email> [-weeks N] [-count M]")
                sys.exit(2)

            # Defaults
            weeks = 4
            count = 3
            if "-weeks" in sys.argv:
                try:
                    weeks = int(sys.argv[sys.argv.index("-weeks") + 1])
                except Exception:
                    pass
            if "-count" in sys.argv:
                try:
                    count = int(sys.argv[sys.argv.index("-count") + 1])
                except Exception:
                    pass

            from datetime import date as _date
            start = _date.today() - timedelta(weeks=weeks)
            end = _date.today()

            learner = Learner.query.filter_by(email=email).first()
            coach = None if learner else Coach.query.filter_by(email=email).first()

            if not learner and not coach:
                print(f"No learner or coach found with email: {email}")
                sys.exit(1)

            # Ensure schedule exists in the past window
            ensure_schedule(start=start, weeks=weeks)

            if learner:
                q = (Lesson.query
                     .filter(Lesson.lesson_date >= start, Lesson.lesson_date < end)
                     .filter(Lesson.grade_level.in_([learner.current_grade, learner.current_grade + 1]))
                     .order_by(Lesson.lesson_date.desc(), Lesson.time_slot.desc()))
                lessons = q.limit(max(count, 0)).all()
                created = 0
                for l in lessons:
                    # Avoid duplicate booking
                    if Booking.query.filter_by(learner_id=learner.id, lesson_id=l.id).first():
                        continue
                    b = Booking(learner_id=learner.id, lesson_id=l.id, booking_status='attended', booking_date=datetime.utcnow(), attended=True)
                    db.session.add(b)
                    created += 1
                db.session.commit()
                print(f"Created {created} past bookings for learner {email}")
                sys.exit(0)

            if coach:
                # Nothing else to do; ensure_schedule already created past lessons
                cnt = Lesson.query.filter(Lesson.lesson_date >= start, Lesson.lesson_date < end, Lesson.coach_id == coach.id).count()
                print(f"Coach {email} has {cnt} past lessons in the last {weeks} weeks.")
                sys.exit(0)

        print("Database tables created successfully!")

    app.run()