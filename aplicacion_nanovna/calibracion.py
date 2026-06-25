from __future__ import annotations
import numpy as np

class CalibracionSOL:

    def __init__(self) -> None:
        self.m_abierto: np.ndarray | None = None
        self.m_corto: np.ndarray | None = None
        self.m_carga: np.ndarray | None = None
        self.Ed: np.ndarray | None = None
        self.Es: np.ndarray | None = None
        self.Er: np.ndarray | None = None
        self.aplicada: bool = False

    def limpiar_mediciones(self) -> None:
        self.m_abierto = self.m_corto = self.m_carga = None
        self.Ed = self.Es = self.Er = None

    def limpiar_todo(self) -> None:
        self.limpiar_mediciones()
        self.aplicada = False

    def tiene_todo(self) -> bool:
        return self.m_abierto is not None and self.m_corto is not None and (self.m_carga is not None)

    def calcular(self) -> bool:
        if not self.tiene_todo():
            return False
        mo = self.m_abierto
        ms = self.m_corto
        ml = self.m_carga
        Ed = ml
        R = mo - Ed
        S = ms - Ed
        eps = 1e-18
        R = np.where(np.abs(R) < eps, eps + 0j, R)
        S = np.where(np.abs(S) < eps, eps + 0j, S)
        den_er = S - R
        den_es = R - S
        den_er = np.where(np.abs(den_er) < eps, eps + 0j, den_er)
        den_es = np.where(np.abs(den_es) < eps, eps + 0j, den_es)
        Er = 2.0 * R * S / den_er
        Es = (R + S) / den_es
        self.Ed, self.Es, self.Er = (Ed, Es, Er)
        return True

    def corregir_medicion_sol(self, m: np.ndarray) -> np.ndarray:
        if not self.aplicada or self.Ed is None or self.Es is None or (self.Er is None):
            return m
        Ed, Es, Er = (self.Ed, self.Es, self.Er)
        num = m - Ed
        den = Er + Es * num
        eps = 1e-18
        den = np.where(np.abs(den) < eps, eps + 0j, den)
        return num / den

class CalibracionSOLT(CalibracionSOL):

    def __init__(self) -> None:
        super().__init__()
        self.m_paso: np.ndarray | None = None
        self.factor_paso: np.ndarray | None = None

    def limpiar_mediciones(self) -> None:
        super().limpiar_mediciones()
        self.m_paso = None
        self.factor_paso = None

    def limpiar_todo(self) -> None:
        super().limpiar_todo()
        self.m_paso = None
        self.factor_paso = None

    def tiene_todo(self) -> bool:
        return self.m_abierto is not None and self.m_corto is not None and (self.m_carga is not None) and (self.m_paso is not None)

    def calcular(self) -> bool:
        if not self.tiene_todo():
            return False
        super().calcular()
        self.factor_paso = self.m_paso.copy() if self.m_paso is not None else None
        return True

    def aplicar_reflexion(self, m: np.ndarray) -> np.ndarray:
        return super().corregir_medicion_sol(m)

    def corregir_transmision_thru(self, m: np.ndarray) -> np.ndarray:
        if not self.aplicada or self.factor_paso is None:
            return m
        eps = 1e-18
        denom = np.where(np.abs(self.factor_paso) < eps, eps + 0j, self.factor_paso)
        return m / denom
