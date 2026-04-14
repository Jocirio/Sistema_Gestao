FROM python:3.12-slim

# WeasyPrint precisa dessas libs do sistema
RUN apt-get update && apt-get install -y \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libfontconfig1 \
    libgdk-pixbuf-2.0-0 \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# API
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
ENV PYTHONPATH=/app
