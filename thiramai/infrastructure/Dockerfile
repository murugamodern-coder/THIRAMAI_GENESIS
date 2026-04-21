FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    wget \
    build-essential \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 10001 -s /bin/bash thiramai_runner

WORKDIR /workspace
RUN chown -R thiramai_runner:thiramai_runner /workspace

USER thiramai_runner

CMD ["bash"]
