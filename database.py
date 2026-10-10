"""SQLite persistence for audit runs and findings."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).with_name("aeo_auditor.db")


def connect(db_path=None):
    conn = sqlite3.connect(str(db_path or DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path=None):
    with connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                root_url TEXT NOT NULL,
                pages_requested INTEGER NOT NULL,
                pages_succeeded INTEGER NOT NULL,
                score_average REAL,
                notes TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS page_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                audit_id INTEGER NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
                url TEXT NOT NULL,
                final_url TEXT,
                status_code INTEGER,
                score INTEGER,
                title TEXT,
                word_count INTEGER,
                result_json TEXT NOT NULL,
                UNIQUE(audit_id, url)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS findings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                audit_id INTEGER NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
                url TEXT NOT NULL,
                category TEXT,
                check_name TEXT,
                status TEXT,
                priority TEXT,
                evidence TEXT,
                recommendation TEXT
            )
        """)
        conn.commit()


def save_audit(root_url, pages_requested, results, notes="", db_path=None):
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    scores = [r.get("score", 0) for r in results if r.get("score") is not None]
    avg = round(sum(scores) / len(scores), 1) if scores else None
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO audits(started_at,root_url,pages_requested,pages_succeeded,score_average,notes) VALUES(?,?,?,?,?,?)",
            (started_at, root_url, pages_requested, len(results), avg, notes)
        )
        audit_id = cur.lastrowid
        for result in results:
            conn.execute(
                """INSERT INTO page_results(audit_id,url,final_url,status_code,score,title,word_count,result_json)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (audit_id, result.get("requested_url", result.get("url", "")), result.get("url", ""),
                 result.get("status_code"), result.get("score"), result.get("title"), result.get("word_count"),
                 json.dumps(result, ensure_ascii=False))
            )
            for f in result.get("findings", []):
                conn.execute(
                    """INSERT INTO findings(audit_id,url,category,check_name,status,priority,evidence,recommendation)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (audit_id, result.get("url", ""), f.get("category"), f.get("check"), f.get("status"),
                     f.get("priority"), f.get("evidence"), f.get("recommendation"))
                )
        conn.commit()
    return audit_id


def list_audits(limit=50, db_path=None):
    with connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM audits ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


def get_audit(audit_id, db_path=None):
    with connect(db_path) as conn:
        audit = conn.execute("SELECT * FROM audits WHERE id=?", (audit_id,)).fetchone()
        if not audit:
            return None, [], []
        pages = conn.execute("SELECT * FROM page_results WHERE audit_id=? ORDER BY score ASC", (audit_id,)).fetchall()
        findings = conn.execute("SELECT * FROM findings WHERE audit_id=? ORDER BY priority,url", (audit_id,)).fetchall()
        return dict(audit), [dict(r) for r in pages], [dict(r) for r in findings]
