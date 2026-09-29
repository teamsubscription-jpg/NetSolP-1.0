# NetSolP-1.0 RunPod serverless worker (GPU via onnxruntime-gpu, falls back to CPU).
# Build from the repository root:  docker build -t netsolp .
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# torch is only used for data loading, so the CPU build keeps the image small.
COPY PredictionServer/requirements_serverless.txt .
RUN pip3 install torch --index-url https://download.pytorch.org/whl/cpu && \
    pip3 install -r requirements_serverless.txt

COPY PredictionServer/ /app/

CMD ["python3", "-u", "handler.py"]
