import json
from mcp_service import mcp_service

def pretty(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)

print("🔍 Starting MCP debug...\n")

tools = mcp_service.get_tools()
print(f"Got {len(tools)} tools.\n")

for t in tools:
    print("=" * 50)
    print(f"🧰 TOOL NAME: {t.name}")
    print("=" * 50)

    print("\n📦 INPUT SCHEMA:")
    print(pretty(t.inputSchema))

    # tentative de debug runtime
    for attr in ["messages", "logs", "history", "events"]:
        if hasattr(t, attr):
            print(f"\n📜 {attr.upper()}:")
            print(pretty(getattr(t, attr)))

print("\n✅ Debug finished.")