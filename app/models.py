import os
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin


class User(UserMixin):
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash


def get_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path):
    conn = get_db(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS versions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            version     TEXT    NOT NULL UNIQUE,
            download_url TEXT   NOT NULL,
            filename    TEXT,
            filesize    TEXT,
            sha256      TEXT,
            direct_url  TEXT,
            changelog   TEXT,
            changelog_zh TEXT,
            is_featured INTEGER DEFAULT 0,
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL
        )
    ''')
    _ensure_column(conn, 'versions', 'changelog_zh', 'TEXT')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    NOT NULL UNIQUE,
            password_hash TEXT    NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()


def _ensure_column(conn, table, column, column_type):
    columns = conn.execute(f'PRAGMA table_info({table})').fetchall()
    if column not in {row['name'] for row in columns}:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {column_type}')


def get_user_by_id(db_path, user_id):
    conn = get_db(db_path)
    row = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    if row:
        return User(row['id'], row['username'], row['password_hash'])
    return None


def get_user_by_username(db_path, username):
    conn = get_db(db_path)
    row = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    conn.close()
    if row:
        return User(row['id'], row['username'], row['password_hash'])
    return None


def create_admin(db_path, username, password):
    conn = get_db(db_path)
    pw_hash = generate_password_hash(password)
    try:
        conn.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', (username, pw_hash))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.execute('UPDATE users SET password_hash = ? WHERE username = ?', (pw_hash, username))
        conn.commit()
    conn.close()


def get_latest_version(db_path):
    conn = get_db(db_path)
    row = conn.execute('SELECT * FROM versions WHERE is_featured = 1 ORDER BY id DESC LIMIT 1').fetchone()
    if not row:
        row = conn.execute('SELECT * FROM versions ORDER BY id DESC LIMIT 1').fetchone()
    conn.close()
    return dict(row) if row else None


def get_version_by_version_str(db_path, version_str):
    conn = get_db(db_path)
    row = conn.execute('SELECT * FROM versions WHERE version = ?', (version_str,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_versions(db_path):
    conn = get_db(db_path)
    rows = conn.execute('SELECT * FROM versions ORDER BY id DESC').fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_version_by_id(db_path, version_id):
    conn = get_db(db_path)
    row = conn.execute('SELECT * FROM versions WHERE id = ?', (version_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def insert_version(db_path, data):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db(db_path)
    # Unfeature all existing
    conn.execute('UPDATE versions SET is_featured = 0')
    cursor = conn.execute(
        'INSERT INTO versions (version, download_url, filename, filesize, sha256, direct_url, changelog, changelog_zh, is_featured, created_at, updated_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)',
        (data['version'], data['download_url'], data.get('filename'), data.get('filesize'),
         data.get('sha256'), data.get('direct_url'), data.get('changelog'), data.get('changelog_zh'), now, now)
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id


def update_version(db_path, version_id, data):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db(db_path)
    fields = []
    values = []
    for key in ('version', 'download_url', 'filename', 'filesize', 'sha256', 'direct_url', 'changelog', 'changelog_zh'):
        if key in data:
            fields.append(f'{key} = ?')
            values.append(data[key])
    fields.append('updated_at = ?')
    values.append(now)
    values.append(version_id)
    conn.execute(f'UPDATE versions SET {", ".join(fields)} WHERE id = ?', values)
    conn.commit()
    conn.close()


def delete_version(db_path, version_id):
    conn = get_db(db_path)
    # Get filename before deleting for local file cleanup
    row = conn.execute('SELECT filename FROM versions WHERE id = ?', (version_id,)).fetchone()
    conn.execute('DELETE FROM versions WHERE id = ?', (version_id,))
    conn.commit()
    conn.close()
    # Delete local file if exists
    if row and row['filename']:
        _delete_local_file(row['filename'])


def _delete_local_file(filename):
    """Delete a file from data/downloads/ if it exists."""
    from app.config import Config
    download_dir = os.path.join(os.path.dirname(Config.DATABASE_PATH), 'downloads')
    file_path = os.path.join(download_dir, filename)
    if os.path.exists(file_path):
        os.remove(file_path)


def refresh_version(db_path, version_id, data):
    """Refresh version fields silently. Only update updated_at if download_url or sha256 changed."""
    conn = get_db(db_path)
    old = conn.execute('SELECT download_url, sha256 FROM versions WHERE id = ?', (version_id,)).fetchone()
    if not old:
        conn.close()
        return

    fields = []
    values = []
    for key in ('download_url', 'filename', 'filesize', 'sha256', 'direct_url', 'changelog', 'changelog_zh'):
        if key in data and data[key] is not None:
            fields.append(f'{key} = ?')
            values.append(data[key])

    # Only update updated_at if download_url or sha256 actually changed
    source_changed = False
    if 'download_url' in data and data['download_url'] and data['download_url'] != old['download_url']:
        source_changed = True
    if 'sha256' in data and data['sha256'] and data['sha256'] != old['sha256']:
        source_changed = True

    if source_changed:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        fields.append('updated_at = ?')
        values.append(now)

    if fields:
        values.append(version_id)
        conn.execute(f'UPDATE versions SET {", ".join(fields)} WHERE id = ?', values)
        conn.commit()
    conn.close()
    return source_changed


def set_featured(db_path, version_id):
    conn = get_db(db_path)
    conn.execute('UPDATE versions SET is_featured = 0')
    conn.execute('UPDATE versions SET is_featured = 1 WHERE id = ?', (version_id,))
    conn.commit()
    conn.close()


def get_setting(db_path, key):
    conn = get_db(db_path)
    row = conn.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
    conn.close()
    return row['value'] if row else None


def set_setting(db_path, key, value):
    conn = get_db(db_path)
    conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()


def get_settings(db_path, keys):
    conn = get_db(db_path)
    placeholders = ','.join('?' for _ in keys)
    rows = conn.execute(f'SELECT key, value FROM settings WHERE key IN ({placeholders})', tuple(keys)).fetchall()
    conn.close()
    found = {row['key']: row['value'] for row in rows}
    return {key: found.get(key) for key in keys}


def set_settings(db_path, settings):
    conn = get_db(db_path)
    for key, value in settings.items():
        conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()
