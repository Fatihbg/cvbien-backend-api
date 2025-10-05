#!/usr/bin/env python3
import os
import uvicorn
from main_auth import app, init_db

if __name__ == "__main__":
    # Initialiser la base de données
    init_db()
    
    # Obtenir le port depuis les variables d'environnement
    port = int(os.getenv("PORT", 8080))
    
    print(f"🚀 Démarrage du serveur sur le port {port}")
    
    # Démarrer le serveur
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=port,
        log_level="info"
    )
