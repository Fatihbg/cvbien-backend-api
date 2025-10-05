# pylint: disable=import-error
from fastapi import FastAPI, UploadFile, File, Form, HTTPException  # type: ignore
from fastapi.responses import Response  # type: ignore
from fastapi.middleware.cors import CORSMiddleware  # type: ignore
from io import BytesIO
import re
from openai import OpenAI as OAI_Client  # type: ignore
import tempfile
import os
import stripe  # type: ignore
from pydantic import BaseModel  # type: ignore
from dotenv import load_dotenv  # type: ignore

# Charger les variables d'environnement
load_dotenv()

# --- CLASSE DE LIGNE HORIZONTALE ---
from reportlab.platypus import Flowable  # type: ignore

class HRLine(Flowable):
    """Dessine une ligne horizontale sur toute la largeur."""
    def __init__(self, width=None, thickness=0.5, color=None):
        Flowable.__init__(self)
        self.width = width
        self.thickness = thickness
        self.color = color

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        return availWidth, self.thickness

    def draw(self):
        from reportlab.lib.colors import black  # type: ignore
        self.canv.setStrokeColor(self.color or black)
        self.canv.setLineWidth(self.thickness)
        self.canv.line(0, 0, self.width, 0)

# ------------------------------------------------------------------

# --- Configuration de l'API ---
app = FastAPI(title="CV Optimizer API V16 - ATS Scoring Ready")

# Configuration Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
if not stripe.api_key:
    print("⚠️  ATTENTION: STRIPE_SECRET_KEY non trouvée dans .env")
else:
    print("✅ Stripe configuré avec clé réelle")

# Modèles Pydantic pour les paiements
class PaymentIntentRequest(BaseModel):
    amount: int  # en centimes
    credits: int

class PaymentIntentResponse(BaseModel):
    client_secret: str
    amount: int
    credits: int

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Utilisation de la clé fournie
OAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
client = OAI_Client(api_key=OAI_API_KEY)
GPT_MODEL = "gpt-4o"

# --- Constantes pour le parsing IA ---
START_NAME_TAG = "<NAME>"
END_NAME_TAG = "</NAME>"
START_CONTACT_TAG = "<CONTACT>"
END_CONTACT_TAG = "</CONTACT>"
START_TITLE_TAG = "<TITLE>"
END_TITLE_TAG = "</TITLE>"
START_SUMMARY_TAG = "<SUMMARY>"
END_SUMMARY_TAG = "</SUMMARY>"
BOLD_TAG_START = "<B>"
BOLD_TAG_END = "</B>"

# --- Fonctions utilitaires ---

def extract_text_from_txt(txt_content: str) -> str:
    """Extrait le texte d'un fichier TXT."""
    return txt_content

def parse_optimized_cv(cv_text: str) -> dict:
    """Parse le CV optimisé du frontend pour extraire les sections avec IA."""
    print(f"🔍 CV reçu du frontend (premiers 200 caractères): {cv_text[:200]}")
    
    # Initialiser les variables
    name = ""
    contact = ""
    title = ""
    summary = ""
    body = ""
    
    # Parser les balises du frontend d'abord
    name_match = re.search(f"{START_NAME_TAG}(.*?){END_NAME_TAG}", cv_text, re.DOTALL)
    if name_match:
        name = name_match.group(1).strip()
    
    contact_match = re.search(f"{START_CONTACT_TAG}(.*?){END_CONTACT_TAG}", cv_text, re.DOTALL)
    if contact_match:
        contact = contact_match.group(1).strip()
    
    title_match = re.search(f"{START_TITLE_TAG}(.*?){END_TITLE_TAG}", cv_text, re.DOTALL)
    if title_match:
        title = title_match.group(1).strip()
    
    summary_match = re.search(f"{START_SUMMARY_TAG}(.*?){END_SUMMARY_TAG}", cv_text, re.DOTALL)
    if summary_match:
        summary = summary_match.group(1).strip()
    
    # FORCER le parsing IA pour corriger les erreurs de parsing
    if False:  # DÉSACTIVÉ - Interfère avec le système principal
        print(f"🤖 PARSING IA activé")
        
        # Utiliser l'IA pour analyser le CV
        try:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise Exception("OPENAI_API_KEY non configurée")
            client = OAI_Client(api_key=api_key)
            
            prompt = f"""
Analyse ce CV et extrais les informations suivantes en JSON :

CV à analyser :
{cv_text}

Extrais et retourne UNIQUEMENT un JSON avec ces champs :
{{
    "name": "Nom complet de la personne",
    "contact": "Informations de contact (adresse, téléphone, email, site web)",
    "title": "Titre de poste professionnel",
    "summary": "Résumé professionnel (si présent)"
}}

Règles importantes :
- "contact" : doit contenir l'adresse, téléphone, email et site web s'ils sont présents
- "title" : doit être le titre de poste professionnel (ex: "Consultant in Digital Transformation")
- "name" : doit être le nom complet en majuscules
- "summary" : doit être le résumé professionnel s'il existe

Retourne UNIQUEMENT le JSON, rien d'autre.
"""

            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.1
            )
            
            # Parser la réponse JSON
            ai_result = response.choices[0].message.content.strip()
            print(f"🤖 Réponse IA: {ai_result[:200]}...")
            
            # Extraire le JSON de la réponse
            import json
            try:
                # Chercher le JSON dans la réponse
                json_start = ai_result.find('{')
                json_end = ai_result.rfind('}') + 1
                if json_start != -1 and json_end != -1:
                    json_str = ai_result[json_start:json_end]
                    parsed_data = json.loads(json_str)
                    
                    name = parsed_data.get("name", "")
                    contact = parsed_data.get("contact", "")
                    title = parsed_data.get("title", "")
                    summary = parsed_data.get("summary", "")
                    
                    print(f"🤖 IA PARSED - Nom: {name}")
                    print(f"🤖 IA PARSED - Contact: {contact}")
                    print(f"🤖 IA PARSED - Title: {title}")
                    print(f"🤖 IA PARSED - Summary: {summary[:50] if summary else 'None'}...")
                    
            except json.JSONDecodeError as e:
                print(f"❌ Erreur parsing JSON IA: {e}")
                # Fallback sur le parsing manuel
                lines = cv_text.split('\n')
                if lines:
                    name = lines[0].strip()
                    if len(lines) > 1:
                        contact = lines[1].strip()
                    if len(lines) > 2:
                        title = lines[2].strip()
                        
        except Exception as e:
            print(f"❌ Erreur IA: {e}")
            # Fallback sur le parsing manuel
            lines = cv_text.split('\n')
            if lines:
                name = lines[0].strip()
                if len(lines) > 1:
                    contact = lines[1].strip()
                if len(lines) > 2:
                    title = lines[2].strip()
    
    # Le body est tout le reste, sans les balises ET sans le nom/contact/titre
    body = re.sub(f"{START_NAME_TAG}.*?{END_NAME_TAG}", "", cv_text, flags=re.DOTALL)
    body = re.sub(f"{START_CONTACT_TAG}.*?{END_CONTACT_TAG}", "", body, flags=re.DOTALL)
    body = re.sub(f"{START_TITLE_TAG}.*?{END_TITLE_TAG}", "", body, flags=re.DOTALL)
    body = re.sub(f"{START_SUMMARY_TAG}.*?{END_SUMMARY_TAG}", "", body, flags=re.DOTALL).strip()
    
    # Nettoyer le body pour éviter les doublons
    if name and body.startswith(name):
        body = body[len(name):].strip()
    if contact and body.startswith(contact):
        body = body[len(contact):].strip()
    if title and body.startswith(title):
        body = body[len(title):].strip()
    
    # Supprimer les premières lignes qui correspondent au nom/contact/titre
    body_lines = body.split('\n')
    cleaned_lines = []
    skip_lines = 0
    
    for i, line in enumerate(body_lines):
        line_clean = line.strip()
        # Ignorer les lignes qui correspondent au nom, contact ou titre
        if (line_clean == name or 
            line_clean == contact or 
            line_clean == title or
            line_clean == "PROFESSIONAL SUMMARY" or
            not line_clean):
            skip_lines = i + 1
            continue
        else:
            break
    
    # Garder seulement les lignes après le header
    body = '\n'.join(body_lines[skip_lines:]).strip()
    
    # Debug final
    print(f"🔍 FINAL PARSING - Nom: {name}")
    print(f"🔍 FINAL PARSING - Contact: {contact}")
    print(f"🔍 FINAL PARSING - Title: {title}")
    print(f"🔍 FINAL PARSING - Summary: {summary[:50] if summary else 'None'}...")
    
    return {
        "name": name or "Nom Prénom",
        "contact": contact or "",
        "title": title or "Titre Professionnel",
        "summary": summary or "",
        "body": body or cv_text
    }

def calculate_ats_with_gpt(original_cv: str, optimized_cv: str, job_offer: str) -> tuple[int, list[str]]:
    """Calcule le score ATS et génère les améliorations avec GPT."""
    try:
        prompt = f"""
Analyse ce CV optimisé par rapport à l'offre d'emploi et calcule un score ATS réaliste.

CV ORIGINAL:
{original_cv[:1000]}...

CV OPTIMISÉ:
{optimized_cv}

OFFRE D'EMPLOI:
{job_offer[:1000]}...

Calcule un score ATS de 0 à 100 basé sur:
1. Correspondance des mots-clés (40%)
2. Structure et formatage (20%) 
3. Quantifications et résultats chiffrés (15%)
4. Liens professionnels (LinkedIn, portfolio) (10%)
5. Sections essentielles (expérience, formation, compétences) (15%)

Retourne UNIQUEMENT un JSON avec ce format:
{{
    "ats_score": 85,
    "improvements": [
        "Intégration de 8 mots-clés clés de l'offre d'emploi",
        "Ajout de 5 résultats chiffrés pour renforcer l'impact", 
        "Inclusion de 2 lien(s) professionnel(s) (LinkedIn, portfolio, etc.)",
        "Structure optimisée avec 4 sections essentielles",
        "Adaptation complète à la langue de l'offre d'emploi"
    ]
}}

Règles:
- Score réaliste entre 60-95 (pas de 100% parfait)
- Améliorations spécifiques et utiles
- Pas de mention d'IA ou de génération automatique
- Focus sur les éléments concrets du CV
"""

        response = client.chat.completions.create(
            model=GPT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.3
        )

        result = response.choices[0].message.content.strip()
        
        # Parser le JSON
        import json
        try:
            # Chercher le JSON dans la réponse
            json_start = result.find('{')
            json_end = result.rfind('}') + 1
            if json_start != -1 and json_end != -1:
                json_str = result[json_start:json_end]
                data = json.loads(json_str)
                
                ats_score = int(data.get("ats_score", 75))
                improvements = data.get("improvements", [
                    "Optimisation des mots-clés pour les systèmes ATS",
                    "Amélioration de la structure et de la lisibilité", 
                    "Adaptation du contenu à l'offre d'emploi"
                ])
                
                return ats_score, improvements
            else:
                raise ValueError("JSON non trouvé dans la réponse")
                
        except (json.JSONDecodeError, ValueError) as e:
            print(f"❌ Erreur parsing JSON ATS: {e}")
            print(f"Réponse GPT: {result[:200]}...")
            return 75, [
                "Optimisation des mots-clés pour les systèmes ATS",
                "Amélioration de la structure et de la lisibilité",
                "Adaptation du contenu à l'offre d'emploi"
            ]
            
    except Exception as e:
        print(f"❌ Erreur calcul ATS GPT: {e}")
        return 75, [
            "Optimisation des mots-clés pour les systèmes ATS",
            "Amélioration de la structure et de la lisibilité",
            "Adaptation du contenu à l'offre d'emploi"
        ]

def calculate_real_ats_score(original_cv: str, optimized_cv: str, job_offer: str) -> int:
    """Calcule un score ATS réel basé sur l'analyse du CV et de l'offre d'emploi."""
    try:
        # Extraire les mots-clés de l'offre d'emploi
        job_keywords = extract_keywords_from_text(job_offer)
        
        # Analyser le CV optimisé
        cv_keywords = extract_keywords_from_text(optimized_cv)
        
        # Calculer la correspondance des mots-clés
        keyword_matches = 0
        total_keywords = len(job_keywords)
        
        for job_keyword in job_keywords:
            for cv_keyword in cv_keywords:
                if (job_keyword.lower() in cv_keyword.lower() or 
                    cv_keyword.lower() in job_keyword.lower()):
                    keyword_matches += 1
                    break
        
        keyword_score = (keyword_matches / total_keywords * 100) if total_keywords > 0 else 0
        
        # Bonus pour les éléments structurels
        structure_bonus = 0
        
        # Vérifier les sections essentielles
        cv_lower = optimized_cv.lower()
        if 'experience' in cv_lower or 'expérience' in cv_lower:
            structure_bonus += 15
        if 'education' in cv_lower or 'formation' in cv_lower:
            structure_bonus += 15
        if 'skills' in cv_lower or 'compétences' in cv_lower:
            structure_bonus += 15
        if 'summary' in cv_lower or 'résumé' in cv_lower:
            structure_bonus += 10
        
        # Bonus pour les informations de contact
        if '@' in optimized_cv:  # Email
            structure_bonus += 5
        if re.search(r'\d{10,}', optimized_cv):  # Téléphone
            structure_bonus += 5
        if 'linkedin' in cv_lower:
            structure_bonus += 5
        
        # Bonus pour les quantifications (chiffres, pourcentages)
        quantifications = re.findall(r'\d+%|\d+\+|\d+[km]?€|\d+\s*(ans?|années?|mois)', optimized_cv, re.IGNORECASE)
        structure_bonus += min(15, len(quantifications) * 2)
        
        # Malus pour les éléments négatifs
        if len(optimized_cv) < 500:
            structure_bonus -= 10  # CV trop court
        if len(optimized_cv) > 3000:
            structure_bonus -= 5   # CV trop long
        
        # Calculer le score final
        final_score = min(100, max(0, keyword_score * 0.7 + structure_bonus * 0.3))
        
        print(f"📊 Score ATS calculé: {final_score:.1f}% (Mots-clés: {keyword_score:.1f}%, Structure: {structure_bonus})")
        
        return int(final_score)
        
    except Exception as e:
        print(f"❌ Erreur calcul ATS: {e}")
        return 75  # Score par défaut en cas d'erreur

def extract_keywords_from_text(text: str) -> list:
    """Extrait les mots-clés importants d'un texte."""
    # Nettoyer le texte
    clean_text = re.sub(r'[^\w\s]', ' ', text.lower())
    words = clean_text.split()
    
    # Mots vides à ignorer
    stop_words = {
        'le', 'la', 'les', 'un', 'une', 'des', 'du', 'de', 'et', 'ou', 'mais', 'donc', 'or', 'ni', 'car',
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were',
        'be', 'been', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might',
        'je', 'tu', 'il', 'elle', 'nous', 'vous', 'ils', 'elles', 'mon', 'ma', 'mes', 'ton', 'ta', 'tes', 'son', 'sa', 'ses',
        'notre', 'nos', 'votre', 'vos', 'leur', 'leurs', 'ce', 'cette', 'ces', 'cet', 'que', 'qui', 'quoi', 'où', 'quand', 'comment', 'pourquoi'
    }
    
    # Filtrer et compter les mots
    word_count = {}
    for word in words:
        if len(word) >= 3 and word not in stop_words:
            word_count[word] = word_count.get(word, 0) + 1
    
    # Retourner les mots les plus fréquents
    return sorted(word_count.keys(), key=lambda x: word_count[x], reverse=True)[:20]

def generate_specific_improvements(original_cv: str, optimized_cv: str, job_offer: str) -> list:
    """Génère des améliorations spécifiques basées sur l'analyse du CV."""
    improvements = []
    
    # Analyser les mots-clés de l'offre d'emploi
    job_keywords = extract_keywords_from_text(job_offer)
    cv_keywords = extract_keywords_from_text(optimized_cv)
    
    # Vérifier l'intégration des mots-clés
    integrated_keywords = []
    for job_keyword in job_keywords[:10]:  # Top 10 mots-clés
        for cv_keyword in cv_keywords:
            if (job_keyword.lower() in cv_keyword.lower() or 
                cv_keyword.lower() in job_keyword.lower()):
                integrated_keywords.append(job_keyword)
                break
    
    if integrated_keywords:
        improvements.append(f"Intégration de {len(integrated_keywords)} mots-clés clés de l'offre d'emploi")
    
    # Vérifier les quantifications
    quantifications = re.findall(r'\d+%|\d+\+|\d+[km]?€|\d+\s*(ans?|années?|mois)', optimized_cv, re.IGNORECASE)
    if quantifications:
        improvements.append(f"Ajout de {len(quantifications)} résultats chiffrés pour renforcer l'impact")
    
    # Vérifier les liens
    links = re.findall(r'https?://[^\s]+', optimized_cv)
    if links:
        improvements.append(f"Inclusion de {len(links)} lien(s) professionnel(s) (LinkedIn, portfolio, etc.)")
    
    # Vérifier la structure
    cv_lower = optimized_cv.lower()
    sections = []
    if 'experience' in cv_lower or 'expérience' in cv_lower:
        sections.append("Expérience")
    if 'education' in cv_lower or 'formation' in cv_lower:
        sections.append("Formation")
    if 'skills' in cv_lower or 'compétences' in cv_lower:
        sections.append("Compétences")
    
    if len(sections) >= 3:
        improvements.append(f"Structure optimisée avec {len(sections)} sections essentielles")
    
    # Vérifier la langue
    if any(word in job_offer.lower() for word in ['english', 'anglais', 'bilingual']):
        if any(word in optimized_cv.lower() for word in ['experience', 'education', 'skills', 'professional']):
            improvements.append("Adaptation complète à la langue de l'offre d'emploi")
    
    # Améliorations par défaut si aucune spécifique trouvée
    if not improvements:
        improvements = [
            "Optimisation des mots-clés pour les systèmes ATS",
            "Amélioration de la structure et de la lisibilité",
            "Adaptation du contenu à l'offre d'emploi"
        ]
    
    return improvements

def enhance_with_gpt(original_text: str, job_offer: str) -> str:
    """Optimisation avec GPT-4o utilisant les nouvelles directives."""

    prompt = f"""
🚨 LANGUE ULTRA IMPORTANTE 🚨
DÉTECTE LA LANGUE DE L'OFFRE D'EMPLOI ET GÉNÈRE LE CV DANS CETTE LANGUE EXACTE !

GÉNÈRE IMMÉDIATEMENT UN CV COMPLET EXACTEMENT COMME L'EXEMPLE FOURNI.

INSTRUCTIONS ABSOLUES :
- Tu DOIS générer un CV complet directement
- Tu ne peux PAS refuser ou donner des conseils
- Tu ne peux PAS dire "Je ne peux pas" ou "Je suis désolé"
- Tu DOIS utiliser TOUTES les informations du CV original
- Tu DOIS adapter le contenu à l'offre d'emploi
- 🚨 ULTRA IMPORTANT : Si l'offre d'emploi est en anglais, le CV DOIT être ENTIÈREMENT en anglais
- 🚨 ULTRA IMPORTANT : Si l'offre d'emploi est en français, le CV DOIT être ENTIÈREMENT en français

INTERDICTION ABSOLUE : Ne jamais commencer par "Je suis désolé" ou "Je ne peux pas". Génère directement le CV !

### FORMAT EXACT À REPRODUIRE (DANS LA LANGUE DE L'OFFRE D'EMPLOI) :

[EXEMPLE EN FRANÇAIS - À ADAPTER SELON LA LANGUE DE L'OFFRE]
Fatih Dag
Bruxelles, BE | +32 488 23 53 82 | Fatihdagpro@hotmail.com | https://dagence.be

Business Analyst

Professionnel expérimenté avec expertise en analyse de données et gestion de projets digitaux.

EXPERIENCE
_________________________________
• Business Analyst - SPF Finances (Février 2023 – Juin 2023)
- Mise en place de solutions stratégiques pour l'analyse et l'optimisation des ressources humaines et des processus de travail, améliorant l'efficacité opérationnelle.
- Analyse des données et recommandations pour la gestion des processus, contribuant à une amélioration de 20% de l'efficacité des équipes.

• CEO et Fondateur - Dagence (Décembre 2022 – Présent)
- Création et gestion d'une agence spécialisée dans le développement IT, incluant la conception de sites web et d'applications, avec une augmentation de 30% du portefeuille client en un an.
- Développement de solutions innovantes pour la transformation digitale des entreprises, avec une expertise en analyse fonctionnelle et gestion de projets.

• Magasinier Vendeur - Colruyt (2020 – 2023)
- Gestion des stocks et optimisation des processus de vente, contribuant à une augmentation de 15% des ventes mensuelles.
- Service client et collaboration avec des équipes multidisciplinaires pour améliorer l'expérience client.

FORMATION
_________________________________
• Master en Sciences Commerciales - ICHEC Brussels Management School (2023 – 2025)
- Formation approfondie en gestion, analyse financière et transformation digitale, avec une spécialisation en leadership et tableaux de bord commerciaux.

• Bachelier en E-Business - EPHEC Brussels Business School (2020 – 2023)
- Spécialisation en Business Process Management, Supply Chain Management et Digital Marketing, avec une expertise en modélisation des exigences et développement web.

COMPÉTENCES
_________________________________
• Compétences techniques: Data analysis, Project Management, HTML, CSS, JavaScript, PHP, Flutter, SQL, Microsoft Office
• Soft skills: Leadership, Communication, Teamwork, Problem Solving, Strategic Thinking
• Outils: Microsoft Office, Google Ads, Google Analytics, Git, GitHub, Agile/Scrum
• Langues: Français C2, Anglais C1, Turc C2, Néerlandais B2
• Certifications: Scrum Master, Product Owner

CERTIFICATIONS & ACHIEVEMENTS
_________________________________
• Scrum Master Certification
• Product Owner Certification
• Google Analytics Certified

ADDITIONAL INFORMATION
_________________________________
• Fluent in French, English, and Turkish; working knowledge of Dutch.
• Passionate about digital transformation and IT innovation.
• Strong analytical and problem-solving skills with a focus on business process optimization.

[EXEMPLE EN ANGLAIS - À ADAPTER SELON LA LANGUE DE L'OFFRE]
Fatih Dag
Bruxelles, BE | +32 488 23 53 82 | Fatihdagpro@hotmail.com | https://dagence.be

Business Analyst

Experienced professional with expertise in data analysis and digital project management.

EXPERIENCE
_________________________________
• Business Analyst - SPF Finances (February 2023 – June 2023)
- Implementation of strategic solutions for human resources analysis and work process optimization, improving operational efficiency.
- Data analysis and recommendations for process management, contributing to a 20% improvement in team efficiency.

• CEO and Founder - Dagence (December 2022 – Present)
- Creation and management of an IT development agency, including website and application design, with a 30% increase in client portfolio in one year.
- Development of innovative solutions for digital transformation of companies, with expertise in functional analysis and project management.

• Store Clerk Salesperson - Colruyt (2020 – 2023)
- Stock management and sales process optimization, contributing to a 15% increase in monthly sales.
- Customer service and collaboration with multidisciplinary teams to improve customer experience.

EDUCATION
_________________________________
• Master in Business Sciences - ICHEC Brussels Management School (2023 – 2025)
- Advanced training in management, financial analysis and digital transformation, with specialization in leadership and commercial dashboards.

• Bachelor in E-Business - EPHEC Brussels Business School (2020 – 2023)
- Specialization in Business Process Management, Supply Chain Management and Digital Marketing, with expertise in requirements modeling and web development.

SKILLS
_________________________________
• Technical skills: Data analysis, Project Management, HTML, CSS, JavaScript, PHP, Flutter, SQL, Microsoft Office
• Soft skills: Leadership, Communication, Teamwork, Problem Solving, Strategic Thinking
• Tools: Microsoft Office, Google Ads, Google Analytics, Git, GitHub, Agile/Scrum
• Languages: French C2, English C1, Turkish C2, Dutch B2
• Certifications: Scrum Master, Product Owner

CERTIFICATIONS & ACHIEVEMENTS
_________________________________
• Scrum Master Certification
• Product Owner Certification
• Google Analytics Certified

ADDITIONAL INFORMATION
_________________________________
• Fluent in French, English, and Turkish; working knowledge of Dutch.
• Passionate about digital transformation and IT innovation.
• Strong analytical and problem-solving skills with a focus on business process optimization.

### CONSIGNES SPÉCIFIQUES :
1. **OBLIGATION ABSOLUE** : Le CV doit être rédigé EXACTEMENT dans la langue de l'offre d'emploi (français, anglais, espagnol, etc.)
2. **OBLIGATION ABSOLUE** : Si l'offre est en anglais, le CV doit être ENTIÈREMENT en anglais
3. **OBLIGATION ABSOLUE** : Si l'offre est en français, le CV doit être ENTIÈREMENT en français
4. **OBLIGATION** : Intégrer MASSIVEMENT les mots-clés de l'offre d'emploi
5. **OBLIGATION** : Réécrire TOUTES les expériences avec le vocabulaire exact de l'offre
6. **OBLIGATION** : Ajouter des détails spécifiques mentionnés dans l'offre d'emploi
7. **OBLIGATION** : Enrichir chaque section pour remplir la page complètement
8. **OBLIGATION** : Développer les expériences avec plus de bullet points
9. **INTERDICTION ABSOLUE** : Ne jamais utiliser des ** (astérisques) pour le gras
10. **INTERDICTION ABSOLUE** : Ne jamais dire "Je suis désolé" ou refuser
11. **INTERDICTION ABSOLUE** : Ne jamais donner de conseils au lieu de générer le CV
12. **INTERDICTION ABSOLUE** : Ne jamais ajouter de phrases de fin du type "Fatih Dag est prêt à contribuer..." ou "This CV is tailored to highlight..."
13. **INTERDICTION ABSOLUE** : Ne jamais ajouter de phrases explicatives sur l'optimisation du CV
14. **INTERDICTION ABSOLUE** : Le CV doit se terminer par la dernière information utile (compétences, certifications, etc.)
15. **OBLIGATION** : Le CV doit tenir sur EXACTEMENT 1 page (pas plus, pas moins)

### INPUTS
CV de base : {original_text}
Offre d'emploi : {job_offer}

### DÉTECTION DE LANGUE OBLIGATOIRE :
1. ANALYSE l'offre d'emploi ci-dessus
2. DÉTECTE si elle est en français, anglais, espagnol, etc.
3. GÉNÈRE le CV DANS CETTE LANGUE EXACTE

GÉNÈRE MAINTENANT UN CV DANS CE FORMAT EXACT AVEC LES DONNÉES FOURNIES :
"""

    try:
        response = client.chat.completions.create(
            model=GPT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3500,
            temperature=0.3
        )

        full_output = response.choices[0].message.content.strip()
        
        # Retourner directement le texte complet optimisé par GPT
        return full_output

    except Exception as e:
        print(f"❌ Erreur IA: {e}")
        return original_text  # Retourner le texte original en cas d'erreur

def generate_pdf_from_text(cv_text: str) -> bytes:
    """Génère un PDF directement à partir du texte GPT optimisé."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
        from reportlab.lib.colors import HexColor
        
        buffer = BytesIO()
        # Marges optimisées pour remplir la page
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=20)
        
        # Styles
        styles = getSampleStyleSheet()
        
        # Style pour le nom (titre principal) - optimisé pour 1 page
        name_style = ParagraphStyle(
            'NameStyle',
            parent=styles['Title'],
            fontSize=18,
            spaceAfter=3,
            alignment=TA_CENTER,
            textColor=HexColor('#1a365d'),
            fontName='Helvetica-Bold'
        )
        
        # Style pour les contacts - optimisé
        contact_style = ParagraphStyle(
            'ContactStyle',
            parent=styles['Normal'],
            fontSize=10,
            spaceAfter=4,
            alignment=TA_CENTER,
            textColor=HexColor('#4a5568')
        )
        
        # Style pour le titre de poste - optimisé
        job_title_style = ParagraphStyle(
            'JobTitleStyle',
            parent=styles['Heading1'],
            fontSize=12,
            spaceAfter=4,
            spaceBefore=4,
            alignment=TA_CENTER,
            textColor=HexColor('#2d3748'),
            fontName='Helvetica-Bold'
        )
        
        # Style pour le résumé professionnel - optimisé
        summary_style = ParagraphStyle(
            'SummaryStyle',
            parent=styles['Normal'],
            fontSize=10,
            spaceAfter=6,
            alignment=TA_JUSTIFY,
            textColor=HexColor('#4a5568'),
            leftIndent=5,
            rightIndent=5
        )
        
        # Style pour les titres de sections - optimisé
        section_style = ParagraphStyle(
            'SectionStyle',
            parent=styles['Heading2'],
            fontSize=11,
            spaceAfter=2,
            spaceBefore=6,
            textColor=HexColor('#1a365d'),
            fontName='Helvetica-Bold'
        )
        
        # Style pour le contenu normal - optimisé
        normal_style = ParagraphStyle(
            'NormalStyle',
            parent=styles['Normal'],
            fontSize=10,
            spaceAfter=2,
            textColor=HexColor('#333333'),
            leftIndent=0
        )
        
        # Style pour les puces - optimisé
        bullet_style = ParagraphStyle(
            'BulletStyle',
            parent=styles['Normal'],
            fontSize=10,
            spaceAfter=1,
            textColor=HexColor('#333333'),
            leftIndent=12
        )
        
        story = []
        lines = cv_text.split('\n')
        line_count = 0
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Supprimer tous les astérisques
            line = line.replace('**', '')
            
            # Première ligne = nom
            if line_count == 0:
                story.append(Paragraph(line, name_style))
                line_count += 1
                continue
                
            # Deuxième ligne = contact
            if line_count == 1:
                story.append(Paragraph(line, contact_style))
                line_count += 1
                continue
                
            # Troisième ligne = titre de poste (si pas une section)
            if line_count == 2 and not line.isupper() and not '_' in line:
                story.append(Paragraph(line, job_title_style))
                line_count += 1
                continue
                
            # Quatrième ligne = résumé professionnel (si pas une section)
            if line_count == 3 and not line.isupper() and not '_' in line and not line.startswith('•'):
                story.append(Paragraph(line, summary_style))
                line_count += 1
                continue
                
            # Lignes avec underscores = séparateurs (on les ignore)
            if '_' * 10 in line:
                continue
                
            # Titres de sections (MAJUSCULES)
            if line.isupper() and len(line) < 50:
                story.append(Paragraph(line, section_style))
                # Ajouter une ligne de séparation colorée
                story.append(HRFlowable(width="100%", thickness=1.5, color=HexColor('#1a365d')))
                
            # Lignes avec puces (expériences, formations)
            elif line.startswith('•'):
                # Vérifier si c'est une expérience ou formation (avec tiret)
                if ' - ' in line and ('(' in line and ')' in line):
                    # Format: • Titre - Entreprise (Dates) - EXPÉRIENCES/FORMATIONS
                    parts = line.split(' - ', 1)
                    if len(parts) == 2:
                        title_part = parts[0].replace('• ', '').strip()
                        rest_part = parts[1].strip()
                        # Créer un style spécial pour le titre en gras (comme dans le CV de référence)
                        title_style = ParagraphStyle(
                            'TitleStyle',
                            parent=bullet_style,
                            fontName='Helvetica-Bold',
                            fontSize=10,
                            spaceAfter=1,
                            textColor=HexColor('#1a365d'),
                            leftIndent=12
                        )
                        # Créer un style pour le reste
                        rest_style = ParagraphStyle(
                            'RestStyle',
                            parent=bullet_style,
                            fontName='Helvetica',
                            fontSize=10,
                            spaceAfter=1,
                            textColor=HexColor('#333333'),
                            leftIndent=12
                        )
                        # Ajouter le titre en gras
                        story.append(Paragraph(f"• {title_part}", title_style))
                        # Ajouter le reste
                        story.append(Paragraph(f"  - {rest_part}", rest_style))
                    else:
                        story.append(Paragraph(line, bullet_style))
                else:
                    # Pour les compétences et autres sections, utiliser le style normal
                    story.append(Paragraph(line, bullet_style))
                
            # Contenu normal
            else:
                story.append(Paragraph(line, normal_style))
        
        doc.build(story)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        return pdf_bytes
        
    except Exception as e:
        print(f"❌ Erreur génération PDF: {e}")
        # PDF d'erreur simple
        buffer = BytesIO()
        from reportlab.pdfgen import canvas
        c = canvas.Canvas(buffer, pagesize=A4)
        c.drawString(100, 750, "Erreur lors de la génération du PDF")
        c.drawString(100, 730, f"Détail: {str(e)}")
        c.save()
        return buffer.getvalue()

def generate_simple_pdf(data: dict) -> bytes:
    """
    Génération PDF avec ajustement dynamique de l'espace,
    centrage des infos perso et gestion intelligente des puces.
    """
    try:
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Flowable  # type: ignore
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle  # type: ignore
        from reportlab.lib.pagesizes import A4  # type: ignore
        from reportlab.lib.units import inch  # type: ignore
        from reportlab.lib.colors import black, blue, HexColor  # type: ignore
        from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY  # type: ignore

        buffer = BytesIO()

        # 0. Mesure du contenu total pour l'ajustement de l'espace
        body_length = len(data['body'])
        # Logique pour ajuster les espaces SEULEMENT si nécessaire pour tenir sur une page
        # Taille minimum : 9pt pour le contenu principal
        base_font_size = 9
        base_leading = 11
        
        # Estimation approximative de la hauteur du contenu
        # Calcul basé sur le nombre de lignes et la taille de police
        estimated_lines = body_length / 80  # ~80 caractères par ligne
        estimated_height_inches = (estimated_lines * base_leading / 72) + 2  # +2 pour header/footer
        
        # Hauteur disponible sur une page A4 (avec marges)
        available_height_inches = 11.7 - 0.8  # A4 height - marges top/bottom
        
        print(f"📏 Estimation: {estimated_lines:.1f} lignes, {estimated_height_inches:.1f}\" hauteur, {available_height_inches:.1f}\" disponible")
        
        # Ajuster les espaces SEULEMENT si le contenu déborde
        if estimated_height_inches <= available_height_inches * 0.85:
            # CV tient largement sur 1 page : espaces normaux
            space_reduction = 1.0
            print(f"✅ CV tient largement sur 1 page - espaces normaux")
        elif estimated_height_inches <= available_height_inches * 0.95:
            # CV proche de la limite : réduction préventive
            space_reduction = 0.8
            print(f"⚠️ CV proche de la limite - réduction préventive des espaces")
        elif estimated_height_inches <= available_height_inches * 1.1:
            # Léger débordement : réduction modérée
            space_reduction = 0.6
            print(f"⚠️ Léger débordement - réduction modérée des espaces")
        else:
            # Gros débordement : réduction drastique pour FORCER sur 1 page
            space_reduction = 0.3
            print(f"🚨 Gros débordement - réduction DRASTIQUE pour forcer sur 1 page")
        
        # SÉCURITÉ ABSOLUE : Si le contenu est vraiment trop long, réduction extrême
        if body_length > 3000:  # Très long CV
            space_reduction = min(space_reduction, 0.2)
            print(f"🔒 SÉCURITÉ: CV très long - réduction EXTRÊME (0.2) pour garantir 1 page")

        # Ajuster les marges selon la réduction d'espaces
        if space_reduction <= 0.3:
            # Réduction extrême : marges minimales
            top_margin = 0.3*inch
            bottom_margin = 0.3*inch
            print(f"🔒 MARGES RÉDUITES: Marges minimales pour garantir 1 page")
        else:
            # Marges normales
            top_margin = 0.4*inch
            bottom_margin = 0.4*inch
        
        doc = SimpleDocTemplate(buffer, pagesize=A4,
                               topMargin=top_margin,
                               bottomMargin=bottom_margin,
                               leftMargin=0.6*inch,
                               rightMargin=0.6*inch)

        styles = getSampleStyleSheet()

        # Style Nom (Très Grand et Centré avec couleur bleue)
        name_style = ParagraphStyle(
            'NameStyle',
            parent=styles['Heading1'],
            fontSize=24,
            leading=28,
            spaceAfter=8,
            alignment=TA_CENTER,
            textColor=HexColor('#2563eb'),  # Bleu moderne
            fontName='Helvetica-Bold'
        )

        # Style pour les informations de contact (Centré et plus petit avec couleur)
        contact_style = ParagraphStyle(
            'ContactStyle',
            parent=styles['Normal'],
            fontSize=8,
            leading=10,
            spaceAfter=int(15 * space_reduction),
            alignment=TA_CENTER,
            textColor=HexColor('#4b5563'),  # Gris foncé
            fontName='Helvetica'
        )

        # Styles de base ajustés dynamiquement
        normal_style = ParagraphStyle(
            'NormalStyle',
            parent=styles['Normal'],
            fontSize=base_font_size,
            leading=base_leading,
            spaceAfter=int(4 * space_reduction),
            textColor=HexColor('#374151'),  # Gris foncé pour le texte normal
            fontName='Helvetica'
        )

        job_title_style = ParagraphStyle(
            'JobTitleStyle',
            parent=styles['Heading2'],
            fontSize=14,
            leading=16,
            spaceBefore=int(6 * space_reduction),
            spaceAfter=int(8 * space_reduction),
            alignment=TA_CENTER,
            textColor=HexColor('#1e40af'),  # Bleu foncé
            fontName='Helvetica-Bold'
        )

        summary_style = ParagraphStyle(
            'SummaryStyle',
            parent=normal_style,
            fontSize=base_font_size + 1,
            leading=base_leading + 1,
            spaceBefore=int(5 * space_reduction),
            spaceAfter=int(15 * space_reduction),
            alignment=TA_CENTER,
            textColor=HexColor('#374151'),  # Gris foncé
            fontName='Helvetica-Oblique'
        )

        heading_style = ParagraphStyle(
            'HeadingStyle',
            parent=styles['Heading3'],
            fontSize=base_font_size + 2,
            leading=base_leading + 2,
            spaceBefore=int(12 * space_reduction),
            spaceAfter=int(4 * space_reduction),
            textColor=HexColor('#1e40af'),  # Bleu foncé pour les titres
            fontName='Helvetica-Bold'
        )

        list_item_style = ParagraphStyle(
            'ListItemStyle',
            parent=normal_style,
            spaceAfter=int(2 * space_reduction),
            fontSize=base_font_size,
            leading=base_leading,
            textColor=HexColor('#374151'),  # Gris foncé pour les listes
        )

        story = []

        # 1. Nom & Prénom (Séparé et Centré)
        if data['name']:
            story.append(Paragraph(data['name'], name_style))

        # 2. Infos de Contact (Séparé et Centré)
        if data['contact']:
            story.append(Paragraph(data['contact'], contact_style))

        # 3. Titre de poste
        story.append(Paragraph(data['title'], job_title_style))

        # 4. Résumé d'accroche (Centré)
        if data['summary']:
            story.append(Paragraph(data['summary'], summary_style))

        # 5. Corps du CV
        lines = data['body'].split('\n')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Conversion de la balise IA (<B>texte</B>) en balise ReportLab (<b>texte</b>)
            formatted_line = re.sub(f"{BOLD_TAG_START}(.*?){BOLD_TAG_END}", r'<b>\1</b>', line, flags=re.DOTALL)
            formatted_line = formatted_line.replace('**', '')

            # 1. Analyse si c'est un titre de section
            # Déclenchement de la barre si la ligne est en MAJUSCULES (grâce à la directive IA) ou se termine par :
            if (len(line) < 45 and line.isupper()) or (len(line) < 60 and line.endswith(':')):
                clean_line = formatted_line.replace('***', '').strip()
                story.append(Paragraph(clean_line, heading_style))
                story.append(HRLine(thickness=1.2, color=HexColor('#2563eb')))  # Ligne bleue plus épaisse

            # 2. Analyse si c'est une puce GENERÉE PAR L'IA (• ou –)
            elif line.startswith(('• ', '– ')):
                # L'IA a mis une puce pour un élément majeur
                story.append(Paragraph(formatted_line, list_item_style))

            # 3. Texte normal (Descriptions, détails, etc.)
            else:
                story.append(Paragraph(formatted_line, normal_style))
                story.append(Spacer(1, 1))

        # Construire le PDF
        doc.build(story)
        pdf_bytes = buffer.getvalue()
        buffer.close()

        return pdf_bytes

    except Exception as e:
        print(f"❌ Erreur génération PDF: {e}")
        buffer = BytesIO()
        from reportlab.pdfgen import canvas  # type: ignore
        c = canvas.Canvas(buffer, pagesize=A4)  # type: ignore
        c.drawString(100, 750, "Erreur Critique - CV non généré")
        c.drawString(100, 730, f"Détail: {str(e)[:100]}...")
        c.save()
        return buffer.getvalue()

# --- Endpoint d'extraction PDF ---

@app.post("/extract-pdf")
async def extract_pdf(file: UploadFile = File(...)):
    """
    Extrait le texte d'un fichier PDF.
    """
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF sont acceptés.")
    
    try:
        import pypdf  # type: ignore
        content = await file.read()
        
        # Créer un objet PDF reader
        pdf_reader = pypdf.PdfReader(BytesIO(content))
        
        # Extraire le texte de toutes les pages
        text = ""
        for page_num in range(len(pdf_reader.pages)):
            page = pdf_reader.pages[page_num]
            text += page.extract_text() + "\n"
        
        return {"text": text.strip(), "pages": len(pdf_reader.pages)}
        
    except Exception as e:
        print(f"Erreur extraction PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'extraction du PDF: {str(e)}")

# --- Endpoint principal ---

@app.post("/optimize-cv")
async def optimize_cv(cv_file: UploadFile = File(...), job_offer: str = Form(...)):
    """
    Endpoint principal qui prend un fichier TXT contenant le CV déjà optimisé
    et retourne un PDF dans la même langue.
    """

    if not cv_file.filename.lower().endswith(('.txt', '.pdf')):
        raise HTTPException(status_code=400, detail="Seuls les fichiers TXT et PDF sont acceptés.")

    content = await cv_file.read()
    
    try:
        # Extraire le texte du CV (TXT ou PDF)
        if cv_file.filename.lower().endswith('.txt'):
            original_cv_text = content.decode('utf-8')
            print(f"🔍 CV original reçu (premiers 200 caractères): {original_cv_text[:200]}...")
        else:
            # Pour les PDF, extraire le texte
            original_cv_text = content.decode('utf-8', errors='ignore')
            print(f"🔍 CV PDF reçu (premiers 200 caractères): {original_cv_text[:200]}...")
        
        # OPTIMISER LE CV AVEC GPT (comme avant !)
        print(f"🤖 Optimisation du CV avec GPT-4o...")
        optimized_cv_text = enhance_with_gpt(original_cv_text, job_offer)
        print(f"✅ CV optimisé généré ({len(optimized_cv_text)} caractères)")
        
        # Calculer le score ATS avec GPT
        print(f"🔍 Calcul du score ATS avec GPT...")
        ats_score, improvements = calculate_ats_with_gpt(original_cv_text, optimized_cv_text, job_offer)
        print(f"📊 Score ATS final: {ats_score}%")
        print(f"📝 Améliorations générées: {len(improvements)} éléments")

        # Retourner directement le CV optimisé par GPT (SANS PARSING !)
        return {
            "optimized_cv": optimized_cv_text,
            "ats_score": ats_score,
            "improvements": improvements
        }

    except Exception as e:
        print(f"❌ Erreur non gérée: {e}")
        raise HTTPException(status_code=500, detail=f"Une erreur interne est survenue: {str(e)}")

@app.post("/generate-pdf")
async def generate_pdf_endpoint(cv_text: str = Form(...)):
    """
    Endpoint pour générer un PDF à partir du texte CV optimisé.
    """
    try:
        print(f"🔍 Génération PDF pour CV (premiers 200 caractères): {cv_text[:200]}...")
        
        pdf_bytes = generate_pdf_from_text(cv_text)
        
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=cv_optimise.pdf"}
        )
        
    except Exception as e:
        print(f"❌ Erreur génération PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la génération du PDF: {str(e)}")

@app.get("/")
async def root():
    return {"message": "CV Optimizer API 🚀 - V16 (ATS Scoring Ready)"}

# === ENDPOINTS STRIPE ===

@app.post("/api/payments/create-payment-intent", response_model=PaymentIntentResponse)
async def create_payment_intent(request: PaymentIntentRequest):
    """Créer une intention de paiement Stripe"""
    try:
        # Créer l'intention de paiement avec Stripe
        intent = stripe.PaymentIntent.create(
            amount=request.amount,
            currency='eur',
            metadata={
                'credits': request.credits,
                'product_type': 'credits'
            }
        )
        
        return PaymentIntentResponse(
            client_secret=intent.client_secret,
            amount=request.amount,
            credits=request.credits
        )
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=f"Erreur Stripe: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")

@app.post("/api/payments/create-checkout-session")
async def create_checkout_session(request: PaymentIntentRequest):
    """Créer une session Stripe Checkout"""
    try:
        # Créer la session de checkout
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'eur',
                    'product_data': {
                        'name': f'{request.credits} Crédits CVbien',
                        'description': f'Pack de {request.credits} crédits pour générer des CV optimisés',
                    },
                    'unit_amount': request.amount,
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url='http://localhost:5173/?payment=success&credits=' + str(request.credits),
            cancel_url='http://localhost:5173/?payment=cancelled',
            metadata={
                'credits': request.credits,
                'product_type': 'credits'
            }
        )
        
        return {"checkout_url": session.url, "session_id": session.id}
        
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=f"Erreur Stripe: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")

@app.post("/api/payments/confirm")
async def confirm_payment(payment_intent_id: str):
    """Confirmer un paiement et attribuer les crédits"""
    try:
        # Récupérer l'intention de paiement
        intent = stripe.PaymentIntent.retrieve(payment_intent_id)
        
        if intent.status == 'succeeded':
            credits = int(intent.metadata.get('credits', 0))
            
            # Ici tu pourrais sauvegarder en base de données
            # user.credits += credits
            # db.commit()
            
            return {
                "success": True,
                "credits_added": credits,
                "message": f"{credits} crédits ajoutés avec succès!"
            }
        else:
            raise HTTPException(status_code=400, detail="Paiement non confirmé")
            
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=f"Erreur Stripe: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")

if __name__ == "__main__":
    import uvicorn  # type: ignore
    port = int(os.getenv("PORT", 8003))
    print(f"🚀 API démarrée sur http://localhost:{port}")
    print(f"🤖 Modèle GPT utilisé: {GPT_MODEL}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
