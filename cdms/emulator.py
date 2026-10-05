from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from psycopg.errors import UniqueViolation
from pydantic import Field

from cdms.config import Settings
from cdms.excel import encode_workbook
from cdms.models import ProductWrite
from cdms.source import Source
from cdms.web import base_app


def create_app(settings=None):
    settings = settings or Settings()
    app, authorize = base_app("Vietful product service emulator", settings)

    @app.exception_handler(UniqueViolation)
    async def duplicate(request: Request, error: UniqueViolation):
        return JSONResponse(status_code=409, content={"detail": "SKU or partnerSKU already exists"})

    @app.get("/api/v1/Products", dependencies=[Depends(authorize)])
    def products(
        request: Request,
        page_index: int = Query(0, alias="PageIndex", ge=0),
        page_size: int = Query(10, alias="PageSize", ge=1, le=1000),
        keyword: str | None = Query(None, alias="Keyword"),
        skus: str | None = Query(None, alias="SKUs"),
        partner_skus: str | None = Query(None, alias="PartnerSKUs"),
    ):
        return Source(request.app.state.store.db).products(
            page_index,
            page_size,
            keyword,
            skus.split(",") if skus else None,
            partner_skus.split(",") if partner_skus else None,
        )

    @app.post("/api/v1/Products", dependencies=[Depends(authorize)])
    def create(
        request: Request,
        products: Annotated[list[ProductWrite], Field(min_length=1, max_length=1000)],
    ):
        return Source(request.app.state.store.db).create(products)

    @app.put("/api/v1/Products/{product_id}", status_code=204, dependencies=[Depends(authorize)])
    def update(request: Request, product_id: int, product: ProductWrite):
        result = Source(request.app.state.store.db).update(product_id, product)
        if result is None:
            raise HTTPException(404, "Product not found")
        return Response(status_code=204)

    @app.get("/api/v1/exports/products.xlsx", dependencies=[Depends(authorize)])
    def export(request: Request):
        source = Source(request.app.state.store.db)
        products, page = [], 0
        while True:
            batch = source.products(page, 1000)
            products.extend(batch)
            if len(products) > settings.max_excel_rows:
                raise HTTPException(413, "Export exceeds row limit")
            if len(batch) < 1000:
                break
            page += 1
        return Response(
            encode_workbook(products),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="products.xlsx"'},
        )

    @app.get("/api/v1/outbox", dependencies=[Depends(authorize)])
    def outbox(request: Request):
        return Source(request.app.state.store.db).outbox_status()

    @app.get("/api/v1/Products/{partner_sku}", dependencies=[Depends(authorize)])
    def detail(request: Request, partner_sku: str):
        products = Source(request.app.state.store.db).products(partner_skus=[partner_sku])
        if not products:
            raise HTTPException(404, "Product not found")
        return products[0]

    return app
