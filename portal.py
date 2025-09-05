from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort
from datetime import date, datetime, timedelta
import os
from werkzeug.utils import secure_filename
from config import db
from models import Coach, Lesson, Booking, Review, Learner, LessonTemplate, ALLOWED_DAYS, TIME_SLOTS_BY_DAY, WEEKDAY_INDEX
from scheduler import ensure_schedule, integrate_new_coach
from auth import login_required, current_user

portal_bp = Blueprint('portal', __name__)


# --- Coach directory ---
@portal_bp.route('/coaches')
def coaches_list():
    coaches = Coach.query.order_by(Coach.first_name, Coach.last_name).all()
    # Precompute rating summary cheaply
    summary = []
    for c in coaches:
        avg = c.get_average_rating()
        count = c.get_review_count()
        summary.append((c, avg, count))
    return render_template('coaches.html', summary=summary)


# --- Coach profile update (picture, about me) ---
@portal_bp.route('/coach/profile', methods=['GET', 'POST'])
@login_required
def coach_profile():
    user, role = current_user()
    if role != 'coach':
        flash('Coaches only.', 'danger')
        return redirect(url_for('auth.account'))

    if request.method == 'POST':
        about = request.form.get('about_me', '').strip()
        user.about_me = about
        # Handle optional image upload
        file = request.files.get('profile_image')
        if file and file.filename:
            filename = secure_filename(file.filename)
            if not _allowed_image(filename):
                flash('Unsupported image type. Use jpg, jpeg, png, gif, or webp.', 'warning')
                return redirect(url_for('portal.coach_profile'))
            # Prefix with coach id and timestamp to avoid clashes
            ts = int(datetime.utcnow().timestamp())
            name, ext = os.path.splitext(filename)
            final_name = f"coach_{user.id}_{ts}{ext.lower()}"
            dest_dir = current_app.config['UPLOAD_FOLDER']
            os.makedirs(dest_dir, exist_ok=True)
            dest_path = os.path.join(dest_dir, final_name)
            file.save(dest_path)
            # Store relative path from /static
            rel = f"uploads/{final_name}"
            user.profile_image = rel
        db.session.commit()
        flash('Profile updated.', 'success')
        return redirect(url_for('portal.coach_profile'))

    return render_template('coach_profile.html', coach=user)


# --- Learner calendar (3 weeks) and booking ---
def _allowed_image(filename: str) -> bool:
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in { 'jpg', 'jpeg', 'png', 'gif', 'webp' }


def _ensure_schedule(start: date, weeks: int = 3):
    ensure_schedule(start=start, weeks=weeks)


@portal_bp.route('/calendar')
@login_required
def calendar_view():
    user, role = current_user()
    # Filters
    coach_id = request.args.get('coach_id', type=int)
    grade = request.args.get('grade', type=int)
    day = request.args.get('date')  # YYYY-MM-DD
    start = date.today()
    end = start + timedelta(weeks=4)

    # Ensure schedule exists for the next 4 weeks if empty
    _ensure_schedule(start, weeks=4)

    q = Lesson.query
    q = q.filter(Lesson.lesson_date >= start, Lesson.lesson_date < end)
    if coach_id:
        q = q.filter(Lesson.coach_id == coach_id)
    if grade:
        q = q.filter(Lesson.grade_level == grade)
    if day:
        try:
            d = datetime.strptime(day, '%Y-%m-%d').date()
            q = q.filter(Lesson.lesson_date == d)
        except ValueError:
            pass
    lessons = q.order_by(Lesson.lesson_date, Lesson.time_slot).all()
    coaches = Coach.query.order_by(Coach.first_name, Coach.last_name).all()

    return render_template('calendar.html', lessons=lessons, coaches=coaches, selected_coach=coach_id, selected_grade=grade, selected_date=day, role=role)


@portal_bp.route('/book/<int:lesson_id>', methods=['POST'])
@login_required
def book_lesson(lesson_id: int):
    user, role = current_user()
    nxt = request.form.get('next')
    if role != 'learner':
        flash('Only learners can book.', 'danger')
        return redirect(nxt or url_for('portal.calendar_view'))
    lesson = Lesson.query.get_or_404(lesson_id)

    # Check booking rules
    if not user.can_book_grade(lesson.grade_level):
        flash('You can only book your current grade or +1.', 'warning')
        return redirect(nxt or url_for('portal.calendar_view'))
    if lesson.is_full():
        flash('This class is full.', 'warning')
        return redirect(nxt or url_for('portal.calendar_view'))

    # Unique booking is enforced by DB; handle gracefully
    existing = Booking.query.filter_by(learner_id=user.id, lesson_id=lesson.id).first()
    if existing and existing.booking_status == 'booked':
        flash('Already booked.', 'info')
        return redirect(url_for('portal.calendar_view'))
    if existing and existing.booking_status in ('cancelled', 'attended'):
        db.session.delete(existing)
        db.session.commit()

    b = Booking(learner_id=user.id, lesson_id=lesson.id, booking_status='booked', booking_date=datetime.utcnow())
    db.session.add(b)
    db.session.commit()
    flash('Booked.', 'success')
    return redirect(nxt or url_for('portal.calendar_view'))


# --- My classes (coach and learner) ---
@portal_bp.route('/my-classes')
@login_required
def my_classes():
    user, role = current_user()
    today = date.today()
    if role == 'coach':
        upcoming = (
            Lesson.query
            .filter(Lesson.coach_id == user.id, Lesson.lesson_date >= today)
            .order_by(Lesson.lesson_date, Lesson.time_slot)
            .all()
        )
        past = (
            Lesson.query
            .filter(Lesson.coach_id == user.id, Lesson.lesson_date < today)
            .order_by(Lesson.lesson_date.desc(), Lesson.time_slot.desc())
            .limit(50)
            .all()
        )
        return render_template('coach_classes.html', lessons=upcoming, past_lessons=past)
    else:
        upcoming = (
            Booking.query
            .join(Lesson, Booking.lesson_id == Lesson.id)
            .filter(
                Booking.learner_id == user.id,
                Booking.booking_status == 'booked',
                Lesson.lesson_date >= today,
            )
            .order_by(Lesson.lesson_date, Lesson.time_slot)
            .all()
        )
        past = (
            Booking.query
            .join(Lesson, Booking.lesson_id == Lesson.id)
            .filter(
                Booking.learner_id == user.id,
                Lesson.lesson_date < today,
            )
            .order_by(Lesson.lesson_date.desc(), Lesson.time_slot.desc())
            .limit(50)
            .all()
        )
        return render_template('learner_classes.html', bookings=upcoming, past_bookings=past)


# Cancel booking if >= 24 hours before start
@portal_bp.route('/cancel/<int:booking_id>', methods=['POST'])
@login_required
def cancel_booking(booking_id: int):
    user, role = current_user()
    b = Booking.query.get_or_404(booking_id)
    if role != 'learner' or b.learner_id != user.id:
        flash('Not allowed.', 'danger')
        return redirect(url_for('portal.my_classes'))
    start_dt = datetime.combine(b.lesson.lesson_date, b.lesson.start_time)
    if start_dt - datetime.utcnow() < timedelta(hours=24):
        flash('Cannot cancel within 24 hours of the class.', 'warning')
        return redirect(url_for('portal.my_classes'))
    b.booking_status = 'cancelled'
    db.session.commit()
    flash('Booking cancelled.', 'info')
    return redirect(url_for('portal.my_classes'))


# --- Coach marks attendance ---
@portal_bp.route('/attendance/<int:lesson_id>', methods=['GET', 'POST'])
@login_required
def attendance(lesson_id: int):
    user, role = current_user()
    lesson = Lesson.query.get_or_404(lesson_id)
    if role != 'coach' or lesson.coach_id != user.id:
        flash('Not allowed.', 'danger')
        return redirect(url_for('portal.my_classes'))

    if request.method == 'POST':
        # Expect form fields like present_<booking_id>=on
        for b in lesson.bookings:
            present = request.form.get(f'present_{b.id}') == 'on'
            if present:
                b.mark_attended()
        db.session.commit()
        flash('Attendance saved.', 'success')
        return redirect(url_for('portal.my_classes'))

    return render_template('attendance.html', lesson=lesson)


# --- Coach view: roster for a lesson ---
@portal_bp.route('/lesson/<int:lesson_id>/roster')
@login_required
def lesson_roster(lesson_id: int):
    user, role = current_user()
    lesson = Lesson.query.get_or_404(lesson_id)
    if role != 'coach' or lesson.coach_id != user.id:
        flash('Not allowed.', 'danger')
        return redirect(url_for('portal.my_classes'))
    # Only currently booked learners
    booked = [b for b in lesson.bookings if b.booking_status == 'booked']
    # Sort by learner name
    booked.sort(key=lambda b: (b.learner.last_name.lower(), b.learner.first_name.lower()))
    return render_template('roster.html', lesson=lesson, bookings=booked)


@portal_bp.route('/review/<int:booking_id>', methods=['GET', 'POST'])
@login_required
def review_booking(booking_id: int):
    user, role = current_user()
    b = Booking.query.get_or_404(booking_id)
    if role != 'learner' or b.learner_id != user.id:
        flash('Not allowed.', 'danger')
        return redirect(url_for('portal.my_classes'))
    # Only allow after class date
    if b.lesson.lesson_date > date.today():
        flash('You can review after the class.', 'info')
        return redirect(url_for('portal.my_classes'))

    if request.method == 'POST':
        try:
            rating = int(request.form.get('rating', '0'))
        except ValueError:
            rating = 0
        comment = request.form.get('comment', '').strip()
        if not (1 <= rating <= 5):
            flash('Rating must be between 1 and 5.', 'danger')
            return render_template('review.html', booking=b)
        if b.review is None:
            r = Review(booking_id=b.id, rating=rating, comment=comment, review_date=datetime.utcnow())
            db.session.add(r)
        else:
            b.review.rating = rating
            b.review.comment = comment
        db.session.commit()
        flash('Review submitted.', 'success')
        return redirect(url_for('portal.my_classes'))

    return render_template('review.html', booking=b)


@portal_bp.route('/coach/learners')
@login_required
def coach_learners_search():
    user, role = current_user()
    if role != 'coach':
        flash('Coaches only.', 'danger')
        return redirect(url_for('auth.account'))
    q = request.args.get('q', '').strip()
    results = []
    if q:
        like = f"%{q}%"
        results = (Learner.query
                   .filter((Learner.first_name.ilike(like)) |
                           (Learner.last_name.ilike(like)) |
                           (Learner.email.ilike(like)))
                   .order_by(Learner.last_name, Learner.first_name)
                   .limit(50)
                   .all())
    return render_template('coach_learners_search.html', q=q, results=results)


@portal_bp.route('/learner/<int:learner_id>', methods=['GET'])
@login_required
def learner_profile(learner_id: int):
    viewer, role = current_user()
    learner = Learner.query.get_or_404(learner_id)
    # Access: coaches can view any; learners can view self only
    if role == 'learner' and viewer.id != learner.id:
        flash('Not allowed.', 'danger')
        return redirect(url_for('auth.account'))

    today = date.today()
    # Upcoming booked lessons
    upcoming = (Booking.query
                .join(Lesson, Booking.lesson_id == Lesson.id)
                .filter(Booking.learner_id == learner.id,
                        Lesson.lesson_date >= today,
                        Booking.booking_status == 'booked')
                .order_by(Lesson.lesson_date, Lesson.time_slot)
                .all())
    # All past bookings (any status)
    past = (Booking.query
            .join(Lesson, Booking.lesson_id == Lesson.id)
            .filter(Booking.learner_id == learner.id,
                    Lesson.lesson_date < today)
            .order_by(Lesson.lesson_date.desc(), Lesson.time_slot.desc())
            .limit(200)
            .all())

    # Attendance summary counts
    attended_count = sum(1 for b in past if b.booking_status == 'attended' or b.attended)
    missed_count = sum(1 for b in past if b.booking_status == 'missed')
    cancelled_count = sum(1 for b in past if b.booking_status == 'cancelled')

    return render_template('learner_profile.html', learner=learner, upcoming=upcoming, past=past,
                           attended_count=attended_count, missed_count=missed_count, cancelled_count=cancelled_count,
                           role=role)


@portal_bp.route('/learner/<int:learner_id>/grade', methods=['POST'])
@login_required
def update_learner_grade(learner_id: int):
    viewer, role = current_user()
    if role != 'coach':
        flash('Coaches only.', 'danger')
        return redirect(url_for('portal.learner_profile', learner_id=learner_id))
    learner = Learner.query.get_or_404(learner_id)
    try:
        new_grade = int(request.form.get('current_grade', ''))
    except ValueError:
        flash('Invalid grade.', 'danger')
        return redirect(url_for('portal.learner_profile', learner_id=learner_id))
    if not (0 <= new_grade <= 5):
        flash('Grade must be between 0 and 5.', 'warning')
        return redirect(url_for('portal.learner_profile', learner_id=learner_id))
    learner.current_grade = new_grade
    db.session.commit()
    flash('Grade updated.', 'success')
    return redirect(url_for('portal.learner_profile', learner_id=learner_id))
