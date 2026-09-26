"""Small SQLite application database. ChromaDB remains dedicated to embeddings."""
import sqlite3

from app.config import DATA_DIRECTORY

DATABASE_PATH = DATA_DIRECTORY / "app.db"


def connection() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATABASE_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def initialize_database() -> None:
    with connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS plans (
          id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT NOT NULL,
          monthly_price_cents INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS subscriptions (
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL UNIQUE, plan_id INTEGER NOT NULL,
          status TEXT NOT NULL DEFAULT 'trial', trial_ends_at TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
          FOREIGN KEY(plan_id) REFERENCES plans(id)
        );
        CREATE TABLE IF NOT EXISTS templates (
          id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
          description TEXT NOT NULL, output_width INTEGER NOT NULL, output_height INTEGER NOT NULL,
          active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS projects (
          id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL,
          template_id INTEGER, script_file TEXT, audio_file TEXT, status TEXT NOT NULL DEFAULT 'uploaded',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
          FOREIGN KEY(template_id) REFERENCES templates(id)
        );
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
          expires_at TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """)
        # Keep upgrades safe for existing local databases created before project
        # outputs were persisted.
        project_columns = {row["name"] for row in db.execute("PRAGMA table_info(projects)")}
        if "output_video_path" not in project_columns:
            db.execute("ALTER TABLE projects ADD COLUMN output_video_path TEXT")
        if "output_duration_seconds" not in project_columns:
            db.execute("ALTER TABLE projects ADD COLUMN output_duration_seconds REAL")
        if "output_file_size_bytes" not in project_columns:
            db.execute("ALTER TABLE projects ADD COLUMN output_file_size_bytes INTEGER")

        db.executemany("INSERT OR IGNORE INTO plans (id, name, description, monthly_price_cents) VALUES (?, ?, ?, ?)", [
          (1, 'Free trial', 'A 14-day trial. Billing and paid upgrades are not enabled yet.', 0),
          (2, 'Creator', 'Planned creator tier. It is not available for purchase yet.', 0),
          (3, 'Team', 'Planned team tier. It is not available for purchase yet.', 0),
        ])
        # Preserve existing IDs so projects made before this update retain their template.
        db.execute("UPDATE templates SET name='Cinematic Landscape', description='16:9 widescreen output for cinematic edits.' WHERE id=1")
        db.executemany("INSERT OR IGNORE INTO templates (id, slug, name, description, output_width, output_height) VALUES (?, ?, ?, ?, ?, ?)", [
          (1, 'cinematic-landscape', 'Cinematic Landscape', '16:9 widescreen output for cinematic edits.', 1920, 1080),
          (2, 'social-media-vertical', 'Social Media Vertical', '9:16 portrait output for mobile-first stories.', 1080, 1920),
          (3, 'documentary', 'Documentary', '16:9 landscape configuration for clear narrative edits.', 1920, 1080),
          (4, 'minimal-story', 'Minimal Story', '1:1 square configuration for concise visual stories.', 1080, 1080),
          (5, 'travel-vlog', 'Travel / Vlog', '16:9 landscape configuration for travel and vlog footage.', 1920, 1080),
        ])
