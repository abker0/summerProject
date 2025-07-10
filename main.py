from config import app, db
from flask import Flask, render_template, jsonify
from models import Learner, Coach, Lesson, Booking, Review

@app.route('/')
def home():
    return "HJSS Management System - Welcome!"

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        print("Database tables created successfully!")
        
    app.run(debug=True)