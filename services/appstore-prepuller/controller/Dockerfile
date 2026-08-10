FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

RUN groupadd -g 1000 helx && \
    useradd -u 1000 -g helx -s /bin/bash helx

WORKDIR /app

RUN chown -R helx:helx /app

RUN pip install --no-cache-dir "Cython<3" wheel setuptools && \
    pip install --no-cache-dir --no-build-isolation "PyYAML==5.4.1"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY prepuller.py .

USER helx:helx

ENTRYPOINT ["python", "-u", "prepuller.py"]
