FROM python:3.12-slim
WORKDIR /app
COPY ledger.py server.py index.html bootstrap_admin.py ./
ENV PORT=8000
EXPOSE 8000
CMD ["python", "server.py"]
