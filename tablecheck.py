from flask import Flask
from extensions import db
import models  # This must import ImportedPhoto

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///your_database.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

with app.app_context():
    db.create_all()
    print("All tables created.")