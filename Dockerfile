FROM python:3.10-slim

WORKDIR /app

COPY flask_app/ .

RUN pip install flask

EXPOSE 5000

CMD ["python", "app.py"]