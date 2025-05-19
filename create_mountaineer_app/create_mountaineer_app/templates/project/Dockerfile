#
# Node dependencies stage
# This stage is only used to install the dependencies that will be used
# by our frontend bundler in later stages.
#
FROM node:20-slim as node-dependencies

WORKDIR /usr/src/app

# We only require the dependency definitions
COPY {{project_name}}/views/package.json {{project_name}}/views/package-lock.json ./
RUN npm install

#
# Python builder stage
#
FROM python:3.11-slim-bookworm AS builder

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs jq curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN uv venv /app/.venv
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"
ENV UV_LINK_MODE=copy

# Download and install dependencies first (without project) for better caching
COPY pyproject.toml uv.lock README.md ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

# Copy application code and install project
COPY {{project_name}} ./{{project_name}}
COPY --from=node-dependencies /usr/src/app/node_modules ./{{project_name}}/views/node_modules

# Build the frontend/script files
RUN --mount=type=cache,target=/root/.cache/uv \
    uv run build

#
# Final stage
#
FROM python:3.11-slim-bookworm as final

ARG ENVIRONMENT=development
ENV ENVIRONMENT=${ENVIRONMENT}

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl dnsutils iputils-ping \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create and switch to a new user
RUN useradd --create-home appuser
WORKDIR /app

COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appuser /app/{{project_name}} ./{{project_name}}

USER appuser

ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 80

# Run the application
CMD ["uvicorn", "{{project_name}}.main:app", "--host", "0.0.0.0", "--port", "80"]
