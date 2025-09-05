from datetime import date, datetime, timedelta
from config import db
from models import Coach, Lesson, LessonTemplate, ALLOWED_DAYS, TIME_SLOTS_BY_DAY, WEEKDAY_INDEX


GRADE_BY_SLOT = {
    '4-5pm': 1,
    '5-6pm': 2,
    '6-7pm': 3,
    '2-3pm': 4,
    '3-4pm': 5,
}


def _next_on_or_after(d: date, weekday_name: str) -> date:
    target = WEEKDAY_INDEX[weekday_name]
    delta = (target - d.weekday()) % 7
    return d + timedelta(days=delta)


def _iter_events(start: date, end: date):
    for day in ALLOWED_DAYS:
        current = _next_on_or_after(start, day)
        while current < end:
            for slot in TIME_SLOTS_BY_DAY[day]:
                yield (current, day, slot)
            current = current + timedelta(days=7)


def ensure_schedule(start: date, weeks: int = 3) -> None:
    end = start + timedelta(weeks=weeks)
    existing = Lesson.query.filter(Lesson.lesson_date >= start, Lesson.lesson_date < end).first()
    if existing:
        return

    coaches = Coach.query.order_by(Coach.id).all()
    if not coaches:
        return

    # If templates exist, expand them
    if LessonTemplate.query.count() > 0:
        Lesson.generate_for_weeks(start_on=start, weeks=weeks, templates=None)
        return

    # Create one lesson per (date,slot) and assign evenly across coaches
    events = sorted(list(_iter_events(start, end)), key=lambda e: (e[0], e[2]))
    for idx, (dt, day, slot) in enumerate(events):
        coach = coaches[idx % len(coaches)]
        grade = GRADE_BY_SLOT.get(slot, 1)
        db.session.add(
            Lesson(
                day_of_week=day,
                time_slot=slot,
                grade_level=grade,
                coach_id=coach.id,
                lesson_date=dt,
            )
        )
    db.session.commit()


def integrate_new_coach(coach_id: int, start: date, weeks: int = 3) -> None:
    end = start + timedelta(weeks=weeks)
    coaches = Coach.query.order_by(Coach.id).all()
    if not coaches:
        return
    id_by_index = [c.id for c in coaches]
    events = sorted(list(_iter_events(start, end)), key=lambda e: (e[0], e[2]))

    for idx, (dt, day, slot) in enumerate(events):
        desired_id = id_by_index[idx % len(id_by_index)]
        # Ensure a single lesson per (date, slot)
        lessons = Lesson.query.filter(Lesson.lesson_date == dt, Lesson.time_slot == slot).all()
        if not lessons:
            db.session.add(
                Lesson(
                    day_of_week=day,
                    time_slot=slot,
                    grade_level=GRADE_BY_SLOT.get(slot, 1),
                    coach_id=desired_id,
                    lesson_date=dt,
                )
            )
            continue
        if len(lessons) > 1:
            # Already multiple; skip to avoid conflicts
            continue
        l = lessons[0]
        if l.coach_id == desired_id:
            continue
        # Only reassign if no bookings
        if len(l.bookings) == 0:
            l.coach_id = desired_id

    db.session.commit()
