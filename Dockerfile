FROM python:3.11-slim
# libgl1/libglib2.0-0: needed by Docling's OpenCV; models are downloaded on first parse and cached in /root/.cache
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu .
ENTRYPOINT ["openparl-extract"]
