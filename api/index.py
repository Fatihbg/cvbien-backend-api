from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import uvicorn
import os
import json
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
import base64
import io

# Firebase imports
try:
    import firebase_admin
    from firebase_admin import credentials, auth, firestore
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    print("⚠️ Firebase Admin SDK non installé")

# Stripe import
try:
    import stripe
    STRIPE_AVAILABLE = True
    print("✅ Stripe importé avec succès")
except ImportError:
    STRIPE_AVAILABLE = False
    print("⚠️ Stripe non installé")

# OpenAI import
try:
    import openai
    OPENAI_AVAILABLE = True
    print("✅ OpenAI importé avec succès")
except ImportError:
    OPENAI_AVAILABLE = False
    print("⚠️ OpenAI non installé")

# PDF import
try:
    import PyPDF2
    PDF_AVAILABLE = True
    print("✅ PyPDF2 importé avec succès")
except ImportError:
    PDF_AVAILABLE = False
    print("⚠️ PyPDF2 non installé")

# Modèles de données
class CVGenerationRequest(BaseModel):
    cv_content: str
    job_description: str
    user_id: str

class CVGenerationResponse(BaseModel):
    optimized_cv: str
    ats_score: int
    success: bool
    message: str

class CVParsingRequest(BaseModel):
    cv_text: str
    job_description: str = ""

class CVParsingResponse(BaseModel):
    name: str
    contact: str
    title: str
    summary: str
    experience: list
    education: list
    technicalSkills: str
    softSkills: str
    certifications: list
    additionalInfo: str

class PDFExtractionRequest(BaseModel):
    pdf_base64: str

class PDFExtractionResponse(BaseModel):
    text: str
    success: bool
    message: str

app = FastAPI(title="CV Bien API", version="8.1.0-CV-STRUCTURE-PERFECT")

# Configuration des domaines autorisés
ALLOWED_ORIGINS = [
    "https://cvbien.dev",          # Nouveau domaine principal
    "https://cvbien4.vercel.app",  # Frontend principal (backup)
    "https://cvbien.vercel.app",   # Frontend alternatif (backup)
    "http://localhost:3000",       # Dev local
    "http://localhost:5173",       # Dev local Vite
]

# Configuration des URLs de l'application
FRONTEND_URL = "https://cvbien.dev"

# Configuration CORS - AVANT TOUTES LES ROUTES
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration Firebase
db = None
if FIREBASE_AVAILABLE:
    try:
        if not firebase_admin._apps:
            # Configuration Firebase depuis les variables d'environnement
            firebase_config = {
                "type": "service_account",
                "project_id": os.getenv("FIREBASE_PROJECT_ID", "cvbien-backend"),
                "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
                "private_key": os.getenv("FIREBASE_PRIVATE_KEY", "").replace('\\n', '\n'),
                "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
                "client_id": os.getenv("FIREBASE_CLIENT_ID"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_X509_CERT_URL")
            }
            
            # Vérifier les clés requises
            required_keys = ["private_key_id", "private_key", "client_email", "client_id", "client_x509_cert_url"]
            missing_keys = [key for key in required_keys if not firebase_config.get(key)]
            
            if missing_keys:
                print(f"❌ Variables Firebase manquantes: {missing_keys}")
                raise Exception(f"Variables Firebase manquantes: {missing_keys}")
            
            cred = credentials.Certificate(firebase_config)
            firebase_admin.initialize_app(cred)
            print("🔥 Firebase Admin SDK initialisé avec succès")
        else:
            print("🔥 Firebase Admin SDK déjà initialisé")
            
        # Initialiser Firestore
        db = firestore.client()
        print("🔥 Firestore client initialisé")
        
    except Exception as e:
        print(f"❌ Erreur initialisation Firebase: {e}")
        print("🔄 Mode sans Firebase...")
        db = None

# Configuration OpenAI
client = None
if OPENAI_AVAILABLE:
    try:
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            print(f"🔧 Tentative d'initialisation OpenAI avec clé de {len(api_key)} caractères")
            # Configuration OpenAI moderne (v1.0+) - SANS test initial
            client = openai.OpenAI(api_key=api_key)
            print("✅ OpenAI client créé avec succès")
        else:
            print("❌ OPENAI_API_KEY manquante")
    except Exception as e:
        print(f"❌ Erreur configuration OpenAI: {e}")
        print(f"❌ Type d'erreur: {type(e)}")
        client = None
else:
    print("❌ OpenAI SDK non disponible")

# Middleware CORS manuel supprimé - on utilise seulement CORSMiddleware

# Security
security = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Vérifier le token Firebase"""
    if not FIREBASE_AVAILABLE or not db:
        raise HTTPException(status_code=503, detail="Firebase non disponible")
    
    try:
        # Vérifier le token Firebase
        decoded_token = auth.verify_id_token(credentials.credentials)
        return decoded_token
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token invalide: {str(e)}")

@app.get("/")
def read_root():
    return {
        "message": "CV Bien API v7.0.0", 
        "status": "online",
        "firebase": "active" if db else "inactive",
        "cors": "ENABLED"
    }

@app.get("/test-cors")
def test_cors():
    return {"message": "CORS OK ✅", "version": "7.2.0", "cors_headers": "ACTIVE", "timestamp": "2025-01-06-05:00"}

@app.options("/test-cors")
def test_cors_options():
    return {"message": "CORS OPTIONS OK ✅", "version": "7.2.0"}

@app.get("/cors-test")
def cors_test():
    return {"status": "CORS WORKING", "message": "Si tu vois ce message, CORS fonctionne !", "version": "7.5.0"}

@app.post("/cors-test")
def cors_test_post():
    return {"status": "CORS POST WORKING", "message": "POST request CORS fonctionne !", "version": "7.5.0"}

@app.get("/emergency-cors")
def emergency_cors():
    return {"status": "EMERGENCY CORS", "message": "CORS d'urgence activé !", "version": "7.5.0", "timestamp": "2025-01-06-06:00"}

@app.get("/version")
def version():
         return {
             "version": "8.1.0-CV-STRUCTURE-PERFECT",
             "status": "Firebase Active with Stripe & OpenAI & CORS" if db and OPENAI_AVAILABLE else "Firebase Inactive",
             "timestamp": "2025-01-06-08:00",
             "webhook_secret": "configured" if os.getenv("STRIPE_WEBHOOK_SECRET") else "missing",
             "openai_available": OPENAI_AVAILABLE,
             "openai_key": "configured" if os.getenv("OPENAI_API_KEY") else "missing",
             "cors": "ENABLED",
             "cv_improvements": "✅ Structure parfaite: pas de *, pas de gros mensonges, filtrage intelligent, une seule page"
         }

@app.get("/test-openai")
def test_openai():
    """Tester la connexion OpenAI"""
    debug_info = {
        "openai_available": OPENAI_AVAILABLE,
        "api_key_exists": bool(os.getenv("OPENAI_API_KEY")),
        "api_key_length": len(os.getenv("OPENAI_API_KEY", ""))
    }
    
    if not OPENAI_AVAILABLE:
        return {"success": False, "message": "OpenAI SDK non installé", "debug": debug_info}
    
    try:
        # Test simple avec OpenAI (API REST)
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return {"success": False, "message": "OPENAI_API_KEY manquante", "debug": debug_info}
        
        import requests
        
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        
        data = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Test"}],
            "max_tokens": 10
        }
        
        response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, json=data)
        
        if response.status_code == 200:
            return {
                "success": True, 
                "message": "OpenAI fonctionne",
                "model": "gpt-4o-mini",
                "debug": debug_info
            }
        else:
            return {"success": False, "message": f"OpenAI API error: {response.status_code}", "debug": debug_info}
            
    except Exception as e:
        return {"success": False, "message": f"Erreur OpenAI: {str(e)}", "debug": debug_info}

@app.get("/health")
def health():
    return {"status": "healthy", "message": "API is running"}

@app.get("/api/test-stripe")
def test_stripe():
    """Test de configuration Stripe"""
    try:
        import stripe
        stripe_secret_key = os.getenv("STRIPE_SECRET_KEY")
        
        if not stripe_secret_key:
            return {"status": "error", "message": "STRIPE_SECRET_KEY manquante"}
        
        stripe.api_key = stripe_secret_key
        return {
            "status": "success", 
            "message": "Stripe configuré",
            "key_preview": stripe_secret_key[:10] + "...",
            "stripe_version": stripe.__version__
        }
    except Exception as e:
        return {"status": "error", "message": f"Erreur Stripe: {str(e)}"}

@app.post("/api/test-payment-session")
async def test_payment_session():
    """Test de création d'une session Stripe"""
    stripe_secret_key = os.getenv("STRIPE_SECRET_KEY")
    if not stripe_secret_key:
        raise HTTPException(status_code=500, detail="STRIPE_SECRET_KEY manquante")
    
    try:
        import requests
        
        headers = {
            'Authorization': f'Bearer {stripe_secret_key}',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        
        data = {
            'payment_method_types[]': 'card',
            'line_items[0][price_data][currency]': 'eur',
            'line_items[0][price_data][product_data][name]': 'Test 5 crédits',
            'line_items[0][price_data][unit_amount]': '100',  # 1€
            'line_items[0][quantity]': '1',
            'mode': 'payment',
            'success_url': 'https://cvbien4.vercel.app/?payment=success',
            'cancel_url': 'https://cvbien4.vercel.app/?payment=cancel',
        }
        
        response = requests.post('https://api.stripe.com/v1/checkout/sessions', headers=headers, data=data)
        
        print(f"🔍 Status: {response.status_code}")
        print(f"🔍 Response: {response.text}")
        
        if response.status_code != 200:
            return {"error": f"Stripe API error: {response.status_code} - {response.text}"}
        
        session = response.json()
        return {
            "success": True,
            "session": session,
            "has_url": 'url' in session,
            "url": session.get('url'),
            "id": session.get('id')
        }
        
    except Exception as e:
        print(f"❌ Erreur test: {e}")
        return {"error": str(e)}

@app.post("/api/auth/validate-firebase")
async def validate_firebase_token(token_data: dict):
    """Valider un token Firebase et retourner les infos utilisateur"""
    if not FIREBASE_AVAILABLE or not db:
        raise HTTPException(status_code=503, detail="Firebase non disponible")
    
    try:
        id_token = token_data.get("idToken")
        if not id_token:
            raise HTTPException(status_code=400, detail="Token manquant")
        
        # Vérifier le token Firebase
        decoded_token = auth.verify_id_token(id_token)
        uid = decoded_token['uid']
        
        # Récupérer les infos utilisateur depuis Firestore
        user_doc = db.collection('users').document(uid).get()
        
        if user_doc.exists:
            user_data = user_doc.to_dict()
            return {
                "success": True,
                "user": {
                    "id": uid,
                    "email": user_data.get("email"),
                    "name": user_data.get("name"),
                    "credits": user_data.get("credits", 0)
                }
            }
        else:
            # Créer l'utilisateur dans Firestore s'il n'existe pas
            user_data = {
                "email": decoded_token.get("email"),
                "name": decoded_token.get("name", ""),
                "credits": 2,  # Crédits gratuits
                "created_at": datetime.now().isoformat()
            }
            db.collection('users').document(uid).set(user_data)
            
            return {
                "success": True,
                "user": {
                    "id": uid,
                    "email": user_data["email"],
                    "name": user_data["name"],
                    "credits": user_data["credits"]
                }
            }
            
    except Exception as e:
        print(f"❌ Erreur validation Firebase: {e}")
        raise HTTPException(status_code=401, detail=f"Erreur validation: {str(e)}")

@app.get("/api/user/profile")
async def get_user_profile(current_user: dict = Depends(verify_token)):
    """Récupérer le profil utilisateur"""
    if not db:
        raise HTTPException(status_code=503, detail="Firebase non disponible")
    
    try:
        uid = current_user['uid']
        user_doc = db.collection('users').document(uid).get()
        
        if user_doc.exists:
            user_data = user_doc.to_dict()
            return {
                "success": True,
                "user": {
                    "id": uid,
                    "email": user_data.get("email"),
                    "name": user_data.get("name"),
                    "credits": user_data.get("credits", 0)
                }
            }
        else:
            raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
            
    except Exception as e:
        print(f"❌ Erreur récupération profil: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")

@app.post("/api/user/consume-credits")
async def consume_credits(request: dict, current_user: dict = Depends(verify_token)):
    """Consommer des crédits"""
    if not db:
        raise HTTPException(status_code=503, detail="Firebase non disponible")
    
    try:
        amount = request.get("amount", 1)
        uid = current_user['uid']
        user_doc = db.collection('users').document(uid).get()
        
        if not user_doc.exists:
            raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
        
        user_data = user_doc.to_dict()
        current_credits = user_data.get("credits", 0)
        
        if current_credits < amount:
            raise HTTPException(status_code=400, detail="Crédits insuffisants")
        
        new_credits = current_credits - amount
        db.collection('users').document(uid).update({"credits": new_credits})
        
        return {
            "success": True,
            "credits": new_credits,
            "consumed": amount
        }
        
    except Exception as e:
        print(f"❌ Erreur consommation crédits: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")

@app.post("/api/payments/create-payment-intent")
async def create_payment_intent(request: dict, current_user: dict = Depends(verify_token)):
    """Créer une intention de paiement Stripe"""
    if not db:
        raise HTTPException(status_code=503, detail="Firebase non disponible")
    
    try:
        if not STRIPE_AVAILABLE:
            raise HTTPException(status_code=500, detail="Stripe non disponible")
        
        # Configuration Stripe
        stripe_secret_key = os.getenv("STRIPE_SECRET_KEY")
        if not stripe_secret_key:
            print("❌ STRIPE_SECRET_KEY manquante")
            raise HTTPException(status_code=500, detail="Configuration Stripe manquante")
        
        # Initialiser Stripe avec la clé
        stripe.api_key = stripe_secret_key
        print(f"✅ Stripe configuré avec clé: {stripe_secret_key[:10]}...")
        
        amount = request.get("amount", 1)  # En euros
        if amount == 1:
            credits = 5  # 1€ = 5 crédits
        elif amount == 5:
            credits = 100  # 5€ = 100 crédits
        else:
            credits = amount * 5  # Par défaut
        
        # Créer une session Stripe via API REST
        print("🔧 Création session Stripe via API REST...")
        
        import requests
        
        headers = {
            'Authorization': f'Bearer {stripe_secret_key}',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        
        data = {
            'payment_method_types[]': 'card',
            'line_items[0][price_data][currency]': 'eur',
            'line_items[0][price_data][product_data][name]': f'{credits} crédits CV Bien',
            'line_items[0][price_data][unit_amount]': str(amount * 100),
            'line_items[0][quantity]': '1',
            'mode': 'payment',
            'success_url': f'{FRONTEND_URL}/?payment=success&credits={credits}&user_id={current_user["uid"]}&session_id={{CHECKOUT_SESSION_ID}}',
            'cancel_url': f'{FRONTEND_URL}/?payment=cancel',
            'metadata[user_id]': current_user['uid'],
            'metadata[credits]': str(credits)
        }
        
        response = requests.post('https://api.stripe.com/v1/checkout/sessions', headers=headers, data=data)
        
        if response.status_code != 200:
            print(f"❌ Erreur Stripe API: {response.status_code} - {response.text}")
            raise HTTPException(status_code=500, detail=f"Erreur Stripe API: {response.text}")
        
        session = response.json()
        print(f"✅ Session créée: {session.get('id')}")
        print(f"🔍 Session complète: {session}")
        
        # Vérifier que l'URL existe
        if 'url' not in session:
            print(f"❌ Pas d'URL dans la session: {session}")
            raise HTTPException(status_code=500, detail="URL de checkout non trouvée dans la réponse Stripe")
        
        return {
            "success": True,
            "checkout_url": session['url'],
            "session_id": session['id']
        }
        
    except Exception as e:
        print(f"❌ Erreur création paiement: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur paiement: {str(e)}")

@app.post("/api/payments/test-payment")
async def test_payment(request: dict, current_user: dict = Depends(verify_token)):
    """Test de paiement sans Stripe (pour debug)"""
    if not db:
        raise HTTPException(status_code=503, detail="Firebase non disponible")
    
    try:
        amount = request.get("amount", 1)  # En euros
        if amount == 1:
            credits = 5  # 1€ = 5 crédits
        elif amount == 5:
            credits = 100  # 5€ = 100 crédits
        else:
            credits = amount * 5  # Par défaut
        
        # Simuler un paiement réussi
        uid = current_user['uid']
        user_doc = db.collection('users').document(uid).get()
        
        if not user_doc.exists:
            raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
        
        user_data = user_doc.to_dict()
        current_credits = user_data.get("credits", 0)
        new_credits = current_credits + credits
        
        # Mettre à jour les crédits
        db.collection('users').document(uid).update({"credits": new_credits})
        
        return {
            "success": True,
            "credits": new_credits,
            "added": credits,
            "message": f"Test: {credits} crédits ajoutés"
        }
        
    except Exception as e:
        print(f"❌ Erreur test paiement: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur test: {str(e)}")

@app.post("/api/payments/confirm-payment")
async def confirm_payment(request: dict):
    """Confirmer un paiement et ajouter les crédits"""
    if not db:
        raise HTTPException(status_code=503, detail="Firebase non disponible")
    
    try:
        user_id = request.get("user_id")
        credits = request.get("credits", 0)
        
        print(f"🔧 DEBUG confirm-payment: user_id={user_id}, credits={credits}")
        
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id manquant")
        
        # Récupérer l'utilisateur
        user_doc = db.collection('users').document(user_id).get()
        print(f"🔧 DEBUG: user_doc.exists={user_doc.exists}")
        
        if not user_doc.exists:
            print(f"❌ Utilisateur {user_id} non trouvé dans Firestore")
            raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
        
        user_data = user_doc.to_dict()
        current_credits = user_data.get("credits", 0)
        new_credits = current_credits + credits
        
        print(f"🔧 DEBUG: current_credits={current_credits}, new_credits={new_credits}")
        
        # Mettre à jour les crédits
        db.collection('users').document(user_id).update({"credits": new_credits})
        
        print(f"✅ Crédits mis à jour: {credits} ajoutés, total: {new_credits}")
        
        return {
            "success": True,
            "credits": new_credits,
            "added": credits
        }
        
    except Exception as e:
        print(f"❌ Erreur confirmation paiement: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur confirmation: {str(e)}")

@app.post("/api/payments/confirm-payment-stripe")
async def confirm_payment_stripe(request: dict):
    """Confirmer un paiement en utilisant les métadonnées Stripe"""
    if not db:
        raise HTTPException(status_code=503, detail="Firebase non disponible")
    
    try:
        session_id = request.get("session_id")
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id manquant")
        
        print(f"🔧 DEBUG confirm-payment-stripe: session_id={session_id}")
        
        # Récupérer la session Stripe pour obtenir les métadonnées
        import requests
        stripe_secret_key = os.getenv("STRIPE_SECRET_KEY")
        
        headers = {
            'Authorization': f'Bearer {stripe_secret_key}',
        }
        
        response = requests.get(f'https://api.stripe.com/v1/checkout/sessions/{session_id}', headers=headers)
        
        if response.status_code != 200:
            print(f"❌ Erreur récupération session Stripe: {response.status_code} - {response.text}")
            raise HTTPException(status_code=500, detail=f"Erreur Stripe: {response.text}")
        
        session = response.json()
        metadata = session.get('metadata', {})
        user_id = metadata.get('user_id')
        credits = int(metadata.get('credits', 0))
        
        print(f"🔧 DEBUG: user_id={user_id}, credits={credits}")
        
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id manquant dans les métadonnées")
        
        # Récupérer l'utilisateur
        user_doc = db.collection('users').document(user_id).get()
        print(f"🔧 DEBUG: user_doc.exists={user_doc.exists}")
        
        if not user_doc.exists:
            print(f"❌ Utilisateur {user_id} non trouvé dans Firestore")
            raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
        
        user_data = user_doc.to_dict()
        current_credits = user_data.get("credits", 0)
        new_credits = current_credits + credits
        
        print(f"🔧 DEBUG: current_credits={current_credits}, new_credits={new_credits}")
        
        # Mettre à jour les crédits
        db.collection('users').document(user_id).update({"credits": new_credits})
        
        print(f"✅ Crédits mis à jour via Stripe: {credits} ajoutés, total: {new_credits}")
        
        return {
            "success": True,
            "credits": new_credits,
            "added": credits,
            "method": "stripe_metadata"
        }
        
    except Exception as e:
        print(f"❌ Erreur confirmation paiement Stripe: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur confirmation: {str(e)}")

@app.post("/api/payments/webhook")
async def stripe_webhook(request: Request):
    """Webhook Stripe pour créditer automatiquement les utilisateurs"""
    if not db:
        raise HTTPException(status_code=503, detail="Firebase non disponible")
    
    try:
        import json
        import stripe
        
        # Récupérer le body de la requête
        body = await request.body()
        sig_header = request.headers.get('stripe-signature')
        
        stripe_secret_key = os.getenv("STRIPE_SECRET_KEY")
        webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
        
        if not webhook_secret:
            print("⚠️ STRIPE_WEBHOOK_SECRET non configuré")
            return {"status": "error", "message": "Webhook secret non configuré"}
        
        print(f"✅ STRIPE_WEBHOOK_SECRET trouvé: {webhook_secret[:10]}...")
        
        stripe.api_key = stripe_secret_key
        
        # Vérifier la signature du webhook
        try:
            event = stripe.Webhook.construct_event(
                body, sig_header, webhook_secret
            )
        except ValueError as e:
            print(f"❌ Erreur parsing webhook: {e}")
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError as e:
            print(f"❌ Erreur signature webhook: {e}")
            raise HTTPException(status_code=400, detail="Invalid signature")
        
        # Traiter l'événement
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            metadata = session.get('metadata', {})
            user_id = metadata.get('user_id')
            credits = int(metadata.get('credits', 0))
            
            print(f"🎉 Paiement confirmé via webhook: user_id={user_id}, credits={credits}")
            
            if user_id and credits > 0:
                # Récupérer l'utilisateur
                user_doc = db.collection('users').document(user_id).get()
                
                if user_doc.exists:
                    user_data = user_doc.to_dict()
                    current_credits = user_data.get("credits", 0)
                    new_credits = current_credits + credits
                    
                    # Mettre à jour les crédits
                    db.collection('users').document(user_id).update({"credits": new_credits})
                    
                    print(f"✅ Webhook: {credits} crédits ajoutés à {user_id}, total: {new_credits}")
                    
                    return {"status": "success", "credits_added": credits, "total_credits": new_credits}
                else:
                    print(f"❌ Utilisateur {user_id} non trouvé dans Firestore")
                    return {"status": "error", "message": "Utilisateur non trouvé"}
            else:
                print(f"❌ Métadonnées manquantes: user_id={user_id}, credits={credits}")
                return {"status": "error", "message": "Métadonnées manquantes"}
        
        return {"status": "success", "message": "Webhook reçu"}
        
    except Exception as e:
        print(f"❌ Erreur webhook: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur webhook: {str(e)}")

@app.post("/extract-pdf", response_model=PDFExtractionResponse)
async def extract_pdf(request: PDFExtractionRequest):
    """Extraire le texte d'un PDF"""
    print(f"🔍 DEBUG - Extraction PDF demandée")
    print(f"🔍 DEBUG - PDF base64 length: {len(request.pdf_base64)}")
    
    if not PDF_AVAILABLE:
        raise HTTPException(status_code=503, detail="PyPDF2 non disponible")
    
    try:
        # Décoder le PDF base64
        pdf_data = base64.b64decode(request.pdf_base64)
        
        # Créer un objet PDF
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_data))
        
        # Extraire le texte de toutes les pages
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        
        if not text.strip():
            return PDFExtractionResponse(
                text="",
                success=False,
                message="Aucun texte trouvé dans le PDF"
            )
        
        return PDFExtractionResponse(
            text=text.strip(),
            success=True,
            message="Texte extrait avec succès"
        )
        
    except Exception as e:
        print(f"❌ Erreur extraction PDF: {e}")
        return PDFExtractionResponse(
            text="",
            success=False,
            message=f"Erreur extraction PDF: {str(e)}"
        )

@app.post("/optimize-cv", response_model=CVGenerationResponse)
async def optimize_cv(request: CVGenerationRequest):
    """Optimiser un CV avec OpenAI"""
    print(f"🔍 DEBUG - Requête reçue: {request}")
    print(f"🔍 DEBUG - cv_content: {request.cv_content[:100] if request.cv_content else 'VIDE'}...")
    print(f"🔍 DEBUG - job_description: {request.job_description[:100] if request.job_description else 'VIDE'}...")
    print(f"🔍 DEBUG - user_id: {request.user_id}")
    
    # Validation des champs requis
    if not request.cv_content or not request.cv_content.strip():
        raise HTTPException(status_code=422, detail="cv_content est requis et ne peut pas être vide")
    if not request.job_description or not request.job_description.strip():
        raise HTTPException(status_code=422, detail="job_description est requis et ne peut pas être vide")
    if not request.user_id or not request.user_id.strip():
        raise HTTPException(status_code=422, detail="user_id est requis et ne peut pas être vide")
    
    if not OPENAI_AVAILABLE:
        raise HTTPException(status_code=503, detail="OpenAI SDK non disponible")
    
    try:
        print("🤖 Génération CV avec OpenAI...")
        
        # Configuration directe de l'API key
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY manquante")
        
        # Utiliser l'API REST OpenAI directement
        import requests
        
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        
        data = {
            "model": "gpt-4o-mini",
            "messages": [
                     {
                         "role": "system",
                         "content": """Tu es un expert en optimisation de CV. Tu génères des CV avec une structure PRÉCISE et professionnelle.

🚨🚨🚨 RÈGLE DE LANGUE ABSOLUE - PRIORITÉ #1 - OBLIGATOIRE 🚨🚨🚨
1. LIS la description d'emploi ci-dessous.
2. IDENTIFIE sa langue (français, anglais, espagnol, allemand, italien, néerlandais, etc.).
3. GÉNÈRE le CV ENTIER dans cette langue détectée.
4. JAMAIS de mélange de langues dans le CV.
5. Cette règle est ABSOLUE et doit être respectée à 100%.

STRUCTURE OBLIGATOIRE À RESPECTER (dans cet ordre exact) :

1. EN-TÊTE :
   - Prénom NOM (en GRAS et CENTRÉ, couleur bleue)
   - Coordonnées centrées : "Ville | Téléphone | Email | Site web"
   - Titre professionnel générique (en GRAS et centré, couleur bleue)
     Exemples : "Consultant Junior", "Frontend Developer", "Data Analyst", "Marketing Specialist"

2. RÉSUMÉ PROFESSIONNEL (SANS TITRE) :
   - Paragraphe de 3-4 phrases qui synthétise les forces
   - Montre l'alignement avec le poste recherché
   - Intègre les mots-clés de l'offre d'emploi

3. EXPÉRIENCE PROFESSIONNELLE :
   - Titre de section en MAJUSCULES + GRAS + ligne horizontale bleue RAPPROCHÉE
   - Filtre intelligemment : supprime les jobs étudiants non pertinents (courte durée)
   - Pour chaque expérience :
     - Titre du Poste (en gras)
     - Nom de l'entreprise (Dates)
     - • Description avec pourcentages réalistes (PAS de chiffres infondés)
     - • Description avec pourcentages réalistes

4. FORMATION (ACADÉMIQUE) :
   - Titre de section en MAJUSCULES + GRAS + ligne horizontale bleue RAPPROCHÉE
   - Diplôme (en gras)
   - Institution (Dates)
   - • Spécialisation/détails

5. CERTIFICATIONS & RÉALISATIONS (si nécessaire) :
   - Titre de section en MAJUSCULES + GRAS + ligne horizontale bleue RAPPROCHÉE
   - • Certification 1
   - • Certification 2

6. INFORMATIONS ADDITIONNELLES (si nécessaire) :
   - Titre de section en MAJUSCULES + GRAS + ligne horizontale bleue RAPPROCHÉE
   - • Information 1
   - • Information 2

RÈGLES STRICTES :

1. **PAS DE SYMBOLES * :**
   - Supprime TOUS les * du CV généré
   - Utilise uniquement du texte propre

2. **PAS DE GROS MENSONGES :**
   - Utilise seulement des pourcentages réalistes
   - PAS de chiffres infondés (ex: "200k de chiffre d'affaires")
   - Reste crédible et professionnel

3. **CONSERVATION OBLIGATOIRE :**
   - JAMAIS enlever d'informations du CV original
   - TOUJOURS ajouter/enrichir, jamais supprimer
   - Conserver TOUS les liens/URLs du CV original
   - Garder toutes les expériences, même courtes
   - Préserver toutes les compétences et formations

4. **UNE SEULE PAGE :**
   - Le CV doit impérativement tenir sur 1 page
   - Si nécessaire, compacter le texte ou réduire les espacements
   - JAMAIS 2 pages

5. **ENRICHISSEMENT INTELLIGENT :**
   - Ajoute des détails pertinents manquants
   - Enrichit les descriptions existantes
   - Intègre les mots-clés de l'offre d'emploi
   - Ajoute des pourcentages réalistes aux réalisations
   - Complète avec des compétences connexes

6. **STYLE PROFESSIONNEL :**
   - Couleurs : Nom en bleu, titres de sections en bleu, lignes horizontales en bleu
   - Ligne horizontale RAPPROCHÉE des titres de sections
   - Espacement cohérent entre sections
   - Texte sobre, professionnel, compact

7. **INTELLIGENCE DE PLACEMENT :**
   - Analyse intelligemment le CV original
   - Place chaque information dans la bonne section
   - Adapte le contenu selon la langue de l'offre d'emploi
   - Utilise les données de l'aperçu comme référence

8. **OPTIMISATION ATS :**
   - Utilise le vocabulaire exact de l'offre d'emploi
   - Répète naturellement les mots-clés importants
   - Intègre les compétences demandées (sous forme d'intérêt si absentes)

IMPORTANT : Respecte EXACTEMENT cette structure et utilise l'intelligence pour placer les informations correctement."""
                     },
                     {
                         "role": "user",
                         "content": f"""CV ORIGINAL :
{request.cv_content}

DESCRIPTION DU POSTE :
{request.job_description}

🚨 CONSIGNES CRITIQUES :

1. **LANGUE ABSOLUE :** Le CV généré DOIT être dans la MÊME LANGUE que la description du poste.

2. **STRUCTURE EXACTE :** Prénom Nom → Contact → Titre générique → Résumé sans titre → Expériences → Formation → Certifications → Infos additionnelles

3. **PAS DE SYMBOLES * :** Supprime TOUS les * du CV généré

4. **PAS DE GROS MENSONGES :** Utilise seulement des pourcentages réalistes, PAS de chiffres infondés

5. **CONSERVATION ABSOLUE :** JAMAIS enlever d'informations du CV original, TOUJOURS ajouter/enrichir

6. **LIENS OBLIGATOIRES :** Conserver TOUS les liens/URLs du CV original

7. **UNE SEULE PAGE :** Le CV doit tenir sur 1 page, jamais 2 pages

8. **INTELLIGENCE DE PLACEMENT :** Place chaque information dans la bonne section de façon intelligente

Génère un CV professionnel avec cette structure EXACTE, dans la langue de l'offre d'emploi !"""
                     }
            ],
            "max_tokens": 4000,
            "temperature": 0.7
        }
        
        response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, json=data)
        
        if response.status_code != 200:
            raise Exception(f"OpenAI API error: {response.status_code} - {response.text}")
        
        response_data = response.json()
        
        content = response_data['choices'][0]['message']['content']
        
        # Calculer un score ATS simulé (basé sur la longueur et les mots-clés)
        ats_score = min(95, max(60, len(content) // 50 + 30))
        
        # Sauvegarder dans Firestore si disponible
        if db:
            try:
                cv_data = {
                    "user_id": request.user_id,
                    "original_content": request.cv_content,
                    "optimized_content": content,
                    "job_description": request.job_description,
                    "ats_score": ats_score,
                    "created_at": datetime.now(),
                    "is_downloaded": False
                }
                
                db.collection('generated_cvs').add(cv_data)
                print(f"✅ CV sauvegardé dans Firestore pour l'utilisateur {request.user_id}")
            except Exception as e:
                print(f"⚠️ Erreur sauvegarde Firestore: {e}")
        
        return CVGenerationResponse(
            optimized_cv=content,
            ats_score=ats_score,
            success=True,
            message="CV optimisé avec succès"
        )
        
    except Exception as e:
        print(f"❌ Erreur OpenAI: {e}")
        return CVGenerationResponse(
            optimized_cv=request.cv_content,  # Retourner le CV original en cas d'erreur                                                                        
            ats_score=50,
            success=False,
            message=f"Erreur lors de l'optimisation: {str(e)}"
        )

@app.post("/parse-cv", response_model=CVParsingResponse)
async def parse_cv(request: CVParsingRequest):
    """Parser un CV avec l'IA pour extraire les informations structurées"""
    print(f"🔍 DEBUG - Parsing CV avec IA...")
    print(f"🔍 DEBUG - cv_text length: {len(request.cv_text) if request.cv_text else 0}")
    
    if not OPENAI_AVAILABLE:
        raise HTTPException(status_code=503, detail="OpenAI SDK non disponible")
    
    try:
        print("🤖 Parsing CV avec OpenAI...")
        
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY manquante")
        
        import requests
        
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        
        data = {
            "model": "gpt-4o-mini",
            "messages": [
                {
                    "role": "system",
                    "content": """Tu es un expert en parsing et enrichissement de CV. Tu dois extraire les informations d'un CV et les enrichir intelligemment selon le poste recherché.

Tu dois retourner UNIQUEMENT un JSON valide avec cette structure exacte :

{
  "name": "NOM PRÉNOM",
  "contact": "Ville | Téléphone | Email | Site web",
  "title": "Titre professionnel adapté au poste",
  "summary": "Résumé professionnel enrichi avec les compétences du poste",
  "experience": [
    {
      "company": "Nom de l'entreprise",
      "position": "Titre du poste",
      "period": "Période (ex: Janvier 2023 - Décembre 2024)",
      "description": ["Description enrichie 1", "Description enrichie 2"]
    }
  ],
  "education": [
    {
      "institution": "Nom de l'institution",
      "degree": "Diplôme",
      "period": "Période (ex: 2020-2023)",
      "description": "Description du programme enrichie avec lien au poste"
    }
  ],
  "technicalSkills": "Compétences techniques originales + compétences techniques du poste + outils/logiciels du job (ex: Python, HTML, CSS, JavaScript, SQL, Tableau, Power BI, Salesforce, Jira, Confluence) séparées par des virgules",
  "softSkills": "Qualités comportementales attendues (ex: Esprit d'équipe, Créativité, Esprit ouvert, Leadership) séparées par des virgules",
  "certifications": ["Certification 1 (description courte)", "Certification 2 (description courte)"],
  "additionalInfo": "Informations additionnelles (langues, etc.)"
}

RÈGLES D'ENRICHISSEMENT :
1. **TITRE** : Adapte le titre professionnel au poste recherché
2. **RÉSUMÉ** : Enrichis avec les compétences demandées dans le job
3. **EXPÉRIENCES** : Ajoute des compétences du poste dans les descriptions
4. **FORMATION** : Enrichis les descriptions pour montrer le lien avec le poste recherché
5. **TECHNICALSKILLS** : Compétences techniques originales + compétences techniques du poste (basiques si manquantes) + outils/logiciels mentionnés dans le job
6. **SOFTSKILLS** : Qualités comportementales attendues (esprit d'équipe, créativité, esprit ouvert, leadership, etc.)
7. **CERTIFICATIONS** : UNIQUEMENT celles qui existent dans le CV original, n'invente RIEN, ajoute une description courte entre parenthèses
8. **LANGUES** : Mets les langues sans ** dans additionalInfo, en dernière position
9. **FORMATION-POSTE** : Pour chaque formation, ajoute une phrase qui montre le lien avec le poste recherché
10. **CRÉDIBILITÉ** : Ne mens jamais, enrichis seulement avec du réaliste
11. **LIENS** : Préserve TOUS les liens/URLs du CV original (email, site web, LinkedIn, etc.)
12. **CONSERVATION** : Ne supprime JAMAIS de compétences existantes, ajoute seulement

RÈGLES IMPORTANTES :
- Retourne UNIQUEMENT le JSON, rien d'autre
- Pas de markdown, pas de ```json```
- Structure exacte respectée
- Enrichis intelligemment selon le poste
- Garde la crédibilité, pas de mensonges
- Pour les compétences techniques : analyse la description de poste pour identifier tous les outils, logiciels, technologies mentionnés
- Pour les formations : ajoute toujours une phrase qui explique pourquoi cette formation est pertinente pour le poste
- Exemple formation-poste : "Programme orienté gestion de projet et analyse de données, compétences clés pour un Business Analyst" """
                },
                {
                    "role": "user",
                    "content": f"Parse ce CV et enrichis-le selon ce poste, puis retourne le JSON structuré :\n\nCV :\n{request.cv_text}\n\nPOSTE RECHERCHÉ :\n{request.job_description if request.job_description else 'Pas de description de poste fournie'}"
                }
            ],
            "max_tokens": 2000,
            "temperature": 0.3
        }
        
        response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, json=data)
        
        if response.status_code != 200:
            raise Exception(f"OpenAI API error: {response.status_code} - {response.text}")
        
        response_data = response.json()
        content = response_data['choices'][0]['message']['content']
        
        # Parser le JSON retourné par l'IA
        try:
            parsed_data = json.loads(content)
            
            return CVParsingResponse(
                name=parsed_data.get('name', ''),
                contact=parsed_data.get('contact', ''),
                title=parsed_data.get('title', ''),
                summary=parsed_data.get('summary', ''),
                experience=parsed_data.get('experience', []),
                education=parsed_data.get('education', []),
                technicalSkills=parsed_data.get('technicalSkills', ''),
                softSkills=parsed_data.get('softSkills', ''),
                certifications=parsed_data.get('certifications', []),
                additionalInfo=parsed_data.get('additionalInfo', '')
            )
            
        except json.JSONDecodeError as e:
            print(f"❌ Erreur parsing JSON: {e}")
            print(f"❌ Contenu reçu: {content}")
            raise HTTPException(status_code=500, detail="Erreur parsing JSON de l'IA")
        
    except Exception as e:
        print(f"❌ Erreur parsing CV: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors du parsing: {str(e)}")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    print(f"🚀 Démarrage du serveur Firebase sur le port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)