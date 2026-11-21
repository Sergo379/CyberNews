# syntax=docker/dockerfile:1
FROM python:3.12.16-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv
COPY requirements.txt .
RUN pip install --only-binary=:all: -r requirements.txt \
    && groupadd --gid 10001 cybernews \
    && useradd --uid 10001 --gid 10001 --no-create-home cybernews

COPY --from=runtime /cybernews_runtime ./cybernews_runtime
COPY app ./app

USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "cybernews_runtime"]
