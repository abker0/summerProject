from config import db
from datetime import datetime, date, timedelta, time as dtime
import bcrypt
import pyotp
from sqlalchemy import and_

#Scheduling constants
ALLOWED_DAYS = ("Monday", "Wednesday", "Friday", "Saturday")
TIME_SLOTS_BY_DAY = {
    "Monday": ("4-5pm", "5-6pm", "6-7pm"),
    "Wednesday": ("4-5pm", "5-6pm", "6-7pm"),
    "Friday": ("4-5pm", "5-6pm", "6-7pm"),
    "Saturday": ("2-3pm", "3-4pm"),
}
TIME_SLOT_RANGES = {
    "4-5pm": (dtime(16, 0), dtime(17, 0)),
    "5-6pm": (dtime(17, 0), dtime(18, 0)),
    "6-7pm": (dtime(18, 0), dtime(19, 0)),
    "2-3pm": (dtime(14, 0), dtime(15, 0)),
    "3-4pm": (dtime(15, 0), dtime(16, 0)),
}
WEEKDAY_INDEX = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}


def _next_weekday_on_or_after(start: date, weekday_name: str) -> date:
    """Get the next date on or after start that matches weekday_name."""
    target = WEEKDAY_INDEX[weekday_name]
    delta = (target - start.weekday()) % 7
    return start + timedelta(days=delta)


class Learner(db.Model):
    __tablename__ = 'learners'
    
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(60), nullable=False)
    last_name = db.Column(db.String(60), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    two_factor_secret = db.Column(db.String(32))
    two_factor_enabled = db.Column(db.Boolean, default=False, nullable=False)
    gender = db.Column(db.String(20), nullable=False)  # Male/Female/Other/Rather not say
    age = db.Column(db.Integer, nullable=False)  #4-11 years
    emergency_contact = db.Column(db.String(15), nullable=False)
    current_grade = db.Column(db.Integer, nullable=False, default=0)  #0-5
    created_at = db.Column(db.DateTime, default=datetime.now())
    
    bookings = db.relationship('Booking', backref='learner', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Learner {self.first_name} {self.last_name}, Grade {self.current_grade}>'
    
    def set_password(self, password):
        """Hash and set the password"""
        password_bytes = password.encode('utf-8')
        salt = bcrypt.gensalt()
        self.password_hash = bcrypt.hashpw(password_bytes, salt).decode('utf-8')
    
    def check_password(self, password):
        """Check if the provided password matches the hash"""
        password_bytes = password.encode('utf-8')
        hash_bytes = self.password_hash.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hash_bytes)
    
    # --- 2FA helpers ---
    def ensure_2fa_secret(self):
        if not self.two_factor_secret:
            self.two_factor_secret = pyotp.random_base32()
        return self.two_factor_secret

    def provisioning_uri(self, issuer: str = "HJSS") -> str:
        secret = self.ensure_2fa_secret()
        # Use role prefix to distinguish in authenticator apps
        return pyotp.totp.TOTP(secret).provisioning_uri(name=f"Learner:{self.email}", issuer_name=issuer)

    def verify_totp(self, code: str) -> bool:
        if not self.two_factor_secret:
            return False
        totp = pyotp.TOTP(self.two_factor_secret)
        return totp.verify(code, valid_window=1)
    
    def can_book_grade(self, lesson_grade):
        """Check if learner can book a lesson of given grade"""
        return lesson_grade == self.current_grade or lesson_grade == self.current_grade + 1

class Coach(db.Model):
    __tablename__ = 'coaches'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(20), nullable=True)
    first_name = db.Column(db.String(60), nullable=False)
    last_name = db.Column(db.String(60), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    two_factor_secret = db.Column(db.String(32))
    two_factor_enabled = db.Column(db.Boolean, default=False, nullable=False)
    phone = db.Column(db.String(15))
    profile_image = db.Column(db.String(255))  # path to uploaded image under static/uploads
    about_me = db.Column(db.Text)
    
    lessons = db.relationship('Lesson', backref='coach', lazy=True)
    
    def __repr__(self):
        name = f"{self.first_name} {self.last_name}"
        return f'<Coach {self.title + " " if self.title else ""}{name}>'
    
    def set_password(self, password):
        """Hash and set the password"""
        password_bytes = password.encode('utf-8')
        salt = bcrypt.gensalt()
        self.password_hash = bcrypt.hashpw(password_bytes, salt).decode('utf-8')
    
    def check_password(self, password):
        """Check if the provided password matches the hash"""
        password_bytes = password.encode('utf-8')
        hash_bytes = self.password_hash.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hash_bytes)
    
    # --- 2FA helpers ---
    def ensure_2fa_secret(self):
        if not self.two_factor_secret:
            self.two_factor_secret = pyotp.random_base32()
        return self.two_factor_secret

    def provisioning_uri(self, issuer: str = "HJSS") -> str:
        secret = self.ensure_2fa_secret()
        return pyotp.totp.TOTP(secret).provisioning_uri(name=f"Coach:{self.email}", issuer_name=issuer)

    def verify_totp(self, code: str) -> bool:
        if not self.two_factor_secret:
            return False
        totp = pyotp.TOTP(self.two_factor_secret)
        return totp.verify(code, valid_window=1)
    
    def get_average_rating(self):
        """Calculate average rating for this coach"""
        ratings = []
        for lesson in self.lessons:
            for booking in lesson.bookings:
                if booking.review and booking.attended:
                    ratings.append(booking.review.rating)
        
        if ratings:
            return round(sum(ratings) / len(ratings), 2)
        return 0

    def get_review_count(self) -> int:
        count = 0
        for lesson in self.lessons:
            for booking in lesson.bookings:
                if booking.review is not None:
                    count += 1
        return count

class Lesson(db.Model):
    __tablename__ = 'lessons'

    id = db.Column(db.Integer, primary_key=True)
    day_of_week = db.Column(db.String(10), nullable=False)  # Monday, Wednesday, Friday, Saturday
    time_slot = db.Column(db.String(10), nullable=False)    # 4-5pm, 5-6pm, 6-7pm, 2-3pm, 3-4pm
    grade_level = db.Column(db.Integer, nullable=False)     # 1-5
    coach_id = db.Column(db.Integer, db.ForeignKey('coaches.id'), nullable=False)
    max_capacity = db.Column(db.Integer, default=4)
    lesson_date = db.Column(db.Date, nullable=False)

    #prevent duplicate lessons for a coach at the same date/time
    __table_args__ = (
        db.UniqueConstraint('lesson_date', 'time_slot', 'coach_id', name='uq_lesson_date_time_coach'),
    )

    # Relationships
    bookings = db.relationship('Booking', backref='lesson', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Lesson Grade {self.grade_level} on {self.day_of_week} {self.time_slot} ({self.lesson_date})>'

    @property
    def start_time(self) -> dtime:
        return TIME_SLOT_RANGES[self.time_slot][0]

    @property
    def end_time(self) -> dtime:
        return TIME_SLOT_RANGES[self.time_slot][1]

    def get_available_spaces(self):
        """Get number of available spaces in this lesson"""
        booked_count = Booking.query.filter_by(
            lesson_id=self.id, 
            booking_status='booked'
        ).count()
        return self.max_capacity - booked_count
    
    def is_full(self):
        """Check if lesson is at capacity"""
        return self.get_available_spaces() <= 0

    # --- Validation helpers ---
    @staticmethod
    def validate_day_and_slot(day_of_week: str, time_slot: str) -> None:
        if day_of_week not in ALLOWED_DAYS:
            raise ValueError(f"Invalid day_of_week: {day_of_week}. Must be one of {ALLOWED_DAYS}")
        allowed_slots = TIME_SLOTS_BY_DAY[day_of_week]
        if time_slot not in allowed_slots:
            raise ValueError(f"Invalid time_slot '{time_slot}' for {day_of_week}. Allowed: {allowed_slots}")

    # --- Query helpers ---
    @classmethod
    def by_date(cls, on_date: date):
        return cls.query.filter_by(lesson_date=on_date).order_by(cls.time_slot, cls.grade_level)

    @classmethod
    def by_day_of_week(cls, day_name: str):
        return cls.query.filter_by(day_of_week=day_name).order_by(cls.lesson_date, cls.time_slot)

    @classmethod
    def by_grade(cls, grade: int):
        return cls.query.filter_by(grade_level=grade).order_by(cls.lesson_date, cls.time_slot)

    @classmethod
    def by_coach(cls, coach_id: int):
        return cls.query.filter_by(coach_id=coach_id).order_by(cls.lesson_date, cls.time_slot)

    #create concrete lessons for a date range
    @classmethod
    def generate_for_weeks(
        cls,
        start_on: date,
        weeks: int = 4,
        templates: list["LessonTemplate"] | None = None,
    ) -> int:

        created = 0
        end_on = start_on + timedelta(weeks=weeks)

        if templates is None:
            templates = LessonTemplate.query.all()

        for tmpl in templates:
            Lesson.validate_day_and_slot(tmpl.day_of_week, tmpl.time_slot)
            first = _next_weekday_on_or_after(start_on, tmpl.day_of_week)
            week = 0
            while True:
                dt = first + timedelta(days=7 * week)
                if dt >= end_on:
                    break
                # Skip duplicates for same date/slot/coach
                exists = cls.query.filter(
                    and_(
                        cls.lesson_date == dt,
                        cls.time_slot == tmpl.time_slot,
                        cls.coach_id == tmpl.coach_id,
                    )
                ).first()
                if not exists:
                    db.session.add(
                        cls(
                            day_of_week=tmpl.day_of_week,
                            time_slot=tmpl.time_slot,
                            grade_level=tmpl.grade_level,
                            coach_id=tmpl.coach_id,
                            lesson_date=dt,
                        )
                    )
                    created += 1
                week += 1

        if created:
            db.session.commit()
        return created


class LessonTemplate(db.Model):
    """Weekly recurring lesson rule used to generate concrete Lessons."""
    __tablename__ = 'lesson_templates'

    id = db.Column(db.Integer, primary_key=True)
    day_of_week = db.Column(db.String(10), nullable=False)  # Must be in ALLOWED_DAYS
    time_slot = db.Column(db.String(10), nullable=False)    # Must be valid for that day
    grade_level = db.Column(db.Integer, nullable=False)     # 1-5
    coach_id = db.Column(db.Integer, db.ForeignKey('coaches.id'), nullable=False)

    coach = db.relationship('Coach', backref='lesson_templates')

    __table_args__ = (
        db.UniqueConstraint('day_of_week', 'time_slot', 'coach_id', 'grade_level', name='uq_template_day_time_coach_grade'),
    )

    def __repr__(self):
        return f'<Template {self.day_of_week} {self.time_slot} G{self.grade_level} Coach#{self.coach_id}>'

    def validate(self):
        Lesson.validate_day_and_slot(self.day_of_week, self.time_slot)
        if not (1 <= int(self.grade_level) <= 5):
            raise ValueError("grade_level must be between 1 and 5")

    def expand(self, start_on: date, weeks: int = 4) -> int:
        """Generate Lessons just for this template."""
        return Lesson.generate_for_weeks(start_on=start_on, weeks=weeks, templates=[self])


class Booking(db.Model):
    __tablename__ = 'bookings'
    
    id = db.Column(db.Integer, primary_key=True)
    learner_id = db.Column(db.Integer, db.ForeignKey('learners.id'), nullable=False)
    lesson_id = db.Column(db.Integer, db.ForeignKey('lessons.id'), nullable=False)
    booking_status = db.Column(db.String(20), default='booked')  # booked, cancelled, attended
    booking_date = db.Column(db.DateTime, default=datetime.now())
    attended = db.Column(db.Boolean, default=False)
    grade_updated = db.Column(db.Boolean, default=False)
    
    review = db.relationship('Review', backref='booking', uselist=False, cascade='all, delete-orphan')
    
    #prevents duplicate bookings
    __table_args__ = (db.UniqueConstraint('learner_id', 'lesson_id', name='unique_learner_lesson'),)
    
    def __repr__(self):
        learner_name = f"{self.learner.first_name} {self.learner.last_name}"
        return f'<Booking {learner_name} - {self.lesson.day_of_week} {self.lesson.time_slot}>'
    
    def mark_attended(self):
        """Mark booking as attended and update learner grade if applicable"""
        self.attended = True
        self.booking_status = 'attended'
        
        #update learner grade if have attended higher
        if (self.lesson.grade_level > self.learner.current_grade and 
            not self.grade_updated):
            self.learner.current_grade = self.lesson.grade_level
            self.grade_updated = True
        
        db.session.commit()

class Review(db.Model):
    __tablename__ = 'reviews'
    
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('bookings.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1-5
    comment = db.Column(db.Text)
    review_date = db.Column(db.DateTime, default=datetime.now)
    
    def __repr__(self):
        return f'<Review {self.rating}/5 for Booking {self.booking_id}>'
    
    @staticmethod
    def validate_rating(rating):
        """Validate rating is between 1 and 5"""
        return 1 <= rating <= 5


class CoachInvite(db.Model):
    __tablename__ = 'coach_invites'

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now())
    expires_at = db.Column(db.DateTime, nullable=True)
    used = db.Column(db.Boolean, default=False, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    used_by_coach_id = db.Column(db.Integer, db.ForeignKey('coaches.id'), nullable=True)

    used_by_coach = db.relationship('Coach', backref='used_invites', foreign_keys=[used_by_coach_id])

    def is_valid(self) -> bool:
        if self.used:
            return False
        if self.expires_at and self.expires_at < datetime.now():
            return False
        return True