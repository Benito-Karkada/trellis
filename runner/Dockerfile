FROM python:3.12-slim
WORKDIR /runner
RUN useradd --uid 10001 --create-home runner
COPY worker.py .
USER 10001
CMD ["python", "worker.py"]
