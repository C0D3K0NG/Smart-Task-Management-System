"""
Smart Task Management System
Flask application with REST APIs, PostgreSQL, WebSockets, and Analytics
"""

from flask import Flask, request, jsonify, session, render_template, redirect, url_for, Response
from flask_socketio import SocketIO, emit, join_room
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import psycopg2
import psycopg2.extras
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, timedelta, timezone
import os
import re
import secrets
import csv
import io
from dotenv import load_dotenv
from analytics import get_analytics

load_dotenv()

# ─── App Setup ───────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")

# ─── Secure Session Config ───────────────────────────────────────────────────
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,   # Set True in production with HTTPS
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)

socketio = SocketIO(app)

# ─── Rate Limiter ────────────────────────────────────────────────────────────
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per minute"],
    storage_uri="memory://",
)

# ─── Database Config ─────────────────────────────────────────────────────────
DB_CONFIG = {
    "dbname":   os.environ.get("DB_NAME",     "task_manager"),
    "user":     os.environ.get("DB_USER",     "postgres"),
    "password": os.environ.get("DB_PASSWORD", "postgres"),
    "host":     os.environ.get("DB_HOST",     "localhost"),
    "port":     os.environ.get("DB_PORT",     "5432"),
}


def get_db():
    """Return a new database connection."""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False
    return conn


# ─── Security Headers ───────────────────────────────────────────────────────
@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # CSP — allow inline scripts for our templates, fonts from Google
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "connect-src 'self' ws: wss:; "
        "img-src 'self' data:; "
        "frame-ancestors 'none';"
    )
    return response


# ─── Validation Helpers ──────────────────────────────────────────────────────
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

def validate_password(password: str) -> str | None:
    """Return an error message if the password is weak, else None."""
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if not re.search(r"[a-z]", password):
        return "Password must contain a lowercase letter."
    if not re.search(r"[A-Z]", password):
        return "Password must contain an uppercase letter."
    if not re.search(r"\d", password):
        return "Password must contain a digit."
    if not re.search(r"[^A-Za-z0-9]", password):
        return "Password must contain a special character."
    return None


def validate_email(email: str) -> bool:
    return bool(EMAIL_REGEX.match(email))


def sanitize_text(text: str, max_len: int = 500) -> str:
    """Strip and truncate user text input."""
    return (text or "").strip()[:max_len]


def _serialize_task_dates(task: dict):
    """Serialize datetime/date fields on a task dict in-place."""
    if task.get("created_at"):
        task["created_at"] = task["created_at"].isoformat()
    if task.get("updated_at"):
        task["updated_at"] = task["updated_at"].isoformat()
    if task.get("due_date"):
        task["due_date"] = str(task["due_date"])


# ─── Auth Helper ─────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            if request.is_json:
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


# ─── Page Routes ─────────────────────────────────────────────────────────────
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login_page"))


@app.route("/login")
def login_page():
    return render_template("login.html")


@app.route("/register")
def register_page():
    return render_template("register.html")


@app.route("/forgot-password")
def forgot_password_page():
    return render_template("forgot_password.html")


@app.route("/reset-password/<token>")
def reset_password_page(token):
    return render_template("reset_password.html")


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", username=session.get("username"))


# ─── Auth API ────────────────────────────────────────────────────────────────
@app.route("/api/auth/register", methods=["POST"])
@limiter.limit("3 per minute")
def register():
    data = request.get_json()
    username = sanitize_text(data.get("username"), 80)
    email    = sanitize_text(data.get("email"), 120).lower()
    password = data.get("password", "")

    if not username or not email or not password:
        return jsonify({"error": "All fields are required"}), 400

    if not validate_email(email):
        return jsonify({"error": "Invalid email address"}), 400

    pw_err = validate_password(password)
    if pw_err:
        return jsonify({"error": pw_err}), 400

    pw_hash = generate_password_hash(password)
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s) RETURNING id",
            (username, email, pw_hash),
        )
        user_id = cur.fetchone()[0]
        conn.commit()
        cur.close(); conn.close()
        return jsonify({"message": "User registered successfully", "user_id": user_id}), 201
    except psycopg2.errors.UniqueViolation:
        return jsonify({"error": "Username or email already exists"}), 409
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/auth/login", methods=["POST"])
@limiter.limit("5 per minute")
def login():
    data     = request.get_json()
    username = sanitize_text(data.get("username"), 80)
    password = data.get("password", "")
    remember = data.get("remember", False)

    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400

    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        cur.close(); conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session.permanent = bool(remember)
            session["user_id"]  = user["id"]
            session["username"] = user["username"]
            return jsonify({"message": "Login successful", "username": user["username"]}), 200
        return jsonify({"error": "Invalid credentials"}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/auth/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    return jsonify({"message": "Logged out successfully"}), 200


# ─── Forgot / Reset Password ────────────────────────────────────────────────
@app.route("/api/auth/forgot-password", methods=["POST"])
@limiter.limit("3 per minute")
def forgot_password():
    data  = request.get_json()
    email = sanitize_text(data.get("email"), 120).lower()

    if not email or not validate_email(email):
        return jsonify({"error": "Valid email is required"}), 400

    # Always return success to avoid email enumeration
    message = "If an account exists for that email, a reset link has been generated. Check the server console."

    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        user = cur.fetchone()

        if user:
            token = secrets.token_urlsafe(48)
            expires = datetime.now(timezone.utc) + timedelta(hours=1)
            cur.execute(
                "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (%s, %s, %s)",
                (user["id"], token, expires),
            )
            conn.commit()

            # In production, send this via email. For dev, print to console.
            reset_url = f"http://localhost:5000/reset-password/{token}"
            print("\n" + "=" * 60)
            print("🔐 PASSWORD RESET LINK (dev mode)")
            print(f"   Email: {email}")
            print(f"   URL:   {reset_url}")
            print(f"   Expires: {expires.isoformat()}")
            print("=" * 60 + "\n")

        cur.close(); conn.close()
    except Exception:
        pass  # Silently fail — don't reveal database errors

    return jsonify({"message": message}), 200


@app.route("/api/auth/reset-password", methods=["POST"])
@limiter.limit("5 per minute")
def reset_password():
    data     = request.get_json()
    token    = (data.get("token") or "").strip()
    password = data.get("password", "")

    if not token:
        return jsonify({"error": "Reset token is required"}), 400

    pw_err = validate_password(password)
    if pw_err:
        return jsonify({"error": pw_err}), 400

    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Find valid, unused, non-expired token
        cur.execute(
            """SELECT * FROM password_reset_tokens
               WHERE token = %s AND used = FALSE AND expires_at > NOW()""",
            (token,),
        )
        reset_row = cur.fetchone()

        if not reset_row:
            cur.close(); conn.close()
            return jsonify({"error": "Invalid or expired reset link"}), 400

        # Update password
        pw_hash = generate_password_hash(password)
        cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (pw_hash, reset_row["user_id"]))

        # Mark token as used
        cur.execute("UPDATE password_reset_tokens SET used = TRUE WHERE id = %s", (reset_row["id"],))

        conn.commit()
        cur.close(); conn.close()

        return jsonify({"message": "Password reset successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Task API ────────────────────────────────────────────────────────────────
@app.route("/api/tasks", methods=["GET"])
@login_required
def get_tasks():
    """Get all tasks for the logged-in user."""
    user_id  = session["user_id"]
    status   = request.args.get("status")
    priority = request.args.get("priority")

    query  = "SELECT * FROM tasks WHERE user_id = %s"
    params = [user_id]

    if status:
        query += " AND status = %s"
        params.append(status)
    if priority:
        query += " AND priority = %s"
        params.append(priority)

    query += " ORDER BY created_at DESC"

    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(query, params)
        tasks = [dict(t) for t in cur.fetchall()]
        for t in tasks:
            _serialize_task_dates(t)
        cur.close(); conn.close()
        return jsonify({"tasks": tasks, "count": len(tasks)}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/tasks", methods=["POST"])
@login_required
def add_task():
    """Add a new task."""
    data        = request.get_json()
    title       = sanitize_text(data.get("title"), 200)
    description = sanitize_text(data.get("description"), 2000)
    priority    = data.get("priority", "medium")
    status      = data.get("status",   "pending")
    due_date    = data.get("due_date") or None
    user_id     = session["user_id"]

    if not title:
        return jsonify({"error": "Title is required"}), 400
    if priority not in ("low", "medium", "high"):
        return jsonify({"error": "Priority must be low, medium, or high"}), 400
    if status not in ("pending", "in_progress", "completed"):
        return jsonify({"error": "Invalid status"}), 400

    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """INSERT INTO tasks (user_id, title, description, priority, status, due_date)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
            (user_id, title, description, priority, status, due_date),
        )
        task = dict(cur.fetchone())
        conn.commit()
        cur.close(); conn.close()
        _serialize_task_dates(task)

        socketio.emit("task_added", task, to=f"user_{user_id}")
        return jsonify({"message": "Task created", "task": task}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/tasks/<int:task_id>", methods=["PUT"])
@login_required
def update_task(task_id):
    """Update an existing task."""
    data    = request.get_json()
    user_id = session["user_id"]

    allowed = {"title", "description", "priority", "status", "due_date"}
    updates = {}
    for k, v in data.items():
        if k in allowed:
            if k == "title":
                updates[k] = sanitize_text(v, 200)
            elif k == "description":
                updates[k] = sanitize_text(v, 2000)
            elif k == "due_date":
                updates[k] = v or None
            else:
                updates[k] = v

    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400

    # Validate enum fields
    if "priority" in updates and updates["priority"] not in ("low", "medium", "high"):
        return jsonify({"error": "Priority must be low, medium, or high"}), 400
    if "status" in updates and updates["status"] not in ("pending", "in_progress", "completed"):
        return jsonify({"error": "Invalid status"}), 400

    set_clause = ", ".join(f"{k} = %s" for k in updates)
    values     = list(updates.values()) + [task_id, user_id]

    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            f"UPDATE tasks SET {set_clause}, updated_at = NOW() "
            f"WHERE id = %s AND user_id = %s RETURNING *",
            values,
        )
        task = cur.fetchone()
        if not task:
            cur.close(); conn.close()
            return jsonify({"error": "Task not found"}), 404
        task = dict(task)
        conn.commit()
        cur.close(); conn.close()

        _serialize_task_dates(task)

        socketio.emit("task_updated", task, to=f"user_{user_id}")
        return jsonify({"message": "Task updated", "task": task}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
@login_required
def delete_task(task_id):
    """Delete a task."""
    user_id = session["user_id"]
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute(
            "DELETE FROM tasks WHERE id = %s AND user_id = %s RETURNING id",
            (task_id, user_id),
        )
        deleted = cur.fetchone()
        if not deleted:
            cur.close(); conn.close()
            return jsonify({"error": "Task not found"}), 404
        conn.commit()
        cur.close(); conn.close()

        socketio.emit("task_deleted", {"id": task_id}, to=f"user_{user_id}")
        return jsonify({"message": "Task deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Task Duplicate ──────────────────────────────────────────────────────────
@app.route("/api/tasks/<int:task_id>/duplicate", methods=["POST"])
@login_required
def duplicate_task(task_id):
    """Duplicate an existing task."""
    user_id = session["user_id"]
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM tasks WHERE id = %s AND user_id = %s", (task_id, user_id))
        original = cur.fetchone()
        if not original:
            cur.close(); conn.close()
            return jsonify({"error": "Task not found"}), 404

        cur.execute(
            """INSERT INTO tasks (user_id, title, description, priority, status, due_date)
               VALUES (%s, %s, %s, %s, 'pending', %s) RETURNING *""",
            (user_id, f"{original['title']} (copy)", original["description"],
             original["priority"], original["due_date"]),
        )
        task = dict(cur.fetchone())
        conn.commit()
        cur.close(); conn.close()
        _serialize_task_dates(task)

        socketio.emit("task_added", task, to=f"user_{user_id}")
        return jsonify({"message": "Task duplicated", "task": task}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Export Tasks (CSV) ──────────────────────────────────────────────────────
@app.route("/api/tasks/export", methods=["GET"])
@login_required
def export_tasks():
    """Export all tasks as CSV."""
    user_id = session["user_id"]
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT title, description, priority, status, due_date, created_at, updated_at FROM tasks WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
        rows = cur.fetchall()
        cur.close(); conn.close()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Title", "Description", "Priority", "Status", "Due Date", "Created", "Updated"])
        for r in rows:
            writer.writerow([
                r["title"], r["description"], r["priority"], r["status"],
                str(r["due_date"]) if r["due_date"] else "",
                r["created_at"].isoformat() if r["created_at"] else "",
                r["updated_at"].isoformat() if r["updated_at"] else "",
            ])

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=taskflow_export.csv"},
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Analytics API ───────────────────────────────────────────────────────────
@app.route("/api/analytics", methods=["GET"])
@login_required
def analytics():
    """Return task analytics using Pandas & NumPy."""
    user_id = session["user_id"]
    try:
        result = get_analytics(user_id, DB_CONFIG)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── WebSocket Events ─────────────────────────────────────────────────────────
@socketio.on("connect")
def on_connect():
    if "user_id" in session:
        join_room(f"user_{session['user_id']}")
        emit("connected", {"message": "Connected to Task Manager WebSocket"})
    else:
        return False


@socketio.on("ping")
def on_ping():
    emit("pong", {"time": datetime.now(timezone.utc).isoformat()})


# ─── Main ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    socketio.run(app, debug=True, port=5000, allow_unsafe_werkzeug=True)
