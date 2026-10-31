FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 docintel \
    && useradd --system --uid 10001 --gid docintel --home-dir /home/docintel --create-home docintel

WORKDIR /app
COPY requirements-prod.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
    && pip install -r requirements.txt
COPY --chown=docintel:docintel app ./app
RUN mkdir -p /var/lib/docintel/storage \
    && chown -R docintel:docintel /var/lib/docintel /home/docintel /app

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
