FROM python:3.13.18-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY config config
COPY src src
COPY templates templates
COPY static static
COPY manage.py manage.py

RUN useradd --create-home datumlex && mkdir data && chmod -R a+rX /app && chown datumlex:datumlex data
USER datumlex

CMD ["sh", "-c", "if [ \"$DATUMLEX_SYNTHETIC_PREVIEW\" = true ]; then python manage.py provision_synthetic_preview || exit $?; fi; exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 120"]
