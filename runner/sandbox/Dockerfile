FROM python:3.12-slim
COPY execute.py /executor.py
COPY visualize.py /visualize.py
USER 65534:65534
WORKDIR /tmp
ENTRYPOINT ["python", "-I", "/executor.py"]
