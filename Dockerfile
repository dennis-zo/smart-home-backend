# Dockerfile
# השתמש ב-Base image קל
FROM python:3.11-slim

WORKDIR /code

# העתקת דרישות והתקנה
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# העתקת הקוד
COPY ./app /code/app

# הרצת השרת (Uvicorn הוא ה-Server המהיר ביותר לפייתון)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]