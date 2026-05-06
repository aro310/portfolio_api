import requests
import json
import urllib.parse
import smtplib
import os
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
MODEL_NAME = "llama-3.3-70b-versatile"
URL = "https://api.groq.com/openai/v1/chat/completions"

# ── Mots déclencheurs des flows ──────────────────────────────────────────────
MEETING_TRIGGERS = [
    "meeting", "rdv", "rendez-vous", "rendez vous",
    "programmer", "planifier", "réunion", "reunion",
    "scheduled", "schedule", "fixer un rendez"
]

CONTACT_TRIGGERS = [
    "contacter", "contacter aro", "envoyer message", "envoyer un message",
    "email", "mail", "devis", "collaboration", "recruter", "embaucher",
    "travailler avec", "te contacter", "vous contacter"
]

# ── Questions signatures de chaque étape ─────────────────────────────────────
MEETING_QUESTIONS = {
    1: ["objet du meeting", "objet du rdv", "objet"],
    2: ["quelle date", "pour quelle date", "quel jour"],
    3: ["quelle heure", "combien de temps", "à quelle heure"],
}

CONTACT_QUESTIONS = {
    1: ["c'est quoi ton nom", "ton nom", "quel est ton nom"],
    2: ["ton adresse email", "adresse email", "ton email", "c'est quoi ton adresse"],
    3: ["ton message pour aro", "message pour aro", "c'est quoi ton message"],
}


# ── Scraping web ─────────────────────────────────────────────────────────────
def scrape_web_context(query: str) -> str:
    try:
        encoded_query = urllib.parse.quote_plus(query + " football news")
        search_url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/91.0.4472.124 Safari/537.36"
            )
        }
        response = requests.get(search_url, headers=headers, timeout=3)
        if response.status_code != 200:
            return ""
        soup = BeautifulSoup(response.text, "html.parser")
        results = []
        snippets = soup.find_all("a", class_="result__snippet")
        for snippet in snippets[:4]:
            text = snippet.get_text(strip=True)
            if text:
                results.append(f"- {text}")
        return "\n".join(results)
    except Exception as e:
        print(f"Erreur Scraping: {e}")
        return ""


# ── Email local ──────────────────────────────────────────────────────────────
def send_email_to_aro(from_name: str, from_email: str, message: str) -> str:
    """Envoie un email à Aro depuis le chatbot."""
    try:
        gmail_user = os.environ.get("GMAIL_USER", "aroratovoharison@gmail.com")
        gmail_pass = os.environ.get("GMAIL_APP_PASSWORD", "")
        body = (
            f"Message reçu via le chatbot de ton portfolio !\n\n"
            f"De : {from_name}\n"
            f"Email : {from_email}\n\n"
            f"Message :\n{message}"
        )
        msg = MIMEMultipart()
        msg["From"] = gmail_user
        msg["To"] = gmail_user
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
                "Utilise cet outil uniquement quand tu as collecté le nom, "
                "l'email ET le message du visiteur."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from_name":  {"type": "string", "description": "Nom complet du visiteur"},
                    "from_email": {"type": "string", "description": "Adresse email du visiteur"},
                    "message":    {"type": "string", "description": "Message complet à transmettre à Aro"},
                },
                "required": ["from_name", "from_email", "message"],
            },
        },
    }
]
LOCAL_TOOL_NAMES = {t["function"]["name"] for t in LOCAL_TOOLS}


# ── Machine à états de la conversation ───────────────────────────────────────
def detect_conversation_state(history: list, current_prompt: str) -> dict:
    """
    Analyse l'historique pour détecter si on est dans un flow actif
    et à quelle étape on en est.

    Retourne : {"flow": "meeting"|"contact"|None, "step": 1|2|3|4, "data": {...}}
      - step 1 = on vient de détecter le déclencheur, on va poser la 1ère question
      - step 2 = la 1ère question a été posée, on a reçu la réponse, on va poser la 2ème
      - step 3 = la 2ème question a été posée, on a reçu la réponse, on va poser la 3ème
      - step 4 = toutes les données sont là, on doit appeler l'outil
    """

    # ── 1. Remonte l'historique pour trouver la dernière question posée ──────
    flow = None
    last_question_step = None

    for i in range(len(history) - 1, -1, -1):
        msg = history[i]
        if msg["role"] != "assistant":
            continue
        content_lower = msg["content"].lower()

        # Cherche une question signature de meeting
        for step_num, keywords in MEETING_QUESTIONS.items():
            if any(k in content_lower for k in keywords):
                flow = "meeting"
                last_question_step = step_num
                break

        # Cherche une question signature de contact
        if not flow:
            for step_num, keywords in CONTACT_QUESTIONS.items():
                if any(k in content_lower for k in keywords):
                    flow = "contact"
                    last_question_step = step_num
                    break

        if flow:
            break  # on a trouvé la dernière question posée

    # ── 2. Si un flow est actif, la prochaine étape = dernière question + 1 ──
    if flow and last_question_step is not None:
        next_step = last_question_step + 1

        # Collecte les réponses utilisateur depuis le déclencheur du flow
        user_answers = _collect_user_answers(history, flow)

        data = {}
        if flow == "meeting":
            if len(user_answers) > 0: data["objet"] = user_answers[0]
            if len(user_answers) > 1: data["date"]  = user_answers[1]
            if len(user_answers) > 2: data["heure"] = user_answers[2]
        elif flow == "contact":
            if len(user_answers) > 0: data["nom"]     = user_answers[0]
            if len(user_answers) > 1: data["email"]   = user_answers[1]
            if len(user_answers) > 2: data["message"] = user_answers[2]

        return {"flow": flow, "step": next_step, "data": data}

    # ── 3. Aucun flow actif dans l'historique → vérifie le message actuel ────
    prompt_lower = current_prompt.lower()
    if any(k in prompt_lower for k in MEETING_TRIGGERS):
        return {"flow": "meeting", "step": 1, "data": {}}
    if any(k in prompt_lower for k in CONTACT_TRIGGERS):
        return {"flow": "contact", "step": 1, "data": {}}

    return {"flow": None, "step": 0, "data": {}}


def _collect_user_answers(history: list, flow: str) -> list:
    """
    Collecte les réponses de l'utilisateur après le déclenchement du flow,
    en alternance avec les questions de l'assistant.
    """
    # Trouve l'index du premier message assistant qui contient une question du flow
    first_question_idx = None
    questions_map = MEETING_QUESTIONS if flow == "meeting" else CONTACT_QUESTIONS

    for i, msg in enumerate(history):
        if msg["role"] == "assistant":
            content_lower = msg["content"].lower()
            for keywords in questions_map.values():
                if any(k in content_lower for k in keywords):
                    first_question_idx = i
                    break
        if first_question_idx is not None:
            break

    if first_question_idx is None:
        return []

    # Collecte les messages utilisateur qui suivent la première question
    answers = []
    for msg in history[first_question_idx + 1:]:
        if msg["role"] == "user":
            answers.append(msg["content"])

    return answers


# ── Construction du bloc d'état injecté dans le system prompt ────────────────
def build_state_block(state: dict) -> str:
    flow = state["flow"]
    step = state["step"]
    data = state["data"]

    if not flow:
        return ""

    if flow == "meeting":
        if step == 1:
            next_action = "→ Réponds UNIQUEMENT : \"C'est quoi l'objet du meeting ?\""
        elif step == 2:
            next_action = "→ Réponds UNIQUEMENT : \"C'est pour quelle date ?\""
        elif step == 3:
            next_action = "→ Réponds UNIQUEMENT : \"À quelle heure, et ça dure combien de temps ?\""
        else:
            next_action = (
                f"→ APPELLE L'OUTIL Create_an_event IMMÉDIATEMENT avec :\n"
                f"  - objet : \"{data.get('objet', '')}\"\n"
                f"  - date  : \"{data.get('date', '')}\"\n"
                f"  - heure : \"{data.get('heure', data.get('heure', ''))}\"\n"
                f"  N'écris rien d'autre avant d'appeler l'outil."
            )
        return f"""
╔══════════════════════════════════════════════════════╗
║         FLOW ACTIF : MEETING — ÉTAPE {step}/4          ║
╚══════════════════════════════════════════════════════╝
Tu collectes les infos pour créer un meeting. NE DÉVIE PAS DU FLOW.
Données déjà collectées : {json.dumps(data, ensure_ascii=False)}

PROCHAINE ACTION OBLIGATOIRE :
{next_action}

RÈGLES ABSOLUES :
- Ne pose PAS d'autre question que celle indiquée.
- Ne change PAS de sujet.
- Ne demande PAS de précisions supplémentaires.
- La réponse de l'utilisateur EST la donnée demandée, accepte-la telle quelle.
"""

    elif flow == "contact":
        if step == 1:
            next_action = "→ Réponds UNIQUEMENT : \"C'est quoi ton nom ?\""
        elif step == 2:
            next_action = "→ Réponds UNIQUEMENT : \"C'est quoi ton adresse email ?\""
        elif step == 3:
            next_action = "→ Réponds UNIQUEMENT : \"C'est quoi ton message pour Aro ?\""
        else:
            next_action = (
                f"→ APPELLE L'OUTIL send_email_to_aro IMMÉDIATEMENT avec :\n"
                f"  - from_name  : \"{data.get('nom', '')}\"\n"
                f"  - from_email : \"{data.get('email', '')}\"\n"
                f"  - message    : \"{data.get('message', '')}\"\n"
                f"  N'écris rien d'autre avant d'appeler l'outil."
            )
        return f"""
╔══════════════════════════════════════════════════════╗
║         FLOW ACTIF : CONTACT — ÉTAPE {step}/4          ║
╚══════════════════════════════════════════════════════╝
Tu collectes les infos pour envoyer un email à Aro. NE DÉVIE PAS DU FLOW.
Données déjà collectées : {json.dumps(data, ensure_ascii=False)}

PROCHAINE ACTION OBLIGATOIRE :
{next_action}

RÈGLES ABSOLUES :
- Ne pose PAS d'autre question que celle indiquée.
- Ne change PAS de sujet.
- Ne demande PAS de précisions supplémentaires.
- La réponse de l'utilisateur EST la donnée demandée, accepte-la telle quelle.
"""

    return ""


# ── Fonction principale ───────────────────────────────────────────────────────
def chat_with_gemini(prompt: str, history: list = None):
    history = history or []

    # 1. Scraping conditionnel (football / sport uniquement)
    web_context = ""
    keywords_web = ["score", "match", "résultat", "transfert", "joueur",
                    "classement", "news", "actu", "qui a gagné"]
    if any(k in prompt.lower() for k in keywords_web):
        print("Scraping en cours...")
        web_data = scrape_web_context(prompt)
        if web_data:
            web_context = (
                f"\n[INFO DU WEB EN TEMPS RÉEL - {datetime.now().year}]:\n{web_data}\n"
                "Utilise ces infos pour répondre si elles sont pertinentes."
            )

    # 2. Date en français
    _jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    _mois  = ["janvier", "février", "mars", "avril", "mai", "juin",
               "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    _now = datetime.now()
    current_date = f"{_jours[_now.weekday()]} {_now.day:02d} {_mois[_now.month - 1]} {_now.year}"

    # 3. Détecte l'état de la conversation
    state = detect_conversation_state(history, prompt)
    state_block = build_state_block(state)

    # 4. System prompt
    if state_block:
        # On est dans un flow actif → le system prompt est ultra-directif
        system_instruction = f"""Tu es l'assistant IA du portfolio de Aro Fortunat.
Date : {current_date}. Fuseau : UTC+3. Langue : Français. Tutoiement.

{state_block}"""
    else:
        # Mode normal → assistant portfolio
        system_instruction = f"""Tu es l'assistant IA du portfolio de Aro Fortunat, développeur Full-Stack & expert n8n basé à Madagascar.
Date : {current_date}. Fuseau : UTC+3. Langue : Français. Tutoiement.

RÈGLE GÉNÉRALE : Réponds en 1 à 2 phrases courtes (max 30 mots). Reste focalisé sur le portfolio d'Aro.

À propos d'Aro Fortunat :
- Développeur Full-Stack (React, Next.js, Node.js, Python, FastAPI)
- Expert en automatisation avec n8n et intégrations IA
- Basé à Madagascar, disponible en remote
- Services : développement web, automatisation, chatbots IA, intégrations API

=== DÉCLENCHEURS DE FLOW ===
Si le visiteur mentionne : {", ".join(MEETING_TRIGGERS)}
  → Réponds UNIQUEMENT : "C'est quoi l'objet du meeting ?"

Si le visiteur mentionne : {", ".join(CONTACT_TRIGGERS)}
  → Réponds UNIQUEMENT : "C'est quoi ton nom ?"

Pour tout le reste → réponds directement en 1-2 phrases sur le portfolio d'Aro.

=== MÉMOIRE ===
Ne repose JAMAIS une question déjà posée dans l'historique."""

    # 5. Construction des messages
    messages = [{"role": "system", "content": system_instruction}]
    if history:
        messages.extend(history)

    final_prompt = f"{web_context}\n\nQuestion: {prompt}" if web_context else prompt
    messages.append({"role": "user", "content": final_prompt})

    # 6. Chargement des tools (locaux + MCP)
    tools = list(LOCAL_TOOLS)
    try:
        from mcp_service import mcp_service
        mcp_tools = mcp_service.get_tools()
        if mcp_tools:
            for t in mcp_tools:
                tools.append({
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.inputSchema,
                    },
                })
    except Exception as e:
        print(f"Erreur chargement outils MCP: {e}")

    # 7. Payload Groq
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": 0.2,   # plus bas = plus déterministe dans les flows
        "max_tokens": 400,
        "top_p": 0.9,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    # 8. Appel API
    try:
        response = requests.post(URL, headers=headers, data=json.dumps(payload), timeout=20)

        if response.status_code != 200:
            return {"response": f"Erreur API ({response.status_code}): {response.text}", "action": None}

        result = response.json()
        message = result["choices"][0]["message"]

        # ── Gestion du Tool Calling ──────────────────────────────────────────
        if message.get("tool_calls"):
            tool_call = message["tool_calls"][0]
            call_name = tool_call["function"]["name"]
            call_args = json.loads(tool_call["function"]["arguments"])
            print(f"Outil appelé : {call_name} | Args : {call_args}")

            # Détecte le type d'action pour le frontend
            action_type = None
            call_name_lower = call_name.lower()
            if "calendar" in call_name_lower or "agenda" in call_name_lower or "event" in call_name_lower:
                action_type = "open_calendar"
            elif "mail" in call_name_lower or "gmail" in call_name_lower or "email" in call_name_lower:
                action_type = "open_email"

            # Dispatch : tool local ou MCP ?
            if call_name in LOCAL_TOOL_NAMES:
                if call_name == "send_email_to_aro":
                    mcp_result_string = send_email_to_aro(
                        from_name=call_args.get("from_name", ""),
                        from_email=call_args.get("from_email", ""),
                        message=call_args.get("message", ""),
                    )
                    action_type = "email_sent"
                else:
                    mcp_result_string = "Tool local exécuté."
            else:
                try:
                    from mcp_service import mcp_service
                    mcp_res = mcp_service.execute_tool(call_name, call_args)
                    text_results = []
                    if mcp_res and getattr(mcp_res, "content", None):
                        for content_item in mcp_res.content:
                            if content_item.type == "text":
                                text_results.append(content_item.text)
                    mcp_result_string = "\n".join(text_results) if text_results else "Tool executed."
                except Exception as e:
                    mcp_result_string = f"Erreur MCP: {str(e)}"

            # Deuxième appel avec le résultat de l'outil
            messages.append(message)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": mcp_result_string,
            })
            payload["messages"] = messages

            response_2 = requests.post(URL, headers=headers, data=json.dumps(payload), timeout=30)
            if response_2.status_code != 200:
                return {
                    "response": f"Erreur API 2ème passe ({response_2.status_code}): {response_2.text}",
                    "action": action_type,
                }

            result_2 = response_2.json()
            content_2 = result_2["choices"][0]["message"].get("content")

            # Fallback si le modèle ne génère pas de texte
            if not content_2:
                if "event" in call_name.lower() or "calendar" in call_name.lower():
                    content_2 = "L'événement a été créé avec succès dans le calendrier d'Aro !"
                elif "email" in call_name.lower() or "mail" in call_name.lower():
                    content_2 = "Ton message a bien été envoyé à Aro !"
                else:
                    content_2 = "C'est fait !"

            return {"response": content_2, "action": action_type}

        # ── Réponse texte normale ────────────────────────────────────────────
        else:
            content = message.get("content") or "Bonjour ! Comment puis-je t'aider ?"
            return {"response": content, "action": None}

    except (KeyError, IndexError, TypeError) as e:
        print("Erreur parsing réponse:", e)
        return {"response": "Désolé, une erreur est survenue. Réessaie !", "action": None}
    except Exception as e:
        return {"response": f"Erreur interne : {str(e)}", "action": None}