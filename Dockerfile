FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONPATH=/app/src

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --upgrade pip \
    && pip install uv

COPY pyproject.toml uv.lock ./
# The API image runs CPU-only; skip CUDA packages from the lock and install
# the matching CPU torch wheel explicitly.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project \
        --no-install-package torch \
        --no-install-package triton \
        --no-install-package cuda-bindings \
        --no-install-package cuda-pathfinder \
        --no-install-package cuda-toolkit \
        --no-install-package nvidia-cublas \
        --no-install-package nvidia-cuda-cupti \
        --no-install-package nvidia-cuda-nvrtc \
        --no-install-package nvidia-cuda-runtime \
        --no-install-package nvidia-cudnn-cu13 \
        --no-install-package nvidia-cufft \
        --no-install-package nvidia-cufile \
        --no-install-package nvidia-curand \
        --no-install-package nvidia-cusolver \
        --no-install-package nvidia-cusparse \
        --no-install-package nvidia-cusparselt-cu13 \
        --no-install-package nvidia-nccl-cu13 \
        --no-install-package nvidia-nvjitlink \
        --no-install-package nvidia-nvshmem-cu13 \
        --no-install-package nvidia-nvtx
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python .venv/bin/python --no-deps \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch==2.12.0+cpu"

COPY . .

EXPOSE 8000

CMD [".venv/bin/uvicorn", "medagentcare.api:app", "--host", "0.0.0.0", "--port", "8000"]
