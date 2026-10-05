import logging
import random
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import psycopg
from psycopg_pool import PoolTimeout
from pydantic import ValidationError

from cdms.config import Settings
from cdms.store import Store, VersionConflict

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.store = Store(settings.database_url)
        self.owns_client = client is None
        self.client = client or httpx.Client(
            timeout=settings.http_timeout,
            headers={"X-API-Key": settings.api_token},
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

    def poll_once(self):
        page, total = 0, 0
        while True:
            response = self.client.get(
                self.settings.source_url.rstrip("/") + "/api/v1/Products",
                params={"PageIndex": page, "PageSize": self.settings.page_size},
                headers={"X-API-Key": self.settings.api_token},
            )
            response.raise_for_status()
            products = response.json()
            if not isinstance(products, list):
                raise ValueError("Source must return a product array")
            self.store.ingest(products)
            total += len(products)
            page += 1
            if len(products) < self.settings.page_size:
                break
        return {"products": total, "pages": page}

    def deliver_once(self):
        delivered, failed = 0, 0
        for _ in range(self.settings.page_size):
            with self.store.db.connection() as connection:
                event = connection.execute(
                    "SELECT event_id, payload, attempts FROM inventory.outbox "
                    "WHERE next_attempt <= now() ORDER BY event_id "
                    "FOR UPDATE SKIP LOCKED LIMIT 1"
                ).fetchone()
                if event is None:
                    break
                try:
                    response = self.client.post(
                        self.settings.callback_url,
                        json=[event["payload"]],
                        headers={"X-API-Key": self.settings.api_token},
                    )
                    response.raise_for_status()
                except httpx.HTTPError as error:
                    attempt = event["attempts"] + 1
                    delay = min(
                        self.settings.retry_cap,
                        self.settings.retry_base * 2 ** min(attempt - 1, 20),
                    )
                    delay *= random.uniform(0.8, 1)
                    connection.execute(
                        "UPDATE inventory.outbox SET attempts = %s, "
                        "next_attempt = now() + %s * interval '1 second', "
                        "last_error = %s WHERE event_id = %s",
                        (attempt, delay, type(error).__name__, event["event_id"]),
                    )
                    failed += 1
                    logger.warning(
                        "Callback %s failed: %s", event["event_id"], type(error).__name__
                    )
                else:
                    connection.execute(
                        "DELETE FROM inventory.outbox WHERE event_id = %s", (event["event_id"],)
                    )
                    delivered += 1
        return {"delivered": delivered, "failed": failed}

    def close(self):
        if self.owns_client:
            self.client.close()
        self.store.close()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings()
    stopped = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stopped.set())
    worker = None
    while not stopped.is_set() and worker is None:
        try:
            worker = Worker(settings)
        except (psycopg.Error, PoolTimeout):
            logger.warning("Waiting for database")
            stopped.wait(2)
    if worker is None:
        return

    def loop(action, interval):
        while not stopped.is_set():
            started = time.monotonic()
            try:
                result = action()
                logger.info("%s: %s", action.__name__, result)
            except (
                httpx.HTTPError,
                psycopg.Error,
                PoolTimeout,
                ValueError,
                ValidationError,
                VersionConflict,
            ) as error:
                logger.warning("%s failed: %s", action.__name__, type(error).__name__)
            stopped.wait(max(0.1, interval - (time.monotonic() - started)))

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(loop, worker.poll_once, settings.poll_interval),
                executor.submit(loop, worker.deliver_once, 0.5),
            ]
            for future in futures:
                future.result()
    finally:
        worker.close()


if __name__ == "__main__":
    main()
