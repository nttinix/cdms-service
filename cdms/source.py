from psycopg.types.json import Jsonb

from cdms.models import ProductWrite


class Source:
    def __init__(self, database):
        self.db = database

    def create(self, products):
        products = [
            item if isinstance(item, ProductWrite) else ProductWrite.model_validate(item)
            for item in products
        ]
        result = []
        with self.db.connection() as connection:
            for item in products:
                payload = item.business_data()
                row = connection.execute(
                    "INSERT INTO inventory.products (sku, partner_sku, payload) "
                    "VALUES (%s, %s, %s) RETURNING product_id, version",
                    (item.sku, item.partner_sku, Jsonb(payload)),
                ).fetchone()
                snapshot = {
                    **payload,
                    "productId": row["product_id"],
                    "sourceVersion": row["version"],
                }
                connection.execute(
                    "INSERT INTO inventory.outbox (payload) VALUES (%s)", (Jsonb(snapshot),)
                )
                result.append(snapshot)
        return result

    def update(self, product_id, product):
        item = (
            product if isinstance(product, ProductWrite) else ProductWrite.model_validate(product)
        )
        payload = item.business_data()
        with self.db.connection() as connection:
            row = connection.execute(
                "SELECT version, payload FROM inventory.products WHERE product_id = %s FOR UPDATE",
                (product_id,),
            ).fetchone()
            if row is None:
                return None
            version = row["version"]
            if payload != row["payload"]:
                version += 1
                connection.execute(
                    "UPDATE inventory.products SET sku = %s, partner_sku = %s, "
                    "payload = %s, version = %s WHERE product_id = %s",
                    (item.sku, item.partner_sku, Jsonb(payload), version, product_id),
                )
                snapshot = {**payload, "productId": product_id, "sourceVersion": version}
                connection.execute(
                    "INSERT INTO inventory.outbox (payload) VALUES (%s)", (Jsonb(snapshot),)
                )
        return {**payload, "productId": product_id, "sourceVersion": version}

    def products(self, page_index=0, page_size=100, keyword=None, skus=None, partner_skus=None):
        clauses, values = [], []
        if keyword:
            clauses.append("(sku ILIKE %s OR payload->>'productName' ILIKE %s)")
            values.extend([f"%{keyword}%", f"%{keyword}%"])
        if skus:
            clauses.append("sku = ANY(%s)")
            values.append(skus)
        if partner_skus:
            clauses.append("partner_sku = ANY(%s)")
            values.append(partner_skus)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.extend([page_size, page_index * page_size])
        with self.db.connection() as connection:
            rows = connection.execute(
                "SELECT product_id, version, payload FROM inventory.products"
                + where
                + " ORDER BY product_id LIMIT %s OFFSET %s",
                values,
            ).fetchall()
        return [
            {**row["payload"], "productId": row["product_id"], "sourceVersion": row["version"]}
            for row in rows
        ]

    def outbox_status(self):
        with self.db.connection() as connection:
            row = connection.execute(
                "SELECT count(*) AS pending, "
                "count(*) FILTER (WHERE attempts > 0) AS retried FROM inventory.outbox"
            ).fetchone()
        return row
