from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from typing import Optional, List
import jwt
import hashlib
import sqlite3
import os
from datetime import datetime, timedelta
import uuid
import stripe

# Configuration
SECRET_KEY = "your-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Configuration Stripe
from dotenv import load_dotenv

# Charger les variables d'environnement depuis .env
load_dotenv()

# Configuration Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
print(f"🔧 DEBUG: Stripe API Key loaded: {stripe.api_key[:10] if stripe.api_key else 'None'}...")

# Vérifier et corriger la clé Stripe si nécessaire
if not stripe.api_key or not stripe.api_key.startswith("sk_"):
    print("⚠️ WARNING: STRIPE_SECRET_KEY not configured properly")
    raise Exception("STRIPE_SECRET_KEY must be configured with a valid Stripe secret key (starts with sk_)")

# Modèles Pydantic
class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class User(BaseModel):
    id: str
    email: str
    name: str
    credits: int
    created_at: str
    last_login_at: str
    subscription_type: str
    is_active: bool

class UserProfile(BaseModel):
    id: str
    email: str
    name: str
    credits: int
    subscription_type: str
    total_cvs_generated: int
    last_cv_generated_at: Optional[str]
    created_at: str

class GeneratedCV(BaseModel):
    id: str
    user_id: str
    original_file_name: str
    job_description: str
    optimized_cv: str
    ats_score: int
    created_at: str
    is_downloaded: bool

class CreditPurchase(BaseModel):
    amount: int
    payment_method: str

class CreditConsumption(BaseModel):
    amount: int

class PaymentIntentRequest(BaseModel):
    credits: int
    amount: int

class PaymentIntentResponse(BaseModel):
    client_secret: str
    amount: int
    credits: int
    checkout_url: str

# Initialisation de l'API
app = FastAPI(title="CVbien Auth API", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", 
        "http://localhost:5174", 
        "http://localhost:5175", 
        "http://localhost:3000",
        "https://cvbien4.vercel.app",
        "https://cvbien.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Sécurité
security = HTTPBearer()

# Base de données
def init_db():
    conn = sqlite3.connect('cvbien.db')
    cursor = conn.cursor()
    
    # Table des utilisateurs
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
    
    # Table des CV générés
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
    
    # Table des transactions de crédits
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
    
    conn.commit()
    conn.close()

# Fonctions utilitaires
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        # Accepter les tokens de test pour le développement
        if credentials.credentials.startswith('test_token_'):
            # Pour les tokens de test, on retourne un ID d'utilisateur factice
            # L'utilisateur de test sera créé lors de la première utilisation
            return "test_user_id"
        
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Token invalide")
        return user_id
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Token invalide")

def get_user_by_id(user_id: str) -> Optional[dict]:
    conn = sqlite3.connect('cvbien.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    
    # Si c'est l'utilisateur de test et qu'il n'existe pas, le créer
    if not user and user_id == "test_user_id":
        try:
            cursor.execute('''
                INSERT INTO users (id, email, name, password_hash, credits, created_at, subscription_type, is_active, last_login_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, 'test@example.com', 'Utilisateur Test', 'test_hash', 10, 
                  datetime.utcnow().isoformat(), 'free', True, datetime.utcnow().isoformat()))
            conn.commit()
            
            # Récupérer l'utilisateur créé
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            user = cursor.fetchone()
        except sqlite3.IntegrityError:
            # L'utilisateur existe déjà, le récupérer
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            user = cursor.fetchone()
    
    conn.close()
    
    if user:
        return {
            "id": user[0],
            "email": user[1],
            "name": user[2],
            "credits": user[4],
            "created_at": user[5],
            "last_login_at": user[6],
            "subscription_type": user[7],
            "is_active": bool(user[8])
        }
    return None

# Routes d'authentification
@app.post("/api/auth/register")
async def register(user_data: UserCreate):
    conn = sqlite3.connect('cvbien.db')
    cursor = conn.cursor()
    
    # Vérifier si l'utilisateur existe déjà
    cursor.execute("SELECT id FROM users WHERE email = ?", (user_data.email,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Email déjà utilisé")
    
    # Créer l'utilisateur
    user_id = str(uuid.uuid4())
    password_hash = hash_password(user_data.password)
    created_at = datetime.utcnow().isoformat()
    
    cursor.execute('''
        INSERT INTO users (id, email, name, password_hash, credits, created_at, subscription_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, user_data.email, user_data.name, password_hash, 2, created_at, 'free'))
    
    conn.commit()
    conn.close()
    
    # Créer le token
    access_token = create_access_token(data={"sub": user_id})
    
    # Retourner l'utilisateur et le token
    user = get_user_by_id(user_id)
    return {
        "user": user,
        "token": access_token
    }

@app.post("/api/auth/login")
async def login(login_data: UserLogin):
    conn = sqlite3.connect('cvbien.db')
    cursor = conn.cursor()
    
    # Trouver l'utilisateur
    cursor.execute("SELECT * FROM users WHERE email = ?", (login_data.email,))
    user = cursor.fetchone()
    
    if not user or not verify_password(login_data.password, user[3]):
        conn.close()
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    
    # Mettre à jour la dernière connexion
    last_login = datetime.utcnow().isoformat()
    cursor.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (last_login, user[0]))
    conn.commit()
    conn.close()
    
    # Créer le token
    access_token = create_access_token(data={"sub": user[0]})
    
    # Retourner l'utilisateur et le token
    user_data = get_user_by_id(user[0])
    return {
        "user": user_data,
        "token": access_token
    }

@app.post("/api/auth/logout")
async def logout(user_id: str = Depends(verify_token)):
    # Dans un vrai système, on pourrait invalider le token
    return {"message": "Déconnexion réussie"}

@app.get("/api/auth/validate")
async def validate_token(user_id: str = Depends(verify_token)):
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur non trouvé")
    return {"user": user}

# Routes utilisateur
@app.get("/api/user/profile")
async def get_profile(user_id: str = Depends(verify_token)):
    conn = sqlite3.connect('cvbien.db')
    cursor = conn.cursor()
    
    # Récupérer l'utilisateur
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    
    # Compter les CV générés
    cursor.execute("SELECT COUNT(*) FROM generated_cvs WHERE user_id = ?", (user_id,))
    total_cvs = cursor.fetchone()[0]
    
    # Dernier CV généré
    cursor.execute("SELECT created_at FROM generated_cvs WHERE user_id = ? ORDER BY created_at DESC LIMIT 1", (user_id,))
    last_cv = cursor.fetchone()
    
    conn.close()
    
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "credits": user["credits"],
        "subscription_type": user["subscription_type"],
        "total_cvs_generated": total_cvs,
        "last_cv_generated_at": last_cv[0] if last_cv else None,
        "created_at": user["created_at"]
    }

@app.put("/api/user/profile")
async def update_profile(updates: dict, user_id: str = Depends(verify_token)):
    conn = sqlite3.connect('cvbien.db')
    cursor = conn.cursor()
    
    # Construire la requête de mise à jour
    set_clause = ", ".join([f"{key} = ?" for key in updates.keys()])
    values = list(updates.values()) + [user_id]
    
    cursor.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()
    
    return get_user_by_id(user_id)

@app.post("/api/user/buy-credits")
async def buy_credits(purchase: CreditPurchase, user_id: str = Depends(verify_token)):
    conn = sqlite3.connect('cvbien.db')
    cursor = conn.cursor()
    
    # Calculer le prix en centimes
    price_cents = purchase.amount * 100  # 1€ = 100 centimes
    
    try:
        # SIMULATION DE PAIEMENT (pour les tests)
        print(f"🔧 DEBUG: Simulation de paiement pour {purchase.amount}€")
        
        # Calculer le nombre de crédits selon le montant
        if purchase.amount == 1:
            credits_to_add = 5  # 1€ = 5 crédits
        elif purchase.amount == 5:
            credits_to_add = 100  # 5€ = 100 crédits
        else:
            credits_to_add = purchase.amount  # Fallback
        
        print(f"🔧 DEBUG: Montant reçu: {purchase.amount}€, Crédits à ajouter: {credits_to_add}")
        
        # Ajouter les crédits
        cursor.execute("UPDATE users SET credits = credits + ? WHERE id = ?", (credits_to_add, user_id))
        
        # Enregistrer la transaction
        transaction_id = str(uuid.uuid4())
        cursor.execute('''
            INSERT INTO credit_transactions (id, user_id, amount, transaction_type, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (transaction_id, user_id, credits_to_add, 'purchase', datetime.utcnow().isoformat()))
        
        conn.commit()
        
        # Récupérer le nouveau solde
        cursor.execute("SELECT credits FROM users WHERE id = ?", (user_id,))
        new_credits = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "credits": new_credits,
            "transaction_id": transaction_id,
            "client_secret": f"simulated_payment_intent_{transaction_id}"
        }
        
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Erreur: {str(e)}")
    
    conn.close()
    raise HTTPException(status_code=400, detail="Erreur de paiement")

@app.post("/api/user/consume-credits")
async def consume_credits(consumption: CreditConsumption, user_id: str = Depends(verify_token)):
    conn = sqlite3.connect('cvbien.db')
    cursor = conn.cursor()
    
    # Vérifier le solde
    cursor.execute("SELECT credits FROM users WHERE id = ?", (user_id,))
    current_credits = cursor.fetchone()[0]
    
    if current_credits < consumption.amount:
        conn.close()
        raise HTTPException(status_code=400, detail="Crédits insuffisants")
    
    # Consommer les crédits
    cursor.execute("UPDATE users SET credits = credits - ? WHERE id = ?", (consumption.amount, user_id))
    
    # Enregistrer la transaction
    transaction_id = str(uuid.uuid4())
    cursor.execute('''
        INSERT INTO credit_transactions (id, user_id, amount, transaction_type, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (transaction_id, user_id, consumption.amount, 'consumption', datetime.utcnow().isoformat()))
    
    conn.commit()
    
    # Récupérer le nouveau solde
    cursor.execute("SELECT credits FROM users WHERE id = ?", (user_id,))
    new_credits = cursor.fetchone()[0]
    
    conn.close()
    
    return {"credits": new_credits}

# Routes CV
@app.get("/api/user/cvs")
async def get_cvs(user_id: str = Depends(verify_token)):
    conn = sqlite3.connect('cvbien.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, user_id, original_file_name, job_description, optimized_cv, ats_score, created_at, is_downloaded
        FROM generated_cvs WHERE user_id = ? ORDER BY created_at DESC
    ''', (user_id,))
    
    cvs = []
    for row in cursor.fetchall():
        cvs.append({
            "id": row[0],
            "user_id": row[1],
            "original_file_name": row[2],
            "job_description": row[3],
            "optimized_cv": row[4],
            "ats_score": row[5],
            "created_at": row[6],
            "is_downloaded": bool(row[7])
        })
    
    conn.close()
    return cvs

@app.post("/api/user/cvs")
async def save_cv(cv_data: dict, user_id: str = Depends(verify_token)):
    print(f"🔧 DEBUG: Données reçues: {cv_data}")
    print(f"🔧 DEBUG: Clés disponibles: {list(cv_data.keys())}")
    
    conn = sqlite3.connect('cvbien.db')
    cursor = conn.cursor()
    
    cv_id = str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat()
    
    cursor.execute('''
        INSERT INTO generated_cvs (id, user_id, original_file_name, job_description, optimized_cv, ats_score, created_at, is_downloaded)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (cv_id, user_id, cv_data.get("original_file_name", "cv_uploaded.pdf"), cv_data.get("job_description", "Job description"), 
          cv_data.get("optimized_cv", ""), cv_data.get("ats_score", 0), created_at, cv_data.get("is_downloaded", False)))
    
    conn.commit()
    conn.close()
    
    return {
        "id": cv_id,
        "user_id": user_id,
        "original_file_name": cv_data.get("original_file_name", "cv_uploaded.pdf"),
        "job_description": cv_data.get("job_description", "Job description"),
        "optimized_cv": cv_data.get("optimized_cv", ""),
        "ats_score": cv_data.get("ats_score", 0),
        "created_at": created_at,
        "is_downloaded": cv_data.get("is_downloaded", False)
    }

# Endpoint de paiement (simulation)
@app.post("/api/payments/create-payment-intent", response_model=PaymentIntentResponse)
async def create_payment_intent(
    payment_data: PaymentIntentRequest,
    user_id: str = Depends(verify_token)
):
    """Créer une intention de paiement (simulation)"""
    try:
        print(f"🔧 DEBUG: Création intention de paiement")
        print(f"🔧 DEBUG: - User ID: {user_id}")
        print(f"🔧 DEBUG: - Credits: {payment_data.credits}")
        print(f"🔧 DEBUG: - Amount: {payment_data.amount}")
        print(f"🔧 DEBUG: - Type credits: {type(payment_data.credits)}")
        print(f"🔧 DEBUG: - Type amount: {type(payment_data.amount)}")
        
        # Validation des données
        if not isinstance(payment_data.credits, int) or payment_data.credits <= 0:
            raise ValueError(f"Credits invalides: {payment_data.credits}")
        
        if not isinstance(payment_data.amount, (int, float)) or payment_data.amount <= 0:
            raise ValueError(f"Amount invalide: {payment_data.amount}")
        
        # Créer une session de paiement Stripe
        print(f"🔧 DEBUG: Configuration Stripe - API Key: {stripe.api_key[:10]}...")
        print(f"🔧 DEBUG: Création session pour {payment_data.credits} crédits à {payment_data.amount}€")
        
        # Vérifier la configuration Stripe
        if not stripe.api_key or not stripe.api_key.startswith("sk_"):
            raise HTTPException(status_code=400, detail="Configuration Stripe invalide. Veuillez configurer STRIPE_SECRET_KEY.")
        
        try:
            # Créer une session de checkout Stripe avec l'API REST
            import requests
            
            headers = {
                'Authorization': f'Bearer {stripe.api_key}',
                'Content-Type': 'application/x-www-form-urlencoded',
            }
            
            data = {
                'payment_method_types[]': 'card',
                'line_items[0][price_data][currency]': 'eur',
                'line_items[0][price_data][product_data][name]': f'{payment_data.credits} crédits CVbien',
                'line_items[0][price_data][unit_amount]': payment_data.amount * 100,
                'line_items[0][quantity]': 1,
                'mode': 'payment',
                'success_url': f'https://cvbien4.vercel.app/payment-success?session_id={{CHECKOUT_SESSION_ID}}&credits={payment_data.credits}&user_id={user_id}',
                'cancel_url': 'https://cvbien4.vercel.app/payment-cancel',
                'metadata[user_id]': user_id,
                'metadata[credits]': str(payment_data.credits),
                'metadata[amount]': str(payment_data.amount)
            }
            
            response = requests.post('https://api.stripe.com/v1/checkout/sessions', headers=headers, data=data)
            
            if response.status_code != 200:
                raise Exception(f"Stripe API error: {response.status_code} - {response.text}")
            
            checkout_session_data = response.json()
            
            print(f"✅ DEBUG: Session Stripe créée: {checkout_session_data['id']}")
            
            response = PaymentIntentResponse(
                client_secret=checkout_session_data.get('payment_intent', 'N/A'),
                amount=payment_data.amount,
                credits=payment_data.credits,
                checkout_url=checkout_session_data['url']
            )
            
        except stripe.error.StripeError as e:
            print(f"❌ Erreur Stripe: {str(e)}")
            print(f"❌ Type d'erreur: {type(e)}")
            raise HTTPException(status_code=400, detail=f"Erreur Stripe: {str(e)}")
        except Exception as e:
            print(f"❌ Erreur générale: {str(e)}")
            raise HTTPException(status_code=400, detail=f"Erreur: {str(e)}")
        
        print(f"✅ DEBUG: Réponse générée: {response}")
        return response
        
    except Exception as e:
        print(f"❌ Erreur création intention de paiement: {str(e)}")
        print(f"❌ Type d'erreur: {type(e)}")
        import traceback
        print(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=400, detail=f"Erreur: {str(e)}")

@app.post("/api/payments/confirm")
async def confirm_payment(session_id: str):
    """Confirmer un paiement Stripe et ajouter les crédits"""
    try:
        # Récupérer la session Stripe avec l'API REST
        import requests
        
        headers = {
            'Authorization': f'Bearer {stripe.api_key}',
        }
        
        response = requests.get(f'https://api.stripe.com/v1/checkout/sessions/{session_id}', headers=headers)
        
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Erreur récupération session: {response.status_code}")
        
        session_data = response.json()
        
        if session_data['payment_status'] != 'paid':
            raise HTTPException(status_code=400, detail="Paiement non confirmé")
        
        # Récupérer les métadonnées
        user_id = session_data['metadata'].get('user_id')
        credits = int(session_data['metadata'].get('credits', 0))
        amount = float(session_data['metadata'].get('amount', 0))
        
        if not user_id or not credits:
            raise HTTPException(status_code=400, detail="Métadonnées de session invalides")
        
        # Ajouter les crédits à l'utilisateur
        conn = sqlite3.connect('cvbien.db')
        cursor = conn.cursor()
        
        cursor.execute("UPDATE users SET credits = credits + ? WHERE id = ?", (credits, user_id))
        
        # Enregistrer la transaction
        transaction_id = str(uuid.uuid4())
        cursor.execute('''
            INSERT INTO credit_transactions (id, user_id, amount, transaction_type, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (transaction_id, user_id, credits, 'purchase', datetime.utcnow().isoformat()))
        
        conn.commit()
        conn.close()
        
        print(f"✅ DEBUG: Paiement confirmé - {credits} crédits ajoutés à l'utilisateur {user_id}")
        
        return {
            "success": True,
            "credits": credits,
            "transaction_id": transaction_id
        }
        
    except stripe.error.StripeError as e:
        print(f"❌ Erreur Stripe: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Erreur de confirmation: {str(e)}")
    except Exception as e:
        print(f"❌ Erreur confirmation: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Erreur: {str(e)}")

@app.get("/api/test-stripe")
async def test_stripe():
    """Tester la configuration Stripe"""
    try:
        # Tester la configuration Stripe
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
        if not stripe.api_key:
            return {
                "status": "error",
                "message": "STRIPE_SECRET_KEY not configured",
                "api_key": "None"
            }
        
        # Tester une requête simple à Stripe
        try:
            # Test simple avec la version de Stripe
            stripe_version = stripe.__version__
            print(f"🔧 DEBUG: Stripe version: {stripe_version}")
            
            # Test de base sans récupérer l'account
            return {
                "status": "success",
                "message": "Stripe configuration OK",
                "api_key": f"{stripe.api_key[:10]}...",
                "mode": "live" if stripe.api_key.startswith("sk_live_") else "test",
                "stripe_version": stripe_version
            }
        except stripe.error.AuthenticationError as e:
            return {
                "status": "error",
                "message": f"Invalid Stripe API key: {str(e)}",
                "api_key": f"{stripe.api_key[:10]}..."
            }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Stripe error: {str(e)}",
            "api_key": f"{stripe.api_key[:10]}..." if stripe.api_key else "None"
        }

@app.post("/api/test-payment-auth")
async def test_payment_with_auth(credits: int = 5, amount: int = 1):
    """Tester la création d'une session de paiement avec authentification simulée"""
    try:
        print("🔧 DEBUG: Test de création de session de paiement avec auth")
        
        # Simuler un user_id pour le test
        user_id = "test_user_123"
        
        # Créer une session de checkout Stripe avec l'API REST
        import requests
        
        headers = {
            'Authorization': f'Bearer {stripe.api_key}',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        
        data = {
            'payment_method_types[]': 'card',
            'line_items[0][price_data][currency]': 'eur',
            'line_items[0][price_data][product_data][name]': f'{credits} crédits CVbien',
            'line_items[0][price_data][unit_amount]': amount * 100,
            'line_items[0][quantity]': 1,
            'mode': 'payment',
            'success_url': f'https://cvbien4.vercel.app/payment-success?session_id={{CHECKOUT_SESSION_ID}}&credits={credits}&user_id={user_id}',
            'cancel_url': 'https://cvbien4.vercel.app/payment-cancel',
            'metadata[user_id]': user_id,
            'metadata[credits]': str(credits),
            'metadata[amount]': str(amount)
        }
        
        response = requests.post('https://api.stripe.com/v1/checkout/sessions', headers=headers, data=data)
        
        if response.status_code != 200:
            raise Exception(f"Stripe API error: {response.status_code} - {response.text}")
        
        checkout_session_data = response.json()
        
        return {
            "status": "success",
            "message": "Session de paiement créée avec succès",
            "session_id": checkout_session_data["id"],
            "checkout_url": checkout_session_data["url"],
            "client_secret": checkout_session_data.get('payment_intent', 'N/A'),
            "amount": amount,
            "credits": credits
        }
        
    except Exception as e:
        print(f"❌ Erreur test paiement: {str(e)}")
        import traceback
        print(f"❌ Traceback: {traceback.format_exc()}")
        return {
            "status": "error",
            "message": f"Erreur: {str(e)}",
            "traceback": traceback.format_exc()
        }

@app.post("/api/test-payment")
async def test_payment():
    """Tester la création d'une session de paiement"""
    try:
        print("🔧 DEBUG: Test de création de session de paiement")
        
        # Test avec des données factices
        test_data = {
            "credits": 5,
            "amount": 1,
            "user_id": "test_user"
        }
        
        # Créer une session de checkout Stripe
        print(f"🔧 DEBUG: Stripe module: {stripe}")
        print(f"🔧 DEBUG: Stripe checkout: {getattr(stripe, 'checkout', 'NOT_FOUND')}")
        
        # Utiliser l'API REST de Stripe directement
        import requests
        
        headers = {
            'Authorization': f'Bearer {stripe.api_key}',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        
        data = {
            'payment_method_types[]': 'card',
            'line_items[0][price_data][currency]': 'eur',
            'line_items[0][price_data][product_data][name]': f'{test_data["credits"]} crédits CVbien',
            'line_items[0][price_data][unit_amount]': test_data["amount"] * 100,
            'line_items[0][quantity]': 1,
            'mode': 'payment',
            'success_url': 'https://cvbien4.vercel.app/payment-success?session_id={CHECKOUT_SESSION_ID}',
            'cancel_url': 'https://cvbien4.vercel.app/payment-cancel',
            'metadata[user_id]': test_data["user_id"],
            'metadata[credits]': str(test_data["credits"]),
            'metadata[amount]': str(test_data["amount"])
        }
        
        response = requests.post('https://api.stripe.com/v1/checkout/sessions', headers=headers, data=data)
        
        if response.status_code != 200:
            raise Exception(f"Stripe API error: {response.status_code} - {response.text}")
        
        checkout_session_data = response.json()
        
        return {
            "status": "success",
            "message": "Session de paiement créée avec succès",
            "session_id": checkout_session_data["id"],
            "checkout_url": checkout_session_data["url"]
        }
        
    except Exception as e:
        print(f"❌ Erreur test paiement: {str(e)}")
        import traceback
        print(f"❌ Traceback: {traceback.format_exc()}")
        return {
            "status": "error",
            "message": f"Erreur: {str(e)}",
            "traceback": traceback.format_exc()
        }

@app.get("/version")
async def get_version():
    return {
        "version": "2.9.0",
        "status": "Payment Test Added",
        "timestamp": "2025-01-05 23:40",
        "fix": "Added payment test endpoint for debugging",
        "action": "PAYMENT_TEST_DEPLOY"
    }

@app.get("/api/admin/users")
async def get_all_users():
    """Récupérer tous les utilisateurs pour l'administration."""
    try:
        print("🔍 Début récupération données admin...")
        conn = sqlite3.connect('cvbien.db')
        cursor = conn.cursor()
        
        # Récupérer tous les utilisateurs avec leurs données
        print("🔍 Récupération des utilisateurs...")
        cursor.execute("""
            SELECT id, email, credits, created_at, last_login_at
            FROM users 
            ORDER BY created_at DESC
        """)
        users = cursor.fetchall()
        print(f"🔍 Utilisateurs trouvés: {len(users)}")
        print(f"🔍 Premier utilisateur: {users[0] if users else 'Aucun'}")
        
        # Récupérer les transactions de crédits
        print("🔍 Récupération des transactions...")
        cursor.execute("""
            SELECT user_id, amount, created_at, transaction_type
            FROM credit_transactions 
            ORDER BY created_at DESC
        """)
        transactions = cursor.fetchall()
        print(f"🔍 Transactions trouvées: {len(transactions)}")
        
        # Récupérer les CV générés
        print("🔍 Récupération des CV...")
        cursor.execute("""
            SELECT user_id, created_at, job_description
            FROM generated_cvs 
            ORDER BY created_at DESC
        """)
        generated_cvs = cursor.fetchall()
        print(f"🔍 CV trouvés: {len(generated_cvs)}")
        
        conn.close()
        
        # Calculer les statistiques
        print("🔍 Calcul des statistiques...")
        total_users = len(users)
        total_credits_sold = sum(10 if t[1] == 1 else 100 for t in transactions if t[3] == 'purchase')
        total_revenue = sum(t[1] for t in transactions if t[3] == 'purchase')
        total_cvs_generated = len(generated_cvs)
        print(f"🔍 Stats: {total_users} users, {total_credits_sold} crédits, {total_revenue}€ revenus, {total_cvs_generated} CV")
        
        return {
            "users": [
                {
                    "id": user[0],
                    "email": user[1],
                    "credits": user[2],
                    "created_at": user[3],
                    "last_login": user[4]
                } for user in users
            ],
            "transactions": [
                {
                    "user_id": t[0],
                    "amount": t[1],
                    "credits_added": 10 if t[1] == 1 else 100,
                    "created_at": t[2],
                    "type": t[3]
                } for t in transactions
            ],
            "generated_cvs": [
                {
                    "user_id": cv[0],
                    "created_at": cv[1],
                    "job_description": cv[2][:100] + "..." if len(cv[2]) > 100 else cv[2]
                } for cv in generated_cvs
            ],
            "statistics": {
                "total_users": total_users,
                "total_credits_sold": total_credits_sold,
                "total_revenue": total_revenue,
                "total_cvs_generated": total_cvs_generated
            }
        }
        
    except Exception as e:
        print(f"❌ Erreur récupération données admin: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erreur lors de la récupération des données")

if __name__ == "__main__":
    init_db()
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
