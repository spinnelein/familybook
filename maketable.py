from flask import Flask
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///your_database.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

class ImportedPhoto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String, unique=True, nullable=False)
    filename = db.Column(db.String, nullable=False)
    status = db.Column(db.String, default="pending")

with app.app_context():
    try:
        db.create_all()
        print("Table 'imported_photo' created!")
    except Exception as e:
        print("ERROR:", e)