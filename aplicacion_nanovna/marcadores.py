from __future__ import annotations
import numpy as np

def _valor_marcador_db(arreglo: np.ndarray | None, indice: int | None) -> float | None:
    try:
        if arreglo is None or indice is None:
            return None
        if indice < 0 or indice >= len(arreglo):
            return None
        valor = arreglo[indice]
        if not np.isfinite(valor):
            return None
        return float(20.0 * np.log10(max(abs(valor), 1e-15)))
    except Exception:
        return None

def construir_lineas_marcadores(frecuencias_mhz: np.ndarray, parametros: dict[str, np.ndarray | None], marcadores: list[tuple[str, int | None]], parametros_visibles: tuple[str, ...]=('S11', 'S21')) -> list[str]:
    lineas: list[str] = []
    valores: list[tuple[float, dict[str, float | None]]] = []
    try:
        frecuencias = np.asarray(frecuencias_mhz, dtype=float)
    except Exception:
        return lineas
    for etiqueta, indice in marcadores:
        try:
            if indice is None or indice < 0 or indice >= len(frecuencias):
                continue
            frecuencia = float(frecuencias[indice])
            valores_parametro: dict[str, float | None] = {}
            partes = [f'{etiqueta}: {frecuencia:.2f} MHz']
            for nombre in parametros_visibles:
                valor_db = _valor_marcador_db(parametros.get(nombre), indice)
                valores_parametro[nombre] = valor_db
                if valor_db is not None:
                    partes.append(f'{nombre}: {valor_db:+.1f} dB')
            lineas.append(' | '.join(partes))
            valores.append((frecuencia, valores_parametro))
        except Exception:
            continue
    if len(valores) >= 2:
        f1, v1 = valores[0]
        f2, v2 = valores[1]
        partes_delta = [f'Δf: {f2 - f1:+.2f} MHz']
        for nombre in parametros_visibles:
            valor_1 = v1.get(nombre)
            valor_2 = v2.get(nombre)
            if valor_1 is not None and valor_2 is not None:
                partes_delta.append(f'Δ{nombre}: {valor_2 - valor_1:+.1f} dB')
        if len(partes_delta) > 1:
            lineas.append(' | '.join(partes_delta))
    return lineas
