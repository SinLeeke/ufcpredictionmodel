"""
Pruebas del proyecto. Se corren desde la raíz:

    python -m unittest discover -s tests -t .

Van con la biblioteca estándar (unittest) a propósito: no agregan dependencias
al requirements.txt de un proyecto que corre en un PC personal.

La RED QUEDA BLOQUEADA para toda la corrida. Una prueba que dependa de que
UFCStats o Betano respondan no prueba el código, prueba internet, y además
haría peticiones reales cada vez que alguien la corre. Si algo intenta salir,
recibe un ConnectionError, que es justo lo que el código ya sabe manejar.
"""
import requests


def _sin_red(*args, **kwargs):
    raise requests.ConnectionError("red bloqueada durante las pruebas")


requests.get = requests.post = requests.request = _sin_red
requests.Session.request = _sin_red
