# Build from the repository root, with this Dockerfile's allowlisted context.
FROM node:24-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DJANGO_SETTINGS_MODULE=config.azure_settings
WORKDIR /app
COPY backend/requirements.txt /build/backend/requirements.txt
COPY deploy/azure/requirements.txt /build/deploy/azure/requirements.txt
RUN pip install --no-cache-dir --upgrade pip==26.3 \
    && pip install --no-cache-dir -r /build/deploy/azure/requirements.txt
COPY backend/ /app/
COPY deploy/azure/settings.py /app/config/azure_settings.py
COPY deploy/azure/storage.py /app/config/azure_storage.py
COPY deploy/azure/urls.py /app/config/azure_urls.py
COPY deploy/azure/wsgi.py /app/config/azure_wsgi.py
COPY --from=frontend /frontend/dist /app/frontend-dist
# collectstatic needs settings but never connects to the database here.
RUN SECRET_KEY=build-only-placeholder POSTGRES_HOST=unused POSTGRES_USER=unused POSTGRES_PASSWORD=unused ALLOWED_HOSTS=localhost python manage.py collectstatic --noinput \
    && useradd --uid 10001 --create-home platform
USER 10001
EXPOSE 8000
CMD ["gunicorn", "config.azure_wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "2", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-"]
