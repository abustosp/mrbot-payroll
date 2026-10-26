"""Interfaz web Jinja2 + HTMX sobre AdminLTE 4.

El coordinador debe montar el router en ``app/main.py``::

    from app.web.routes import router as web_router

    app.include_router(web_router)

Los estilos y el JavaScript local se sirven desde el propio router, por lo que
no hace falta configurar ``StaticFiles`` ni depender de CDN para que la
interfaz funcione sin red.
"""

from app.web.routes import router

__all__ = ["router"]
