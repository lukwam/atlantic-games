FROM python:3.13-slim

WORKDIR /app
RUN pip install --no-cache-dir "atlantic-games[api]>=0.1"
COPY main.py .

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
