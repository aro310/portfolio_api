import requests
import json
import urllib.parse
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
MODEL_NAME = "llama-3.3-70b-versatile"
URL = "https://api.groq.com/openai/v1/chat/completions"

def scrape_web_context(query: str) -> str:
    try:
        encoded_query = urllib.parse.quote_plus(query + " football news")
        search_url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
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

# ── Email local (sans n8n) ───────────────────────────────────────────────────
def send_email_to_aro(from_name: str, from_email: str, message: str) -> str:
    """Envoie un email à Aro depuis le chatbot."""
    try:
        gmail_user = os.environ.get("GMAIL_USER", "aroratovoharison@gmail.com")
        gmail_pass = os.environ.get("GMAIL_APP_PASSWORD", "")
        body = f"Message reçu via le chatbot de ton portfolio !····\n\nDe : {from_name}\nEmail : {from_email}\n\nMessage :\n{message}"
        msg = MIMEMultipart()
        msg["From"] = gmail_user
        msg["To"]   = gmail_user
        msg["Subject"] = f"[Portfolio Chatbot] Message de {from_name}"
        msg["Reply-To"] = from_email
        msg.attach(MIMEText(body, "plain"))
        if gmail_pass:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(gmail_user, gmail_pass)
                server.sendmail(gmail_user, gmail_user, msg.as_string())
            return f"Email envoyé avec succès à Aro de la part de {from_name}."
        else:
            print(f"[DEV] Email simulé de {from_name} ({from_email}): {message}")
            return f"[Mode dev] Email simulé — Aro a bien reçu ton message."
    except Exception as e:
        return f"Erreur envoi email: {str(e)}"

# ── Définition des tools locaux (appelés directement, pas via MCP) ──────────
LOCAL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "send_email_to_aro",
            "description": "Envoie un email à Aro Fortunat au nom du visiteur. Utilise cet outil quand le visiteur veut contacter Aro, envoyer un message, ou demander un devis. Tu dois collecter le nom, email et message du visiteur avant d'appeler cet outil.",
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
    current_date = "Lundi 26 Janvier 2026"
    from datetime import datetime
    import locale

    try:
        locale.setlocale(locale.LC_TIME, 'fr_FR.UTF-8')
    except:
        locale.setlocale(locale.LC_TIME, '')

    current_date = datetime.now().strftime("%A %d %B %Y")

    system_instruction = (
        f"Tu es Aro, l'assistant IA intégré au portfolio de Aro Fortunat, développeur Full-Stack et expert n8n. "
        f"Tu parles au nom d'Aro et tu accueilles les visiteurs de son portfolio. "
        f"Nous sommes le {current_date}.\n\n"
        "FUSEAU HORAIRE : UTC+3 (Madagascar). "
        "Toutes les heures sont en UTC+3. Format ISO 8601 avec +03:00 (ex: '2026-05-06T10:00:00+03:00').\n\n"
        "TES CAPACITÉS :\n"
        "1. PROGRAMMER UN RENDEZ-VOUS : Si le visiteur veut rencontrer Aro, prendre RDV ou planifier une réunion, "
        "utilise l'outil Google Calendar pour créer un événement dans le calendrier d'Aro. "
        "Demande d'abord le nom, la date souhaitée et l'heure.\n"
        "2. ENVOYER UN EMAIL À ARO : Si le visiteur veut contacter Aro, envoyer un message, demander un devis ou une collaboration, "
        "utilise l'outil send_email_to_aro. Collecte d'abord le nom, email et message du visiteur, "
        "puis compose un email professionnel et envoie-le. Aro recevra l'email dans sa boîte Gmail.\n"
        "3. AGENDA : Si Aro lui-même demande son planning, utilise Get_many_events_in_Google_Calendar.\n\n"
        "RÈGLES :\n"
        "- Propose spontanément ces deux services aux visiteurs intéressés par Aro.\n"
        "- NE JAMAIS inventer des événements, utilise TOUJOURS l'outil Calendar.\n"
        "- Réponds en français, de manière directe et sympa (tutoiement). Max 3 phrases."
    )

    # 3. Construction des messages (format OpenAI)
    messages = [{"role": "system", "content": system_instruction}]

    if history:
        messages.extend(history)

    final_prompt = f"{web_context}\n\nQuestion: {prompt}" if web_context else prompt
    messages.append({"role": "user", "content": final_prompt})

    # 4. Intégration ALL Tools = MCP + locaux
    tools = list(LOCAL_TOOLS)  # on commence avec les tools locaux
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

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(URL, headers=headers, data=json.dumps(payload), timeout=20)

        if response.status_code != 200:
            return f"Erreur API ({response.status_code}): {response.text}"

        result = response.json()
        message = result['choices'][0]['message']

        # Gestion du Tool Calling (MCP)
        if message.get('tool_calls'):
            tool_call = message['tool_calls'][0]
            call_name = tool_call['function']['name']
            
            # --- LOG START: ACTION DETECTION FOR FRONTEND ---
            action_type = None
            call_name_lower = call_name.lower()
            if 'calendar' in call_name_lower or 'agenda' in call_name_lower:
                action_type = "open_calendar"
            elif 'mail' in call_name_lower or 'gmail' in call_name_lower or 'email' in call_name_lower:
                action_type = "open_email"
            # --- LOG END ---
            
            call_args = json.loads(tool_call['function']['arguments'])
            print(f"Utilisation de l'outil: {call_name}")

            # ── Dispatch : local ou MCP ? ──────────────────────────────────
            if call_name in LOCAL_TOOL_NAMES:
                # Appel local direct (pas besoin de MCP)
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
                # Exécution via MCP (n8n)
                mcp_res = mcp_service.execute_tool(call_name, call_args)
                text_results = []
                if mcp_res and getattr(mcp_res, 'content', None):
                    for content_item in mcp_res.content:
                        if content_item.type == "text":
                            text_results.append(content_item.text)
                mcp_result_string = "\n".join(text_results) if text_results else "Tool executed."

            # Deuxième appel avec le résultat de l'outil
            messages.append(message)  # réponse du modèle avec tool_call
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call['id'],
                "content": mcp_result_string
            })

            payload["messages"] = messages

            response_2 = requests.post(URL, headers=headers, data=json.dumps(payload), timeout=30)
            if response_2.status_code != 200:
                return f"Erreur API 2ème passe ({response_2.status_code}): {response_2.text}"

            result_2 = response_2.json()
            return {"response": result_2['choices'][0]['message']['content'], "action": action_type}

        else:
            return {"response": message['content'], "action": None}

    except (KeyError, IndexError, TypeError) as e:
        print("Erreur parsing réponse:", result, e)
        return "Pas de réponse lisible du modèle."
    except Exception as e:
        return f"Erreur interne : {str(e)}"