from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://cdms:cdms@127.0.0.1:55432/cdms"
    source_url: str = "http://127.0.0.1:8001"
    callback_url: str = "http://127.0.0.1:8000/api/v1/webhooks/products"
    api_token: str = "local-demo-token"
    poll_interval: float = 10.0
    page_size: int = 100
    http_timeout: float = 5.0
    retry_base: float = 1.0
    retry_cap: float = 30.0
    max_upload_bytes: int = 10 * 1024 * 1024
    max_excel_rows: int = 10000
