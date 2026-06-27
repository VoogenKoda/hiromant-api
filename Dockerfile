FROM python:3.11-slim

# Määra töökataloog
WORKDIR /app

# Kopeeri requirements fail ja paigalda sõltuvused
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopeeri kogu ülejäänud API kood
COPY . .

# Ava port, mida FastAPI kasutab
EXPOSE 8002

# Käivita Uvicorn server (kohanda pordi ja hostiga)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
