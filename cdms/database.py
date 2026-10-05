from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS cdms;
CREATE SCHEMA IF NOT EXISTS inventory;
CREATE TABLE IF NOT EXISTS cdms.products (
    product_id BIGINT PRIMARY KEY,
    version BIGINT NOT NULL CHECK (version > 0),
    payload JSONB NOT NULL,
    fingerprint TEXT NOT NULL,
    change_count BIGINT NOT NULL CHECK (change_count > 0),
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS inventory.products (
    product_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    partner_sku TEXT NOT NULL UNIQUE,
    version BIGINT NOT NULL DEFAULT 1,
    payload JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS inventory.outbox (
    event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    payload JSONB NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error TEXT
);
CREATE INDEX IF NOT EXISTS outbox_due ON inventory.outbox(next_attempt, event_id);
"""


class Database:
    def __init__(self, database_url):
        self.pool = ConnectionPool(
            database_url,
            min_size=1,
            max_size=20,
            timeout=5,
            open=True,
            kwargs={
                "row_factory": dict_row,
                "connect_timeout": 3,
                "options": "-c lock_timeout=5000 -c statement_timeout=15000",
            },
        )
        try:
            with self.pool.connection() as connection:
                connection.execute("SELECT pg_advisory_xact_lock(hashtext('cdms_schema_init'))")
                connection.execute(SCHEMA)
        except BaseException:
            self.pool.close()
            raise

    def connection(self):
        return self.pool.connection()

    def ready(self):
        with self.connection() as connection:
            connection.execute("SELECT 1")

    def close(self):
        self.pool.close()
