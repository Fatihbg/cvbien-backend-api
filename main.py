from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
import uvicorn
import os
import json
from datetime import datetime
from typing import Optional
import openai

# Firebase imports
try:
    import firebase_admin
    from firebase_admin import credentials, auth, firestore
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    print("⚠️ Firebase Admin SDK non installé")

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
        "version": "6.1.0",
        "status": "Firebase Active" if db else "Firebase Inactive",
        "timestamp": "2025-01-06-01:30"
    }

@app.get("/health")
def health():
    return {"status": "healthy", "message": "API is running"}

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
                "credits": 0,  # Nouveau compte sans crédits
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

# --- Endpoint pour génération CV ---
@app.post("/optimize-cv")
async def optimize_cv(request: dict):
    """
    Endpoint pour générer un CV optimisé avec les nouvelles instructions détaillées.
    """
    try:
        cv_content = request.get("cv_content", "")
        job_description = request.get("job_description", "")
        target_language = request.get("target_language", "french")
        instructions = request.get("instructions", "")
        
        print(f"🚀 Requête CV - Langue: {target_language}")
        print(f"📄 CV Content length: {len(cv_content)}")
        print(f"📋 Job Description length: {len(job_description)}")
        
        # Instructions détaillées pour l'IA
        detailed_instructions = """
Instructions de Traitement du Modèle (Pour l'IA): 
Objectif Principal : Adapter, reformuler et enrichir le CV actuel afin qu'il corresponde parfaitement à 100% aux exigences et au langage de l'offre d'emploi cible, positionnant le candidat comme le profil idéal.

Analyse Approfondie :
- Analyser le [Description d'Emploi Cible] pour identifier tous les mots-clés, les compétences techniques (hard skills), les qualités interpersonnelles (soft skills), les responsabilités et les exigences spécifiques (outils, méthodologies, certifications).
- Analyser le [CV Actuel Complet] pour extraire toutes les informations pertinentes (expériences, formations, compétences, etc.).
- S'assurer que 100% des informations du [CV Actuel Complet] sont conservées dans le nouveau CV, uniquement reformulées si nécessaire.

Harmonisation et Reformulation (Stratégie d'Adaptation) :
- Expériences Professionnelles : Pour chaque poste, réécrire les descriptions de responsabilités et d'accomplissements. Utiliser le langage et les mots-clés exacts trouvés dans l'offre d'emploi. Mettre l'accent sur les résultats (si possible, quantification) qui sont directement pertinents pour les fonctions listées dans l'offre cible. Chaque point doit sembler être une préparation directe au poste visé.
- Éducation/Formation : Reformuler les descriptions de cours, projets ou mémoires pour souligner leur lien avec le domaine ou les technologies mentionnées dans l'offre d'emploi.

Compétences Techniques (Hard Skills) :
- Intégrer tous les outils/technologies mentionnés dans l'offre.
- Règle du "Mensonge Blanc" : Si une compétence technique est demandée (ex. Python) et est absente du CV initial, l'ajouter avec une mention d'un niveau d'expertise de base ou intermédiaire (ex. "Bases solides en Python pour l'analyse de données" ou "Connaissance fonctionnelle de..."). NE PASinventer un niveau Expert si l'information n'est pas présente.

Soft Skills : Intégrer tous les soft skills mentionnés dans l'offre d'emploi (ex. "Proactif", "Esprit d'équipe", "Résolution de problèmes complexes") dans la section Compétences sans justification supplémentaire.

Rédaction des Éléments Clés :
- Résumé Professionnel (Objectif) : Rédiger un paragraphe de 3-4 lignes percutant. Il doit immédiatement positionner le candidat comme la personne idéale en citant directement les exigences et la culture de l'entreprise (si elle est mentionnée) et en mentionnant les années d'expérience pertinentes et les compétences clés demandées dans l'offre.

Structure et Mise en Forme (Pour l'Optimisation ATS) :
Le nouveau CV doit respecter la structure exacte suivante pour faciliter la lecture des systèmes de suivi des candidatures (ATS) et des recruteurs :

A. En-tête (Centré) :
- Prénom NOM (Taille de police plus grande)
- Informations de contact (Téléphone | E-mail | Lien LinkedIn/Portfolio) (Taille de police plus petite, centré)

B. Résumé Professionnel (Centré) :
- Le paragraphe rédigé selon l'instruction ci-dessus.

C. Expériences Professionnelles (Titre Alignement à Gauche) :
- Titre : EXPÉRIENCES PROFESSIONNELLES
- Format : [Intitulé du Poste] | [Nom de l'Entreprise] | [Dates]
- Liste à puces des responsabilités et réalisations reformulées.

D. Éducation et Formations (Titre Alignement à Gauche) :
- Titre : ÉDUCATION ET FORMATIONS
- Format : [Diplôme] | [Établissement] | [Dates]
- Liste des formations reformulées.

E. Compétences (Titre Alignement à Gauche) :
- Titre : COMPÉTENCES
- Sous-sections claires :
  - Hard Skills : Liste des technologies, outils, et méthodologies (y compris celles ajoutées via la règle du "Mensonge Blanc").
  - Soft Skills : Liste de tous les soft skills demandés dans l'offre.
  - Certifications/Projets : Toutes les certifications ou projets personnels/académiques mentionnés dans le CV initial. Pour chaque certification, ajouter une phrase explicative courte (ex: "Python Programming Certification (Certification professionnelle en programmation Python)").
  - Langues : Niveaux de langue.

F. Soft Skills (Titre Alignement à Gauche) :
- Titre : SOFT SKILLS
- Lister explicitement tous les soft skills demandés dans l'offre d'emploi avec des puces (ex: "• Leadership", "• Teamwork", "• Proactive", "• Analytical skills").

Livrable : Le nouveau CV rédigé intégralement, structuré selon le format A-B-C-D-E, prêt à être copié/collé dans un document de mise en page. Ne pas fournir d'explication, seulement le CV final.
        """
        
        # Configuration OpenAI
        openai.api_key = os.getenv("OPENAI_API_KEY")
        
        if not openai.api_key:
            print("⚠️ OpenAI API Key non configurée, retour du CV original")
            return JSONResponse({
                "success": True,
                "optimized_cv": cv_content,
                "ats_score": 75,
                "message": "CV retourné sans optimisation (OpenAI non configuré)"
            })
        
        # Prompts selon la langue
        language_prompts = {
            "french": f"""
{detailed_instructions}

CV ACTUEL COMPLET:
{cv_content}

DESCRIPTION D'EMPLOI CIBLE:
{job_description}

Génère le nouveau CV optimisé selon les instructions ci-dessus, en français.
""",
            "english": f"""
{detailed_instructions}

CURRENT COMPLETE CV:
{cv_content}

TARGET JOB DESCRIPTION:
{job_description}

Generate the optimized CV according to the instructions above, in English.
""",
            "dutch": f"""
{detailed_instructions}

HUIDIGE VOLLEDIGE CV:
{cv_content}

DOELSTELLING FUNCTIEBESCHRIJVING:
{job_description}

Genereer de geoptimaliseerde CV volgens de bovenstaande instructies, in het Nederlands.
"""
        }
        
        prompt = language_prompts.get(target_language, language_prompts["french"])
        
        try:
            # Appel à l'API OpenAI
            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "Tu es un expert en recrutement et optimisation de CV. Tu adaptes parfaitement les CV aux offres d'emploi en respectant scrupuleusement toutes les instructions fournies."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=4000,
                temperature=0.7
            )
            
            optimized_cv = response.choices[0].message.content.strip()
            
            # Calculer un score ATS réaliste
            ats_score = calculate_ats_score(optimized_cv, job_description)
            
            print(f"✅ CV optimisé généré - Score ATS: {ats_score}")
            
            return JSONResponse({
                "success": True,
                "optimized_cv": optimized_cv,
                "ats_score": ats_score,
                "message": "CV optimisé avec succès selon les nouvelles instructions"
            })
            
        except Exception as openai_error:
            print(f"❌ Erreur OpenAI: {openai_error}")
            # Fallback: retourner le CV original
            return JSONResponse({
                "success": True,
                "optimized_cv": cv_content,
                "ats_score": 75,
                "message": "CV retourné sans optimisation (erreur OpenAI)"
            })
        
    except Exception as e:
        print(f"❌ Erreur optimisation CV: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"Erreur: {str(e)}"
            }
        )

def calculate_ats_score(cv_content: str, job_description: str) -> int:
    """Calculer un score ATS réaliste basé sur la correspondance des mots-clés"""
    try:
        # Extraire les mots-clés de l'offre d'emploi
        job_keywords = set()
        job_lower = job_description.lower()
        
        # Mots-clés techniques communs
        tech_keywords = ['python', 'javascript', 'react', 'node', 'sql', 'excel', 'powerpoint', 'leadership', 'management', 'communication', 'project', 'team', 'analysis', 'data', 'development', 'design']
        
        for keyword in tech_keywords:
            if keyword in job_lower:
                job_keywords.add(keyword)
        
        # Extraire les mots-clés du CV
        cv_keywords = set()
        cv_lower = cv_content.lower()
        
        for keyword in tech_keywords:
            if keyword in cv_lower:
                cv_keywords.add(keyword)
        
        # Calculer le score de correspondance
        if len(job_keywords) == 0:
            return 80  # Score par défaut si pas de mots-clés détectés
        
        match_count = len(job_keywords.intersection(cv_keywords))
        match_percentage = (match_count / len(job_keywords)) * 100
        
        # Bonus pour la structure
        structure_bonus = 0
        if 'experience' in cv_lower or 'expérience' in cv_lower:
            structure_bonus += 10
        if 'education' in cv_lower or 'formation' in cv_lower:
            structure_bonus += 10
        if 'skills' in cv_lower or 'compétences' in cv_lower:
            structure_bonus += 10
        if '@' in cv_content:  # Email
            structure_bonus += 5
        
        final_score = min(100, match_percentage + structure_bonus)
        return max(70, int(final_score))  # Score minimum de 70
        
    except Exception as e:
        print(f"❌ Erreur calcul score ATS: {e}")
        return 80  # Score par défaut

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    print(f"🚀 Démarrage du serveur Firebase sur le port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)