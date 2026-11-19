"""Provision the lab role, its database, and its database creation privilege."""

import json
import sys

import psycopg2
from psycopg2 import extensions, sql


def main():
    name, database, password = json.load(sys.stdin)
    connection = psycopg2.connect(
        host="/var/run/postgresql", port=5432, dbname="postgres", user="postgres"
    )
    try:
        connection.autocommit = True  # CREATE DATABASE cannot run in a transaction.
        with connection.cursor() as cursor:
            # Hold one session lock across both operations, including CREATE DATABASE.
            cursor.execute("SELECT pg_advisory_lock(334512, 1)")
            cursor.execute(
                "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s",
                (database,),
            )
            owner = cursor.fetchone()
            if owner and owner[0] != name:
                raise RuntimeError("Existing lab database has a different owner.")

            cursor.execute(
                """
                SELECT rolcanlogin AND NOT
                    (rolsuper OR rolcreaterole OR rolreplication OR rolbypassrls),
                    rolcreatedb
                FROM pg_roles WHERE rolname = %s
                """,
                (name,),
            )
            role = cursor.fetchone()
            if role and not role[0]:
                raise RuntimeError("Existing lab role does not have the expected login privileges.")

            if not role:
                verifier = extensions.encrypt_password(
                    password, name, connection, algorithm="scram-sha-256"
                )
                cursor.execute(
                    sql.SQL("CREATE ROLE {} LOGIN CREATEDB PASSWORD %s").format(sql.Identifier(name)),
                    (verifier,),
                )

            elif not role[1]:
                cursor.execute(sql.SQL("ALTER ROLE {} CREATEDB").format(sql.Identifier(name)))

            if not owner:
                cursor.execute(
                    sql.SQL("CREATE DATABASE {} OWNER {}").format(
                        sql.Identifier(database), sql.Identifier(name)
                    )
                )

            print("changed" if not role or not role[1] or not owner else "present")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
