from typing import Annotated

from fastapi import Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from cdms.config import Settings
from cdms.excel import SpreadsheetError, decode_workbook
from cdms.models import Product
from cdms.store import VersionConflict
from cdms.web import base_app


def create_app(settings=None):
    settings = settings or Settings()
    app, authorize = base_app("Change Data Management Service", settings)

    @app.post("/api/v1/webhooks/products", dependencies=[Depends(authorize)])
    def webhook(
        request: Request, products: Annotated[list[Product], Field(min_length=1, max_length=1000)]
    ):
        results = request.app.state.store.ingest(products)
        return {"results": results}

    @app.get("/api/v1/products", dependencies=[Depends(authorize)])
    def products(
        request: Request,
        page_index: int = Query(default=0, ge=0),
        page_size: int = Query(default=100, ge=1, le=1000),
    ):
        return request.app.state.store.products(page_index, page_size)

    @app.post("/api/v1/imports", dependencies=[Depends(authorize)])
    async def import_excel(request: Request, file: Annotated[UploadFile, File()]):
        if not file.filename or not file.filename.lower().endswith(".xlsx"):
            raise HTTPException(422, {"message": "An .xlsx file is required"})
        try:
            content = await file.read(settings.max_upload_bytes + 1)
        finally:
            await file.close()
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(413, "Upload exceeds size limit")
        try:
            products, rows = await run_in_threadpool(
                decode_workbook, content, settings.max_excel_rows
            )
        except SpreadsheetError as error:
            raise HTTPException(422, {"message": str(error), "row": error.row}) from error
        try:
            results = await run_in_threadpool(request.app.state.store.ingest, products)
        except VersionConflict as error:
            raise HTTPException(
                409, {"message": str(error), "productId": error.product_id, "row": rows[error.row]}
            ) from error
        return {"results": results, "rowCount": len(products)}

    return app
