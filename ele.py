# ele.py — ElevenLabs TTS with smart quota-aware key rotation
import requests
import base64
import os

# ── API Keys ──────────────────────────────────────────────────────────────────
# Load from env var (comma-separated) or fallback to hardcoded list
_env_keys = os.environ.get("ELEVENLABS_API_KEYS", "")
if _env_keys:
    ELEVENLABS_API_KEYS = [k.strip() for k in _env_keys.split(",") if k.strip()]
else:
    ELEVENLABS_API_KEYS = [
        "sk_33b9dee5ac3ac4e3c55b337d04d644816fcbf497dc93408e",
        "sk_b15828ef829138a668570cf2e049bbee8b474c79dbc5e8e6",
        "sk_55524b9c3e4677f0e279ec7db556e1d9d9e3b90a5329e83e",
        "sk_347b68e3aec98ee812e93934c9844c323356af05713ad9a0",
    ]

# Quota-exhausted keys are temporarily blacklisted to avoid repeated failures.
# Key: api_key string, Value: True if blacklisted
_blacklisted = set()

VOICE_ID = "SOYHLrjzK2X1ezoPC6cr"
TTS_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"


def _get_active_keys():
    """Return keys that are not yet blacklisted."""
    active = [k for k in ELEVENLABS_API_KEYS if k not in _blacklisted]
    if not active:
        # All keys exhausted — reset blacklist and try again (new billing cycle maybe?)
        _blacklisted.clear()
        active = list(ELEVENLABS_API_KEYS)
    return active


def generate_audio_base64(texte: str) -> str | None:
    """
    Try each active ElevenLabs API key in sequence.
    - On quota error (429 / 401) → blacklist that key and try the next one.
    - On other errors        → skip silently.
    - Returns base64 audio string, or None if all keys failed.
    """
    active_keys = _get_active_keys()

    for api_key in active_keys:
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": api_key,
        }
        payload = {
            "text": texte,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.5},
        }

        try:
            resp = requests.post(TTS_URL, json=payload, headers=headers, timeout=15)
        except requests.RequestException as e:
            print(f"[ElevenLabs] Network error with key …{api_key[-6:]}: {e}")
            continue

        if resp.status_code == 200:
            return base64.b64encode(resp.content).decode("utf-8")

        # Quota exceeded or auth failure → blacklist this key
        if resp.status_code in (401, 403, 429):
            print(f"[ElevenLabs] Key …{api_key[-6:]} blacklisted (HTTP {resp.status_code})")
            _blacklisted.add(api_key)
            continue

        # Other error (5xx etc.) — log briefly and skip
        print(f"[ElevenLabs] Key …{api_key[-6:]} failed HTTP {resp.status_code}")
        continue

    # All keys failed — caller should handle None gracefully
    print("[ElevenLabs] All keys exhausted. Returning None (text-only mode).")
    return None
