FROM python:3.12-slim

WORKDIR /app

COPY ledger.py server.py index.html bootstrap_admin.py demo.py ./

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data \
    && chown -R app:app /app /data

ENV PORT=8000
ENV PYTHONUNBUFFERED=1
ENV LEDGER_DB=/data/ledgerline.db

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health',timeout=3)" || exit 1

CMD ["python", "server.py"]
