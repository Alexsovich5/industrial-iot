FROM python:3.5.4-jessie@sha256:925b54caeb148843b2f6b5ff8ddd8f5600d4cc07995db78e3adca46e15a67d03

WORKDIR /app

COPY requirements*.txt ./
RUN pip install --no-cache-dir --no-deps -r requirements.txt -r requirements-dev.txt \
    && pip check

COPY . .

ENV PYTHONPATH=/app/src:/app
