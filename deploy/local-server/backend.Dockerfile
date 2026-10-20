FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt gunicorn==23.0.0
COPY backend/config ./config
COPY backend/src ./src
COPY backend/manage.py ./manage.py
RUN useradd --create-home datumlex && mkdir data && chown datumlex:datumlex data
USER datumlex
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py bootstrap_support && exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 120 --access-logfile -"]
