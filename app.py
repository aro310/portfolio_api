# app.py
from flask import Flask, request, jsonify
from flask_cors import CORS
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from gemini_api import chat_with_gemini

# ── Supabase (optionnel : uniquement si les variables d'env sont définies) ──
_supabase = None
try:
    _sb_url = os.environ.get("SUPABASE_URL", "")
    _sb_key = os.environ.get("SUPABASE_KEY", "")
    if _sb_url and _sb_key:
        from supabase import create_client
        _supabase = create_client(_sb_url, _sb_key)
        print("Supabase connecté ✓")
except Exception as _e:
    print(f"Supabase non disponible : {_e}")


def _load_history(session_id: str, limit: int = 20) -> list:
    """Charge les derniers messages d'une session depuis Supabase."""
    if not _supabase or not session_id:
        return []
    try:
        res = (
            _supabase.table("conversations")
            .select("role, content")
            .eq("session_id", session_id)
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return [{"role": r["role"], "content": r["content"]} for r in (res.data or [])]
    except Exception as e:
        print(f"Erreur chargement historique : {e}")
        return []


def _save_message(session_id: str, role: str, content: str):
    """Sauvegarde un message dans Supabase."""
    if not _supabase or not session_id:
        return
    try:
        _supabase.table("conversations").insert({
            "session_id": session_id,
            "role": role,
            "content": content
        }).execute()
    except Exception as e:
        print(f"Erreur sauvegarde message : {e}")

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
    Endpoint Chat.
    Accepte { "prompt": "...", "session_id": "..." }
    Historique chargé/sauvegardé dans Supabase si configuré.
    """
    try:
        data = request.get_json()
        prompt = data.get("prompt")
        session_id = data.get("session_id", "")

        if not prompt:
            return jsonify({"status": "error", "message": "Prompt vide"}), 400

        # Charger l'historique depuis Supabase (ou liste vide si pas configuré)
        history = _load_history(session_id)

        # Sauvegarder le message user
        _save_message(session_id, "user", prompt)

        # Appel LLM
        chat_result = chat_with_gemini(prompt, history)

        response_text = ""
        action = None

        if isinstance(chat_result, dict):
            response_text = chat_result.get("response", "")
            action = chat_result.get("action")
        else:
            response_text = str(chat_result)

        # Sauvegarder la réponse assistant
        if response_text:
            _save_message(session_id, "assistant", response_text)

        return jsonify({
            "status": "success",
            "response": response_text,
            "action": action
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