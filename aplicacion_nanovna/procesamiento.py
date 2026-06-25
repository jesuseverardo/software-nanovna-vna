from __future__ import annotations
import numpy as np
from .configuracion import registro

def limpiar_parametro_s(arreglo: np.ndarray | None, mascara: np.ndarray | None=None, quitar_ultimo: bool=True) -> np.ndarray | None:
    if arreglo is None:
        return None
    try:
        arreglo_filtrado = arreglo[mascara] if mascara is not None else arreglo
    except Exception as exc:
        registro.exception('Failed to apply mask to S‑parameter array', exc_info=exc)
        arreglo_filtrado = arreglo
    if quitar_ultimo and len(arreglo_filtrado) > 1:
        arreglo_filtrado = arreglo_filtrado[:-1]
    return arreglo_filtrado

def recortar_frecuencias(arreglo: np.ndarray | None, frecuencias_mhz_completas: np.ndarray) -> np.ndarray:
    if arreglo is None or len(arreglo) == 0:
        return np.array([])
    n = min(len(frecuencias_mhz_completas), len(arreglo))
    return frecuencias_mhz_completas[:n]

def calcular_metricas_parametro_s(arreglo: np.ndarray | None, frecuencias_mhz_completas: np.ndarray) -> dict[str, np.ndarray | tuple[np.ndarray, np.ndarray]]:
    arreglo_s = arreglo if arreglo is None else arreglo
    frecuencias_recortadas = recortar_frecuencias(arreglo_s, frecuencias_mhz_completas)
    magnitud = np.array([])
    valores_fase = np.array([])
    angulo = np.array([])
    radio = np.array([])
    reales_smith = np.array([])
    imag_smith = np.array([])
    if arreglo is not None and len(arreglo):
        try:
            magnitud = 20 * np.log10(np.maximum(np.abs(arreglo), 1e-15))
            magnitud = magnitud[:len(frecuencias_recortadas)]
        except Exception as exc:
            registro.exception('Failed to compute magnitude', exc_info=exc)
            magnitud = np.array([])
        try:
            valores_fase = (np.angle(arreglo) * 180.0 / np.pi)[:len(frecuencias_recortadas)]
        except Exception as exc:
            registro.exception('Failed to compute phase', exc_info=exc)
            valores_fase = np.array([])
        try:
            angulo = np.angle(arreglo)[:len(frecuencias_recortadas)]
            radio = np.abs(arreglo)[:len(frecuencias_recortadas)]
        except Exception as exc:
            registro.exception('Failed to compute polar coordinates', exc_info=exc)
            angulo = np.array([])
            radio = np.array([])
        try:
            mascara = np.abs(arreglo) > 1e-15
            reales_smith = np.real(arreglo[mascara])
            imag_smith = np.imag(arreglo[mascara])
        except Exception as exc:
            registro.exception('Failed to compute Smith chart coordinates', exc_info=exc)
            reales_smith = np.array([])
            imag_smith = np.array([])
    return {'freq': frecuencias_recortadas, 'mag': magnitud, 'phase': valores_fase, 'polar': (angulo, radio), 'smith': (reales_smith, imag_smith)}

def calcular_metricas_analisis(frecuencias_mhz: np.ndarray, param_s11: np.ndarray | None, param_s21: np.ndarray | None) -> dict[str, float | None]:
    metricas: dict[str, float | None] = {'min_return_db': None, 'min_return_freq': None, 'max_gain_db': None, 'max_gain_freq': None, 'bw3db': None, 'bw3db_low': None, 'bw3db_high': None}
    if param_s11 is not None and len(param_s11) and len(frecuencias_mhz):
        try:
            mag_s11_db = 20.0 * np.log10(np.maximum(np.abs(param_s11), 1e-15))
            indice_min = int(np.argmin(mag_s11_db))
            metricas['min_return_db'] = float(mag_s11_db[indice_min])
            metricas['min_return_freq'] = float(frecuencias_mhz[indice_min])
        except Exception as exc:
            registro.exception('Error computing return loss metrics', exc_info=exc)
    if param_s21 is not None and len(param_s21) and len(frecuencias_mhz):
        try:
            mag_s21_db = 20.0 * np.log10(np.maximum(np.abs(param_s21), 1e-15))
            indice_max = int(np.argmax(mag_s21_db))
            max_db = float(mag_s21_db[indice_max])
            metricas['max_gain_db'] = max_db
            metricas['max_gain_freq'] = float(frecuencias_mhz[indice_max])
            target = max_db - 3.0
            above = np.where(mag_s21_db >= target)[0]
            if above.size >= 2:
                f_low = float(frecuencias_mhz[int(above[0])])
                f_high = float(frecuencias_mhz[int(above[-1])])
                metricas['bw3db'] = f_high - f_low
                metricas['bw3db_low'] = f_low
                metricas['bw3db_high'] = f_high
        except Exception as exc:
            registro.exception('Error computing insertion gain metrics', exc_info=exc)
    return metricas

def _limpiar_traza(frecuencias_mhz: np.ndarray, param_s11: np.ndarray, param_s21: np.ndarray, eps: float=1e-12):
    try:
        finite_mask = np.isfinite(param_s11) & np.isfinite(param_s21)
        fmhz_f = frecuencias_mhz[finite_mask]
        s11_f = param_s11[finite_mask]
        s21_f = param_s21[finite_mask]
    except Exception:
        fmhz_f, s11_f, s21_f = (frecuencias_mhz, param_s11, param_s21)
    if len(fmhz_f) > 1:
        return (fmhz_f[:-1], s11_f[:-1], s21_f[:-1])
    return (fmhz_f, s11_f, s21_f)
