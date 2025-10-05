#!/usr/bin/env python3
import sqlite3
from datetime import datetime

def init_database():
    conn = sqlite3.connect('cvbien.db')
    cursor = conn.cursor()
    
    # Créer les tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            credits INTEGER DEFAULT 2,
            created_at TEXT NOT NULL,
            last_login_at TEXT,
            subscription_type TEXT DEFAULT 'free',
            is_active BOOLEAN DEFAULT 1
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS generated_cvs (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            original_file_name TEXT NOT NULL,
            job_description TEXT NOT NULL,
            optimized_cv TEXT NOT NULL,
            ats_score INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            is_downloaded BOOLEAN DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS credit_transactions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            amount INTEGER NOT NULL,
            transaction_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Créer l'utilisateur de test
    try:
        cursor.execute('''
            INSERT INTO users (id, email, name, password_hash, credits, created_at, subscription_type, is_active, last_login_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', ('test_user_id', 'test@example.com', 'Utilisateur Test', 'test_hash', 10, 
              datetime.utcnow().isoformat(), 'free', True, datetime.utcnow().isoformat()))
        print('✅ Utilisateur de test créé avec succès')
    except sqlite3.IntegrityError:
        print('ℹ️  Utilisateur de test existe déjà')
    
    conn.commit()
    conn.close()
    print('✅ Base de données initialisée')

if __name__ == "__main__":
    init_database()

