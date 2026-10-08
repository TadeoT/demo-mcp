FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir prometheus_client==0.21.1
COPY app.py .
EXPOSE 8080
CMD ["python", "-u", "app.py"]
