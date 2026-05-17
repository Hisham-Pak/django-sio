Tutorial Part 1: Basic setup
============================

In this part you create or prepare a Django project for Socket.IO traffic.

Create a project
----------------

Start with a normal Django project and app:

.. code-block:: bash

   django-admin startproject config .
   python manage.py startapp chat

Install the package once published:

.. code-block:: bash

   pip install django-sio

Configure Channels
------------------

Add Channels and your app to Django settings:

.. code-block:: python

   INSTALLED_APPS = [
       "daphne",
       "django.contrib.admin",
       "django.contrib.auth",
       "django.contrib.contenttypes",
       "django.contrib.sessions",
       "django.contrib.messages",
       "django.contrib.staticfiles",
       "channels",
       "chat",
   ]

   ASGI_APPLICATION = "config.asgi.application"

For the tutorial, use the in-memory channel layer:

.. code-block:: python

   CHANNEL_LAYERS = {
       "default": {
           "BACKEND": "channels.layers.InMemoryChannelLayer",
       }
   }

The channel layer is used for Socket.IO room broadcasting. The in-memory layer
is enough for a single-process tutorial server.

Run migrations
--------------

Run normal Django migrations:

.. code-block:: bash

   python manage.py migrate

At this point the project is still an ordinary Django project. In the next part
you add a Socket.IO consumer.
