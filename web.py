from flask import Flask, render_template, request, redirect, url_for
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

import os
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3

import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'

login_manager = LoginManager(app)
login_manager.login_view = 'login'

connection = sqlite3.connect("sqlite.db", check_same_thread=False)
connection.row_factory = sqlite3.Row
cursor = connection.cursor()

UPLOAD_FOLDER = 'static/blog_images'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg'}

def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

class User(UserMixin):
    def __init__(self, id, username, password_hash):
        self.id = int(id)
        self.username = username
        self.password_hash = password_hash

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    user = cursor.execute("SELECT * FROM user WHERE id = ?", (user_id,)).fetchone()
    if user is not None:
        return User(user[0], user[1], user[2])
    return None

def create_table():
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS post (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            content_image IMAGE
        )
    """)
    connection.commit()

create_table()

@app.route('/')
def index():
    cursor.execute("""
        SELECT
            post.id,
            post.title,
            post.content,
            post.content_image,
            post.author_id,
            user.username,
            COUNT(like.id) AS likes
        FROM post
        JOIN user ON post.author_id = user.id
        LEFT JOIN like ON post.id = like.post_id
        GROUP BY post.id, post.title, post.content, post.content_image, post.author_id, user.username
    """)

    result = cursor.fetchall()
    posts = []
    for post in reversed(result):
        posts.append(
            {'id': post[0], 'title': post[1], 'content': post[2], 'content_image': post[3], 'author_id': post[4], 'username': post[5], 'likes': post[6]}
        )
        if current_user.is_authenticated:
            cursor.execute(
                'SELECT post_id FROM like WHERE user_id = ?', (current_user.id,)
            )
            likes_result = cursor.fetchall()
            liked_posts = []
            for like in likes_result:
                liked_posts.append(like[0])
            posts[-1]['liked_posts'] = liked_posts
    context = {'posts': posts}
    return render_template("index.html", **context)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        try:
            cursor.execute('INSERT INTO user (username, password_hash, email) VALUES (?, ?, ?)', (username, generate_password_hash(password), email))
            connection.commit()
            print("User registered successfully")
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            return render_template('register.html', message="Username already exists")
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = cursor.execute(
            "SELECT id, username, password_hash FROM user WHERE username = ?",
            (username,)
        ).fetchone()

        if user:
            user_obj = User(user[0], user[1], user[2])
            if user_obj.check_password(password):
                login_user(user_obj)
                return redirect(url_for('index'))
            print("User logged in")

        return render_template("login.html", message="Invalid username or password")

    return render_template("login.html")

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/post/<int:post_id>')
def post(post_id):
    cursor.execute("""
        SELECT post.id, post.title, post.content, post.content_image , post.author_id, user.username
        FROM post
        JOIN user ON post.author_id = user.id
        WHERE post.id = ?
    """, (post_id,))

    row = cursor.fetchone()
    if not row:
        return "Post not found", 404

    post = {
        "id": row["id"],
        "title": row["title"],
        "content": row["content"],
        "content_image": row["content_image"],
        "author_id": row["author_id"],
        "username": row["username"]
    }

    return render_template("post.html", post=post)

@app.route('/add_post', methods=['GET', 'POST'])
@login_required
def add_post():
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']

        image = request.files.get('image')

        image_filename = None

        if image and image.filename != "":
            if allowed_file(image.filename):
                ext = image.filename.rsplit('.', 1)[1].lower()
                filename = f"{uuid.uuid4()}.{ext}"

                image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                image_filename = filename

        cursor.execute(
            'INSERT INTO post (title, content, content_image, author_id) VALUES (?, ?, ?, ?)',
            (title, content, image_filename, current_user.id)
        )
        connection.commit()

        return redirect(url_for('index'))

    return render_template('add_post.html')

@app.route('/delete/<int:post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    post = cursor.execute(
        "SELECT id, title, content, content_image, author_id FROM post WHERE id = ?",
        (post_id,)
    ).fetchone()

    if post is None:
        return "Post not found", 404

    if int(post["author_id"]) != int(current_user.id):
        return "Error", 403

    if post and post[4] == current_user.id:
        cursor.execute('DELETE FROM post WHERE id = ?', (post_id,))
        connection.commit()
        return redirect(url_for('index'))
    else:
        return redirect(url_for('index'))

def user_is_liking(user_id, post_id):
    like = cursor.execute('SELECT * FROM like WHERE user_id = ? AND post_id = ?',
        (user_id, post_id)).fetchone()
    return bool(like)

@app.route('/like/<int:post_id>')
@login_required
def like_post(post_id):
    post = cursor.execute('SELECT * FROM post WHERE id = ?', (post_id,)).fetchone()
    if post:
        if user_is_liking(current_user.id, post_id):
            cursor.execute(
                'DELETE FROM like WHERE user_id = ? AND post_id = ?',
                (current_user.id, post_id))
            connection.commit()
            print("You unliked this post.")
        else:
            cursor.execute(
                'INSERT INTO like (user_id, post_id) VALUES (?, ?)',
                (current_user.id, post_id))
            connection.commit()
            print("You liked this post.")
        return redirect(url_for('index'))
    return 'Post not found', 404

if __name__ == '__main__':
    app.run()