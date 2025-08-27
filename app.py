import os
import sqlite3
import uuid
from flask import Flask, jsonify, request, redirect, url_for, render_template, send_from_directory, flash, g

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max upload size
app.config['DATABASE'] = 'familybook.db'
app.secret_key = 'your-secret-key'

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'mov', 'avi', 'webm'}

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def allowed_file(filename, allowed_exts):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_exts

def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            image_filename TEXT,
            video_filename TEXT,
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        db.commit()

@app.route('/create-post', methods=['GET', 'POST'])
def create_post():
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']

        image_filename = None
        video_filename = None

        # Handle image upload
        image_file = request.files.get('image')
        if image_file and image_file.filename:
            ext = image_file.filename.rsplit('.', 1)[-1].lower()
            if ext in ALLOWED_IMAGE_EXTENSIONS:
                image_filename = f"img_{uuid.uuid4().hex}.{ext}"
                image_path = os.path.join(app.config['UPLOAD_FOLDER'], image_filename)
                image_file.save(image_path)

        # Handle video upload
        video_file = request.files.get('video')
        if video_file and video_file.filename:
            ext = video_file.filename.rsplit('.', 1)[-1].lower()
            if ext in ALLOWED_VIDEO_EXTENSIONS:
                video_filename = f"vid_{uuid.uuid4().hex}.{ext}"
                video_path = os.path.join(app.config['UPLOAD_FOLDER'], video_filename)
                video_file.save(video_path)

        db = get_db()
        db.execute(
            "INSERT INTO posts (title, content, image_filename, video_filename) VALUES (?, ?, ?, ?)",
            (title, content, image_filename, video_filename)
        )
        db.commit()
        flash("Post created!", "success")
        return redirect(url_for('create_post'))    
    return render_template('create_post.html')

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

from flask import Flask, render_template, request, redirect, url_for, flash, abort
import uuid
import sqlite3
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['DATABASE'] = 'familybook.db'

def get_db():
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    return conn

# User management page
@app.route('/admin/users', methods=['GET', 'POST'])
def manage_users():
    db = get_db()
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        magic_token = uuid.uuid4().hex
        try:
            db.execute('INSERT INTO users (name, email, magic_token) VALUES (?, ?, ?)', (name, email, magic_token))
            db.commit()
            flash('User added!', 'success')
        except sqlite3.IntegrityError:
            flash('Email already exists!', 'danger')
        return redirect(url_for('manage_users'))

    users = db.execute('SELECT * FROM users').fetchall()
    return render_template('manage_users.html', users=users)

# Remove user
@app.route('/admin/users/remove/<int:user_id>', methods=['POST'])
def remove_user(user_id):
    db = get_db()
    db.execute('DELETE FROM users WHERE id = ?', (user_id,))
    db.commit()
    flash('User removed.', 'info')
    return redirect(url_for('manage_users'))

# Posts feed with magic link
@app.route('/posts/<magic_token>')
def posts(magic_token):
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE magic_token = ?', (magic_token,)).fetchone()
    if not user:
        abort(403)
    posts = db.execute('SELECT * FROM posts ORDER BY id DESC').fetchall()
    return render_template('posts.html', posts=posts, user=user)

# Remove the old /posts endpoint if it exists, or make it forbidden
@app.route('/posts')
def posts_no_token():
    abort(403)


if __name__ == "__main__":
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    init_db()
    app.run(debug=True)
    
    
    