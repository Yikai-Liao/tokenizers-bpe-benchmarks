# syntax=docker/dockerfile:1
ARG RUST_IMAGE=rust:1-bookworm
ARG PYTHON_IMAGE=python:3.13-slim-bookworm
FROM ${RUST_IMAGE} AS rust
FROM ${PYTHON_IMAGE} AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    git gcc g++ make libc6-dev pkg-config libssl-dev util-linux ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=rust /usr/local/cargo /usr/local/cargo
COPY --from=rust /usr/local/rustup /usr/local/rustup
ENV PATH="/usr/local/cargo/bin:${PATH}" CARGO_HOME=/usr/local/cargo RUSTUP_HOME=/usr/local/rustup
ARG BUILD_JOBS=4
ENV CARGO_BUILD_JOBS=${BUILD_JOBS}
WORKDIR /opt/benchmark
COPY bench/__init__.py bench/__main__.py bench/config.py bench/builds.py bench/bundle.py bench/
COPY runner runner
COPY docker/sources.toml docker/sources.toml
# A caller can supply another source manifest without specializing the harness.
ARG SOURCES_CONFIG=docker/sources.toml
COPY docker docker
RUN python -m bench bundle --portable-release --config "${SOURCES_CONFIG}" --out /opt/builds --cache /tmp/bpe-builds \
    && rm -rf /tmp/bpe-builds

FROM ${PYTHON_IMAGE} AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    git util-linux numactl libssl3 libstdc++6 ca-certificates fonts-liberation2 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/benchmark
COPY pyproject.toml README.md ./
COPY bench bench
COPY assets/fonts assets/fonts
COPY .agents/skills/nature-figure/scripts .agents/skills/nature-figure/scripts
COPY .agents/skills/nature-figure/LICENSE .agents/skills/nature-figure/LICENSE
RUN pip install --no-cache-dir '.[corpus,plots]'
COPY --from=builder /opt/builds /opt/builds
COPY experiments experiments
COPY datasets datasets
COPY tests/test_corpora.py tests/test_corpora.py
COPY scripts/docker_smoke.py scripts/docker_smoke.py
ENV MPLBACKEND=Agg PYTHONUNBUFFERED=1 PYTHONPATH=/opt/benchmark MPLCONFIGDIR=/tmp/matplotlib
ENTRYPOINT ["python", "-m", "bench"]
CMD ["suite", "--config", "/config/suite.toml", "--bundle", "/opt/builds/bundle.json", "--out", "/results"]
