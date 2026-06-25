from __future__ import annotations
import numpy as np
from .configuracion import plt, registro

def dibujar_rejilla_smith(ax: plt.Axes) -> None:
    ax.set_aspect('equal', adjustable='box')
    ax.set_xlim(-1.1, 1.1)
    ax.set_ylim(-1.1, 1.1)
    angulo = np.linspace(0, 2 * np.pi, 600)
    ax.plot(np.cos(angulo), np.sin(angulo), linewidth=1.0, color='black')
    reales_smith = [0.2, 0.5, 1, 2, 5]
    for r in reales_smith:
        c = r / (1 + r)
        rad = 1 / (1 + r)
        phi = np.linspace(0, 2 * np.pi, 600)
        ax.plot(c + rad * np.cos(phi), rad * np.sin(phi), color='gray', linewidth=0.8)
    xs = [0.2, 0.5, 1, 2, 5]
    for x in xs:
        cy = 1 / x
        rad = 1 / abs(x)
        phi = np.linspace(-np.pi / 2, np.pi / 2, 400)
        ax.plot(1 + rad * np.cos(phi), cy + rad * np.sin(phi), color='gray', linewidth=0.8)
        ax.plot(1 + rad * np.cos(phi), -cy - rad * np.sin(phi), color='gray', linewidth=0.8)
    ax.axhline(0, color='black', linewidth=0.5)
    ax.set_xticks([])
    ax.set_yticks([])
SMITH_FONDO_ARCHIVO = 'fondo_carta_smith.png'
SMITH_FONDO_AUTO_RECORTAR = True
SMITH_FONDO_ESCALA_X = 1.05
SMITH_FONDO_ESCALA_Y = 1.0
SMITH_FONDO_DESPLAZAMIENTO_X = 0.007
SMITH_FONDO_DESPLAZAMIENTO_Y = 0.0
SMITH_LIMITE_EJES = 1.08

def _configurar_eje_smith(ax: plt.Axes) -> None:
    ax.set_xlim(-SMITH_LIMITE_EJES, SMITH_LIMITE_EJES)
    ax.set_ylim(-SMITH_LIMITE_EJES, SMITH_LIMITE_EJES)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_aspect('equal', adjustable='box')

def _extension_fondo_smith() -> tuple[float, float, float, float]:
    sx = float(SMITH_FONDO_ESCALA_X)
    sy = float(SMITH_FONDO_ESCALA_Y)
    dx = float(SMITH_FONDO_DESPLAZAMIENTO_X)
    dy = float(SMITH_FONDO_DESPLAZAMIENTO_Y)
    return (-sx + dx, sx + dx, -sy + dy, sy + dy)

def _recortar_margenes_claros(imagen: np.ndarray) -> np.ndarray:
    try:
        arr = np.asarray(imagen)
        if arr.ndim < 3 or arr.shape[0] < 20 or arr.shape[1] < 20:
            return imagen
        rgb = arr[..., :3].astype(float)
        if rgb.max(initial=0) > 1.0:
            rgb = rgb / 255.0
        rgb = np.clip(rgb, 0.0, 1.0)
        h, w = rgb.shape[:2]
        margen_y = max(2, int(h * 0.04))
        margen_x = max(2, int(w * 0.04))
        muestras_fondo = np.concatenate((rgb[:margen_y, :margen_x].reshape(-1, 3), rgb[:margen_y, -margen_x:].reshape(-1, 3), rgb[-margen_y:, :margen_x].reshape(-1, 3), rgb[-margen_y:, -margen_x:].reshape(-1, 3)), axis=0)
        color_fondo = np.median(muestras_fondo, axis=0)
        diferencia = np.max(np.abs(rgb - color_fondo), axis=2)
        mascara = diferencia > 0.035
        if arr.shape[-1] >= 4:
            alpha = arr[..., 3].astype(float)
            if alpha.max(initial=0) > 1.0:
                alpha = alpha / 255.0
            mascara &= alpha > 0.02
        ys, xs = np.where(mascara)
        if xs.size < 100 or ys.size < 100:
            return imagen
        pad_x = max(2, int(w * 0.006))
        pad_y = max(2, int(h * 0.006))
        x0 = max(0, int(xs.min()) - pad_x)
        x1 = min(w, int(xs.max()) + pad_x + 1)
        y0 = max(0, int(ys.min()) - pad_y)
        y1 = min(h, int(ys.max()) + pad_y + 1)
        if x1 - x0 > w * 0.985 and y1 - y0 > h * 0.985:
            return imagen
        return arr[y0:y1, x0:x1]
    except Exception as exc:
        registro.exception('No se pudo recortar la imagen Smith', exc_info=exc)
        return imagen

def preparar_imagen_fondo_smith(imagen: np.ndarray) -> np.ndarray:
    if SMITH_FONDO_AUTO_RECORTAR:
        return _recortar_margenes_claros(imagen)
    return imagen

def dibujar_imagen_fondo_smith(ax: plt.Axes, imagen: np.ndarray) -> None:
    ax.imshow(imagen, extent=_extension_fondo_smith(), origin='upper', zorder=0)
    _configurar_eje_smith(ax)
