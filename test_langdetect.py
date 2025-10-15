#!/usr/bin/env python3
"""
Test de la détection de langue avec langdetect
"""

from langdetect import detect, DetectorFactory

# Configuration pour des résultats reproductibles
DetectorFactory.seed = 0

def detect_job_language(job_offer_text: str) -> str:
    """
    Détecte automatiquement la langue de l'offre d'emploi avec langdetect.
    Retourne 'english', 'french', ou 'dutch'.
    """
    try:
        if not job_offer_text or len(job_offer_text.strip()) < 10:
            return "english"  # Par défaut si texte trop court
            
        # Détecter la langue
        lang = detect(job_offer_text)
        print(f"🔍 Langdetect détecté: {lang}")
        
        # Mapper vers nos langues supportées
        if lang.startswith("en"):
            return "english"
        elif lang.startswith("fr"):
            return "french"
        elif lang.startswith("nl"):
            return "dutch"
        else:
            return "english"  # Par défaut pour les autres langues
            
    except Exception as e:
        print(f"⚠️ Erreur détection langue: {e}")
        return "english"  # Fallback en cas d'erreur

# Tests
test_cases = [
    {
        "text": "We are looking for a Senior Software Developer with 5+ years of experience in React and Node.js. The ideal candidate should have strong communication skills and be able to work in a team environment.",
        "expected": "english"
    },
    {
        "text": "Nous recherchons un Développeur Senior avec 5+ ans d'expérience en React et Node.js. Le candidat idéal doit avoir de solides compétences en communication et savoir travailler en équipe.",
        "expected": "french"
    },
    {
        "text": "Wij zoeken een Senior Software Developer met 5+ jaar ervaring in React en Node.js. De ideale kandidaat moet sterke communicatieve vaardigheden hebben en kunnen werken in een teamomgeving.",
        "expected": "dutch"
    }
]

print("🧪 Test de détection de langue avec langdetect\n")

for i, test in enumerate(test_cases, 1):
    print(f"Test {i} (attendu: {test['expected']}):")
    result = detect_job_language(test['text'])
    status = "✅" if result == test['expected'] else "❌"
    print(f"{status} Résultat: {result}")
    print(f"Texte: {test['text'][:80]}...")
    print()


