FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt
COPY storage.py upload_server.py archive_io.py server.py webapp.py ezshare.py file_ops.py wifi_utils.py ./
COPY templates ./templates
COPY static ./static
USER 1000:1000
CMD ["python", "webapp.py"]
