import requests
import json
import urllib.parse
from bs4 import BeautifulSoup
import os

# --- CONFIGURATION ---
# Use Env var or fallback
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")

# On passe sur gemini-1.5-flash car il gère les Tools MCP beaucoup mieux que Gemma.
MODEL_NAME = "gemini-2.0-flash"

URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={GOOGLE_API_KEY}"

def scrape_web_context(query: str) -> str:
    """
    Scrape les résultats de recherche via DuckDuckGo (Version HTML légère).
    C'est plus rapide et moins bloqué que Google pour du scraping serveur.
    """
    try:
        # On nettoie la requête pour l'URL
        encoded_query = urllib.parse.quote_plus(query + " football news")
        search_url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

        # Headers pour ressembler à un vrai navigateur (Indispensable pour ne pas être bloqué)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        

        # Timeout court (3s) pour ne pas faire laguer Vercel
        response = requests.get(search_url, headers=headers, timeout=3)
        
        if response.status_code != 200:
            return ""

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extraction des snippets (les résumés de recherche)
        results = []
        # DuckDuckGo HTML utilise souvent la classe 'result__snippet'
        snippets = soup.find_all('a', class_='result__snippet')
        
        for snippet in snippets[:4]: # On prend seulement les 4 premiers pour limiter la taille
            text = snippet.get_text(strip=True)
            if text:
                results.append(f"- {text}")
        
        return "\n".join(results)

    except Exception as e:
        print(f"Erreur Scraping: {e}")
        return "" # En cas d'erreur, on renvoie vide pour ne pas bloquer le chat

from mcp_service import mcp_service

def chat_with_gemini(prompt: str, history: list = None) -> str:
    # 1. Scraping des infos récentes (Grounding Manuel)
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
    system_instruction = (
        f"Tu es Aro, assistant personnel intelligent et expert football. Tu as accès à des outils externes MCP (n8n, Google Agenda). "
        f"Nous sommes le {current_date}. \n\n"
        "RÈGLES STRICTES POUR L'AGENDA :\n"
        "- Si l'utilisateur demande son agenda, programme, ou événements, TU DOIS ABSOLUMENT utiliser ton outil Google Calendar.\n"
        "- NE TENTE JAMAIS D'INVENTER ou de deviner des événements (comme des séances d'entraînement), utilise OBLIGATOIREMENT l'outil pour obtenir les vraies données.\n"
        "- Attends le retour de l'outil avant d'affirmer quoi que ce soit sur le planning de l'utilisateur.\n\n"
        "Réponds de manière directe, factuelle et sympa (tutoiement). "
        "Pas de 'Bonjour' répétitif. Max 3 phrases par réponse."
    )

    # 3. Construction du Payload
    contents = []
    
    if history:
        contents.extend(history)
    
    final_prompt = f"{system_instruction}\n{web_context}\n\nQuestion: {prompt}"

    contents.append({
        "role": "user",
        "parts": [{"text": final_prompt}]
    })

    # 4. Intégration MCP Tools
    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 300,
            "topP": 0.9
        }
    }
    
    def clean_schema_for_gemini(schema):
        if isinstance(schema, dict):
            schema.pop("$schema", None)
            schema.pop("additionalProperties", None)
            for key, value in schema.items():
                schema[key] = clean_schema_for_gemini(value)
        elif isinstance(schema, list):
            for i in range(len(schema)):
                schema[i] = clean_schema_for_gemini(schema[i])
        return schema

    try:
        mcp_tools = mcp_service.get_tools()
        if mcp_tools:
            formatted_tools = []
            for t in mcp_tools:
                clean_params = clean_schema_for_gemini(t.inputSchema)
                formatted_tools.append({
                    "name": t.name,
                    "description": t.description,
                    "parameters": clean_params
                })
            payload["tools"] = [{"functionDeclarations": formatted_tools}]
    except Exception as e:
        print(f"Erreur lors du chargement des outils MCP: {e}")

    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(URL, headers=headers, data=json.dumps(payload), timeout=20)
        
        if response.status_code != 200:
            return f"Erreur API ({response.status_code}): {response.text}"

        result = response.json()
        
        try:
            part = result['candidates'][0]['content']['parts'][0]
            
            # Gestion du Function Calling (Outil MCP)
            if 'functionCall' in part:
                call_name = part['functionCall']['name']
                call_args = part['functionCall'].get('args', {})
                print(f"Utilisation de l'outil n8n: {call_name}")
                
                # Exécution via n8n MCP
                mcp_res = mcp_service.execute_tool(call_name, call_args)
                
                text_results = []
                if mcp_res and getattr(mcp_res, 'content', None):
                    for content_item in mcp_res.content:
                        if content_item.type == "text":
                            text_results.append(content_item.text)
                
                mcp_result_string = "\n".join(text_results) if text_results else "Tool executed."

                # Deuxième appel vers Gemini avec le résultat
                contents.append({"role": "model", "parts": [part]})
                contents.append({
                    "role": "function",
                    "parts": [{
                        "functionResponse": {
                            "name": call_name,
                            "response": { 
                                "name": call_name, 
                                "content": mcp_result_string 
                            }
                        }
                    }]
                })
                
                payload["contents"] = contents
                
                # Refaire la requête avec la réponse de l'outil
                response_2 = requests.post(URL, headers=headers, data=json.dumps(payload), timeout=30)
                if response_2.status_code != 200:
                    return f"Erreur API 2ème passe ({response_2.status_code}): {response_2.text}"
                
                result_2 = response_2.json()
                return result_2['candidates'][0]['content']['parts'][0]['text']
            
            else:
                return part['text']
            
        except (KeyError, IndexError, TypeError) as e:
            print("Erreur parsing Gemini part:", result, e)
            return "Pas de réponse lisible du modèle."

    except Exception as e:
        return f"Erreur interne : {str(e)}"