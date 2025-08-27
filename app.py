import os
import uuid
import secrets
from flask import Flask, jsonify, request, redirect, url_for, render_template, send_from_directory, flash, session
from config import Config
from extensions import db
from models import User, Post, Comment, Tag, ImportedPhoto

app = Flask(__name__)
app.config.from_object(Config)

# Initialize extensions
db.init_app(app)

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'mov', 'avi', 'webm'}

def allowed_file(filename, allowed_exts):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_exts

def generate_magic_token():
    """Generate a secure random token for user authentication"""
    return secrets.token_urlsafe(32)

def require_valid_token(f):
    """Decorator to require a valid magic token for access"""
    def decorated_function(*args, **kwargs):
        token = request.args.get('token')
        if not token:
            return "Access denied. Valid token required.", 403
        
        user = User.query.filter_by(magic_token=token).first()
        if not user:
            return "Invalid token.", 403
            
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

def require_admin():
    """Decorator to require admin access"""
    def decorator(f):
        def decorated_function(*args, **kwargs):
            # Simple admin check - in a real app, this would be more sophisticated
            admin_key = request.args.get('admin_key') or request.form.get('admin_key')
            if admin_key != 'admin123':  # Simple admin key for demo
                return "Admin access required.", 403
            return f(*args, **kwargs)
        decorated_function.__name__ = f.__name__
        return decorated_function
    return decorator

@app.route('/create-post', methods=['GET', 'POST'])
@require_valid_token
def create_post():
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        
        post = Post(title=title, body=content)
        db.session.add(post)
        db.session.commit()
        
        flash("Post created!", "success")
        return redirect(url_for('create_post') + f"?token={request.args.get('token')}")

    return render_template('create_post.html', token=request.args.get('token'))

@app.route('/admin/users')
@require_admin()
def manage_users():
    users = User.query.all()
    return render_template('manage_users.html', users=users)

@app.route('/admin/users/add', methods=['POST'])
@require_admin()
def add_user():
    name = request.form['name']
    email = request.form['email']
    
    # Check if user already exists
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        flash("User with this email already exists!", "error")
        return redirect(url_for('manage_users') + "?admin_key=admin123")
    
    # Generate magic token
    magic_token = generate_magic_token()
    
    # Create new user
    user = User(name=name, email=email, magic_token=magic_token)
    db.session.add(user)
    db.session.commit()
    
    flash(f"User {name} added successfully!", "success")
    return redirect(url_for('manage_users') + "?admin_key=admin123")

@app.route('/admin/users/remove/<int:user_id>', methods=['POST'])
@require_admin()
def remove_user(user_id):
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    
    flash(f"User {user.name} removed successfully!", "success")
    return redirect(url_for('manage_users') + "?admin_key=admin123")

@app.route('/posts')
@require_valid_token
def posts_feed():
    posts = Post.query.order_by(Post.created_at.desc()).all()
    return render_template('posts_feed.html', posts=posts, token=request.args.get('token'))

@app.route('/upload-media', methods=['POST'])
def upload_media():
    file = request.files.get('file')
    if not file:
        return jsonify(error='No file'), 400
    ext = file.filename.rsplit('.', 1)[-1].lower()
    filename = f"img_{uuid.uuid4().hex}.{ext}"
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(path)
    url = url_for('uploaded_file', filename=filename, _external=True)
    return jsonify(location=url)
    
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/init_db')
def init_database():
    """Initialize the database with tables"""
    with app.app_context():
        db.create_all()
        flash("Database initialized!", "success")
    return "Database initialized successfully!"

if __name__ == "__main__":
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    with app.app_context():
        db.create_all()
    app.run(debug=True)