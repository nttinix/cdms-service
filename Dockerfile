FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY cdms cdms

ENV PYTHONUNBUFFERED=1
EXPOSE 8000 8001

CMD ["uvicorn", "cdms.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
