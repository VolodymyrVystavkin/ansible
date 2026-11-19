"""Create a verified SQLite database before making it visible to Gunicorn."""

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile


def main():
    app_dir, database = map(Path, sys.argv[1:])
    if database.exists():
        return

    email, password = json.load(sys.stdin)
    os.umask(0o077)
    sys.path.insert(0, str(app_dir))
    with tempfile.TemporaryDirectory(prefix=".bootstrap-", dir=database.parent) as work:
        candidate = Path(work) / database.name
        os.environ.update(
            PGADMIN_SERVER_MODE="ON",
            PGADMIN_BOOTSTRAP_SQLITE=str(candidate),
            PGADMIN_SETUP_EMAIL=email,
            PGADMIN_SETUP_PASSWORD=password,
        )
        try:
            from pgAdmin4 import app
        except PermissionError:
            return 20
        except ImportError:
            return 21
        except (Exception, SystemExit):
            return 22

        if not callable(app):
            return 23

        with closing(sqlite3.connect(f"{candidate.as_uri()}?mode=rw", uri=True)) as connection:
            administrator = connection.execute(
                """
                SELECT 1 FROM "user" AS u
                JOIN roles_users AS membership ON membership.user_id = u.id
                JOIN role AS r ON r.id = membership.role_id
                WHERE u.email = ? AND u.active = 1 AND r.name = 'Administrator'
                """,
                (email,),
            ).fetchone()
            if administrator is None:
                return 24
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            if journal_mode.lower() == "wal":
                return 25

        try:
            os.link(candidate, database)
        except FileExistsError:
            # A concurrent bootstrap already published a database.
            pass


if __name__ == "__main__":
    sys.exit(main())
