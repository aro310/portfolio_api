import json
from gemini_api import chat_with_gemini
from mcp_service import mcp_service

print("Testing MCP tools fetch directly...")
try:
    tools = mcp_service.get_tools()
    print("Found tools:", len(tools))
    for t in tools:
        print(" -", t.name)
except Exception as e:
    print("Failed fetching tools:", e)

print("\nTesting chat with gemini...")
prompt = "Quelles sont les dernières actualités sur le football mondial ? Utilise tes outils si nécessaire."
response = chat_with_gemini(prompt)
print("\nResponse:")
print(response)
