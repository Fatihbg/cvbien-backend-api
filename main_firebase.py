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
import firebase_admin
from firebase_admin import credentials, firestore
import openai
import requests
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import black, blue
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
import PyPDF2
import io
import re

# Configuration
SECRET_KEY = "your-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Configuration Stripe
from dotenv import load_dotenv
load_dotenv()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
print(f"🔧 DEBUG: Stripe API Key loaded: {stripe.api_key[:10] if stripe.api_key else 'None'}...")

# Configuration Firebase
if not firebase_admin._apps:
    # Utiliser les credentials par défaut (variables d'environnement)
    cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(cred)

db = firestore.client()

# Configuration OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

# Modèles Pydantic
class UserCreate(BaseModel):
    email: EmailStr
    name: str
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    credits: int
    created_at: str
    last_login: Optional[str] = None
    subscription_type: str = "free"
    is_active: bool = True

class CVGenerationRequest(BaseModel):
    cv_text: str
    job_description: str

class CVGenerationResponse(BaseModel):
    optimized_cv: str
    ats_score: int
    suggestions: List[str]

class PaymentIntentResponse(BaseModel):
    checkout_url: str
    session_id: str

class CreditConsumptionRequest(BaseModel):
    credits: int

class CreditConsumptionResponse(BaseModel):
    success: bool
    remaining_credits: int
    message: str

# Fonctions utilitaires
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Token invalide")
        return user_id
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Token invalide")

# Initialisation FastAPI
app = FastAPI(title="CVbien API - Firebase Version", version="4.0.0")

# CORS
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

# Endpoints
@app.get("/")
async def root():
    return {"message": "CVbien API - Firebase Version", "version": "4.0.0"}

@app.get("/version")
async def get_version():
    return {
        "version": "4.1.0",
        "status": "Firebase Migration Complete",
        "timestamp": "2025-01-05-23:58",
        "fix": "Migrated to Firebase for reliable data persistence",
        "action": "FIREBASE_MIGRATION"
    }

@app.post("/api/auth/register", response_model=dict)
async def register(user: UserCreate):
    """Inscription d'un nouvel utilisateur"""
    try:
        # Vérifier si l'utilisateur existe déjà
        users_ref = db.collection('users')
        query = users_ref.where('email', '==', user.email).limit(1)
        existing_users = query.get()
        
        if existing_users:
            raise HTTPException(status_code=400, detail="Email déjà utilisé")
        
        # Créer l'utilisateur
        user_id = str(uuid.uuid4())
        password_hash = hash_password(user.password)
        created_at = datetime.utcnow().isoformat()
        
        user_data = {
            'id': user_id,
            'email': user.email,
            'name': user.name,
            'password_hash': password_hash,
            'credits': 2,
            'created_at': created_at,
            'last_login': None,
            'subscription_type': 'free',
            'is_active': True
        }
        
        # Sauvegarder dans Firebase
        users_ref.document(user_id).set(user_data)
        
        # Créer le token
        access_token = create_access_token(data={"sub": user_id})
        
        return {
            "status": "success",
            "message": "Utilisateur créé avec succès",
            "user": UserResponse(**user_data),
            "access_token": access_token
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la création: {str(e)}")

@app.post("/api/auth/login", response_model=dict)
async def login(user: UserLogin):
    """Connexion d'un utilisateur"""
    try:
        # Trouver l'utilisateur par email
        users_ref = db.collection('users')
        query = users_ref.where('email', '==', user.email).limit(1)
        users = query.get()
        
        if not users:
            raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
        
        user_doc = users[0]
        user_data = user_doc.to_dict()
        
        # Vérifier le mot de passe
        if user_data['password_hash'] != hash_password(user.password):
            raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
        
        # Mettre à jour la dernière connexion
        user_data['last_login'] = datetime.utcnow().isoformat()
        users_ref.document(user_doc.id).update({'last_login': user_data['last_login']})
        
        # Créer le token
        access_token = create_access_token(data={"sub": user_data['id']})
        
        return {
            "status": "success",
            "message": "Connexion réussie",
            "user": UserResponse(**user_data),
            "access_token": access_token
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la connexion: {str(e)}")

@app.get("/api/auth/validate")
async def validate_token(user_id: str = Depends(verify_token)):
    """Valider un token JWT"""
    try:
        # Récupérer l'utilisateur
        user_doc = db.collection('users').document(user_id).get()
        if not user_doc.exists:
            raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
        
        user_data = user_doc.to_dict()
        return {"valid": True, "user": UserResponse(**user_data)}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur de validation: {str(e)}")

@app.get("/api/user/profile", response_model=UserResponse)
async def get_profile(user_id: str = Depends(verify_token)):
    """Récupérer le profil de l'utilisateur"""
    try:
        user_doc = db.collection('users').document(user_id).get()
        if not user_doc.exists:
            raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
        
        user_data = user_doc.to_dict()
        return UserResponse(**user_data)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur récupération profil: {str(e)}")

@app.post("/optimize-cv", response_model=CVGenerationResponse)
async def optimize_cv(request: CVGenerationRequest):
    """Optimiser un CV avec OpenAI"""
    try:
        print("🤖 Génération CV avec OpenAI...")
        
        # Appel à OpenAI
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": """Tu es un expert en recrutement et optimisation de CV. 
                    Analyse le CV fourni et la description de poste, puis génère un CV optimisé.
                    
                    RÉPONSE OBLIGATOIRE EN JSON:
                    {
                        "optimized_cv": "CV optimisé complet en texte brut",
                        "ats_score": 85,
                        "suggestions": ["suggestion 1", "suggestion 2", "suggestion 3"]
                    }
                    
                    Le CV optimisé doit être détaillé, professionnel, et correspondre parfaitement au poste."""
                },
                {
                    "role": "user",
                    "content": f"CV actuel:\n{request.cv_text}\n\nDescription du poste:\n{request.job_description}\n\nGénère un CV optimisé."
                }
            ],
            max_tokens=3000,
            temperature=0.7
        )
        
        content = response.choices[0].message.content
        
        # Parser la réponse JSON
        try:
            import json
            result = json.loads(content)
            return CVGenerationResponse(
                optimized_cv=result.get("optimized_cv", content),
                ats_score=result.get("ats_score", 85),
                suggestions=result.get("suggestions", [])
            )
        except:
            # Si pas de JSON, retourner le contenu brut
            return CVGenerationResponse(
                optimized_cv=content,
                ats_score=85,
                suggestions=["CV généré avec succès"]
            )
            
    except Exception as e:
        print(f"❌ Erreur OpenAI: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur génération CV: {str(e)}")

@app.post("/api/user/consume-credits", response_model=CreditConsumptionResponse)
async def consume_credits(request: CreditConsumptionRequest, user_id: str = Depends(verify_token)):
    """Consommer des crédits"""
    try:
        # Récupérer l'utilisateur
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
        
        user_data = user_doc.to_dict()
        current_credits = user_data.get('credits', 0)
        
        if current_credits < request.credits:
            raise HTTPException(status_code=400, detail="Crédits insuffisants")
        
        # Déduire les crédits
        new_credits = current_credits - request.credits
        user_ref.update({'credits': new_credits})
        
        # Enregistrer la transaction
        transaction_data = {
            'id': str(uuid.uuid4()),
            'user_id': user_id,
            'amount': request.credits,
            'credits_added': -request.credits,
            'created_at': datetime.utcnow().isoformat(),
            'type': 'consumption'
        }
        db.collection('transactions').add(transaction_data)
        
        return CreditConsumptionResponse(
            success=True,
            remaining_credits=new_credits,
            message=f"{request.credits} crédits consommés"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur consommation crédits: {str(e)}")

@app.get("/api/admin/users")
async def get_all_users():
    """Récupérer tous les utilisateurs (admin)"""
    try:
        users_ref = db.collection('users')
        users = users_ref.stream()
        
        users_list = []
        for user in users:
            user_data = user.to_dict()
            users_list.append(user_data)
        
        # Récupérer les transactions
        transactions_ref = db.collection('transactions')
        transactions = transactions_ref.stream()
        
        transactions_list = []
        for trans in transactions:
            trans_data = trans.to_dict()
            transactions_list.append(trans_data)
        
        return {
            "users": users_list,
            "transactions": transactions_list,
            "statistics": {
                "total_users": len(users_list),
                "total_credits_sold": sum(t.get('credits_added', 0) for t in transactions_list if t.get('type') == 'purchase'),
                "total_revenue": sum(t.get('amount', 0) for t in transactions_list if t.get('type') == 'purchase'),
                "total_cvs_generated": len([t for t in transactions_list if t.get('type') == 'consumption'])
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur récupération utilisateurs: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
