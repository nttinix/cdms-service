from psycopg.types.json import Jsonb

from cdms.database import Database
from cdms.models import Product


class VersionConflict(Exception):
    def __init__(self, product_id, version, row=None):
        self.product_id = product_id
        self.version = version
        self.row = row
        super().__init__(f"Conflicting content for product {product_id}, version {version}")


class Store:
    def __init__(self, database_url):
        self.db = Database(database_url)

    def ingest(self, products):
        normalized = [
            item if isinstance(item, Product) else Product.model_validate(item) for item in products
        ]
        fingerprints = {}
        for index, item in enumerate(normalized):
            key = (item.product_id, item.source_version)
            fingerprint = item.fingerprint()
            if key in fingerprints and fingerprints[key] != fingerprint:
                raise VersionConflict(item.product_id, item.source_version, index)
            fingerprints[key] = fingerprint

        results = []
        with self.db.connection() as connection:
            for product_id in sorted({item.product_id for item in normalized}):
                connection.execute("SELECT pg_advisory_xact_lock(%s)", (product_id,))

            for index, item in enumerate(normalized):
                existing = connection.execute(
                    "SELECT version, fingerprint FROM cdms.products WHERE product_id = %s",
                    (item.product_id,),
                ).fetchone()
                fingerprint = fingerprints[(item.product_id, item.source_version)]
                if existing is None:
                    connection.execute(
                        "INSERT INTO cdms.products "
                        "(product_id, version, payload, fingerprint, change_count) "
                        "VALUES (%s, %s, %s, %s, 1)",
                        (
                            item.product_id,
                            item.source_version,
                            Jsonb(item.business_data()),
                            fingerprint,
                        ),
                    )
                    outcome = "created"
                elif item.source_version < existing["version"]:
                    outcome = "stale"
                elif item.source_version == existing["version"]:
                    if fingerprint != existing["fingerprint"]:
                        raise VersionConflict(item.product_id, item.source_version, index)
                    outcome = "duplicate"
                else:
                    changed = fingerprint != existing["fingerprint"]
                    connection.execute(
                        "UPDATE cdms.products SET version = %s, payload = %s, "
                        "fingerprint = %s, change_count = change_count + %s, "
                        "received_at = now() WHERE product_id = %s",
                        (
                            item.source_version,
                            Jsonb(item.business_data()),
                            fingerprint,
                            int(changed),
                            item.product_id,
                        ),
                    )
                    outcome = "updated" if changed else "unchanged"
                results.append(
                    {
                        "productId": item.product_id,
                        "sourceVersion": item.source_version,
                        "outcome": outcome,
                    }
                )
        return results

    def products(self, page_index=0, page_size=1000):
        with self.db.connection() as connection:
            rows = connection.execute(
                "SELECT payload, version, change_count FROM cdms.products "
                "ORDER BY product_id LIMIT %s OFFSET %s",
                (page_size, page_index * page_size),
            ).fetchall()
        return [
            {**row["payload"], "sourceVersion": row["version"], "changeCount": row["change_count"]}
            for row in rows
        ]

    def close(self):
        self.db.close()
