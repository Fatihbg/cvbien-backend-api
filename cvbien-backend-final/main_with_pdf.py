from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from io import BytesIO
import re
from openai import OpenAI as OAI_Client
import tempfile
import os
import PyPDF2

# --- CLASSE DE LIGNE HORIZONTALE ---
from reportlab.platypus import Flowable

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
        from reportlab.lib.colors import black
        self.canv.setStrokeColor(self.color or black)
        self.canv.setLineWidth(self.thickness)
        self.canv.line(0, 0, self.width, 0)

# ------------------------------------------------------------------

# --- Configuration de l'API ---
app = FastAPI(title="CV Optimizer API V17 - PDF Reading Ready")

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

def extract_text_from_pdf(pdf_path: str) -> str:
    """Extrait le texte d'un PDF avec PyPDF2."""
    try:
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
        return text.strip()
    except Exception as e:
        print(f"❌ Erreur extraction PDF: {e}")
        return "Erreur lors de l'extraction du PDF"

def extract_text_from_txt(txt_content: str) -> str:
    """Extrait le texte d'un fichier TXT."""
    return txt_content

def enhance_with_gpt(original_text: str, job_offer: str) -> dict:
    """Optimisation avec GPT-4o utilisant les nouvelles directives."""

    prompt = f"""
Vous êtes un expert en recrutement. Votre mission est d'optimiser le CV fourni pour qu'il corresponde de manière PERTINENTE et NATURELLE à l'offre d'emploi. L'objectif est de générer un CV **d'une seule page** avec une mise en forme professionnelle et compacte.

**Le CV ci-dessous a été extrait d'un PDF, sa structure peut être imparfaite, mais vous devez la reconstruire logiquement et synthétiquement.**

**DIRECTIVES TRÈS STRICTES (Stratégie d'Intelligence et de Cohérence):**

1. **Méthode de Travail (Critique) :** Avant de générer la réponse finale, vous devez effectuer une analyse logique du CV brut pour **identifier clairement les titres d'entreprise, les diplômes, les dates et les descriptions d'actions**. Cette analyse interne doit garantir que chaque section est présentée de manière hiérarchique et non mélangée.

2. **Contenu Intact (CRITIQUE ABSOLUE) :** Vous devez **ABSOLUMENT** inclure **TOUTES** les expériences et formations existantes. **RIEN NE DOIT ÊTRE SUPPRIMÉ OU EXCESSSIVEMENT RACCOURCI**. L'amélioration et la synthèse doivent se concentrer sur la **reformulation PERCUTANTE et les résultats mesurables** pour augmenter la densité d'information.

3. **Objectif ATS (CRITIQUE) :** L'objectif est d'atteindre le score ATS le plus élevé possible. Utilisez la terminologie et les mots-clés exacts de l'OFFRE D'EMPLOI pour reformuler les descriptions d'expériences et les compétences.

4. **Nom & Prénom :** Extrayez le nom et prénom, en utilisant UNIQUEMENT les balises {START_NAME_TAG} et {END_NAME_TAG}.

5. **Contacts & Liens (CRITIQUE) :** Extrayez les coordonnées. Si un lien (URL LinkedIn, Portfolio, etc.) existe dans le CV original, vous **DEVEZ** l'inclure. **NE JAMAIS INVENTER DE LIEN** s'il n'est pas déjà dans le CV. Utilisez UNIQUEMENT les balises {START_CONTACT_TAG} et {END_CONTACT_TAG}.

6. **Titre de Poste :** Générez un titre de poste clair, en utilisant UNIQUEMENT les balises {START_TITLE_TAG} et {END_TITLE_TAG}.

7. **Résumé :** Générez un mini-texte de 3-4 lignes max, en utilisant UNIQUEMENT les balises {START_SUMMARY_TAG} et {END_SUMMARY_TAG}.

8. **Objectif de Page Unique (CRITIQUE) :** L'objectif ABSOLU est de générer un CV qui tienne sur **UNE SEULE PAGE**. Ce but doit être atteint par l'**organisation intelligente** et le **phrasé extrêmement concis** (Haute densité d'information), et **NON** par l'omission d'expériences.

9. **Titres de Section (CRITIQUE pour le Design) :** Chaque titre de section (EXEMPLE: **EXPÉRIENCE**, **FORMATION**, **COMPÉTENCES**, etc.) doit être **écrit en MAJUSCULES** pour que la mise en forme du PDF (la barre de séparation) s'applique correctement.

10. **Gestion des Puces (CRITIQUE) :**
   * Utilisez le caractère `•` ou `–` **UNIQUEMENT** devant l'**introduction d'un nouvel élément majeur** (ex: *une nouvelle entreprise*, *un nouveau diplôme*).
   * Pour les listes d'actions et les détails dans les descriptions de poste, utilisez des **tirets plats** (`-`) ou des **paragraphes simples** (sans puce) pour ne pas fausser la lecture.
   * **NE JAMAIS** utiliser de puces (`•` ou `–`) dans la section Compétences ou Langues.

11. **Formatage :** Mettez en **gras** les éléments clés ATS avec les balises **<B>** et **</B>**.

12. **Fin de la Réponse (CRITIQUE) :** La réponse doit **ABSOLUMENT** se terminer après le dernier mot du CV généré. **N'ajoutez AUCUN commentaire, explication, ou phrase de conclusion** sur l'optimisation, l'ATS, ou l'offre d'emploi.

OFFRE D'EMPLOI:
---
{job_offer}
---

CV ORIGINAL BRUT (Extrait du PDF):
---
{original_text}
---

RÉPONSE (Inclure les balises {START_NAME_TAG}, {START_CONTACT_TAG}, {START_TITLE_TAG}, {START_SUMMARY_TAG}, et utiliser <B>...</B>):
"""

    try:
        response = client.chat.completions.create(
            model=GPT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3500,
            temperature=0.3
        )

        full_output = response.choices[0].message.content.strip()

        # 1. Extraction du Nom
        name_match = re.search(f"{START_NAME_TAG}(.*?){END_NAME_TAG}", full_output, re.DOTALL)
        name = name_match.group(1).strip() if name_match else ""

        # 2. Extraction des Contacts
        contact_match = re.search(f"{START_CONTACT_TAG}(.*?){END_CONTACT_TAG}", full_output, re.DOTALL)
        contact = contact_match.group(1).strip() if contact_match else ""

        # 3. Extraction du Titre
        title_match = re.search(f"{START_TITLE_TAG}(.*?){END_TITLE_TAG}", full_output, re.DOTALL)
        title = title_match.group(1).strip() if title_match else "Profil Professionnel"

        # 4. Extraction du Résumé
        summary_match = re.search(f"{START_SUMMARY_TAG}(.*?){END_SUMMARY_TAG}", full_output, re.DOTALL)
        summary = summary_match.group(1).strip() if summary_match else ""

        # 5. Extraction du corps (tout sauf les balises)
        body = re.sub(f"{START_NAME_TAG}.*?{END_NAME_TAG}", "", full_output, flags=re.DOTALL)
        body = re.sub(f"{START_CONTACT_TAG}.*?{END_CONTACT_TAG}", "", body, flags=re.DOTALL)
        body = re.sub(f"{START_TITLE_TAG}.*?{END_TITLE_TAG}", "", body, flags=re.DOTALL)
        body = re.sub(f"{START_SUMMARY_TAG}.*?{END_SUMMARY_TAG}", "", body, flags=re.DOTALL).strip()

        # Sécurité: enlève tout ** résiduel (bien que le prompt demande <B>)
        body = re.sub(r'\*\*(.*?)\*\*', r'<B>\1</B>', body)

        return {"name": name, "contact": contact, "title": title, "summary": summary, "body": body}

    except Exception as e:
        print(f"❌ Erreur IA: {e}")
        return {"name": "Erreur d'Optimisation", "contact": "", "title": "Erreur d'Optimisation", "summary": "", "body": original_text}

def generate_simple_pdf(data: dict) -> bytes:
    """
    Génération PDF avec ajustement dynamique de l'espace,
    centrage des infos perso et gestion intelligente des puces.
    """
    try:
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Flowable
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import inch
        from reportlab.lib.colors import black, blue, HexColor
        from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY

        buffer = BytesIO()

        # 0. Mesure du contenu total pour l'ajustement de l'espace
        body_length = len(data['body'])
        # Logique pour ajuster la taille de police dynamiquement pour tenir sur une page
        if body_length < 1000:
            base_font_size = 10
            base_leading = 12
        elif body_length > 2200:
            # Très compact si très long
            base_font_size = 8
            base_leading = 10
        else:
            # Standard pour la page unique
            base_font_size = 9
            base_leading = 11

        doc = SimpleDocTemplate(buffer, pagesize=A4,
                               topMargin=0.4*inch,
                               bottomMargin=0.4*inch,
                               leftMargin=0.6*inch,
                               rightMargin=0.6*inch)

        styles = getSampleStyleSheet()

        # Style Nom (Très Grand et Centré)
        name_style = ParagraphStyle(
            'NameStyle',
            parent=styles['Heading1'],
            fontSize=24,
            leading=28,
            spaceAfter=8,
            alignment=TA_CENTER,
            textColor=HexColor('#000000'),
            fontName='Helvetica-Bold'
        )

        # Style pour les informations de contact (Centré et plus petit)
        contact_style = ParagraphStyle(
            'ContactStyle',
            parent=styles['Normal'],
            fontSize=base_font_size,
            leading=base_leading,
            spaceAfter=15,
            alignment=TA_CENTER,
            fontName='Helvetica'
        )

        # Styles de base ajustés dynamiquement
        normal_style = ParagraphStyle(
            'NormalStyle',
            parent=styles['Normal'],
            fontSize=base_font_size,
            leading=base_leading,
            spaceAfter=4,
            fontName='Helvetica'
        )

        job_title_style = ParagraphStyle(
            'JobTitleStyle',
            parent=styles['Heading2'],
            fontSize=14,
            leading=16,
            spaceBefore=4,
            spaceAfter=8,
            alignment=TA_CENTER,
            textColor=HexColor('#000000'),
            fontName='Helvetica'
        )

        summary_style = ParagraphStyle(
            'SummaryStyle',
            parent=normal_style,
            fontSize=base_font_size + 1,
            leading=base_leading + 1,
            spaceBefore=5,
            spaceAfter=15,
            alignment=TA_CENTER,
            fontName='Helvetica-Oblique'
        )

        heading_style = ParagraphStyle(
            'HeadingStyle',
            parent=styles['Heading3'],
            fontSize=base_font_size + 2,
            leading=base_leading + 2,
            spaceBefore=12,
            spaceAfter=4,
            textColor=black,
            fontName='Helvetica-Bold'
        )

        list_item_style = ParagraphStyle(
            'ListItemStyle',
            parent=normal_style,
            spaceAfter=2,
            fontSize=base_font_size,
            leading=base_leading,
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
                story.append(HRLine(thickness=0.8, color=HexColor('#000000')))

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
        from reportlab.pdfgen import canvas
        c = canvas.Canvas(buffer, pagesize=A4)
        c.drawString(100, 750, "Erreur Critique - CV non généré")
        c.drawString(100, 730, f"Détail: {str(e)[:100]}...")
        c.save()
        return buffer.getvalue()

# --- Endpoint principal ---

@app.post("/optimize-cv")
async def optimize_cv(cv_file: UploadFile = File(...), job_offer: str = Form(...)):
    """
    Endpoint principal qui prend un fichier PDF ou TXT et une offre d'emploi,
    optimise le CV avec GPT-4o, et retourne un PDF.
    """

    if not cv_file.filename.lower().endswith(('.txt', '.pdf')):
        raise HTTPException(status_code=400, detail="Seuls les fichiers TXT et PDF sont acceptés.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{cv_file.filename.split(".")[-1]}') as tmp_file:
        content = await cv_file.read()
        tmp_file.write(content)
        original_path = tmp_file.name

    try:
        if cv_file.filename.lower().endswith('.pdf'):
            print(f"📄 Extraction du PDF: {cv_file.filename}")
            original_text = extract_text_from_pdf(original_path)
            print(f"✅ Texte extrait du PDF: {len(original_text)} caractères")
        else:
            print(f"📄 Extraction du TXT: {cv_file.filename}")
            original_text = extract_text_from_txt(content.decode('utf-8'))
            print(f"✅ Texte extrait du TXT: {len(original_text)} caractères")

        print(f"📝 Texte original (premiers 200 chars): {original_text[:200]}...")

        data = enhance_with_gpt(original_text, job_offer)
        pdf_bytes = generate_simple_pdf(data)

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=cv_optimise_{cv_file.filename.replace('.txt', '').replace('.pdf', '')}.pdf"}
        )

    except Exception as e:
        print(f"❌ Erreur non gérée: {e}")
        raise HTTPException(status_code=500, detail=f"Une erreur interne est survenue: {str(e)}")

    finally:
        if os.path.exists(original_path):
            os.unlink(original_path)

@app.get("/")
async def root():
    return {"message": "CV Optimizer API 🚀 - V17 (PDF Reading Ready)"}

if __name__ == "__main__":
    import uvicorn
    print("🚀 API démarrée sur http://localhost:8001")
    print(f"🤖 Modèle GPT utilisé: {GPT_MODEL}")
    print("📄 Support PDF: PyPDF2")
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")

