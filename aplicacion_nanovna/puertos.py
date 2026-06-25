from __future__ import annotations
import os
import time
from pathlib import Path
import serial
from serial.tools import list_ports
from .configuracion import NOMBRE_MANUAL_USUARIO, VIDPIDS_VNA, registro

def _leer_serial_disponible(s: serial.Serial, duracion: float=0.7) -> bytes:
    fin = time.monotonic() + max(0.05, float(duracion))
    datos = bytearray()
    while time.monotonic() < fin:
        try:
            n = max(int(getattr(s, 'in_waiting', 0) or 0), 1)
            chunk = s.read(n)
        except (serial.SerialException, OSError):
            raise
        except Exception:
            chunk = b''
        if chunk:
            datos.extend(chunk)
            bajo = bytes(datos).lower()
            if b'ch>' in bajo or b'nanovna' in bajo:
                break
        else:
            time.sleep(0.03)
    return bytes(datos)

def detectar_tipo_vna(dev: str) -> str | None:
    try:
        with serial.Serial(dev, baudrate=115200, timeout=0.45, write_timeout=0.45) as s:
            time.sleep(0.2)
            try:
                s.reset_input_buffer()
                s.reset_output_buffer()
            except Exception:
                pass
            respuesta = bytearray()
            for cmd in (b'\r', b'version\r', b'info\r'):
                try:
                    s.write(cmd)
                    s.flush()
                except Exception:
                    break
                time.sleep(0.12)
                respuesta.extend(_leer_serial_disponible(s, 0.45))
                texto = respuesta.decode('ascii', errors='ignore').lower()
                if 'ch>' in texto or 'nanovna' in texto:
                    return 'text'
            try:
                s.reset_input_buffer()
                s.reset_output_buffer()
            except Exception:
                pass
            s.write(b'\x00' * 8)
            time.sleep(0.03)
            s.write(b'\r')
            s.flush()
            if s.read(1) == b'2':
                return 'v2'
    except Exception:
        return None
    return None

def _puerto_responde_como_vna(dev: str) -> bool:
    return detectar_tipo_vna(dev) is not None

def _directorio_script() -> Path:
    try:
        return Path(__file__).resolve().parent
    except Exception as exc:
        registro.exception('Falling back to current working directory for script directory', exc_info=exc)
        return Path(os.getcwd()).resolve()

def _leer_ultimo_puerto_arduino() -> str | None:
    try:
        p = _directorio_script() / '.last_arduino_port.txt'
        if p.exists():
            t = p.read_text(encoding='utf-8', errors='ignore').strip()
            return t or None
    except Exception as exc:
        registro.exception('Failed to read last Arduino port', exc_info=exc)
    return None

def _guardar_ultimo_puerto_arduino(puerto: str) -> None:
    try:
        p = _directorio_script() / '.last_arduino_port.txt'
        p.write_text(str(puerto).strip() + '\n', encoding='utf-8')
    except Exception as exc:
        registro.exception('Failed to write last Arduino port', exc_info=exc)

def _rutas_manual_usuario() -> list[Path]:
    candidatos = [_directorio_script() / NOMBRE_MANUAL_USUARIO, Path.cwd() / NOMBRE_MANUAL_USUARIO, Path.home() / 'Downloads' / NOMBRE_MANUAL_USUARIO]
    rutas: list[Path] = []
    for ruta in candidatos:
        ruta = ruta.expanduser()
        if ruta not in rutas:
            rutas.append(ruta)
    return rutas

def abrir_manual_usuario() -> None:
    rutas = _rutas_manual_usuario()
    for ruta in rutas:
        if not ruta.exists():
            continue
        try:
            iniciador = getattr(os, 'startfile', None)
            if iniciador is not None:
                iniciador(str(ruta))
            else:
                import subprocess
                import sys
                comando = ['open', str(ruta)] if sys.platform == 'darwin' else ['xdg-open', str(ruta)]
                subprocess.Popen(comando)
            return
        except Exception as exc:
            try:
                from tkinter import messagebox
                messagebox.showerror('Guía de usuario', f'No se pudo abrir el manual:\n{ruta}\n\n{exc}')
            except Exception:
                registro.exception('No se pudo abrir el manual', exc_info=exc)
            return
    try:
        from tkinter import messagebox
        ubicaciones = '\n'.join((str(ruta) for ruta in rutas))
        messagebox.showerror('Guía de usuario', f'No se encontró el manual de usuario.\n\nUbicaciones revisadas:\n{ubicaciones}')
    except Exception:
        registro.error('No se encontró el manual de usuario: %s', rutas)

def intentar_obtener_puerto() -> str | None:
    try:
        puertos = list(list_ports.comports())
    except Exception as exc:
        registro.exception('Error al obtener la lista de puertos', exc_info=exc)
        return None
    candidatos: list[str] = []

    def agregar(dev: str | None) -> None:
        if dev and dev not in candidatos:
            candidatos.append(dev)
    puertos_normales: list[list_ports.ListPortInfo] = []
    for d in puertos:
        try:
            descr = (d.description or '').upper()
        except Exception:
            descr = ''
        if 'USB MODE' in descr:
            agregar(d.device)
        puertos_normales.append(d)
    for d in puertos_normales:
        try:
            if (d.vid, d.pid) in VIDPIDS_VNA:
                agregar(d.device)
        except Exception:
            continue
    for d in puertos_normales:
        texto = ' '.join((str(x or '') for x in (getattr(d, 'description', ''), getattr(d, 'manufacturer', ''), getattr(d, 'hwid', '')))).upper()
        if 'NANOVNA' in texto or 'VNA' in texto or 'USB MODE' in texto:
            agregar(d.device)
    if not candidatos:
        for d in puertos_normales:
            agregar(d.device)
    for dev in candidatos:
        if _puerto_responde_como_vna(dev):
            return dev
    return None

def obtener_puerto() -> str:
    puerto = intentar_obtener_puerto()
    if puerto is None:
        raise OSError('No se detectó ningún puerto serie para el VNA.')
    return puerto

def listar_puertos_seriales() -> list[tuple[str, str]]:
    elementos: list[tuple[str, str]] = []
    for d in list_ports.comports():
        etiqueta = f'{d.device}  —  {d.description}'
        elementos.append((d.device, etiqueta))
    return elementos

def dialogo_elegir_puerto() -> str | None:
    import tkinter as tk
    from tkinter import ttk, messagebox
    puertos = listar_puertos_seriales()
    if not puertos:
        messagebox.showerror('Puertos', 'No hay puertos serie disponibles.')
        return None
    raiz = tk.Toplevel()
    raiz.title('Seleccionar dispositivo')
    raiz.geometry('460x330')
    raiz.resizable(False, False)
    ttk.Label(raiz, text='Seleccionar dispositivo:', font=('Segoe UI', 11, 'bold')).pack(anchor='w', padx=12, pady=(12, 6))
    marco = ttk.Frame(raiz)
    marco.pack(fill='both', expand=True, padx=12)
    lb = tk.Listbox(marco, height=10, activestyle='dotbox', exportselection=False)
    lb.pack(fill='both', expand=True, side='left')
    for _, etiqueta in puertos:
        lb.insert('end', etiqueta)
    sb = ttk.Scrollbar(marco, orient='vertical', command=lb.yview)
    lb.config(yscrollcommand=sb.set)
    sb.pack(side='right', fill='y')
    elegido = {'dev': None}
    if puertos:
        lb.selection_set(0)
        lb.activate(0)

    def seleccionar_actual() -> None:
        indices = lb.curselection()
        if not indices:
            messagebox.showwarning('Puertos', 'Selecciona un puerto.')
            return
        elegido['dev'] = puertos[indices[0]][0]
        raiz.destroy()

    def _al_doble_clic(event: tk.Event) -> None:
        seleccionar_actual()
    lb.bind('<Double-Button-1>', _al_doble_clic)
    lb.bind('<Return>', lambda event: seleccionar_actual())

    def al_cancelar() -> None:
        elegido['dev'] = None
        raiz.destroy()
    botones = ttk.Frame(raiz)
    botones.pack(fill='x', padx=12, pady=10)
    ttk.Button(botones, text='Seleccionar', command=seleccionar_actual).pack(side='right', padx=6)
    ttk.Button(botones, text='Cancelar', command=al_cancelar).pack(side='right')
    lb.focus_set()
    raiz.grab_set()
    raiz.transient()
    raiz.wait_window()
    return elegido['dev']
