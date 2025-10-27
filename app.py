from flask import Flask, jsonify, render_template, request, redirect, url_for, flash, session
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import os
import twilio
from twilio.rest import Client

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET')
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

MAX_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(hours=1)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        conn = get_db_connection()
        cur = conn.cursor()

        # Fetch user info
        cur.execute("SELECT id, password, failed_attempts, lockout_time FROM users WHERE username = %s", (username,))
        user = cur.fetchone()

        if not user:
            flash("Invalid username or password.", "danger")
            cur.close()
            conn.close()
            return render_template("login.html")

        user_id, db_password, failed_attempts, lockout_time = user
        now = datetime.utcnow()

        # Check lockout
        if lockout_time and now < lockout_time:
            remaining = lockout_time - now
            minutes = remaining.seconds // 60
            flash(f"Too many failed attempts. Try again in {minutes} minutes.", "danger")
            cur.close()
            conn.close()
            return render_template("login.html")
        elif lockout_time and now >= lockout_time:
            # Reset lockout
            failed_attempts = 0
            lockout_time = None
            cur.execute("UPDATE users SET failed_attempts = 0, lockout_time = NULL WHERE id = %s", (user_id,))
            conn.commit()

        # Check password
        if password == db_password:  # replace with check_password_hash(db_password, password) if you hash
            # Successful login
            session["user"] = username
            cur.execute("UPDATE users SET failed_attempts = 0, lockout_time = NULL WHERE id = %s", (user_id,))
            conn.commit()
            flash("Welcome back!", "success")
            cur.close()
            conn.close()
            return redirect(url_for("index"))
        else:
            # Failed login
            failed_attempts += 1
            if failed_attempts >= MAX_ATTEMPTS:
                lockout_time = now + LOCKOUT_DURATION
                cur.execute("UPDATE users SET failed_attempts = %s, lockout_time = %s WHERE id = %s",
                            (failed_attempts, lockout_time, user_id))
                conn.commit()
                flash("Too many failed attempts. You are locked out for 1 hour.", "danger")
            else:
                cur.execute("UPDATE users SET failed_attempts = %s WHERE id = %s", (failed_attempts, user_id))
                conn.commit()
                attempts_left = MAX_ATTEMPTS - failed_attempts
                flash(f"Invalid credentials. You have {attempts_left} attempts left.", "danger")

        cur.close()
        conn.close()

    return render_template("login.html")

# optional: protect routes
from functools import wraps
def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapped


# ===========================
# 🔧 DATABASE CONFIGURATION
# ===========================
DB_URL = os.getenv('DB_URL')
# Helper function for connection
def get_db_connection():
    conn = psycopg2.connect(DB_URL)
    return conn

# Initialize the tables if they don't exist
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS workers (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT NOT NULL
        );
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS schedules (
            id SERIAL PRIMARY KEY,
            working_id INTEGER REFERENCES workers(id) ON DELETE CASCADE,
            date DATE,
            time TIME,
            place TEXT
        );
    ''')
    conn.commit()
    cur.close()
    conn.close()


# ===========================
# 📋 ROUTES
# ===========================

@app.route('/')
@login_required
def index():
    init_db()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        SELECT s.id, w.name, s.date, s.place, w.phone, w.id
        FROM schedules s
        JOIN workers w ON s.working_id = w.id
        ORDER BY s.date;
    ''')
    schedules = cur.fetchall()
    cur.close()
    conn.close()

    return render_template('index.html', schedules=schedules)

@app.route('/print_phones', methods=['POST'])
@login_required
def print_phones():
    selected_ids = request.form.getlist('worker_ids')
    print("📤 Received from frontend:", selected_ids)  # debug print

    if not selected_ids:
        print("⚠️ No IDs received")
        return redirect(url_for('index'))

    selected_ids = [int(i) for i in selected_ids if i.isdigit()]
    if not selected_ids:
        print("⚠️ After conversion, empty list")
        return redirect(url_for('index'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT name, phone FROM workers WHERE id = ANY(%s::int[])", (selected_ids,))
    workers = cur.fetchall()
    cur.close()
    conn.close()

    print("\n📞 Selected workers' phone numbers:")
    for w in workers:
        print(f"{w[0]}: {w[1]}")
    print("=====================================\n")

    return redirect(url_for('index'))

@app.route('/add_worker', methods=['GET', 'POST'])
@login_required
def add_worker():
    init_db()
    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO workers (name, phone) VALUES (%s, %s);", (name, phone))
        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for('index'))

    return render_template('add_worker.html')

from datetime import date

@app.route('/remind', methods=['POST'])
@login_required
def reminder():
    data = request.get_json()
    phone = data.get('phone')
    name = data.get('name')
    sms(name, phone,date= date.today(), time='the previous time specified', place='the previous place specified')
    return jsonify({"status": "success"})


def sms(name, phone, date, time, place):
    message = f'Good morning {name}, this is Marate AI. You are scheduled by Lat Dior SECURITY on {date} at {time} to be on shift at {place}. Be sure to be on time. Happy work.',
    try:
        account_sid = os.getenv('account_sid')
        auth_token = os.getenv('auth_token')
        client = Client(account_sid, auth_token)
        message = client.messages.create(
        from_='+18666100438',
        body=message,
        to=f'+{phone}'
        )
        print(message.sid)
        print(f'Good morning {name}, this is Marate AI. You are scheduled by Lat Dior SECURITY on {date} at {time} to be on shift at {place}. Be sure to be on time. Happy work.')
            
    except Exception as e:
        print(e)
        
@app.route('/schedule', methods=['GET', 'POST'])
@login_required
def schedule():
    init_db()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, phone FROM workers ORDER BY name;")
    workers = cur.fetchall()

    if request.method == 'POST':
        worker_id = request.form['worker']
        date = request.form['date']
        time = request.form['time']
        place = request.form['place']
        print(worker_id, date, time, place)
        cur.execute('select name, phone from workers where id = %s', (worker_id, ))
        res = cur.fetchall()
        print(res)
        res = res[0] # [('Jedidiah Mabuduko', '17249925310')]
        name = res[0]
        phone = res[1]
        try:
            account_sid = os.getenv('account_sid')
            auth_token = os.getenv('auth_token')
            client = Client(account_sid, auth_token)
            message = client.messages.create(
            from_='+18666100438',
            body=f'Good morning {name}, this is Marate AI. You are scheduled by Lat Dior SECURITY on {date} at {time} to be on shift at {place}. Be sure to be on time. Happy work. -- this is my last test i promise lol :)',
            to=f'+{phone}'
            )
            print(message.sid)
            print(f'Good morning {name}, this is Marate AI. You are scheduled by Lat Dior SECURITY on {date} at {time} to be on shift at {place}. Be sure to be on time. Happy work. -- this is my last test i promise lol :)')
            
        except Exception as e:
            print(e)

        cur.execute('''
            INSERT INTO schedules (working_id, date, place)
            VALUES (%s, %s, %s);
        ''', (worker_id, date, place))
        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for('index'))

    cur.close()
    conn.close()
    return render_template('schedule.html', workers=workers)

@app.route('/delete_schedule/<int:schedule_id>', methods=['POST'])
@login_required
def delete_schedule(schedule_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM schedules WHERE id = %s;", (schedule_id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('index'))


@app.route('/edit_worker/<int:worker_id>', methods=['GET', 'POST'])
@login_required
def edit_worker(worker_id):
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']

        # If you have profile pictures, handle file upload here
        # file = request.files.get('picture')
        # if file and file.filename != '':
        #     filename = secure_filename(file.filename)
        #     file.save(os.path.join('static/uploads', filename))
        #     cur.execute('UPDATE workers SET name=%s, phone=%s, picture=%s WHERE id=%s',
        #                 (name, phone, filename, worker_id))
        # else:
        cur.execute('UPDATE workers SET name=%s, phone=%s WHERE id=%s',
                    (name, phone, worker_id))
        conn.commit()

        cur.close()
        conn.close()
        flash('Worker information updated successfully!', 'success')
        return redirect(url_for('index'))  # or 'workers' if you have a dedicated workers list page

    # --- GET request: display form ---
    cur.execute('SELECT id, name, phone FROM workers WHERE id = %s', (worker_id,))
    worker = cur.fetchone()
    cur.close()
    conn.close()

    if not worker:
        return "Worker not found", 404

    return render_template('edit_worker.html', worker=worker)

@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))

@app.route('/workers')
@login_required
def workers():
    q = request.args.get('q', '').lower()
    conn = get_db_connection()
    cur = conn.cursor()
    if q:
        cur.execute("SELECT * FROM workers WHERE LOWER(name) LIKE %s OR phone LIKE %s", (f'%{q}%', f'%{q}%'))
    else:
        cur.execute("SELECT * FROM workers")
    workers = cur.fetchall()
    cur.close()
    conn.close()
    print(workers)
    return render_template('workers.html', workers=workers)

@app.route('/delete_worker/<int:worker_id>', methods=['POST'])
@login_required
def delete_worker(worker_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM workers WHERE id = %s", (worker_id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('workers'))


# ===========================
# 🚀 MAIN ENTRY
# ===========================
if __name__ == '__main__':
    init_db()
    app.run(debug=True)

