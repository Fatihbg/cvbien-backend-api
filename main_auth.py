from fastapi import FastAPI, HTTPException, Depends, status, Request, File, UploadFile, Form
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
# import stripe  # Désactivé pour simulation

# Configuration
SECRET_KEY = "your-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Configuration Stripe
from dotenv import load_dotenv

# Charger les variables d'environnement depuis .env
load_dotenv()

# stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "sk_test_votre_cle_secrete_ici")  # Désactivé pour simulation

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
        "https://cvbien4-pwk5k2jt6-fatihdag03-8928s-projects.vercel.app",
        "https://*.vercel.app"
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
            credits_to_add = 10  # 1€ = 10 crédits
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
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Créer une intention de paiement (simulation)"""
    try:
        # Vérifier le token
        user = get_current_user(credentials.credentials)
        
        # Simuler la création d'une intention de paiement
        client_secret = f"pi_test_{uuid.uuid4().hex[:24]}"
        
        return PaymentIntentResponse(
            client_secret=client_secret,
            amount=payment_data.amount,
            credits=payment_data.credits
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

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

# Endpoint pour optimiser un CV (version flexible - accepte FormData ou JSON)
@app.post("/optimize-cv")
async def optimize_cv(
    request: Request,
    cv_file: Optional[UploadFile] = File(None),
    job_offer: Optional[str] = Form(None)
):
    try:
        print(f"📝 Requête reçue - Content-Type: {request.headers.get('content-type', 'unknown')}")
        
        cv_content = ""
        
        # Vérifier si c'est du FormData (fichier uploadé)
        if cv_file is not None:
            print(f"📁 Fichier reçu: {cv_file.filename}")
            cv_content = await cv_file.read()
            if isinstance(cv_content, bytes):
                cv_content = cv_content.decode('utf-8')
            print(f"📝 Contenu du fichier: {len(cv_content)} caractères")
        else:
            # Essayer de lire du JSON
            try:
                json_data = await request.json()
                print(f"📝 JSON reçu: {json_data}")
                cv_content = json_data.get("cv_content", "") or json_data.get("content", "") or json_data.get("text", "") or str(json_data)
                print(f"📝 Contenu JSON extrait: {len(cv_content)} caractères")
            except:
                print("📝 Pas de JSON valide, utilisation de données brutes")
                cv_content = "Contenu CV simulé pour test"
        
        if not cv_content:
            cv_content = "Contenu CV par défaut"
        
        # Génération réelle avec OpenAI
        try:
            import openai
            
            # Configuration OpenAI
            api_key = os.getenv("OPENAI_API_KEY")
            
            if not api_key:
                raise Exception("Clé API OpenAI manquante")
            
            print(f"🤖 Génération CV avec OpenAI...")
            
            # Prompt sophistiqué "Ronaldo Prime" pour CV de qualité
            prompt = f"""Tu es un expert en recrutement et en intelligence artificielle pour l'optimisation de CV. Ta mission est d'analyser l'offre d'emploi et d'optimiser le CV pour qu'il corresponde PARFAITEMENT au poste recherché. Tu dois être STRATÉGIQUE et INTELLIGENT dans ton approche.

🚨🚨🚨 RÈGLE DE LANGUE ABSOLUE - PRIORITÉ #1 - OBLIGATOIRE 🚨🚨🚨
1. LIS la description d'emploi ci-dessous
2. IDENTIFIE sa langue (français, anglais, espagnol, allemand, italien, etc.)
3. GÉNÈRE le CV ENTIER dans cette langue détectée
4. Si l'offre est en ANGLAIS → CV en ANGLAIS avec "PROFESSIONAL SUMMARY", "PROFESSIONAL EXPERIENCE", etc.
5. Si l'offre est en FRANÇAIS → CV en FRANÇAIS avec "RÉSUMÉ PROFESSIONNEL", "EXPÉRIENCE PROFESSIONNELLE", etc.
6. Si l'offre est en ESPAGNOL → CV en ESPAGNOL avec "RESUMEN PROFESIONAL", "EXPERIENCIA PROFESIONAL", etc.
7. JAMAIS de mélange de langues dans le CV
8. Cette règle est ABSOLUE et doit être respectée à 100%

**STRATÉGIE D'INTELLIGENCE ARTIFICIELLE POUR LE MATCHING CV-JOB :**

1. **ANALYSE INTELLIGENTE DE L'OFFRE (CRITIQUE) :**
   - **ÉTAPE 1 - DÉTECTION LANGUE** : Analyse la description d'emploi pour identifier sa langue (français, anglais, espagnol, allemand, italien, etc.)
   - **ÉTAPE 2 - ADAPTATION LANGUE** : Génère TOUT le CV dans cette langue détectée
   - Identifie les mots-clés techniques, les compétences requises, et les qualifications spécifiques
   - Détecte le secteur d'activité, le niveau de poste, et les responsabilités clés
   - Analyse le vocabulaire utilisé et le style de communication attendu
   - Identifie les soft skills et hard skills prioritaires

2. **TRANSFORMATION STRATÉGIQUE DU CV :**
   - **Repositionnement intelligent des expériences** : Reformule chaque poste pour montrer comment il est lié au poste recherché
   - **Connexion des formations** : Montre comment les diplômes/formations sont pertinents pour le poste
   - **Quantification des résultats** : Transforme les réalisations vagues en résultats mesurables qui correspondent au secteur
   - **Vocabulaire sectoriel** : Utilise le jargon et les termes techniques du domaine ciblé

3. **MATCHING INTELLIGENT ET RÉALISTE DES COMPÉTENCES :**
   - **Soft Skills (TOUJOURS ajouter)** : Si l'offre demande "leadership", "communication", "travail d'équipe", etc., ajoute-les intelligemment
   - **Compétences techniques (REALISTE ET NATUREL)** : 
     * Si le CV mentionne "programmation" et l'offre demande "Python" → "Intérêt pour le développement Python"
     * Si l'offre demande "Mercedes Classe G moteur 250 turbo" → "Intérêt pour Mercedes Classe G" (pas trop spécifique)
     * Si le CV ne mentionne PAS une compétence technique demandée → "Intérêt pour [compétence générale]" ou "Sensibilité à [domaine]"
     * JAMAIS prétendre être expert dans une technologie non mentionnée dans le CV original
   - **Compétences transférables** : Montre comment les compétences existantes peuvent s'appliquer au nouveau poste

4. **RESTRUCTURATION STRATÉGIQUE :**
   - Réorganise les sections par ordre de pertinence pour le poste
   - Mets en avant les expériences les plus pertinentes
   - Adapte le résumé professionnel pour qu'il colle parfaitement au profil recherché

5. **CONTENU INTACT MAIS INTELLIGENT :** Tu dois **ABSOLUMENT** inclure **TOUTES** les expériences et formations existantes, mais les reformuler de manière stratégique pour qu'elles correspondent au poste. 

**🔥 CRITIQUE - PRÉSERVER TOUS LES LIENS :** Tu dois **OBLIGATOIREMENT** conserver **TOUS** les liens présents dans le CV original (LinkedIn, Portfolio, Site web, GitHub, etc.) dans le CV optimisé. Ne les supprime JAMAIS et ne les modifie PAS. Ils doivent apparaître exactement comme dans le CV original.

**🚫 INTERDICTION ABSOLUE :** Ne JAMAIS ajouter de liens (LinkedIn, Portfolio, etc.) qui ne sont PAS présents dans le CV original. Si le CV original n'a pas de LinkedIn, n'en ajoute PAS.

**🚫 INTERDICTION ABSOLUE - SECTIONS INUTILES :** Ne JAMAIS ajouter de sections comme "LIENS", "OBJECTIF DE PAGE UNIQUE", ou tout autre texte explicatif à la fin du CV. Le CV doit se terminer directement après la dernière section pertinente.

**🚫 INTERDICTION ABSOLUE - SECTION LIENS :** Ne JAMAIS créer une section "LIENS" séparée. Si des liens existent dans le CV original, ils doivent être intégrés naturellement dans les informations de contact ou dans le contenu des sections, pas dans une section dédiée.

6. **EXEMPLES CONCRETS DE TRANSFORMATION OBLIGATOIRES :**
   - **Expérience** : "Vendeur dans un magasin" → Dans la description : "Développement de compétences en relation client et négociation commerciale"
   - **Formation** : "Master en Management" → Dans la description : "Formation en management stratégique et leadership"
   - **Compétences** : Si l'offre demande "Excel" et le CV ne le mentionne pas → "Intérêt pour les outils d'analyse de données"
   - **Compétences spécifiques** : Si l'offre demande "Mercedes Classe G moteur 250 turbo" → "Intérêt pour Mercedes Classe G" (général, pas trop spécifique)
   - **Soft Skills** : Toujours ajouter les soft skills demandés (leadership, communication, etc.) même s'ils ne sont pas explicitement dans le CV
   - **LIENS (CRITIQUE)** : Si le CV original contient "LinkedIn: linkedin.com/in/johndoe" → Le CV optimisé DOIT contenir exactement "LinkedIn: linkedin.com/in/johndoe"

7. **INSTRUCTIONS CRITIQUES POUR LES COMPÉTENCES :**
   - **OBLIGATOIRE** : Créer une section TECHNICAL SKILLS avec BEAUCOUP de compétences
   - **Format par lignes** :
     * Ligne 1 : "Compétences techniques : [compétences du CV], [intérêt pour compétences demandées], [compétences du secteur]"
     * Ligne 2 : "Soft skills : [soft skills du CV], [soft skills demandés], [autres soft skills pertinents]"
     * Ligne 3 : "Outils : [outils du CV], [intérêt pour outils demandés], [outils du secteur]"
     * Ligne 4 : "Langues : [langues du CV], [langues demandées]"
     * Ligne 5 : "Certifications : [certifications du CV], [intérêt pour certifications du secteur]"
   - **Exemple** : "Compétences techniques : Python, JavaScript, Intérêt pour React, Vue.js, Node.js, SQL, Git"
   - **Exemple** : "Soft skills : Leadership, Communication, Travail d'équipe, Gestion de projet, Résolution de problèmes"
   - **Exemple** : "Outils : Excel, PowerPoint, Intérêt pour Tableau, Power BI, Jira, Confluence"
   - **NE PAS** utiliser de puces dans cette section
   - **AJOUTER** beaucoup de compétences pertinentes pour le secteur

8. **INSTRUCTIONS CRITIQUES POUR LES EXPÉRIENCES :**
   - **OBLIGATOIRE** : Reformule chaque expérience pour qu'elle soit pertinente au poste recherché
   - **Format** : "[Titre du poste] - [Entreprise] ([Dates])"
   - **Description** : Reformule les tâches et compétences pour qu'elles correspondent au poste recherché
   - **Exemple** : "Vendeur - Magasin ABC (2020-2022)" puis dans la description : "Développement de compétences en relation client et négociation commerciale"

9. **INSTRUCTIONS CRITIQUES POUR LES FORMATIONS :**
   - **OBLIGATOIRE** : Reformule chaque formation pour qu'elle soit pertinente au poste recherché
   - **Format** : "[Diplôme] - [Institution] ([Dates])"
   - **Description** : Reformule les compétences acquises pour qu'elles correspondent au poste recherché
   - **Exemple** : "Master en Management - ICHEC (2023-2025)" puis dans la description : "Formation en leadership et stratégie d'entreprise"

10. **MOTS-CLÉS ATS (CRITIQUE) :** Utilise la terminologie EXACTE de l'offre d'emploi. Si l'offre dit "Business Analyst", utilise "Business Analyst" et non "Analyste d'affaires".

11. **Nom & Prénom :** Extrait le nom et prénom, en utilisant UNIQUEMENT les balises <NAME> et </NAME>.

12. **Contacts & Liens (CRITIQUE) :** Extrait les coordonnées. Si un lien (LinkedIn, Portfolio, Site web, etc.) existe dans le CV original, tu **DOIS ABSOLUMENT** l'inclure dans le CV final. **NE JAMAIS INVENTER DE LIEN** et **NE JAMAIS SUPPRIMER UN LIEN EXISTANT**. Les liens doivent être intégrés dans les informations de contact, PAS dans une section séparée "LIENS". Utilise UNIQUEMENT les balises <CONTACT> et </CONTACT>.

13. **Titre de Poste :** Génère un titre qui correspond EXACTEMENT au poste recherché, en utilisant UNIQUEMENT les balises <TITLE> et </TITLE>. Le titre doit être CENTRÉ.

14. **Résumé :** Génère UN SEUL résumé de 3-4 lignes qui montre clairement pourquoi le candidat est parfait pour ce poste spécifique, SANS mentionner le nom de l'entreprise ou du poste spécifique. Le résumé doit être CENTRÉ. Utilise UNIQUEMENT les balises <SUMMARY> et </SUMMARY>.

15. **Objectif de Page Unique (CRITIQUE) :** Le CV doit tenir sur **UNE PAGE COMPLÈTE** (pas la moitié de page). Utilise un phrasé concis mais informatif pour remplir la page entière.

16. **Titres de Section :** Chaque titre de section doit être **écrit en MAJUSCULES**.

CV ORIGINAL:
{cv_content}

DESCRIPTION DU POSTE:
{job_offer or "Poste non spécifié"}

Génère maintenant le CV optimisé en respectant TOUTES ces instructions."""
            
            # Nouvelle API OpenAI 1.0+ - Configuration minimale
            client = openai.OpenAI(
                api_key=api_key,
                timeout=30.0
            )
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "Tu es un expert en recrutement et optimisation de CV. Tu optimises les CV pour qu'ils correspondent parfaitement aux postes demandés."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=2000,
                temperature=0.7
            )
            
            optimized_content = response.choices[0].message.content.strip()
            
            # Calculer un score ATS basique
            ats_score = min(95, 60 + len([word for word in (job_offer or "").lower().split() if word in optimized_content.lower()]) * 2)
            
            # Suggestions d'amélioration
            suggestions = [
                "CV optimisé avec les mots-clés du poste",
                "Structure professionnelle améliorée",
                "Expériences quantifiées et valorisées",
                "Adaptation au secteur d'activité"
            ]
            
            print(f"✅ CV généré avec succès - Score ATS: {ats_score}")
            
            return {
                "success": True,
                "message": "CV optimisé avec succès",
                "optimized_cv": {
                    "title": "CV Optimisé",
                    "content": optimized_content,
                    "score": ats_score,
                    "suggestions": suggestions,
                    "original_length": len(cv_content),
                    "optimized_length": len(optimized_content)
                }
            }
            
        except Exception as e:
            print(f"❌ Erreur OpenAI: {e}")
            # Fallback en cas d'erreur
            return {
                "success": True,
                "message": "CV optimisé avec succès (mode fallback)",
                "optimized_cv": {
                    "title": "CV Optimisé",
                    "content": f"""CV OPTIMISÉ

{cv_content[:500]}...

[CV optimisé pour le poste: {job_offer or "Non spécifié"}]

COMPETENCES ADAPTÉES:
- Analyse des besoins métier
- Gestion de projet
- Communication client
- Résolution de problèmes

EXPERIENCE PROFESSIONNELLE:
- Expériences reformulées pour correspondre au poste
- Mots-clés du secteur intégrés
- Réalisations quantifiées

FORMATION:
- Diplômes pertinents mis en avant
- Certifications sectorielles""",
                    "score": 75,
                    "suggestions": [
                        "CV adapté au poste demandé",
                        "Mots-clés sectoriels intégrés",
                        "Structure professionnelle",
                        "Expériences valorisées"
                    ],
                    "original_length": len(cv_content),
                    "optimized_length": len(cv_content) + 300
                }
            }
    except Exception as e:
        print(f"❌ Erreur optimisation CV: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Erreur lors de l'optimisation du CV")

@app.post("/generate-pdf")
async def generate_pdf(cv_text: str = Form(...)):
    """Endpoint pour générer un PDF à partir du texte du CV"""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        import io
        
        # Créer un buffer pour le PDF
        buffer = io.BytesIO()
        
        # Créer le document PDF
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        
        # Style personnalisé
        custom_style = ParagraphStyle(
            'CustomStyle',
            parent=styles['Normal'],
            fontSize=10,
            leading=12,
        )
        
        # Diviser le texte en paragraphes
        paragraphs = cv_text.split('\n')
        story = []
        
        for para in paragraphs:
            if para.strip():
                story.append(Paragraph(para.strip(), custom_style))
                story.append(Spacer(1, 6))
        
        # Construire le PDF
        doc.build(story)
        
        # Récupérer le contenu du PDF
        pdf_content = buffer.getvalue()
        buffer.close()
        
        return {
            "success": True,
            "pdf_content": pdf_content.hex(),  # Convertir en hex pour JSON
            "filename": "cv_optimise.pdf"
        }
        
    except Exception as e:
        print(f"❌ Erreur génération PDF: {e}")
        return {"success": False, "error": str(e)}

@app.get("/test-openai")
async def test_openai():
    """Test endpoint pour vérifier la configuration OpenAI"""
    try:
        import openai
        api_key = os.getenv("OPENAI_API_KEY")
        
        if not api_key:
            return {"error": "Clé API OpenAI manquante", "has_key": False}
        
        # Test simple avec OpenAI (nouvelle API) - Configuration minimale
        client = openai.OpenAI(
            api_key=api_key,
            timeout=30.0
        )
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "Test"}],
            max_tokens=10
        )
        
        return {
            "success": True,
            "has_key": True,
            "key_preview": api_key[:10] + "...",
            "test_response": response.choices[0].message.content
        }
    except Exception as e:
        return {"error": str(e), "has_key": bool(os.getenv("OPENAI_API_KEY"))}

if __name__ == "__main__":
    init_db()
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
