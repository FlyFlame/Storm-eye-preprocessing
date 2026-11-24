FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/src

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py preprocess_sentinel2.py conductor_worker.py ./

CMD ["python", "preprocess_sentinel2.py"]

