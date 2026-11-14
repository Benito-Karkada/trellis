FROM python:3.12-slim
COPY execute.py /executor.py
USER 65534:65534
WORKDIR /tmp
ENTRYPOINT ["python", "-I", "/executor.py"]
