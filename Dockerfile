FROM python:3.12-slim
WORKDIR /app
COPY ledger.py server.py index.html bootstrap_admin.py demo.py ./
ENV PORT=8000
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "server.py"]
