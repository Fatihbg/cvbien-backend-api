FROM python:3.11-slim

WORKDIR /app

# Copier requirements.txt
COPY requirements.txt .

# Installer les dépendances
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code
COPY . .

# Exposer le port
EXPOSE 8080

# Commande de démarrage
CMD ["sh", "-c", "python -m uvicorn main_auth:app --host 0.0.0.0 --port ${PORT:-8080}"]