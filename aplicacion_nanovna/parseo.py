from __future__ import annotations
from .configuracion import _NUMERO_RE

def _entero_u16(b: bytes) -> int:
    return int.from_bytes(b[0:2], 'little', signed=False)

def _entero_s32(b: bytes) -> int:
    return int.from_bytes(b[0:4], 'little', signed=True)

def _numeros_en_linea(linea: str) -> list[float]:
    texto = str(linea or '').replace(',', ' ')
    valores: list[float] = []
    for m in _NUMERO_RE.findall(texto):
        try:
            valores.append(float(m))
        except Exception:
            continue
    return valores

def _lineas_contienen_error(lineas: list[str]) -> bool:
    texto = '\n'.join(lineas).lower()
    pistas = ('usage', 'invalid', 'unknown', 'error', 'fail', 'unrecognized', 'not supported', 'argument')
    return any((p in texto for p in pistas))

def _parsear_datos_complejos(lineas: list[str]) -> list[complex]:
    valores: list[complex] = []
    for ln in lineas:
        nums = _numeros_en_linea(ln)
        if len(nums) < 2:
            continue
        idx = 0
        if len(nums) >= 3 and (abs(nums[0]) > 1000 or nums[0].is_integer()):
            idx = 1
        if len(nums) >= idx + 2:
            valores.append(float(nums[idx]) + 1j * float(nums[idx + 1]))
    return valores

def _parsear_barrido_directo(lineas: list[str]) -> tuple[list[complex], list[complex]]:
    a0: list[complex] = []
    a1: list[complex] = []
    for ln in lineas:
        nums = _numeros_en_linea(ln)
        if len(nums) < 4:
            continue
        idx = 1 if abs(nums[0]) > 1000 else 0
        if len(nums) >= 6 and abs(nums[1]) > 1000:
            idx = 2
        if len(nums) >= idx + 4:
            a0.append(float(nums[idx]) + 1j * float(nums[idx + 1]))
            a1.append(float(nums[idx + 2]) + 1j * float(nums[idx + 3]))
    return (a0, a1)
