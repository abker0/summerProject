from config import app, db
from flask import Flask, render_template, jsonify
from models import Learner, Coach, Lesson, Booking, Review
from sqlalchemy.orm import joinedload
import os

@app.route('/')
def home():
    return "HJSS Management System - Welcome!"

@app.route("/api/lessons", methods=["GET"])
def get_all_lessons():
    try:
        lessons = Lesson.query.options(joinedload(Lesson.coach)).all()
        
        lessons_data = []
        for lesson in lessons:
            lesson_dict = {
                'id': lesson.id,
                'day_of_week': lesson.day_of_week,
                'time_slot': lesson.time_slot,
                'grade_level': lesson.grade_level,
                'coach_id': lesson.coach_id,
                'coach_name': lesson.coach.name if lesson.coach else None,
                'max_capacity': lesson.max_capacity,
                'lesson_date': lesson.lesson_date.isoformat() if lesson.lesson_date else None,
                'available_spaces': lesson.get_available_spaces(),
                'is_full': lesson.is_full()
            }
            lessons_data.append(lesson_dict)
        
        return jsonify({
            'lessons': lessons_data,
            'total_count': len(lessons_data)
        })
    except Exception as e:
        return jsonify({
            'error': str(e),
            'message': 'Database error occurred while fetching lessons'
        }), 500


if __name__ == "__main__": 
    with app.app_context():
        db.create_all()
        
    app.run(debug=True)