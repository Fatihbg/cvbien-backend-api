from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from typing import Optional, List
import jwt
import hashlib
import os
from datetime import datetime, timedelta
import uuid
import stripe
import psycopg2
from psycopg2.extras import RealDictCursor
import sqlalchemy
from sqlalchemy import create_engine, Column, String, Integer, Boolean, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

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

# Configuration PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("⚠️ WARNING: DATABASE_URL not configured, falling back to SQLite")
    DATABASE_URL = "sqlite:///./cvbien.db"

# Créer l'engine SQLAlchemy
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Modèles de base de données
class User(Base):
    __tablename__ = "users"
    
    id = Column(String, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    credits = Column(Integer, default=2)
    created_at = Column(DateTime, nullable=False)
    last_login_at = Column(DateTime)
    subscription_type = Column(String, default='free')
    is_active = Column(Boolean, default=True)

class GeneratedCV(Base):
    __tablename__ = "generated_cvs"
    
    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    original_text = Column(Text)
    optimized_text = Column(Text)
    created_at = Column(DateTime, nullable=False)

class Transaction(Base):
    __tablename__ = "transactions"
    
    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    amount = Column(Integer, nullable=False)
    credits_added = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False)
    type = Column(String, nullable=False)  # 'purchase' or 'consumption'

# Créer les tables
Base.metadata.create_all(bind=engine)

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

class CVGenerationRequest(BaseModel):
    cv_text: str

class CVGenerationResponse(BaseModel):
    optimizedCV: str
    atsScore: int
    message: str

class PaymentIntentRequest(BaseModel):
    credits: int
    amount: int

class PaymentIntentResponse(BaseModel):
    client_secret: str
    amount: int
    credits: int
    checkout_url: str

class CreditConsumptionRequest(BaseModel):
    credits: int

class CreditConsumptionResponse(BaseModel):
    success: bool
    remaining_credits: int
    message: str

# Fonctions utilitaires
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return hash_password(plain_password) == hashed_password

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Token invalide")
        return user_id
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Token invalide")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_user_by_id(user_id: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            return {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "credits": user.credits,
                "created_at": user.created_at.isoformat(),
                "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
                "subscription_type": user.subscription_type,
                "is_active": user.is_active
            }
        return None
    finally:
        db.close()

# Initialisation de l'application
app = FastAPI(title="CVbien API", version="3.0.0")

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "https://cvbien4.vercel.app",
        "https://cvbien.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer()

# Routes d'authentification
@app.post("/api/auth/register")
async def register(user_data: UserCreate):
    db = SessionLocal()
    try:
        # Vérifier si l'utilisateur existe déjà
        existing_user = db.query(User).filter(User.email == user_data.email).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="Email déjà utilisé")
        
        # Créer l'utilisateur
        user_id = str(uuid.uuid4())
        password_hash = hash_password(user_data.password)
        created_at = datetime.utcnow()
        
        new_user = User(
            id=user_id,
            email=user_data.email,
            name=user_data.name,
            password_hash=password_hash,
            credits=2,
            created_at=created_at,
            subscription_type='free',
            is_active=True
        )
        
        db.add(new_user)
        db.commit()
        
        # Créer le token
        access_token = create_access_token(data={"sub": user_id})
        
        # Retourner l'utilisateur et le token
        user = get_user_by_id(user_id)
        return {
            "user": user,
            "access_token": access_token,
            "token_type": "bearer"
        }
    finally:
        db.close()

@app.post("/api/auth/login")
async def login(user_data: UserLogin):
    db = SessionLocal()
    try:
        # Vérifier l'utilisateur
        user = db.query(User).filter(User.email == user_data.email).first()
        if not user or not verify_password(user_data.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
        
        # Mettre à jour la dernière connexion
        user.last_login_at = datetime.utcnow()
        db.commit()
        
        # Créer le token
        access_token = create_access_token(data={"sub": user.id})
        
        # Retourner l'utilisateur et le token
        user_data = get_user_by_id(user.id)
        return {
            "user": user_data,
            "access_token": access_token,
            "token_type": "bearer"
        }
    finally:
        db.close()

@app.get("/api/auth/validate")
async def validate_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    user_id = verify_token(token)
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur non trouvé")
    return user

@app.post("/api/auth/logout")
async def logout():
    return {"message": "Déconnexion réussie"}

# Routes utilisateur
@app.get("/api/user/profile")
async def get_profile(user_id: str = Depends(verify_token)):
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    return user

@app.post("/api/user/consume-credits")
async def consume_credits(request: CreditConsumptionRequest, user_id: str = Depends(verify_token)):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
        
        if user.credits < request.credits:
            raise HTTPException(status_code=400, detail="Crédits insuffisants")
        
        # Consommer les crédits
        user.credits -= request.credits
        
        # Enregistrer la transaction
        transaction = Transaction(
            id=str(uuid.uuid4()),
            user_id=user_id,
            amount=request.credits,
            credits_added=0,
            created_at=datetime.utcnow(),
            type='consumption'
        )
        
        db.add(transaction)
        db.commit()
        
        return CreditConsumptionResponse(
            success=True,
            remaining_credits=user.credits,
            message=f"{request.credits} crédit(s) consommé(s)"
        )
    finally:
        db.close()

# Routes de génération de CV
@app.post("/optimize-cv", response_model=CVGenerationResponse)
async def optimize_cv(request: CVGenerationRequest):
    try:
        from openai import OpenAI
        
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        prompt = f"""
        Optimisez ce CV pour qu'il soit plus attractif pour les recruteurs et les systèmes ATS (Applicant Tracking Systems).
        
        CV à optimiser:
        {request.cv_text}
        
        Instructions:
        - Améliorez la structure et la présentation
        - Optimisez les mots-clés pour les ATS
        - Rendez le contenu plus impactant et professionnel
        - Gardez toutes les informations importantes
        - Assurez-vous que le CV fait exactement 1 page
        - Ajoutez des chiffres et pourcentages dans les descriptions d'expérience
        - Rendez les descriptions plus longues et détaillées
        - Utilisez un format professionnel et moderne
        
        Retournez uniquement le CV optimisé, sans commentaires supplémentaires.
        """
        
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.7
        )
        
        optimized_cv = response.choices[0].message.content
        
        # Calculer un score ATS simulé
        ats_score = min(95, 70 + len(optimized_cv.split()) // 10)
        
        return CVGenerationResponse(
            optimizedCV=optimized_cv,
            atsScore=ats_score,
            message="CV optimisé avec succès"
        )
        
    except Exception as e:
        print(f"❌ Erreur OpenAI: {str(e)}")
        return CVGenerationResponse(
            optimizedCV=request.cv_text,
            atsScore=50,
            message="Erreur lors de l'optimisation, CV original retourné"
        )

# Routes de paiement
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
        print(f"🔧 DEBUG: - Payment data: {payment_data}")
        
        # Validation des données
        if not isinstance(payment_data.credits, int) or payment_data.credits <= 0:
            raise ValueError(f"Credits invalides: {payment_data.credits}")
        
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
                'success_url': f'https://cvbien4.vercel.app/?payment=success&session_id={{CHECKOUT_SESSION_ID}}&credits={payment_data.credits}&user_id={user_id}',
                'cancel_url': 'https://cvbien4.vercel.app/?payment=cancelled',
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
            print(f"❌ Erreur création intention de paiement: {str(e)}")
            print(f"❌ Type d'erreur: {type(e)}")
            import traceback
            print(f"❌ Traceback: {traceback.format_exc()}")
            error_detail = f"Erreur: {str(e)}" if str(e) else "Erreur inconnue"
            raise HTTPException(status_code=400, detail=error_detail)
        
        print(f"✅ DEBUG: Réponse générée: {response}")
        return response
        
    except Exception as e:
        print(f"❌ Erreur création intention de paiement: {str(e)}")
        print(f"❌ Type d'erreur: {type(e)}")
        import traceback
        print(f"❌ Traceback: {traceback.format_exc()}")
        error_detail = f"Erreur: {str(e)}" if str(e) else "Erreur inconnue"
        raise HTTPException(status_code=400, detail=error_detail)

@app.post("/api/payments/confirm")
async def confirm_payment(session_id: str, user_id: str, credits: int):
    """Confirmer un paiement et ajouter les crédits"""
    try:
        db = SessionLocal()
        try:
            # Récupérer l'utilisateur
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
            
            # Ajouter les crédits
            user.credits += credits
            
            # Enregistrer la transaction
            transaction = Transaction(
                id=str(uuid.uuid4()),
                user_id=user_id,
                amount=credits // 5,  # 1€ = 5 crédits
                credits_added=credits,
                created_at=datetime.utcnow(),
                type='purchase'
            )
            
            db.add(transaction)
            db.commit()
            
            return {
                "success": True,
                "message": f"{credits} crédits ajoutés avec succès",
                "new_balance": user.credits
            }
        finally:
            db.close()
    except Exception as e:
        print(f"❌ Erreur confirmation paiement: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Erreur: {str(e)}")

# Routes d'administration
@app.get("/api/admin/users")
async def get_all_users():
    """Récupérer tous les utilisateurs (admin)"""
    db = SessionLocal()
    try:
        users = db.query(User).all()
        transactions = db.query(Transaction).all()
        
        users_data = []
        for user in users:
            users_data.append({
                "id": user.id,
                "email": user.email,
                "credits": user.credits,
                "created_at": user.created_at.isoformat(),
                "last_login": user.last_login_at.isoformat() if user.last_login_at else None
            })
        
        transactions_data = []
        for transaction in transactions:
            transactions_data.append({
                "user_id": transaction.user_id,
                "amount": transaction.amount,
                "credits_added": transaction.credits_added,
                "created_at": transaction.created_at.isoformat(),
                "type": transaction.type
            })
        
        return {
            "users": users_data,
            "transactions": transactions_data,
            "generated_cvs": [],
            "statistics": {
                "total_users": len(users_data),
                "total_credits_sold": sum(t.credits_added for t in transactions if t.type == 'purchase'),
                "total_revenue": sum(t.amount for t in transactions if t.type == 'purchase'),
                "total_cvs_generated": 0
            }
        }
    finally:
        db.close()

@app.post("/api/admin/add-credits")
async def add_credits_to_user(email: str, credits: int):
    """Ajouter des crédits à un utilisateur par email"""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            return {"status": "error", "message": f"Utilisateur {email} non trouvé"}
        
        user.credits += credits
        db.commit()
        
        return {
            "status": "success",
            "message": f"{credits} crédits ajoutés à {email}",
            "new_balance": user.credits
        }
    finally:
        db.close()

# Routes de test
@app.get("/version")
async def get_version():
    return {
        "version": "3.0.0",
        "database": "PostgreSQL",
        "status": "active",
        "timestamp": "2025-01-05 23:45",
        "fix": "Migrated to PostgreSQL for data persistence",
        "action": "POSTGRES_MIGRATION"
    }

@app.get("/")
async def root():
    return {"message": "CVbien API - PostgreSQL Version", "version": "3.0.0"}

@app.get("/test")
async def test():
    return {"status": "ok", "message": "PostgreSQL backend is working", "timestamp": datetime.utcnow().isoformat()}

# Endpoint de migration des données SQLite vers PostgreSQL
@app.post("/api/migrate-sqlite-to-postgres")
async def migrate_sqlite_to_postgres():
    """Migrer les données de SQLite vers PostgreSQL"""
    try:
        import sqlite3
        
        # Connexion à SQLite (si le fichier existe)
        try:
            sqlite_conn = sqlite3.connect('cvbien.db')
            sqlite_cursor = sqlite_conn.cursor()
            
            # Récupérer les utilisateurs de SQLite
            sqlite_cursor.execute("SELECT * FROM users")
            sqlite_users = sqlite_cursor.fetchall()
            
            # Récupérer les transactions de SQLite
            sqlite_cursor.execute("SELECT * FROM transactions")
            sqlite_transactions = sqlite_cursor.fetchall()
            
            sqlite_conn.close()
            
            print(f"📊 Données SQLite trouvées: {len(sqlite_users)} utilisateurs, {len(sqlite_transactions)} transactions")
            
        except Exception as e:
            print(f"⚠️ Pas de base SQLite trouvée: {e}")
            return {"status": "error", "message": "Aucune base SQLite trouvée"}
        
        # Connexion à PostgreSQL
        db = SessionLocal()
        
        # Migrer les utilisateurs
        migrated_users = 0
        for user in sqlite_users:
            try:
                # Vérifier si l'utilisateur existe déjà
                existing_user = db.query(User).filter(User.email == user[1]).first()
                if not existing_user:
                    new_user = User(
                        id=user[0],
                        email=user[1],
                        name=user[2],
                        password_hash=user[3],
                        credits=user[4],
                        created_at=datetime.fromisoformat(user[5]) if user[5] else datetime.utcnow(),
                        last_login=datetime.fromisoformat(user[6]) if user[6] else None,
                        subscription_type=user[7] if len(user) > 7 else 'free',
                        is_active=bool(user[8]) if len(user) > 8 else True
                    )
                    db.add(new_user)
                    migrated_users += 1
            except Exception as e:
                print(f"❌ Erreur migration utilisateur {user[1]}: {e}")
        
        # Migrer les transactions
        migrated_transactions = 0
        for trans in sqlite_transactions:
            try:
                # Vérifier si la transaction existe déjà
                existing_trans = db.query(Transaction).filter(
                    Transaction.user_id == trans[1],
                    Transaction.created_at == datetime.fromisoformat(trans[4]) if trans[4] else datetime.utcnow()
                ).first()
                if not existing_trans:
                    new_transaction = Transaction(
                        id=trans[0],
                        user_id=trans[1],
                        amount=trans[2],
                        credits_added=trans[3],
                        created_at=datetime.fromisoformat(trans[4]) if trans[4] else datetime.utcnow(),
                        type=trans[5] if len(trans) > 5 else 'consumption'
                    )
                    db.add(new_transaction)
                    migrated_transactions += 1
            except Exception as e:
                print(f"❌ Erreur migration transaction {trans[0]}: {e}")
        
        # Sauvegarder les changements
        db.commit()
        db.close()
        
        return {
            "status": "success",
            "message": f"Migration réussie ! {migrated_users} utilisateurs et {migrated_transactions} transactions migrés",
            "migrated_users": migrated_users,
            "migrated_transactions": migrated_transactions
        }
        
    except Exception as e:
        return {"status": "error", "message": f"Erreur migration: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
