from __future__ import annotations
from aplicacion_nanovna.interfaz import vista_tiempo_real

def principal() -> None:
    vista_tiempo_real(inicio_hz=None, fin_hz=None, puntos=None, fps_interfaz=60, puerto_sugerido=None)
if __name__ == '__main__':
    principal()
