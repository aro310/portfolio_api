# app.py
from flask import Flask, request, jsonify
from flask_cors import CORS
from gemini_api import chat_with_gemini

# Importation de notre fonction allégée
try:
    from ele import generate_audio_base64
except ImportError:
    generate_audio_base64 = None

app = Flask(__name__)
CORS(app)

# Note: J'ai retiré Swagger pour économiser de l'espace disque sur Vercel

@app.route("/", methods=["GET"])
def home():
    return "API Aro en ligne (Vercel Optimized)"

@app.route("/api/run-script", methods=["POST"])
def run_script():
    try:
        data = request.get_json()
        texte = data.get("texte")

        if not texte:
            return jsonify({"status": "error", "message": "Le texte est manquant"}), 400

        if generate_audio_base64:
            audio_b64 = generate_audio_base64(texte)
            
            if not audio_b64:
                return jsonify({"status": "error", "message": "Échec génération audio ElevenLabs"}), 500

            return jsonify({
                "status": "success", 
                "message": "Audio généré",
                "audio_base64": audio_b64,
                "texte_original": texte
            })
        else:
             return jsonify({"status": "error", "message": "Module Audio non chargé"}), 500

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        prompt = data.get("prompt")
        history = data.get("history", [])  # Liste des messages précédents (client doit la gérer)

        if not prompt:
            return jsonify({"status": "error", "message": "Prompt manquant"}), 400

        response_text = chat_with_gemini(prompt, history)

        return jsonify({
            "status": "success",
            "response": response_text
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    
if __name__ == "__main__":
    app.run(debug=True, port=5001)