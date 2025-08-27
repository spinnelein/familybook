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
        db = get_db()
        db.execute(
            "INSERT INTO posts (title, content) VALUES (?, ?)",
            (title, content)
        )
        db.commit()
        flash("Post created!", "success")
        return redirect(url_for('create_post'))

    return render_template('create_post.html')

@app.route('/posts')
def posts_feed():
    db = get_db()
    posts = db.execute("SELECT * FROM posts ORDER BY created DESC").fetchall()
    return render_template('posts_feed.html', posts=posts)

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

if __name__ == "__main__":
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    init_db()
    app.run(debug=True)