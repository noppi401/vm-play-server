FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=2

RUN groupadd --gid 1000 sandbox \
    && useradd --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin sandbox \
    && mkdir -p /workspace/output \
    && chown -R sandbox:sandbox /workspace

WORKDIR /workspace

COPY requirements.txt /tmp/requirements.txt

RUN python -m pip install --upgrade pip \
    && python -m pip install --requirement /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

USER sandbox

CMD ["python"]
