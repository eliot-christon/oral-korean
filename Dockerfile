# syntax=docker/dockerfile:1

# Why the backend runs in a container at all: MeloTTS cannot speak Korean on Windows.
# Its Korean G2P (g2pkk) needs a Korean MeCab, and the only one that installs on Python
# 3.12, `python-mecab-ko`, collides with the Japanese `mecab-python3` that MeloTTS also
# requires, because Windows filesystems treat `mecab/` and `MeCab/` as one directory. The
# Windows-only alternative g2pkk asks for, `eunjeon`, stopped publishing wheels at cp36.
# Linux has neither problem. See `pyproject.toml` for the pins this all rests on.
FROM python:3.12-slim

# git: the `tts` extra installs MeloTTS from its official git repository, not from PyPI.
RUN apt-get update \
    && apt-get install --no-install-recommends -y git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies in their own layer, before the source: torch and friends are the slow part
# of this build and they change far less often than the code does.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra tts --no-install-project

# MeloTTS expects this dictionary, but downloads it from a post-install hook that only
# fires under `setup.py install`. uv builds a wheel, so the hook never runs and MeCab
# fails to initialise the moment MeloTTS is imported. Baking the 526 MB dictionary in
# here keeps it out of every container's first run.
RUN uv run --frozen --no-sync python -m unidic download

COPY src ./src
COPY main.py ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra tts

# Reachable from the host. Off-container the default stays on loopback: see AppConfig.
ENV ORAL_KOREAN_HOST=0.0.0.0 \
    ORAL_KOREAN_PORT=8000

# Hugging Face's Xet backend (cas-server.xethub.hf.co) fails from this network with
# "Request middleware error" even though the host resolves and huggingface.co answers
# fine, which leaves the Korean checkpoint undownloadable. This falls back to the classic
# CDN, which works. Drop it if Xet ever starts behaving; nothing else depends on it.
ENV HF_HUB_DISABLE_XET=1

EXPOSE 8000

CMD ["uv", "run", "--frozen", "--no-sync", "python", "main.py"]
