from typing import Any

from sio import SocketIOConsumer
from sio.socketio import NamespaceSocket
from sio.consumer import Ack

class MainSocketIOConsumer(SocketIOConsumer):
    namespace = "/"

    async def connect(self, socket: NamespaceSocket, auth: Any) -> bool:
        # Equivalent to:
        #   socket.emit("auth", socket.handshake.auth);z
        await socket.emit("auth", auth)
        return True  # allow the connection

    async def event_message(
        self,
        socket: NamespaceSocket,
        *args: Any,
        ack: Ack | None = None,
    ) -> None:
        # Equivalent to:
        #   socket.on("message", (...args) => {
        #     socket.emit("message-back", ...args);
        #   });
        await socket.emit("message-back", *args)
        # no ack behavior here in the Node version

    async def event_message_with_ack(
        self,
        socket: NamespaceSocket,
        *args: Any,
        ack: Ack | None = None,
    ) -> None:
        # Equivalent to:
        #   socket.on("message-with-ack", (...args) => {
        #     const ack = args.pop();
        #     ack(...args);
        #   });
        if ack is not None:
            await ack(*args)


class CustomSocketIOConsumer(SocketIOConsumer):
    namespace: str = "/custom"

    async def connect(self, socket: NamespaceSocket, auth: Any) -> bool:
        await socket.emit("auth", auth)
        return True

