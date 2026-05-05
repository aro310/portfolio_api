# app.py
from flask import Flask, request, jsonify
from flask_cors import CORS
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
# Import relatif propre
from gemini_api import chat_with_gemini

# Initialisation Flask
app = Flask(__name__)

# CORS explicite : autorise Netlify, Vercel et localhost
CORS(app, resources={r"/api/*": {
    "origins": ["*"],  # En prod, remplace par ton URL Netlify exacte
    "methods": ["GET", "POST", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization"]
}})


# Import optionnel Audio (Gestion d'erreur silencieuse si module absent)
try:
    from ele import generate_audio_base64
except ImportError:
    generate_audio_base64 = None


@app.route("/", methods=["GET"])
def home():
    """Health check rapide pour Vercel"""
    return jsonify({
        "status": "online",
        "service": "API Aro Football",
        "date_simulation": "26 Janvier 2026",
        "version": "Vercel-Optimized 2.0"
    })

@app.route("/api/chat", methods=["POST"])
def chat():
    """
    Endpoint Chat optimisé.
    Accepte { "prompt": "...", "history": [...] }
    """
    try:
        data = request.get_json()
        prompt = data.get("prompt")
        history = data.get("history", []) # Le frontend gère la mémoire

        if not prompt:
            return jsonify({"status": "error", "message": "Il manque le ballon (Prompt vide)"}), 400

        # Appel à la logique NLP
        chat_result = chat_with_gemini(prompt, history)
        
        response_text = ""
        action = None
        
        if isinstance(chat_result, dict):
            response_text = chat_result.get("response", "")
            action = chat_result.get("action")
        else:
            response_text = chat_result

        return jsonify({
            "status": "success",
            "response": response_text,
            "action": action
            # On pourrait renvoyer l'historique mis à jour ici si on voulait faire du stateful
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/run-script", methods=["POST"])
def run_script():
    """Endpoint Audio (TTS)"""
    try:
        if not generate_audio_base64:
             return jsonify({"status": "error", "message": "Module Audio (ele.py) non trouvé sur le serveur"}), 503

        data = request.get_json()
        texte = data.get("texte")

        if not texte:
            return jsonify({"status": "error", "message": "Texte manquant pour l'audio"}), 400

        # Génération
        audio_b64 = generate_audio_base64(texte)
        
        if not audio_b64:
            return jsonify({"status": "error", "message": "Échec génération ElevenLabs"}), 500

        return jsonify({
            "status": "success",
            "message": "Audio généré",
            "audio_base64": audio_b64
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# IMPORTANT POUR VERCEL :
# Vercel cherche 'app' automatiquement.
# Le bloc __main__ ne sert qu'au développement local.

@app.route("/api/contact", methods=["POST"])
def contact():
    """Envoie un email depuis le formulaire de contact du portfolio."""
    try:
        data = request.get_json()
        name = data.get("name", "").strip()
        sender_email = data.get("email", "").strip()
        message = data.get("message", "").strip()

        if not name or not sender_email or not message:
            return jsonify({"status": "error", "message": "Tous les champs sont requis."}), 400

        gmail_user = os.environ.get("GMAIL_USER", "aroratovoharison@gmail.com")
        gmail_pass = os.environ.get("GMAIL_APP_PASSWORD", "")

        body = f"""Nouveau message depuis ton portfolio !\n
Nom : {name}
Email : {sender_email}
\nMessage :\n{message}
        """

        msg = MIMEMultipart()
        msg["From"] = gmail_user
        msg["To"] = gmail_user
        msg["Subject"] = f"[Portfolio] Message de {name}"
        msg["Reply-To"] = sender_email
        msg.attach(MIMEText(body, "plain"))

        if gmail_pass:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(gmail_user, gmail_pass)
                server.sendmail(gmail_user, gmail_user, msg.as_string())
            return jsonify({"status": "success", "message": "Message envoyé !"})
        else:
            # Pas de mot de passe configuré - on simule l'envoi en dev
            print(f"[DEV] Email simulé de {name} ({sender_email}): {message}")
            return jsonify({"status": "success", "message": "Message reçu (mode dev) !"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5001)