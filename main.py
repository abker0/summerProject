from config import app, db
from flask import Flask,render_template, jsonify
from models import Learner, Coach, Lesson, Booking, Review








if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        
    app.run(debug=True)