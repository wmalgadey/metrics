FROM python:3.12-slim

RUN pip install --no-cache-dir uv \
 && groupadd --gid 1000 metrics \
 && useradd --uid 1000 --gid metrics --create-home --shell /bin/bash metrics

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev \
 && chown -R metrics:metrics /app

ENV PATH="/app/.venv/bin:$PATH"
USER metrics

ENTRYPOINT ["metrics"]
CMD ["--help"]
