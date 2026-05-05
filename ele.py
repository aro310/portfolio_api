# ele.py
import requests
import base64
import itertools

# Liste des clés API
ELEVENLABS_API_KEYS = [
    "sk_b15828ef829138a668570cf2e049bbee8b474c79dbc5e8e6",
    "sk_55524b9c3e4677f0e279ec7db556e1d9d9e3b90a5329e83e",
    "sk_b15828ef829138a668570cf2e049bbee8b474c79dbc5e8e6"
]

# Générateur circulaire (A → B → C → A → ...)
api_keys_cycle = itertools.cycle(ELEVENLABS_API_KEYS)

def generate_audio_base64(texte):
    api_key = next(api_keys_cycle)  # clé suivante à chaque appel

    voice_id = "SOYHLrjzK2X1ezoPC6cr"
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": api_key
    }

    data = {
        "text": texte,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.5
        }
    }

    response = requests.post(url, json=data, headers=headers)

    if response.status_code != 200:
        print(f"Erreur ElevenLabs ({response.status_code}): {response.text}")
        return None

    return base64.b64encode(response.content).decode("utf-8")
