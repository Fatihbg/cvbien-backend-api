from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import uvicorn
import os
import json
from datetime import datetime
from typing import Optional

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

app = FastAPI(title="CV Bien API", version="6.1.0")

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
        "message": "CV Bien API v6.1.0", 
        "status": "online",
        "firebase": "active" if db else "inactive"
    }

@app.get("/version")
def version():
    return {
        "version": "6.3.0",
        "status": "Firebase Active with Stripe" if db else "Firebase Inactive",
        "timestamp": "2025-01-06-02:30",
        "webhook_secret": "configured" if os.getenv("STRIPE_WEBHOOK_SECRET") else "missing"
    }

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
            'success_url': f'https://cvbien4.vercel.app/?payment=success&credits={credits}&user_id={current_user["uid"]}&session_id={{CHECKOUT_SESSION_ID}}',
            'cancel_url': 'https://cvbien4.vercel.app/?payment=cancel',
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

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    print(f"🚀 Démarrage du serveur Firebase sur le port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)