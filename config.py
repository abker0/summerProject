from flask import Flask
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
CORS(app)

# Flask configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')

# Set up base directory for fallback SQLite database
basedir = os.path.abspath(os.path.dirname(__file__))
# Determine database URI from environment or fallback to a local SQLite file
db_url = os.environ.get('DATABASE_URL')
if not db_url:
    db_file = os.path.join(basedir, 'app.db')
    db_url = 'sqlite:///{}'.format(db_file.replace(os.sep, '/'))
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize SQLAlchemy
db = SQLAlchemy(app)
