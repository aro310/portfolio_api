import asyncio
from typing import List, Dict, Any
from mcp.client.sse import sse_client
from mcp.client.session import ClientSession
import os

N8N_MCP_SERVER_URL = os.environ.get("N8N_MCP_SERVER_URL", "")

class MCPService:
    def __init__(self, url: str):
        self.url = url

    async def get_tools_async(self) -> List[Any]:
        try:
            async with sse_client(self.url) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    response = await session.list_tools()
                    return response.tools
        except Exception as e:
            print(f"Erreur MCP get_tools_async: {e}")
            return []

    async def execute_tool_async(self, tool_name: str, args: Dict[str, Any]) -> Any:
        try:
            async with sse_client(self.url) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    response = await session.call_tool(tool_name, arguments=args)
                    return response
        except Exception as e:
            print(f"Erreur MCP execute_tool_async: {e}")
            return None

    def get_tools(self) -> List[Any]:
        """ Récupère les outils de n8n de manière synchrone """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return loop.run_until_complete(self.get_tools_async())
        except RuntimeError:
            pass
        return asyncio.run(self.get_tools_async())

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        """ Exécute un outil n8n de manière synchrone """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return loop.run_until_complete(self.execute_tool_async(tool_name, args))
        except RuntimeError:
            pass
        return asyncio.run(self.execute_tool_async(tool_name, args))

mcp_service = MCPService(N8N_MCP_SERVER_URL)
