FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/insurance_claims/fixtures DEMO_TODAY=2026-02-15

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent ./agent
COPY insurance_claims ./insurance_claims
COPY app.py main.py ./

EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--browser.gatherUsageStats=false"]
