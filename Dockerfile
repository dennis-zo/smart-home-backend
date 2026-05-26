# Dockerfile
# השתמש ב-Base image קל
FROM python:3.11-slim

WORKDIR /code

# העתקת דרישות והתקנה
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# העתקת הקוד
COPY ./app /code/app

# הרצת הבוט (הרצת הקובץ main.py)
CMD ["python", "app/main.py"]