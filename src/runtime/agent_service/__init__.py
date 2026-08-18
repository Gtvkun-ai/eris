"""Local WebSocket bridge giữa Eris brain và IDE clients."""

from .ide_rpc import IdeRpcBroker
from .websocket_server import AgentWebSocketService

__all__ = ["AgentWebSocketService", "IdeRpcBroker"]
