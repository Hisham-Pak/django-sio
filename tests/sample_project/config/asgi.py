"""
ASGI config for sample_project project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/

"""

from django.core.asgi import get_asgi_application
from django.urls import re_path

application = get_asgi_application()

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator

from sample_project.sampleapp.consumers import LiveMessageConsumer
from sample_project.socketiotestsuiteapp.consumers import MainSocketIOConsumer, CustomSocketIOConsumer

application = ProtocolTypeRouter(
    {
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(
                URLRouter(
                    [
                        re_path(
                            r"^socket\.io/?$", LiveMessageConsumer.as_asgi()
                        ),
                        re_path(
                            r"^testsuitesocket\.io/?$", MainSocketIOConsumer.as_asgi()
                        ),
                        re_path(
                            r"^testsuitecustomsocket\.io/?$", CustomSocketIOConsumer.as_asgi()
                        ),
                    ]
                )
            )
        ),
        "http": AuthMiddlewareStack(
            URLRouter(
                [
                    re_path(r"^socket\.io/?$", LiveMessageConsumer.as_asgi()),
                    re_path(
                        r"^testsuitesocket\.io/?$", MainSocketIOConsumer.as_asgi()
                    ),
                    re_path(
                        r"^testsuitecustomsocket\.io/?$", CustomSocketIOConsumer.as_asgi()
                    ),
                    # Catch-all: send everything else (like /admin/login/) to Django
                    re_path("", application),
                ]
            )
        ),
    }
)
