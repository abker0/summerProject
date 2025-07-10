from config import db
from datetime import datetime
import bcrypt

class Learner(db.Model):
    __tablename__ = 'learners'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    gender = db.Column(db.String(10), nullable=False)  # Male/Female
    age = db.Column(db.Integer, nullable=False)  #4-11 years
    emergency_contact = db.Column(db.String(15), nullable=False)
    current_grade = db.Column(db.Integer, nullable=False, default=0)  #0-5
    created_at = db.Column(db.DateTime, default=datetime.now())
    
    bookings = db.relationship('Booking', backref='learner', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Learner {self.name}, Grade {self.current_grade}>'
    
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
    
    def can_book_grade(self, lesson_grade):
        """Check if learner can book a lesson of given grade"""
        return lesson_grade == self.current_grade or lesson_grade == self.current_grade + 1

class Coach(db.Model):
    __tablename__ = 'coaches'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    phone = db.Column(db.String(15))
    
    lessons = db.relationship('Lesson', backref='coach', lazy=True)
    
    def __repr__(self):
        return f'<Coach {self.name}>'
    
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

class Lesson(db.Model):
    __tablename__ = 'lessons'
    
    id = db.Column(db.Integer, primary_key=True)
    day_of_week = db.Column(db.String(10), nullable=False)  #Monday, Wednesday, Friday, Saturday
    time_slot = db.Column(db.String(10), nullable=False)    #4-5pm, 5-6pm, 6-7pm, 2-3pm, 3-4pm
    grade_level = db.Column(db.Integer, nullable=False)     #1-5
    coach_id = db.Column(db.Integer, db.ForeignKey('coaches.id'), nullable=False)
    max_capacity = db.Column(db.Integer, default=4)
    lesson_date = db.Column(db.Date, nullable=False)
    
    # Relationships
    bookings = db.relationship('Booking', backref='lesson', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Lesson Grade {self.grade_level} on {self.day_of_week} {self.time_slot}>'
    
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
        return f'<Booking {self.learner.name} - {self.lesson.day_of_week} {self.lesson.time_slot}>'
    
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
    review_date = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Review {self.rating}/5 for Booking {self.booking_id}>'
    
    @staticmethod
    def validate_rating(rating):
        """Validate rating is between 1 and 5"""
        return 1 <= rating <= 5