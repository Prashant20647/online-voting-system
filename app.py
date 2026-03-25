from flask import Flask, render_template, request, redirect, session
import os
import re
from werkzeug.utils import secure_filename

# DB imports
import sqlite3

app = Flask(__name__)
app.secret_key = "secret123"

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

UPLOAD_FOLDER = "static/images"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'png','jpg','jpeg'}


# ---------------- DB LOGIC ----------------

def get_db_connection():
    DATABASE_URL = os.environ.get("DATABASE_URL")

    if DATABASE_URL:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
    else:
        conn = sqlite3.connect("database.db", check_same_thread=False)

    return conn


def q(query):
    if os.environ.get("DATABASE_URL"):
        return query.replace("?", "%s")
    return query


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS


# ---------------- DATABASE ----------------

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    if os.environ.get("DATABASE_URL"):
        id_type = "SERIAL PRIMARY KEY"
    else:
        id_type = "INTEGER PRIMARY KEY AUTOINCREMENT"

    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS users(
        id {id_type},
        username TEXT UNIQUE,
        password TEXT,
        voter_id TEXT UNIQUE,
        approved INTEGER DEFAULT 1
    )
    """)

    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS elections(
        id {id_type},
        title TEXT,
        status TEXT DEFAULT 'stopped'
    )
    """)

    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS candidates(
        id {id_type},
        election_id INTEGER,
        name TEXT,
        party TEXT,
        photo TEXT,
        symbol TEXT
    )
    """)

    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS votes(
        id {id_type},
        election_id INTEGER,
        username TEXT,
        candidate TEXT
    )
    """)

    conn.commit()
    conn.close()





# ---------------- HOME ----------------

@app.route('/')
def home():
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(q("SELECT * FROM elections"))
        elections = cur.fetchall()

        conn.close()
    except:
        elections = []

    return render_template("index.html", elections=elections)


# ---------------- REGISTER ----------------

@app.route('/register',methods=['GET','POST'])
def register():
    if request.method == 'POST':

        username = request.form['username']
        password = request.form['password']
        voter_id = request.form['voter_id']

        pattern = r'^[A-Z]{3}[0-9]{7}$'

        if not re.match(pattern, voter_id):
            return render_template("register.html",
                                   message="Invalid Voter ID format")

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(q("SELECT * FROM users WHERE username=?"), (username,))
        if cur.fetchone():
            conn.close()
            return render_template("register.html", message="Username exists")

        cur.execute(q("SELECT * FROM users WHERE voter_id=?"), (voter_id,))
        if cur.fetchone():
            conn.close()
            return render_template("register.html", message="Voter ID exists")

        cur.execute(
            q("INSERT INTO users (username,password,voter_id,approved) VALUES (?,?,?,1)"),
            (username,password,voter_id)
        )

        conn.commit()
        conn.close()

        return redirect('/login')

    return render_template("register.html")


# ---------------- LOGIN ----------------

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method == 'POST':

        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            q("SELECT * FROM users WHERE username=? AND password=?"),
            (username,password)
        )

        user = cur.fetchone()
        conn.close()

        if user:
            session['username'] = username
            return redirect('/')
        else:
            return render_template("login.html", message="Invalid login")

    return render_template("login.html")


# ---------------- VOTE ----------------

@app.route('/vote/<int:election_id>',methods=['GET','POST'])
def vote(election_id):

    if 'username' not in session:
        return redirect('/login')

    username = session['username']

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(q("SELECT approved FROM users WHERE username=?"), (username,))
    approved = cur.fetchone()

    if not approved or approved[0] == 0:
        return "Not verified"

    cur.execute(q("SELECT status FROM elections WHERE id=?"), (election_id,))
    status = cur.fetchone()

    if not status or status[0] == "stopped":
        return "Election not running"

    cur.execute(q("SELECT * FROM candidates WHERE election_id=?"), (election_id,))
    candidates = cur.fetchall()

    message = None

    if request.method == 'POST':

        candidate = request.form['candidate']

        cur.execute(q("""
        SELECT * FROM votes WHERE username=? AND election_id=?
        """),(username,election_id))

        if cur.fetchone():
            message = "Already voted"
        else:
            cur.execute(q("""
            INSERT INTO votes (election_id,username,candidate)
            VALUES (?,?,?)
            """),(election_id,username,candidate))

            conn.commit()
            message = "Vote success"

    conn.close()

    return render_template("vote.html", candidates=candidates, message=message)


# ---------------- RESULTS ----------------

@app.route('/results/<int:election_id>')
def results(election_id):

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(q("""
    SELECT c.name, c.party, c.photo, c.symbol, COUNT(v.id)
    FROM candidates c
    LEFT JOIN votes v
    ON c.name = v.candidate AND c.election_id = v.election_id
    WHERE c.election_id=?
    GROUP BY c.id
    ORDER BY COUNT(v.id) DESC
    """), (election_id,))

    data = cur.fetchall()
    conn.close()

    # total votes
    total_votes = sum([row[4] for row in data])

    winner = None
    is_tie = False

    if total_votes == 0:
        winner = None   # no votes
    else:
        max_votes = data[0][4]
        top_candidates = [row for row in data if row[4] == max_votes]

        if len(top_candidates) > 1:
            is_tie = True
            winner = None
        else:
            winner = data[0]

    return render_template("result.html",
                           candidates=data,
                           winner=winner,
                           is_tie=is_tie,
                           total_votes=total_votes)


# ---------------- ADMIN ----------------

@app.route('/admin')
def admin():

    if 'admin' not in session:
        return redirect('/admin_login')

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(q("SELECT * FROM elections"))
    elections = cur.fetchall()

    cur.execute(q("SELECT * FROM candidates"))
    candidates = cur.fetchall()

    cur.execute(q("SELECT id,username,voter_id,approved FROM users"))
    voters = cur.fetchall()

    conn.close()

    return render_template("admin.html",
                           elections=elections,
                           candidates=candidates,
                           voters=voters)


# ---------------- CREATE ELECTION ----------------

@app.route('/create_election',methods=['POST'])
def create_election():

    title = request.form['title']

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(q("INSERT INTO elections (title,status) VALUES (?,?)"),
                (title,'stopped'))

    conn.commit()
    conn.close()

    return redirect('/admin')


# ---------------- TOGGLE ----------------

@app.route('/toggle_election/<int:election_id>')
def toggle_election(election_id):

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(q("SELECT status FROM elections WHERE id=?"), (election_id,))
    status = cur.fetchone()

    if status and status[0] == "running":
        cur.execute(q("UPDATE elections SET status='stopped' WHERE id=?"), (election_id,))
    else:
        cur.execute(q("UPDATE elections SET status='running' WHERE id=?"), (election_id,))

    conn.commit()
    conn.close()

    return redirect('/admin')


# ---------------- DELETE ----------------

# ---------------- DELETE USER ----------------

@app.route('/delete_user/<int:id>')
def delete_user(id):

    if 'admin' not in session:
        return redirect('/admin_login')

    conn = get_db_connection()
    cur = conn.cursor()

    # get username first
    cur.execute(q("SELECT username FROM users WHERE id=?"), (id,))
    user = cur.fetchone()

    if user:
        username = user[0]

        # delete votes of that user
        cur.execute(q("DELETE FROM votes WHERE username=?"), (username,))

        # delete user
        cur.execute(q("DELETE FROM users WHERE id=?"), (id,))

        conn.commit()

    conn.close()
    return redirect('/admin')



# ---------------- ADD ----------------

@app.route('/add_candidate',methods=['POST'])
def add_candidate():

    election_id = request.form['election_id']
    name = request.form['name']
    party = request.form['party']

    photo = request.files['photo']
    symbol = request.files['symbol']

    if photo and symbol:

        photo_filename = secure_filename(photo.filename)
        symbol_filename = secure_filename(symbol.filename)

        photo.save(os.path.join(UPLOAD_FOLDER,photo_filename))
        symbol.save(os.path.join(UPLOAD_FOLDER,symbol_filename))

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(q("""
        INSERT INTO candidates (election_id,name,party,photo,symbol)
        VALUES (?,?,?,?,?)
        """),(election_id,name,party,photo_filename,symbol_filename))

        conn.commit()
        conn.close()

    return redirect('/admin')


# ---------------- ADMIN LOGIN ----------------

@app.route('/admin_login',methods=['GET','POST'])
def admin_login():

    if request.method == 'POST':

        username = request.form['username']
        password = request.form['password']

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect('/admin')
        else:
            return render_template("admin_login.html", message="Invalid admin credentials")

    return render_template("admin_login.html")


# ---------------- LOGOUT ----------------

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


# IMPORTANT FIX FOR RENDER
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)