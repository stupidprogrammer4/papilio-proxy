"""Bounded read-only observation of the owning database clock."""

import time

import pymysql
from sqlalchemy.engine import make_url


def wait_owned_checkout_expired(dsn, intent_id):
    url = make_url(dsn)
    assert url.database is not None and "test" in url.database
    monitor = pymysql.connect(
        host=url.host or "127.0.0.1",
        port=url.port or 3306,
        user=url.username,
        password=url.password or "",
        database=url.database,
        autocommit=True,
        connect_timeout=5,
        read_timeout=5,
        write_timeout=5,
    )
    try:
        deadline = time.monotonic() + 10
        with monitor.cursor() as cursor:
            while time.monotonic() < deadline:
                cursor.execute(
                    "SELECT expires_at<=UTC_TIMESTAMP() "
                    "FROM tbl_checkout_intents WHERE id=%s",
                    (intent_id,),
                )
                row = cursor.fetchone()
                if row is not None and row[0]:
                    return
        raise AssertionError("Owning checkout clock boundary not observed")
    finally:
        monitor.close()
