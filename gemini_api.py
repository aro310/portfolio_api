import requests
import json
import urllib.parse
import smtplib
import os
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
_GROQ_KEYS = [k.strip() for k in os.environ.get("GROQ_API_KEYS", "").split(",") if k.strip()]

if not _GROQ_KEYS:
    legacy = os.environ.get("GROQ_API_KEY", "")
    if legacy:
        _GROQ_KEYS = [legacy]

if not _GROQ_KEYS:
    raise ValueError("Aucune clé Groq trouvée. Définis GROQ_API_KEYS dans Vercel.")

MODEL_NAME = "llama-3.3-70b-versatile"
URL = "https://api.groq.com/openai/v1/chat/completions"

# ── Rotation des clés Groq (thread-safe) ─────────────────────────────────────
_key_index = 0
_key_lock  = threading.Lock()

def get_next_key() -> str:
    global _key_index
    with _key_lock:
        key = _GROQ_KEYS[_key_index % len(_GROQ_KEYS)]
        _key_index += 1
    return key

def _call_groq(payload: dict, timeout: int = 20) -> dict:
    last_error = None
    tried = 0
    total = len(_GROQ_KEYS)

    while tried < total:
        key = get_next_key()
        tried += 1
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }
        try:
            resp = requests.post(URL, headers=headers, data=json.dumps(payload), timeout=timeout)

            if resp.status_code == 429:
                print(f"[ROTATION] Clé {key[:8]}... épuisée (429), passage à la suivante.")
                last_error = "quota_exceeded"
                continue

            if resp.status_code != 200:
                # Try to extract a clean error code without raw JSON
                try:
                    err_body = resp.json()
                    err_code = err_body.get("error", {}).get("code", "")
                    err_type = err_body.get("error", {}).get("type", "")
                    if err_code == "organization_restricted" or "restricted" in str(err_body):
                        raise RuntimeError("api_restricted")
                    last_error = f"HTTP {resp.status_code} ({err_code or err_type})"
                except RuntimeError:
                    raise
                except Exception:
                    last_error = f"HTTP {resp.status_code}"
                continue

            return resp.json()

        except RuntimeError:
            raise  # propagate clean errors upward immediately
        except requests.exceptions.Timeout:
            last_error = "timeout"
            continue
        except Exception as e:
            last_error = str(e)
            continue

    raise RuntimeError("all_keys_exhausted")

# ── Web scraping ──────────────────────────────────────────────────────────────
def scrape_web_context(query: str) -> str:
    try:
        encoded_query = urllib.parse.quote_plus(query + " football news")
        search_url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(search_url, headers=headers, timeout=3)
        if response.status_code != 200:
            return ""
        soup = BeautifulSoup(response.text, 'html.parser')
        results = []
        snippets = soup.find_all('a', class_='result__snippet')
        for snippet in snippets[:4]:
            text = snippet.get_text(strip=True)
            if text:
                results.append(f"- {text}")
        return "\n".join(results)
    except Exception as e:
        print(f"Erreur Scraping: {e}")
        return ""

from mcp_service import mcp_service

# ── Email local ───────────────────────────────────────────────────────────────
def send_email_to_aro(from_name: str, from_email: str, message: str) -> str:
    try:
        gmail_user = os.environ.get("GMAIL_USER", "aroratovoharison@gmail.com")
        gmail_pass = os.environ.get("GMAIL_APP_PASSWORD", "")
        body = (
            f"Message reçu via le chatbot de ton portfolio !\n\n"
            f"De : {from_name}\nEmail : {from_email}\n\nMessage :\n{message}"
        )
        msg = MIMEMultipart()
        msg["From"]     = gmail_user
        msg["To"]       = gmail_user
        msg["Subject"]  = f"[Portfolio Chatbot] Message de {from_name}"
        msg["Reply-To"] = from_email
        msg.attach(MIMEText(body, "plain"))

        if gmail_pass:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(gmail_user, gmail_pass)
                server.sendmail(gmail_user, gmail_user, msg.as_string())
            return f"Email envoyé avec succès à Aro de la part de {from_name}."
        else:
            print(f"[DEV] Email simulé de {from_name} ({from_email}): {message}")
            return "[Mode dev] Email simulé — Aro a bien reçu ton message."
    except Exception as e:
        return f"Erreur envoi email: {str(e)}"

# ── Définition des tools locaux ───────────────────────────────────────────────
LOCAL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "send_email_to_aro",
            "description": (
                "Envoie un email à Aro Fortunat au nom du visiteur. "
                "Utilise cet outil quand le visiteur veut contacter Aro, envoyer un message, "
                "ou demander un devis. Tu dois collecter le nom, email et message du visiteur "
                "avant d'appeler cet outil."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from_name":  {"type": "string", "description": "Nom complet du visiteur"},
                    "from_email": {"type": "string", "description": "Adresse email du visiteur"},
                    "message":    {"type": "string", "description": "Message complet à transmettre à Aro"}
                },
                "required": ["from_name", "from_email", "message"]
            }
        }
    }
]
LOCAL_TOOL_NAMES = {t["function"]["name"] for t in LOCAL_TOOLS}

# ── Fonction principale ───────────────────────────────────────────────────────
def chat_with_gemini(prompt: str, history: list = None):

    # 1. Scraping des infos récentes
    web_context = ""
    keywords = ["score", "match", "résultat", "transfert", "joueur", "classement", "news", "actu", "qui"]
    if any(k in prompt.lower() for k in keywords):
        print("Scraping en cours...")
        web_data = scrape_web_context(prompt)
        if web_data:
            web_context = (
                f"\n[INFO DU WEB EN TEMPS RÉEL - UPDATE 2026]:\n{web_data}\n"
                "Utilise ces infos pour répondre si elles sont pertinentes."
            )

    # 2. Setup Persona
    from datetime import datetime
    _jours = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"]
    _mois  = ["janvier","février","mars","avril","mai","juin",
              "juillet","août","septembre","octobre","novembre","décembre"]
    _now = datetime.now()
    current_date = f"{_jours[_now.weekday()]} {_now.day:02d} {_mois[_now.month-1]} {_now.year}"

    system_instruction = f"""Tu es l'assistant IA du portfolio de Aro Fortunat (développeur & expert n8n, Madagascar).
Date actuelle : {current_date}. Fuseau horaire : UTC+3.

=== RÈGLE PREMIER MESSAGE ===
Si l'historique est vide (toute nouvelle session), commence TOUJOURS ta réponse par cette présentation COURTE, avant de répondre à la question :

"Je suis Aro, étudiant IDEV à l'ESTI. Je peux :
• 📅 Programmer un meeting (dis-moi l'objet, la date, l'heure et la durée)
• 📧 Contacter Aro par email (dis-moi ton nom, email et message)
• 💼 Te parler de mes services (web, automatisation n8n, IA)
• ❓ Répondre à tes questions sur mon portfolio"

Après cette intro, réponds directement à la question du visiteur.

RÈGLES STRICTES DE COMMUNICATION :
1. Réponds toujours en phrases courtes (maximum 2 phrases par réponse hors intro).
2. Ne fais jamais de mondanités (pas de "Ah super", "Très bien", "C'est noté").
3. Si on te pose une question, réponds directement SANS utiliser d'outil.
4. NE DÉCLENCHE UN OUTIL QUE SI ON TE DEMANDE EXPRESSÉMENT ET SI TU AS TOUTES LES INFOS.

=== RÈGLE PRIORITAIRE ===
Si le visiteur envoie un message hors-sujet PENDANT une collecte d'infos (meeting, email), réponds brièvement PUIS rappelle où tu en es.

=== PROCESSUS POUR PROGRAMMER UN MEETING ===
Si le visiteur demande un meeting/rendez-vous, applique CE DIALOGUE EXACT étape par étape :

Bot: "C'est quoi l'objet du meeting ?"
(Le visiteur répond l'objet)
Bot: "C'est pour quelle date ?"
(Le visiteur répond la date)
Bot: "À quelle heure, et ça dure combien de temps ?"
(Le visiteur répond)
Bot: [APPELLE L'OUTIL Create_an_event_in_Google_Calendar]

INTERDIT : Ne demande JAMAIS autre chose entre ces étapes.

=== PROCESSUS POUR CONTACTER/ENVOYER UN EMAIL ===
Si le visiteur veut envoyer un email/contacter :
1. "C'est quoi ton nom ?"
2. "C'est quoi ton adresse email ?"
3. "Quel est ton message ?"
4. [APPELLE L'OUTIL send_email_to_aro]

=== EXEMPLES ===
User: Bonjour
Bot: [intro complète] — puis "Bonjour ! Comment puis-je t'aider ?"

User: Je veux programmer un meeting
Bot: "C'est quoi l'objet du meeting ?"

User: Hackathon
Bot: "C'est pour quelle date ?"

User: 3 juin
Bot: "À quelle heure, et ça dure combien de temps ?"

User: 14h, 1 heure
Bot: [appelle Create_an_event_in_Google_Calendar]"""

    # 3. Construction des messages
    messages = [{"role": "system", "content": system_instruction}]
    if history:
        messages.extend(history)
    final_prompt = f"{web_context}\n\nQuestion: {prompt}" if web_context else prompt
    messages.append({"role": "user", "content": final_prompt})

    # 4. Chargement des outils MCP + locaux
    tools = list(LOCAL_TOOLS)
    try:
        mcp_tools = mcp_service.get_tools()
        if mcp_tools:
            for t in mcp_tools:
                tools.append({
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.inputSchema
                    }
                })
    except Exception as e:
        print(f"Erreur lors du chargement des outils MCP: {e}")

    # 5. Payload Groq
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 400,
        "top_p": 0.9
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    # 6. Premier appel — raises RuntimeError on API failure
    result = _call_groq(payload)

    try:
        message = result['choices'][0]['message']
    except (KeyError, IndexError, TypeError) as e:
        print("Erreur parsing réponse:", e)
        return {"response": "Désolé, une erreur est survenue. Réessaie !", "action": None}

    # 7. Gestion du Tool Calling
    if message.get('tool_calls'):
        tool_call  = message['tool_calls'][0]
        call_name  = tool_call['function']['name']
        call_args  = json.loads(tool_call['function']['arguments'])

        # Détection du type d'action pour le frontend
        action_type = None
        call_name_lower = call_name.lower()
        if 'calendar' in call_name_lower or 'agenda' in call_name_lower or 'event' in call_name_lower:
            action_type = "open_calendar"
        elif 'mail' in call_name_lower or 'gmail' in call_name_lower or 'email' in call_name_lower:
            action_type = "open_email"

        print(f"Utilisation de l'outil: {call_name} avec args: {call_args}")

        # Dispatch : local ou MCP ?
        if call_name in LOCAL_TOOL_NAMES:
            if call_name == "send_email_to_aro":
                mcp_result_string = send_email_to_aro(
                    from_name=call_args.get("from_name", ""),
                    from_email=call_args.get("from_email", ""),
                    message=call_args.get("message", "")
                )
                action_type = "email_sent"
            else:
                mcp_result_string = "Tool local exécuté."
        else:
            mcp_res = mcp_service.execute_tool(call_name, call_args)
            text_results = []
            if mcp_res and getattr(mcp_res, 'content', None):
                for content_item in mcp_res.content:
                    if content_item.type == "text":
                        text_results.append(content_item.text)
            mcp_result_string = "\n".join(text_results) if text_results else "Tool executed successfully."

        # ── FIX 2 : safe_message — évite que tool_calls soit sérialisé comme JSON brut ──
        safe_message = {
            "role": "assistant",
            "content": message.get("content") or "",
            "tool_calls": message.get("tool_calls")
        }
        messages.append(safe_message)
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call['id'],
            "content": mcp_result_string
        })
        payload["messages"] = messages

        # Deuxième appel
        result_2 = _call_groq(payload, timeout=30)
        if "error" in result_2:
            return result_2["error"]

        try:
            content_2 = result_2['choices'][0]['message'].get('content')
        except (KeyError, IndexError, TypeError):
            content_2 = None

        # ── FIX 2 : fallback si content vide ou JSON brut ──
        if not content_2 or content_2.strip().startswith("{"):
            if 'calendar' in call_name_lower or 'event' in call_name_lower:
                content_2 = "L'événement a été créé avec succès dans le calendrier d'Aro !"
            elif 'email' in call_name_lower or 'mail' in call_name_lower:
                content_2 = "L'email a été envoyé à Aro !"
            else:
                content_2 = "C'est fait !"

        return {"response": content_2, "action": action_type}

    else:
        content = message.get('content') or "Bonjour ! Comment puis-je t'aider ?"
        return {"response": content, "action": None}