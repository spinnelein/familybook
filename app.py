from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

app = Flask(__name__)
app.config.from_object('config.Config')

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

from models import User, Post, Comment, Tag  # Import models

# Register blueprints/routes (to be implemented)
# from routes import main as main_blueprint
# app.register_blueprint(main_blueprint)

# Start the scheduler
from scheduler import start_scheduler
start_scheduler()

if __name__ == "__main__":
    app.run(debug=True)
