FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/private-media && chmod +x start-web.sh && useradd -m platform && chown -R platform /app
USER platform
CMD ["./start-web.sh"]
