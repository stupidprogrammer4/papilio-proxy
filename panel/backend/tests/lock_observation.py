import time

import pymysql
from sqlalchemy.engine import make_url


class MySQLLockObservation:
    def wait_for_queries(
        self,
        dsn: str,
        table: str,
        prefixes: tuple[str, ...],
        required_count: int,
        timeout_seconds: float,
        poll_seconds: float,
        require_update_lock: bool,
    ) -> bool:
        url = make_url(dsn)
        with pymysql.connect(
            host=url.host or "localhost",
            port=url.port or 3306,
            user=url.username,
            password=url.password or "",
            database=url.database,
            connect_timeout=int(timeout_seconds),
            read_timeout=int(timeout_seconds),
            write_timeout=int(timeout_seconds),
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        ) as connection:
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                with connection.cursor() as cursor:
                    cursor.execute("SHOW FULL PROCESSLIST")
                    processes = cursor.fetchall()
                matched = sum(
                    row["db"] == url.database
                    and table in str(row["Info"])
                    and str(row["Info"]).startswith(prefixes)
                    and (
                        not require_update_lock
                        or "FOR UPDATE" in str(row["Info"])
                    )
                    for row in processes
                )
                if matched >= required_count:
                    return True
                time.sleep(poll_seconds)
        return False
