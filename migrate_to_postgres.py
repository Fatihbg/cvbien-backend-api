#!/usr/bin/env python3
"""
Script de migration de SQLite vers PostgreSQL
Ce script transfère toutes les données de la base SQLite vers PostgreSQL
"""

import sqlite3
import psycopg2
import os
from datetime import datetime
import uuid

def migrate_data():
    # Connexion SQLite
    sqlite_conn = sqlite3.connect('cvbien.db')
    sqlite_cursor = sqlite_conn.cursor()
    
    # Connexion PostgreSQL
    postgres_url = os.getenv("DATABASE_URL")
    if not postgres_url:
        print("❌ DATABASE_URL not found in environment variables")
        return
    
    postgres_conn = psycopg2.connect(postgres_url)
    postgres_cursor = postgres_conn.cursor()
    
    try:
        print("🔄 Starting migration from SQLite to PostgreSQL...")
        
        # 1. Migrer les utilisateurs
        print("📊 Migrating users...")
        sqlite_cursor.execute("SELECT * FROM users")
        users = sqlite_cursor.fetchall()
        
        for user in users:
            user_id, email, name, password_hash, credits, created_at, last_login_at, subscription_type, is_active = user
            
            # Convertir les dates
            created_at_dt = datetime.fromisoformat(created_at) if created_at else datetime.utcnow()
            last_login_dt = datetime.fromisoformat(last_login_at) if last_login_at else None
            
            # Insérer dans PostgreSQL
            postgres_cursor.execute("""
                INSERT INTO users (id, email, name, password_hash, credits, created_at, last_login_at, subscription_type, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    email = EXCLUDED.email,
                    name = EXCLUDED.name,
                    password_hash = EXCLUDED.password_hash,
                    credits = EXCLUDED.credits,
                    created_at = EXCLUDED.created_at,
                    last_login_at = EXCLUDED.last_login_at,
                    subscription_type = EXCLUDED.subscription_type,
                    is_active = EXCLUDED.is_active
            """, (user_id, email, name, password_hash, credits, created_at_dt, last_login_dt, subscription_type, bool(is_active)))
        
        print(f"✅ Migrated {len(users)} users")
        
        # 2. Migrer les CV générés
        print("📄 Migrating generated CVs...")
        sqlite_cursor.execute("SELECT * FROM generated_cvs")
        cvs = sqlite_cursor.fetchall()
        
        for cv in cvs:
            cv_id, user_id, original_text, optimized_text, created_at = cv
            created_at_dt = datetime.fromisoformat(created_at) if created_at else datetime.utcnow()
            
            postgres_cursor.execute("""
                INSERT INTO generated_cvs (id, user_id, original_text, optimized_text, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    original_text = EXCLUDED.original_text,
                    optimized_text = EXCLUDED.optimized_text,
                    created_at = EXCLUDED.created_at
            """, (cv_id, user_id, original_text, optimized_text, created_at_dt))
        
        print(f"✅ Migrated {len(cvs)} generated CVs")
        
        # 3. Migrer les transactions
        print("💰 Migrating transactions...")
        sqlite_cursor.execute("SELECT * FROM transactions")
        transactions = sqlite_cursor.fetchall()
        
        for transaction in transactions:
            trans_id, user_id, amount, credits_added, created_at, type_trans = transaction
            created_at_dt = datetime.fromisoformat(created_at) if created_at else datetime.utcnow()
            
            postgres_cursor.execute("""
                INSERT INTO transactions (id, user_id, amount, credits_added, created_at, type)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    amount = EXCLUDED.amount,
                    credits_added = EXCLUDED.credits_added,
                    created_at = EXCLUDED.created_at,
                    type = EXCLUDED.type
            """, (trans_id, user_id, amount, credits_added, created_at_dt, type_trans))
        
        print(f"✅ Migrated {len(transactions)} transactions")
        
        # Valider les changements
        postgres_conn.commit()
        print("🎉 Migration completed successfully!")
        
        # Afficher les statistiques
        postgres_cursor.execute("SELECT COUNT(*) FROM users")
        user_count = postgres_cursor.fetchone()[0]
        
        postgres_cursor.execute("SELECT COUNT(*) FROM transactions")
        trans_count = postgres_cursor.fetchone()[0]
        
        postgres_cursor.execute("SELECT COUNT(*) FROM generated_cvs")
        cv_count = postgres_cursor.fetchone()[0]
        
        print(f"📊 Final statistics:")
        print(f"   - Users: {user_count}")
        print(f"   - Transactions: {trans_count}")
        print(f"   - Generated CVs: {cv_count}")
        
    except Exception as e:
        print(f"❌ Error during migration: {str(e)}")
        postgres_conn.rollback()
    finally:
        sqlite_conn.close()
        postgres_conn.close()

if __name__ == "__main__":
    migrate_data()
