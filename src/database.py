import sqlite3
import json
import logging
import bcrypt
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
DB_PATH = Path("database.db")


def get_db_connection() -> sqlite3.Connection:
    """Return a connection to the SQLite database with row factory enabled."""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize database schemas if tables do not exist."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON;")

    # 1. Users Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT CHECK(role IN ('researcher', 'approver', 'professor', 'student')) NOT NULL,
            learning_preference TEXT
        );
    """)
    
    # Run migration if adding column to existing DB
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN learning_preference TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # 2. Gap Reports Table (Stage 1-3 results)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gap_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sector TEXT UNIQUE NOT NULL,
            industry_demand TEXT NOT NULL,       -- JSON
            academic_landscape TEXT NOT NULL,     -- JSON
            gap_analysis TEXT NOT NULL,           -- JSON
            approved_by TEXT,
            approved_at TEXT
        );
    """)

    # 3. Syllabi Table (Stage 4 result)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS syllabi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gap_report_id INTEGER NOT NULL,
            course_title TEXT NOT NULL,
            course_code TEXT NOT NULL,
            credits INTEGER NOT NULL,
            hours_per_week REAL NOT NULL,
            learning_objectives TEXT NOT NULL,    -- JSON
            bibliography TEXT NOT NULL,           -- JSON
            approved_by TEXT,
            approved_at TEXT,
            FOREIGN KEY (gap_report_id) REFERENCES gap_reports (id) ON DELETE CASCADE
        );
    """)

    # 4. Weekly Contents Table (Lecciones, lecturas y consignas generadas por profesores/agentes)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS weekly_contents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            syllabus_id INTEGER NOT NULL,
            week_number INTEGER NOT NULL,
            title TEXT NOT NULL,
            activity_type TEXT NOT NULL,
            reading_material TEXT,                -- HTML/Markdown text generated for reading
            assignment_prompt TEXT,               -- Assignment text/question
            points INTEGER DEFAULT 10,
            UNIQUE(syllabus_id, week_number),
            FOREIGN KEY (syllabus_id) REFERENCES syllabi (id) ON DELETE CASCADE
        );
    """)

    # 5. Submissions Table (Respuestas enviadas por estudiantes)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weekly_content_id INTEGER NOT NULL,
            student_id TEXT NOT NULL,
            submitted_text TEXT NOT NULL,
            submitted_at TEXT NOT NULL,
            grade REAL,
            feedback TEXT,
            UNIQUE(weekly_content_id, student_id),
            FOREIGN KEY (weekly_content_id) REFERENCES weekly_contents (id) ON DELETE CASCADE
        );
    """)


    # 6. Learning Profiles (VARK Assessment)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS learning_profiles (
            user_id INTEGER PRIMARY KEY,
            visual_score INTEGER NOT NULL DEFAULT 0,
            aural_score INTEGER NOT NULL DEFAULT 0,
            reading_score INTEGER NOT NULL DEFAULT 0,
            kinesthetic_score INTEGER NOT NULL DEFAULT 0,
            dominant_style TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        );
    ''')

    # 7. Exam Diagnostics Table (Store adaptive practice exam results & knowledge gaps)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS exam_diagnostics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            weekly_content_id INTEGER NOT NULL,
            score REAL NOT NULL,
            mastered_topics TEXT NOT NULL,       -- JSON list
            knowledge_gaps TEXT NOT NULL,        -- JSON list
            completed_at TEXT NOT NULL,
            UNIQUE(student_id, weekly_content_id),
            FOREIGN KEY (weekly_content_id) REFERENCES weekly_contents (id) ON DELETE CASCADE
        );
    ''')

    # Seed some default users (upserting password_hash to ensure valid login)
    default_users = [
        ("investigador1", "password123", "researcher"),
        ("coordinador1", "password123", "approver"),
        ("profesor1", "password123", "professor"),
        ("estudiante1", "password123", "student"),
        ("VinicioPrueba", "1234", "student"),
        ("admin", "1234", "approver"),
    ]
    for username, plain_password, role in default_users:
        hashed_pw = bcrypt.hashpw(plain_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor.execute("SELECT id FROM users WHERE LOWER(username) = LOWER(?)", (username,))
        row = cursor.fetchone()
        if not row:
            cursor.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", (username, hashed_pw, role))
            logger.info(f"[DB SEED] Created user '{username}' (role={role})")
        else:
            cursor.execute("UPDATE users SET password_hash = ?, role = ? WHERE id = ?", (hashed_pw, role, row[0]))
            logger.info(f"[DB SEED] Updated password_hash for user '{username}' (id={row[0]})")

    try:
        cursor.execute("ALTER TABLE syllabi ADD COLUMN reference_material TEXT;")
    except Exception:
        pass

    conn.commit()
    conn.close()
    logger.info("Database initialized successfully.")


# --- Database Helper Functions ---

def save_gap_report(
    sector: str,
    industry_demand: Dict[str, Any],
    academic_landscape: Dict[str, Any],
    gap_analysis: Dict[str, Any],
    approved_by: Optional[str] = None,
    approved_at: Optional[str] = None
) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO gap_reports (sector, industry_demand, academic_landscape, gap_analysis, approved_by, approved_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(sector) DO UPDATE SET
            industry_demand=excluded.industry_demand,
            academic_landscape=excluded.academic_landscape,
            gap_analysis=excluded.gap_analysis,
            approved_by=excluded.approved_by,
            approved_at=excluded.approved_at;
    """, (
        sector,
        json.dumps(industry_demand, ensure_ascii=False),
        json.dumps(academic_landscape, ensure_ascii=False),
        json.dumps(gap_analysis, ensure_ascii=False),
        approved_by,
        approved_at
    ))
    # If updated, get row ID
    cursor.execute("SELECT id FROM gap_reports WHERE sector = ?", (sector,))
    row_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return row_id


def get_gap_report(sector: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM gap_reports WHERE sector = ?", (sector,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row["id"],
        "sector": row["sector"],
        "industry_demand": json.loads(row["industry_demand"]),
        "academic_landscape": json.loads(row["academic_landscape"]),
        "gap_analysis": json.loads(row["gap_analysis"]),
        "approved_by": row["approved_by"],
        "approved_at": row["approved_at"]
    }


def list_gap_reports() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, sector, approved_by, approved_at FROM gap_reports")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_users() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, role, learning_preference FROM users")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_learning_profile(username: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT lp.* FROM learning_profiles lp
        JOIN users u ON u.id = lp.user_id
        WHERE u.username = ?
    ''', (username,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def save_learning_profile(username: str, v: int, a: int, r: int, k: int, dominant: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
    user_row = cursor.fetchone()
    if not user_row:
        conn.close()
        return
        
    user_id = user_row["id"]
    cursor.execute('''
        INSERT INTO learning_profiles (user_id, visual_score, aural_score, reading_score, kinesthetic_score, dominant_style)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            visual_score=excluded.visual_score,
            aural_score=excluded.aural_score,
            reading_score=excluded.reading_score,
            kinesthetic_score=excluded.kinesthetic_score,
            dominant_style=excluded.dominant_style;
    ''', (user_id, v, a, r, k, dominant))
    conn.commit()
    conn.close()


def save_syllabus(
    gap_report_id: int,
    course_title: str,
    course_code: str,
    credits: int,
    hours_per_week: float,
    learning_objectives: List[Dict[str, Any]],
    bibliography: List[str],
    approved_by: Optional[str] = None,
    approved_at: Optional[str] = None,
    reference_material: Optional[str] = None
) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO syllabi (gap_report_id, course_title, course_code, credits, hours_per_week, learning_objectives, bibliography, approved_by, approved_at, reference_material)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        gap_report_id,
        course_title,
        course_code,
        credits,
        hours_per_week,
        json.dumps(learning_objectives, ensure_ascii=False),
        json.dumps(bibliography, ensure_ascii=False),
        approved_by,
        approved_at,
        reference_material
    ))
    syllabus_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return syllabus_id


def get_syllabus_by_gap(gap_report_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM syllabi WHERE gap_report_id = ? ORDER BY id DESC LIMIT 1", (gap_report_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row["id"],
        "gap_report_id": row["gap_report_id"],
        "course_title": row["course_title"],
        "course_code": row["course_code"],
        "credits": row["credits"],
        "hours_per_week": row["hours_per_week"],
        "learning_objectives": json.loads(row["learning_objectives"]),
        "bibliography": json.loads(row["bibliography"]),
        "approved_by": row["approved_by"],
        "approved_at": row["approved_at"]
    }


def list_syllabi() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, gap_report_id, course_title, course_code, approved_by, approved_at FROM syllabi")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_weekly_content(
    syllabus_id: int,
    week_number: int,
    title: str,
    activity_type: str,
    reading_material: Optional[str] = None,
    assignment_prompt: Optional[str] = None,
    points: int = 10
) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO weekly_contents (syllabus_id, week_number, title, activity_type, reading_material, assignment_prompt, points)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(syllabus_id, week_number) DO UPDATE SET
            title=excluded.title,
            activity_type=excluded.activity_type,
            reading_material=COALESCE(excluded.reading_material, reading_material),
            assignment_prompt=COALESCE(excluded.assignment_prompt, assignment_prompt),
            points=excluded.points;
    """, (syllabus_id, week_number, title, activity_type, reading_material, assignment_prompt, points))
    conn.commit()
    conn.close()


def get_weekly_contents(syllabus_id: int) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM weekly_contents WHERE syllabus_id = ? ORDER BY week_number ASC", (syllabus_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_submission(
    weekly_content_id: int,
    student_id: str,
    submitted_text: str,
    submitted_at: str
) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if weekly_content_id exists in weekly_contents table
    cursor.execute("SELECT id FROM weekly_contents WHERE id = ?", (weekly_content_id,))
    wc_row = cursor.fetchone()
    
    if not wc_row:
        # If weekly_content_id doesn't exist, pick the most recent weekly_content or create a fallback row
        cursor.execute("SELECT id FROM weekly_contents ORDER BY id DESC LIMIT 1")
        latest_wc = cursor.fetchone()
        if latest_wc:
            weekly_content_id = latest_wc["id"]
        else:
            # Create a fallback syllabus and weekly_content row so foreign key constraint is satisfied
            cursor.execute("SELECT id FROM syllabi ORDER BY id DESC LIMIT 1")
            s_row = cursor.fetchone()
            if s_row:
                s_id = s_row["id"]
            else:
                cursor.execute("""
                    INSERT INTO gap_reports (sector, industry_demand, academic_landscape, gap_analysis)
                    VALUES ('General', '{}', '{}', '{}')
                """)
                g_id = cursor.lastrowid
                cursor.execute("""
                    INSERT INTO syllabi (gap_report_id, course_title, course_code, credits, hours_per_week, learning_objectives, bibliography)
                    VALUES (?, 'Curso General', 'CG-101', 3, 4, '[]', '[]')
                """, (g_id,))
                s_id = cursor.lastrowid
            
            cursor.execute("""
                INSERT INTO weekly_contents (syllabus_id, week_number, title, activity_type, assignment_prompt, points)
                VALUES (?, 1, 'Semana 1', 'Tarea', 'Consigna General', 10)
            """, (s_id,))
            weekly_content_id = cursor.lastrowid
            conn.commit()

    cursor.execute("""
        INSERT INTO submissions (weekly_content_id, student_id, submitted_text, submitted_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(weekly_content_id, student_id) DO UPDATE SET
            submitted_text=excluded.submitted_text,
            submitted_at=excluded.submitted_at;
    """, (weekly_content_id, student_id, submitted_text, submitted_at))
    conn.commit()
    
    # Fetch the ID
    cursor.execute("SELECT id FROM submissions WHERE weekly_content_id = ? AND student_id = ?", (weekly_content_id, student_id))
    row = cursor.fetchone()
    sub_id = row["id"] if row else cursor.lastrowid
    conn.close()
    return sub_id


def get_submissions(student_id: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.*, wc.week_number, wc.title as week_title, wc.assignment_prompt
        FROM submissions s
        JOIN weekly_contents wc ON s.weekly_content_id = wc.id
        WHERE s.student_id = ?
        ORDER BY wc.week_number ASC
    """, (student_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def grade_submission(submission_id: int, grade: float, feedback: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE submissions SET grade = ?, feedback = ? WHERE id = ?
    """, (grade, feedback, submission_id))
    conn.commit()
    conn.close()

# --- Auth Helper Functions ---

def create_user(username: str, plain_password: str, role: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    hashed_pw = bcrypt.hashpw(plain_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    try:
        cursor.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", (username, hashed_pw, role))
        user_id = cursor.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise ValueError(f"User {username} already exists")
    conn.close()
    return user_id

def verify_user(username: str, plain_password: str) -> Optional[Dict[str, Any]]:
    clean_user = username.strip()
    logger.info(f"[DB AUTH] Verifying credentials for username='{clean_user}'")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (clean_user,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        logger.warning(f"[DB AUTH] FAILED: Username '{clean_user}' not found in SQLite DB!")
        return None

    db_username = row["username"]
    db_role = row["role"]
    db_hash = row["password_hash"]
    logger.info(f"[DB AUTH] User '{db_username}' found in DB (role={db_role}). Checking bcrypt hash...")

    try:
        pw_bytes = plain_password.encode('utf-8')
        hash_bytes = db_hash.encode('utf-8') if isinstance(db_hash, str) else db_hash
        if bcrypt.checkpw(pw_bytes, hash_bytes):
            logger.info(f"[DB AUTH] SUCCESS: Password verified for user='{db_username}' (role={db_role})")
            return {"id": row["id"], "username": db_username, "role": db_role}
        else:
            logger.warning(f"[DB AUTH] FAILED: Password mismatch for user='{db_username}'!")
    except Exception as e:
        logger.exception(f"[DB AUTH] ERROR during bcrypt.checkpw for user='{db_username}': {e}")

    return None


def save_exam_diagnostic(
    student_id: str,
    weekly_content_id: int,
    score: float,
    mastered_topics: List[str],
    knowledge_gaps: List[str]
) -> int:
    import datetime
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.datetime.now().isoformat()
    cursor.execute("""
        INSERT INTO exam_diagnostics (student_id, weekly_content_id, score, mastered_topics, knowledge_gaps, completed_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(student_id, weekly_content_id) DO UPDATE SET
            score=excluded.score,
            mastered_topics=excluded.mastered_topics,
            knowledge_gaps=excluded.knowledge_gaps,
            completed_at=excluded.completed_at;
    """, (student_id, weekly_content_id, score, json.dumps(mastered_topics), json.dumps(knowledge_gaps), now_str))
    diag_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return diag_id


def get_exam_diagnostic(student_id: str, weekly_content_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM exam_diagnostics WHERE student_id = ? AND weekly_content_id = ?
    """, (student_id, weekly_content_id))
    row = cursor.fetchone()
    conn.close()
    if row:
        d = dict(row)
        d["mastered_topics"] = json.loads(d["mastered_topics"]) if d["mastered_topics"] else []
        d["knowledge_gaps"] = json.loads(d["knowledge_gaps"]) if d["knowledge_gaps"] else []
        return d
    return None


def get_student_analytics_data(student_id: str) -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Exam Diagnostics
    cursor.execute("""
        SELECT ed.*, wc.week_number, wc.title as week_title, s.course_title
        FROM exam_diagnostics ed
        JOIN weekly_contents wc ON ed.weekly_content_id = wc.id
        JOIN syllabi s ON wc.syllabus_id = s.id
        WHERE ed.student_id = ?
        ORDER BY wc.week_number ASC
    """, (student_id,))
    diag_rows = cursor.fetchall()
    
    exam_history = []
    total_score = 0.0
    all_mastered = []
    all_gaps = []

    for r in diag_rows:
        row_dict = dict(r)
        m_list = json.loads(row_dict["mastered_topics"]) if row_dict["mastered_topics"] else []
        g_list = json.loads(row_dict["knowledge_gaps"]) if row_dict["knowledge_gaps"] else []
        score = float(row_dict["score"])
        total_score += score
        all_mastered.extend(m_list)
        all_gaps.extend(g_list)

        exam_history.append({
            "weekly_content_id": row_dict["weekly_content_id"],
            "week_number": row_dict["week_number"],
            "week_title": row_dict["week_title"],
            "course_title": row_dict["course_title"],
            "score": score,
            "mastered_topics": m_list,
            "knowledge_gaps": g_list,
            "completed_at": row_dict["completed_at"]
        })

    avg_score = round(total_score / len(exam_history), 1) if exam_history else 0.0

    # 2. Submissions count
    cursor.execute("SELECT COUNT(*) as cnt FROM submissions WHERE student_id = ?", (student_id,))
    sub_row = cursor.fetchone()
    submission_count = sub_row["cnt"] if sub_row else 0

    # 3. VARK Profile
    cursor.execute("""
        SELECT lp.*, u.username
        FROM users u
        LEFT JOIN learning_profiles lp ON u.id = lp.user_id
        WHERE u.username = ?
    """, (student_id,))
    prof_row = cursor.fetchone()
    vark_profile = dict(prof_row) if prof_row else {}

    conn.close()

    return {
        "student_id": student_id,
        "avg_score": avg_score,
        "exams_completed": len(exam_history),
        "submissions_count": submission_count,
        "mastered_topics_count": len(all_mastered),
        "active_gaps_count": len(all_gaps),
        "exam_history": exam_history,
        "mastered_topics": list(set(all_mastered)),
        "knowledge_gaps": list(set(all_gaps)),
        "vark_profile": vark_profile
    }


def resolve_student_knowledge_gap(student_id: str, weekly_content_id: int, gap_name: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM exam_diagnostics WHERE student_id = ? AND weekly_content_id = ?
    """, (student_id, weekly_content_id))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return False

    mastered = json.loads(row["mastered_topics"]) if row["mastered_topics"] else []
    gaps = json.loads(row["knowledge_gaps"]) if row["knowledge_gaps"] else []

    target_gap = None
    gap_clean = gap_name.strip().lower()
    for g in gaps:
        if g.strip().lower() == gap_clean or gap_clean in g.lower() or g.lower() in gap_clean:
            target_gap = g
            break

    if target_gap:
        gaps.remove(target_gap)
        if target_gap not in mastered:
            mastered.append(target_gap)

        cursor.execute("""
            UPDATE exam_diagnostics
            SET mastered_topics = ?, knowledge_gaps = ?
            WHERE id = ?
        """, (json.dumps(mastered), json.dumps(gaps), row["id"]))
        conn.commit()
        conn.close()
        return True

    if gap_name and gap_name not in mastered:
        mastered.append(gap_name)
        cursor.execute("""
            UPDATE exam_diagnostics
            SET mastered_topics = ?
            WHERE id = ?
        """, (json.dumps(mastered), row["id"]))
        conn.commit()

    conn.close()
    return True

