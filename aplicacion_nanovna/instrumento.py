from __future__ import annotations
import time
import numpy as np
import serial
from .configuracion import registro
from .parseo import _entero_s32, _entero_u16, _lineas_contienen_error, _parsear_datos_complejos, _parsear_barrido_directo
from .puertos import obtener_puerto

class NanoVNA:

    def __init__(self, puerto: str | None=None):
        self.dev = puerto or obtener_puerto()
        self.ser: serial.Serial | None = None
        self.puntos = 101
        self._frequencies: np.ndarray | None = None
        self.wait = 0.05

    def abrir(self) -> None:
        if self.ser is None:
            try:
                self.ser = serial.Serial(self.dev, baudrate=115200, timeout=1.0, write_timeout=1.0)
                time.sleep(0.25)
                try:
                    self.ser.reset_input_buffer()
                    self.ser.reset_output_buffer()
                except Exception:
                    pass
            except Exception as exc:
                self.ser = None
                raise OSError(f'No se pudo abrir el puerto {self.dev}: {exc}') from exc

    def cerrar(self) -> None:
        if self.ser:
            self.ser.close()
        self.ser = None

    def _enviar_comando(self, s: str) -> None:
        self._ejecutar(s.strip(), espera=self.wait)
        return

    def _ejecutar(self, comando: str, espera: float | None=None) -> list[str]:
        self.abrir()
        w = self.wait if espera is None else espera
        try:
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
        except Exception:
            pass
        cmd = f'{comando}\r'
        self.ser.write(cmd.encode('ascii', errors='ignore'))
        time.sleep(w)
        res: list[str] = []
        deadline = time.monotonic() + max(3.0, min(12.0, self.puntos * 0.04))
        while time.monotonic() < deadline:
            line_b = self.ser.readline()
            if not line_b:
                time.sleep(w)
                continue
            line = line_b.decode('ascii', errors='ignore').strip()
            if line == comando:
                continue
            if line.startswith('ch>'):
                break
            res.append(line)
        return res

    def _ejecutar(self, comando: str, espera: float | None=None) -> list[str]:
        w = max(0.02, self.wait if espera is None else float(espera))
        cmd_text = comando.strip()
        last_exc: Exception | None = None
        for intento in range(2):
            try:
                self.abrir()
                if self.ser is None:
                    raise serial.SerialException('Puerto serie no abierto')
                try:
                    self.ser.reset_input_buffer()
                    self.ser.reset_output_buffer()
                except Exception:
                    pass
                self.ser.write(f'{cmd_text}\r'.encode('ascii', errors='ignore'))
                try:
                    self.ser.flush()
                except Exception:
                    pass
                time.sleep(w)
                res: list[str] = []
                timeout_cmd = max(4.0, min(18.0, self.puntos * 0.08))
                if cmd_text.startswith('scan'):
                    timeout_cmd = max(timeout_cmd, min(20.0, self.puntos * 0.12))
                deadline = time.monotonic() + timeout_cmd
                while time.monotonic() < deadline:
                    line_b = self.ser.readline()
                    if not line_b:
                        time.sleep(w)
                        continue
                    line = line_b.decode('ascii', errors='ignore').strip()
                    if not line or line == cmd_text:
                        continue
                    if line.startswith('ch>'):
                        return res
                    res.append(line)
                return res
            except (serial.SerialException, OSError) as exc:
                last_exc = exc
                registro.warning('Error serie en comando %s (intento %s): %s', cmd_text, intento + 1, exc)
                try:
                    self.cerrar()
                except Exception:
                    pass
                time.sleep(0.25)
        if last_exc is not None:
            raise last_exc
        return []

    def configurar_frecuencias_barrido(self, frecuencia_inicial_hz: float, frecuencia_final_hz: float, puntos: int) -> None:
        self.puntos = int(puntos)
        self._frequencies = np.linspace(frecuencia_inicial_hz, frecuencia_final_hz, self.puntos)

    def establecer_espera(self, espera: float) -> None:
        if espera <= 0:
            return
        self.wait = float(espera)

    def configurar_barrido(self, frecuencia_inicial_hz: float, frecuencia_final_hz: float) -> None:
        pts = getattr(self, 'points', None)
        if pts is None:
            pts = 101
            self.puntos = pts
        self._enviar_comando(f'sweep {int(frecuencia_inicial_hz)} {int(frecuencia_final_hz)} {int(pts)}')

    def leer_respuesta_datos(self) -> str:
        res: list[str] = []
        linea = b''
        while True:
            ch = self.ser.read(1)
            if not ch:
                break
            if ch == b'\r':
                continue
            linea += ch
            if ch == b'\n':
                res.append(linea.decode('utf-8', errors='ignore'))
                linea = b''
            if linea.endswith(b'ch>'):
                break
        return ''.join(res)

    def leer_datos(self, arreglo: int) -> np.ndarray:
        try:
            lines = self._ejecutar(f'data {arreglo}')
        except Exception as exc:
            registro.exception('Error al solicitar datos', exc_info=exc)
            lines = []
        out = _parsear_datos_complejos(lines)
        return np.array(out, np.complex128)

    def obtener_frecuencias(self) -> None:
        try:
            lines = self._ejecutar('frequencies')
        except Exception as exc:
            registro.exception('Error al obtener frecuencias', exc_info=exc)
            lines = []
        frecuencias: list[float] = []
        for ln in lines:
            t = ln.strip()
            if not t:
                continue
            try:
                frecuencias.append(float(t))
            except Exception:
                continue
        if frecuencias:
            self._frequencies = np.array(frecuencias)
        elif self._frequencies is None or len(self._frequencies) == 0:
            self._frequencies = np.array([])
        else:
            registro.warning('El comando frequencies no devolvio datos; se conserva el barrido configurado.')

    def enviar_barrido(self, frecuencia_inicial_hz: float, frecuencia_final_hz: float, puntos: int | None=None) -> list[str]:
        pts = int(puntos) if puntos else None
        if pts:
            comando_scan = f'scan {int(frecuencia_inicial_hz)} {int(frecuencia_final_hz)} {pts}'
            comando_sweep = f'sweep {int(frecuencia_inicial_hz)} {int(frecuencia_final_hz)} {pts}'
        else:
            comando_scan = f'scan {int(frecuencia_inicial_hz)} {int(frecuencia_final_hz)}'
            comando_sweep = f'sweep {int(frecuencia_inicial_hz)} {int(frecuencia_final_hz)}'
        try:
            lineas = self._ejecutar(comando_scan, espera=max(self.wait, 0.08))
        except Exception as exc:
            registro.warning('Fallo scan con parametros: %s', exc)
            lineas = []
        directo0, directo1 = _parsear_barrido_directo(lineas)
        if directo0 and directo1:
            return lineas
        if lineas and (not _lineas_contienen_error(lineas)):
            return lineas
        try:
            self._ejecutar(comando_sweep, espera=max(self.wait, 0.08))
            return self._ejecutar('scan', espera=max(self.wait, 0.08))
        except Exception as exc:
            registro.warning('Fallo scan por sweep+scan: %s', exc)
            return lineas

    def medir_parametros_s(self) -> tuple[np.ndarray, np.ndarray]:
        seg = 101
        if self._frequencies is None:
            self.obtener_frecuencias()
        frecuencias = self._frequencies
        if frecuencias is None or len(frecuencias) == 0:
            return (np.array([], np.complex128), np.array([], np.complex128))
        a0: list[complex] = []
        a1: list[complex] = []
        i = 0
        n = len(frecuencias)
        while i < n:
            s = frecuencias[i]
            j = min(i + seg - 1, n - 1)
            e = frecuencias[j]
            count = j - i + 1
            lineas_scan = self.enviar_barrido(s, e, count)
            directo0, directo1 = _parsear_barrido_directo(lineas_scan)
            if len(directo0) >= count and len(directo1) >= count:
                a0.extend(directo0[:count])
                a1.extend(directo1[:count])
                i += seg
                continue
            try:
                vals0 = _parsear_datos_complejos(self._ejecutar('data 0'))
            except Exception as exc:
                registro.warning('No se pudo leer data 0: %s', exc)
                vals0 = []
            try:
                vals1 = _parsear_datos_complejos(self._ejecutar('data 1'))
            except Exception as exc:
                registro.warning('No se pudo leer data 1: %s', exc)
                vals1 = []
            if vals0 and vals1:
                a0.extend(vals0[:count])
                a1.extend(vals1[:count])
            elif directo0 and directo1:
                a0.extend(directo0[:count])
                a1.extend(directo1[:count])
            i += seg
        try:
            self._ejecutar('resume')
        except Exception:
            pass
        return (np.array(a0, np.complex128), np.array(a1, np.complex128))

    @property
    def frecuencias(self) -> np.ndarray | None:
        return self._frequencies

class NanoVNAV2(NanoVNA):

    def __init__(self, puerto: str | None=None):
        super().__init__(puerto)
        self.sweepStartHz = 1000000.0
        self.sweepStopHz = 900000000.0
        self.puntos = 1000
        self.sweepData: list[tuple[complex, complex]] = [(0 + 0j, 0 + 0j)] * self.puntos

    def configurar_barrido(self, frecuencia_inicial_hz: float, frecuencia_final_hz: float, puntos: int) -> None:
        self.sweepStartHz = float(frecuencia_inicial_hz)
        self.sweepStopHz = float(frecuencia_final_hz)
        self.puntos = int(puntos)
        self.sweepData = [(0 + 0j, 0 + 0j)] * self.puntos
        self.abrir()
        step = 0 if self.puntos <= 1 else int(round((self.sweepStopHz - self.sweepStartHz) / (self.puntos - 1)))
        self._reiniciar_protocolo()
        self._escribir_registro8(0, int(round(self.sweepStartHz)))
        self._escribir_registro8(16, step)
        self._escribir_registro2(32, self.puntos)
        self._limpiar_fifo()

    def obtener_frecuencias(self) -> None:
        self._frequencies = np.linspace(self.sweepStartHz, self.sweepStopHz, self.puntos)

    def _reiniciar_protocolo(self) -> None:
        self.abrir()
        self.ser.write(b'\x00' * 8)

    def _escribir_registro(self, op: int, addr: int, value: int, nbytes: int) -> None:
        self.abrir()
        self.ser.write(bytes([op, addr]) + int(value).to_bytes(nbytes, 'little', signed=False))

    def _escribir_registro2(self, addr: int, value: int) -> None:
        self._escribir_registro(33, addr, value, 2)

    def _escribir_registro8(self, addr: int, value: int) -> None:
        self._escribir_registro(35, addr, value, 8)

    def _limpiar_fifo(self) -> None:
        self.abrir()
        self.ser.write(b' 0\x00')

    def _leer_fifo(self, puntos: int) -> bytes:
        self.abrir()
        datos = bytearray()
        restantes = int(puntos)
        deadline_total = time.monotonic() + max(4.0, min(30.0, puntos * 0.15))
        while restantes > 0:
            bloque = min(255, restantes)
            self.ser.write(bytes([24, 48, bloque]))
            esperado = bloque * 32
            chunk = bytearray()
            while len(chunk) < esperado and time.monotonic() < deadline_total:
                parte = self.ser.read(esperado - len(chunk))
                if parte:
                    chunk.extend(parte)
                else:
                    time.sleep(0.02)
            if len(chunk) != esperado:
                raise IOError(f'Lectura incompleta del NanoVNA-V2: {len(chunk)}/{esperado} bytes')
            datos.extend(chunk)
            restantes -= bloque
        return bytes(datos)

    def _ejecutar_barrido(self) -> None:
        self.abrir()
        self._limpiar_fifo()
        time.sleep(max(0.15, min(3.0, self.puntos * 0.025)))
        buf = self._leer_fifo(self.puntos)
        for i in range(self.puntos):
            b = buf[i * 32:(i + 1) * 32]
            re_fwd = _entero_s32(b[0:4])
            im_fwd = _entero_s32(b[4:8])
            re_ref = _entero_s32(b[8:12])
            im_ref = _entero_s32(b[12:16])
            re_thr = _entero_s32(b[16:20])
            im_thr = _entero_s32(b[20:24])
            indice = _entero_u16(b[24:26])
            fwd = complex(re_fwd, im_fwd)
            param_s11 = complex(re_ref, im_ref) / fwd if fwd != 0 else 0.0
            param_s21 = complex(re_thr, im_thr) / fwd if fwd != 0 else 0.0
            pos = indice if 0 <= indice < self.puntos else i
            self.sweepData[pos] = (param_s11, param_s21)

    def medir_parametros_s(self) -> tuple[np.ndarray, np.ndarray]:
        if self._frequencies is None:
            self.obtener_frecuencias()
        self._ejecutar_barrido()
        param_s11 = np.array([p[0] for p in self.sweepData], np.complex128)
        param_s21 = np.array([p[1] for p in self.sweepData], np.complex128)
        return (param_s11, param_s21)
