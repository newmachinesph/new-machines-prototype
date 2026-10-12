FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1 PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
# The project is virtual (no build-system), so one sync installs everything; app/ is plain source.
RUN uv sync --locked --no-install-project
COPY app ./app
# Run as an unprivileged user; the app only reads its files.
RUN useradd --system --no-create-home app
USER app
# Verify Firebase sign-in by default; run locally with -e AUTH_MODE=dev to skip it.
ENV PATH="/app/.venv/bin:$PATH" AUTH_MODE=firebase FIREBASE_PROJECT_ID=nm-demo-iu7uo4
# The demo state lives in memory, in one process: run exactly one instance (Cloud Run --max-instances 1)
# and never add --workers, or visitors would see different, diverging copies of the state.
# exec makes uvicorn PID 1, so SIGTERM from `docker stop` or Cloud Run reaches it and it shuts down cleanly.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
