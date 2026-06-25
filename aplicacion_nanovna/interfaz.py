from __future__ import annotations
import os
import threading
import time
import matplotlib.image as mpimg
import matplotlib.ticker as ticker
import numpy as np
import serial
from matplotlib.widgets import Button, RadioButtons, Slider
from serial.tools import list_ports
from .calibracion import CalibracionSOL, CalibracionSOLT
from .configuracion import VIDPIDS_ARDUINO, matplotlib, plt, registro
from .instrumento import NanoVNA, NanoVNAV2
from .marcadores import construir_lineas_marcadores
from .puertos import _guardar_ultimo_puerto_arduino, _leer_ultimo_puerto_arduino, abrir_manual_usuario, detectar_tipo_vna, dialogo_elegir_puerto, listar_puertos_seriales
from .procesamiento import _limpiar_traza, calcular_metricas_analisis, calcular_metricas_parametro_s, limpiar_parametro_s, recortar_frecuencias
from .carta_smith import dibujar_imagen_fondo_smith, dibujar_rejilla_smith, preparar_imagen_fondo_smith
from .barrido import ParametrosBarrido, pedir_parametros_barrido

def vista_tiempo_real(inicio_hz: float | None, fin_hz: float | None, puntos: int | None, fps_interfaz: int=60, puerto_sugerido: str | None=None) -> None:
    puerto_seleccionado = {'dev': puerto_sugerido}
    puerto_aplicado = {'dev': puerto_seleccionado['dev']}
    dispositivo_conectado = puerto_aplicado['dev'] is not None

    def iniciar_dispositivo(nombre_puerto: str):
        nonlocal dispositivo_conectado, dispositivo, nv
        dispositivo_conectado = False
        tipo_vna = detectar_tipo_vna(nombre_puerto)
        if tipo_vna == 'text':
            try:
                nv = NanoVNA(nombre_puerto)
                dispositivo = 'NanoVNA'
                if inicio_hz is None or fin_hz is None or puntos is None:
                    start, stop, pts = (200000000.0, 1425000000.0, 50)
                else:
                    start, stop, pts = (inicio_hz, fin_hz, puntos)
                nv.configurar_frecuencias_barrido(start, stop, pts)
                try:
                    nv.configurar_barrido(start, stop)
                except Exception:
                    pass
                nv.obtener_frecuencias()
                reflexion, transmision = nv.medir_parametros_s()
                if reflexion is not None and len(reflexion) > 0:
                    dispositivo_conectado = True
                    return
            except Exception as exc:
                registro.warning('No se pudo iniciar NanoVNA clasico: %s', exc)
                try:
                    if hasattr(nv, 'cerrar'):
                        nv.cerrar()
                except Exception:
                    pass
            dispositivo_conectado = False
            return
        try:
            nv = NanoVNAV2(nombre_puerto)
            dispositivo = 'NanoVNA-V2'
            if inicio_hz is None or fin_hz is None or puntos is None:
                start, stop, pts = (200000000.0, 1425000000.0, 50)
            else:
                start, stop, pts = (inicio_hz, fin_hz, puntos)
            nv.configurar_barrido(start, stop, pts)
            nv.obtener_frecuencias()
            exito_v2 = False
            try:
                reflexion, transmision = nv.medir_parametros_s()
                if reflexion is not None and len(reflexion) > 0:
                    exito_v2 = True
            except Exception:
                exito_v2 = False
            if exito_v2:
                dispositivo_conectado = True
                return
            try:
                nv.cerrar()
            except Exception:
                pass
        except Exception:
            pass
        try:
            if hasattr(nv, 'cerrar'):
                nv.cerrar()
        except Exception:
            pass
        try:
            nv = NanoVNA(nombre_puerto)
            dispositivo = 'NanoVNA'
            if inicio_hz is None or fin_hz is None or puntos is None:
                start, stop, pts = (200000000.0, 1425000000.0, 50)
            else:
                start, stop, pts = (inicio_hz, fin_hz, puntos)
            nv.configurar_frecuencias_barrido(start, stop, pts)
            try:
                nv.configurar_barrido(start, stop)
            except Exception:
                pass
            nv.obtener_frecuencias()
            exito_v1 = False
            try:
                reflexion, transmision = nv.medir_parametros_s()
                if reflexion is not None and len(reflexion) > 0:
                    exito_v1 = True
            except Exception:
                exito_v1 = False
            dispositivo_conectado = exito_v1
        except Exception:
            dispositivo_conectado = False
    nv = None
    dispositivo = 'Viewer (sin VNA)'
    if dispositivo_conectado:
        iniciar_dispositivo(puerto_aplicado['dev'])
    if not dispositivo_conectado:
        dispositivo = 'Viewer (sin VNA)'
        if inicio_hz is None or fin_hz is None or puntos is None:
            inicio_hz, fin_hz, puntos = (200000000.0, 1425000000.0, 50)
        fake_f = np.linspace(inicio_hz, fin_hz, puntos)

        class _Simulado:
            frecuencias = fake_f

            def cerrar(self) -> None:
                pass
        nv = _Simulado()
    ultimos: dict[str, np.ndarray | None] = {'s11': None, 's21': None, 's12': None, 's22': None, 'f': nv.frecuencias}
    if ultimos['f'] is not None and len(ultimos['f']) > 0:
        rango_x = {'lo': float(ultimos['f'][0] / 1000000.0), 'hi': float(ultimos['f'][-1] / 1000000.0)}
    else:
        rango_x = {'lo': 0.0, 'hi': 1.0}
    evento_detener = threading.Event()
    hilo_escaneo: threading.Thread | None = None
    calibracion = CalibracionSOL()
    baudios_arduino: int = 115200
    puerto_arduino: str | None = None
    serie_arduino: serial.Serial | None = None
    mostrar_errores_arduino: bool = False
    estado_switch = {'v': False}
    estado_vista_param_s = {'v': False}
    switch_hw_disponible = {'v': False}
    boton_switch = None
    boton_vista_param_s = None
    texto_estado_switch = None
    texto_estado_vista_param_s = None
    texto_titulo_switch = None
    pausado: dict[str, bool] = {'v': False}
    modo_adquisicion = {'modo': 'live', 'single_pending': False}
    bloqueo_medicion = threading.Lock()
    ciclo_switch_ocupado = {'v': False}
    SEGUNDOS_ESTABILIZACION_SWITCH: float = 0.15

    def _leer_texto_arduino(duration_s: float=0.8) -> str:
        if serie_arduino is None:
            return ''
        end_t = time.time() + max(0.05, float(duration_s))
        chunks: list[str] = []
        while time.time() < end_t:
            try:
                n = int(getattr(serie_arduino, 'in_waiting', 0) or 0)
                if n > 0:
                    raw = serie_arduino.read(n)
                    chunks.append(raw.decode('utf-8', errors='ignore'))
                else:
                    time.sleep(0.03)
            except Exception:
                break
        return ''.join(chunks)

    def _probar_puerto_arduino() -> bool:
        if serie_arduino is None:
            return False
        try:
            time.sleep(0.4)
            try:
                serie_arduino.reset_input_buffer()
                serie_arduino.reset_output_buffer()
            except Exception:
                pass
            serie_arduino.write(b'PING\n')
            serie_arduino.flush()
            respuesta = _leer_texto_arduino(1.0).upper()
            if 'PONG' in respuesta or 'ESP32_READY' in respuesta:
                return True
            serie_arduino.write(b'STATUS\n')
            serie_arduino.flush()
            respuesta = _leer_texto_arduino(1.0).upper()
            return 'STATUS' in respuesta or 'MODO=' in respuesta
        except Exception:
            return False

    def detectar_puerto_arduino(exclude: set[str] | None=None) -> str | None:
        exclude = exclude or set()
        mejor: tuple[int, str] | None = None
        ultimo = _leer_ultimo_puerto_arduino()
        if ultimo and ultimo not in exclude:
            try:
                if any((p.device == ultimo for p in list_ports.comports())):
                    return ultimo
            except Exception:
                pass
        for d in list_ports.comports():
            puerto = d.device
            if not puerto or puerto in exclude:
                continue
            try:
                puntuacion = 0
                vidpid = (getattr(d, 'vid', None), getattr(d, 'pid', None))
                if None not in vidpid and (vidpid[0], vidpid[1]) in VIDPIDS_ARDUINO:
                    puntuacion += 100
                descripcion = (d.description or '').lower().replace('‑', '-')
                hwid = (d.hwid or '').lower()
                if 'arduino' in descripcion or 'arduino' in hwid:
                    puntuacion += 80
                if any((k in descripcion or k in hwid for k in ('ch340', 'ch341', 'cp210', 'ftdi', 'usb serial'))):
                    puntuacion += 50
                if puerto.upper().startswith('COM'):
                    puntuacion += 1
                if mejor is None or puntuacion > mejor[0]:
                    mejor = (puntuacion, puerto)
            except Exception:
                continue
        return mejor[1] if mejor else None

    def conectar_arduino() -> bool:
        nonlocal serie_arduino, puerto_arduino
        if serie_arduino is not None:
            return True
        puertos_excluidos: set[str] = set()
        try:
            vna_port = puerto_aplicado.get('dev')
            if vna_port:
                puertos_excluidos.add(str(vna_port))
        except Exception:
            pass
        if not puerto_arduino:
            puerto_arduino = detectar_puerto_arduino(puertos_excluidos)
        if not puerto_arduino:
            try:
                disponibles = [p.device for p in list_ports.comports() if p.device and p.device not in puertos_excluidos]
                if disponibles:
                    puerto_arduino = disponibles[0]
            except Exception:
                pass
        if not puerto_arduino:
            if mostrar_errores_arduino:
                try:
                    messagebox.showerror('Arduino', 'No se encontró ningún puerto Arduino.\nConecta tu Arduino y vuelve a intentarlo.')
                except Exception:
                    pass
            return False
        candidatos: list[str] = []
        try:
            candidatos.append(str(puerto_arduino))
            for d in list_ports.comports():
                puerto = d.device
                if not puerto or puerto in puertos_excluidos:
                    continue
                if puerto not in candidatos:
                    candidatos.append(puerto)
        except Exception:
            candidatos = [str(puerto_arduino)]
        ultimo_error: Exception | None = None
        for puerto in candidatos:
            try:
                serie_arduino = serial.Serial(puerto, baudios_arduino, timeout=0.1)
                time.sleep(1.8)
                if not _probar_puerto_arduino():
                    ultimo_error = RuntimeError(f'{puerto} abrió, pero no respondió PING/STATUS como ESP32')
                    try:
                        serie_arduino.close()
                    except Exception:
                        pass
                    serie_arduino = None
                    continue
                puerto_arduino = puerto
                _guardar_ultimo_puerto_arduino(puerto)
                try:
                    registro.info('ESP32 detectado en %s', puerto)
                except Exception:
                    pass
                return True
            except Exception as ex:
                ultimo_error = ex
                try:
                    if serie_arduino is not None:
                        serie_arduino.close()
                except Exception:
                    pass
                serie_arduino = None
                continue
        if mostrar_errores_arduino:
            try:
                extra = '\n\nTip: cierra el Arduino IDE/Monitor Serie si está abierto.' if 'PermissionError' in str(ultimo_error) or 'Access' in str(ultimo_error) or 'acceso' in str(ultimo_error).lower() else ''
                messagebox.showerror('Arduino', f"No se pudo abrir el puerto del Arduino (probé: {', '.join(candidatos)}).\n\nDetalle:\n{ultimo_error}{extra}")
            except Exception:
                pass
        return False

    def _aplicar_vista_parametros_s(mostrar_s12_s22: bool) -> None:
        estado_vista_param_s['v'] = bool(mostrar_s12_s22)
        etiqueta = 'S12/S22' if mostrar_s12_s22 else 'S11/S21'
        try:
            variables_param_s['S11'].set(not mostrar_s12_s22)
            variables_param_s['S21'].set(not mostrar_s12_s22)
            variables_param_s['S12'].set(mostrar_s12_s22)
            variables_param_s['S22'].set(mostrar_s12_s22)
            _al_cambiar_menu()
        except Exception:
            pass
        try:
            if boton_vista_param_s is not None:
                boton_vista_param_s.label.set_text(etiqueta)
                establecer_color_boton(boton_vista_param_s, OK_COLOR if mostrar_s12_s22 else WARN_COLOR)
        except Exception:
            pass
        try:
            if texto_estado_vista_param_s is not None:
                texto_estado_vista_param_s.set_text(f'Vista: {etiqueta}')
        except Exception:
            pass

    def alternar_vista_parametros_s(_event=None) -> None:
        _aplicar_vista_parametros_s(not estado_vista_param_s['v'])

    def _usar_boton_switch_como_vista() -> None:
        nonlocal boton_vista_param_s
        switch_hw_disponible['v'] = False
        boton_vista_param_s = boton_switch
        try:
            if texto_titulo_switch is not None:
                texto_titulo_switch.set_text('Vista S')
                texto_titulo_switch.set_visible(True)
        except Exception:
            pass
        try:
            if boton_switch is not None and hasattr(boton_switch, 'ax'):
                boton_switch.ax.set_visible(True)
        except Exception:
            pass
        try:
            if texto_estado_switch is not None:
                texto_estado_switch.set_text('Vista: S11/S21')
                texto_estado_switch.set_visible(True)
        except Exception:
            pass
        _aplicar_vista_parametros_s(estado_vista_param_s['v'])

    def _actualizar_ui_switch() -> None:
        try:
            if boton_switch is not None:
                if estado_switch['v']:
                    boton_switch.label.set_text('S12/S22')
                    establecer_color_boton(boton_switch, OK_COLOR)
                    if texto_estado_switch is not None:
                        texto_estado_switch.set_text('Switch: S12/S22')
                else:
                    boton_switch.label.set_text('S11/S21')
                    establecer_color_boton(boton_switch, WARN_COLOR)
                    if texto_estado_switch is not None:
                        texto_estado_switch.set_text('Switch: S11/S21')
                _aplicar_vista_parametros_s(estado_switch['v'])
        except Exception:
            pass

    def _escribir_linea_arduino(linea: str) -> bool:
        nonlocal serie_arduino
        "\n        Enviar una línea de texto al Arduino asegurando que termine con un salto\n        de línea y realizando reconexiones automáticas si fuese necesario.\n\n        Este helper añade automáticamente un carácter de nueva línea ('\n') si\n        no está presente al final de la cadena proporcionada.  Luego codifica\n        la cadena como ASCII antes de enviarla por el puerto serie.  Si el\n        envío falla, intenta cerrar y reabrir el puerto antes de volver a\n        intentarlo.  Cualquier error persistente se notifica a la interfaz\n        mediante un cuadro de diálogo.\n        "
        if not conectar_arduino():
            return False
        if not linea.endswith('\n'):
            linea = linea + '\n'
        carga = linea.encode('ascii', errors='ignore')
        try:
            serie_arduino.write(carga)
            serie_arduino.flush()
            try:
                respuesta = _leer_texto_arduino(0.25).strip()
                if respuesta:
                    registro.info('Arduino respuesta: %s', respuesta.replace('\n', ' | '))
            except Exception:
                pass
            return True
        except Exception:
            try:
                if serie_arduino is not None:
                    serie_arduino.close()
            except Exception:
                pass
            serie_arduino = None
            if not conectar_arduino():
                return False
            try:
                serie_arduino.write(carga)
                serie_arduino.flush()
                try:
                    respuesta = _leer_texto_arduino(0.25).strip()
                    if respuesta:
                        registro.info('Arduino respuesta: %s', respuesta.replace('\n', ' | '))
                except Exception:
                    pass
                return True
            except Exception as ex:
                try:
                    messagebox.showerror('Arduino', f'Error al enviar comando al Arduino:\n{ex}')
                except Exception:
                    pass
                return False

    def _establecer_switch_hw(new_state: bool) -> bool:
        if not _escribir_linea_arduino('SW1' if new_state else 'SW0'):
            return False
        estado_switch['v'] = bool(new_state)
        return True

    def alternar_switch(_event=None) -> None:
        if not switch_hw_disponible.get('v'):
            alternar_vista_parametros_s()
            return
        estado_final = not estado_switch['v']
        if ciclo_switch_ocupado.get('v'):
            return
        if not dispositivo_conectado or not hasattr(nv, 'medir_parametros_s'):
            if _establecer_switch_hw(estado_final):
                _actualizar_ui_switch()
            return
        ciclo_switch_ocupado['v'] = True
        pausa_original = pausado.get('v', False)
        pausado['v'] = True
        try:
            with bloqueo_medicion:
                if not _establecer_switch_hw(False):
                    return
                time.sleep(SEGUNDOS_ESTABILIZACION_SWITCH)
                medicion_s11, medicion_s21 = nv.medir_parametros_s()
                if not _establecer_switch_hw(True):
                    return
                time.sleep(SEGUNDOS_ESTABILIZACION_SWITCH)
                medicion_s22, medicion_s12 = nv.medir_parametros_s()
            ultimos['s11'] = medicion_s11
            ultimos['s21'] = medicion_s21
            ultimos['s12'] = medicion_s12
            ultimos['s22'] = medicion_s22
            if not _establecer_switch_hw(estado_final):
                return
            _actualizar_ui_switch()
        except Exception as ex:
            try:
                messagebox.showerror('Switch', f'Error al medir con el switch:\n{ex}')
            except Exception:
                pass
        finally:
            pausado['v'] = pausa_original
            ciclo_switch_ocupado['v'] = False
            try:
                actualizar_frame()
                fig.canvas.draw_idle()
            except Exception:
                pass

    def _datos_parametro_validos(arreglo: np.ndarray | None) -> bool:
        try:
            arr = np.asarray(arreglo)
            return arr.size > 0 and bool(np.isfinite(arr).any())
        except Exception:
            return False

    def _medir_parametros_s_completos_para_exportar() -> bool:
        nonlocal boton_vista_param_s, texto_estado_vista_param_s
        if not dispositivo_conectado or not hasattr(nv, 'medir_parametros_s'):
            return False
        if ciclo_switch_ocupado.get('v'):
            return False
        if not switch_hw_disponible.get('v'):
            if not conectar_arduino():
                return False
            switch_hw_disponible['v'] = True
            boton_vista_param_s = None
            texto_estado_vista_param_s = None
            try:
                if texto_titulo_switch is not None:
                    texto_titulo_switch.set_text('Switch')
            except Exception:
                pass
        estado_inicial = bool(estado_switch.get('v'))
        pausa_original = pausado.get('v', False)
        ciclo_switch_ocupado['v'] = True
        pausado['v'] = True
        ok = False
        try:
            with bloqueo_medicion:
                if not _establecer_switch_hw(False):
                    return False
                time.sleep(SEGUNDOS_ESTABILIZACION_SWITCH)
                medicion_s11, medicion_s21 = nv.medir_parametros_s()
                if not _establecer_switch_hw(True):
                    return False
                time.sleep(SEGUNDOS_ESTABILIZACION_SWITCH)
                medicion_s22, medicion_s12 = nv.medir_parametros_s()
                if not all((_datos_parametro_validos(a) for a in (medicion_s11, medicion_s21, medicion_s12, medicion_s22))):
                    return False
                ultimos['s11'] = medicion_s11
                ultimos['s21'] = medicion_s21
                ultimos['s12'] = medicion_s12
                ultimos['s22'] = medicion_s22
                try:
                    ultimos['f'] = nv.frecuencias
                except Exception:
                    pass
                ok = True
        except Exception as ex:
            registro.exception('Error midiendo los cuatro parametros S para exportar', exc_info=ex)
            try:
                messagebox.showerror('Export', f'No se pudieron medir los cuatro parÃ¡metros S:\n{ex}')
            except Exception:
                pass
        finally:
            try:
                if estado_switch.get('v') != estado_inicial:
                    _establecer_switch_hw(estado_inicial)
            except Exception:
                pass
            pausado['v'] = pausa_original
            ciclo_switch_ocupado['v'] = False
            try:
                _actualizar_ui_switch()
                actualizar_frame()
                fig.canvas.draw_idle()
            except Exception:
                pass
        return ok

    def hilo_medicion() -> None:
        if not dispositivo_conectado or not hasattr(nv, 'medir_parametros_s'):
            return
        while not evento_detener.is_set():
            if pausado.get('v'):
                time.sleep(0.05)
                continue
            if modo_adquisicion.get('modo') == 'single' and (not modo_adquisicion.get('single_pending')):
                time.sleep(0.05)
                continue
            try:
                with bloqueo_medicion:
                    reflexion, transmision = nv.medir_parametros_s()
                if estado_switch.get('v'):
                    ultimos['s22'] = reflexion
                    ultimos['s12'] = transmision
                else:
                    ultimos['s11'] = reflexion
                    ultimos['s21'] = transmision
                if modo_adquisicion.get('modo') == 'single':
                    modo_adquisicion['single_pending'] = False
                time.sleep(0.05)
            except Exception:
                time.sleep(0.05)
    hilo_escaneo = threading.Thread(target=hilo_medicion, daemon=True)
    hilo_escaneo.start()
    fig = plt.figure(figsize=(14, 5))
    axS = fig.add_subplot(1, 3, 1)
    axM = fig.add_subplot(1, 3, 2)
    axPhase = fig.add_axes(axM.get_position(), sharex=axM)
    axPhase.set_xlabel('Frecuencia (MHz)')
    axPhase.set_ylabel('Fase (°)')
    axPhase.set_visible(False)
    axP = fig.add_subplot(1, 3, 3, projection='polar')
    fig.canvas.manager.set_window_title('NANOVNA Visor')
    indicador_medicion = fig.text(0.02, 0.97, '●', fontsize=9, color='red', fontweight='bold', va='center', ha='left')
    texto_estado_inferior = fig.text(0.12, 0.01, '', transform=fig.transFigure, fontsize=8, va='bottom', ha='left', visible=False)
    texto_estado_panel_titulo = fig.text(0.018, 0.935, 'Estado', transform=fig.transFigure, fontsize=11, fontweight='bold', va='bottom', ha='left', color='black')
    texto_estado_panel = fig.text(0.018, 0.928, '', transform=fig.transFigure, fontsize=8.5, va='top', ha='left', linespacing=1.05, bbox=dict(boxstyle='round,pad=0.25', facecolor='#F7FAFC', edgecolor='#1E88E5', linewidth=1.4, alpha=0.98))
    estado_pantalla_completa = {'active': False, 'ax': None, 'positions': {}, 'vis': {}}
    info_fps = {'count': 0, 'last_time': time.time(), 'fps': 0}
    medicion_actual = {'components': []}

    def actualizar_barra_estado(componentes_medicion: list[str] | None=None) -> None:
        try:
            if componentes_medicion is not None:
                medicion_actual['components'] = [c for c in componentes_medicion if c]
            arreglo_frecuencias = ultimos.get('f')
            if arreglo_frecuencias is not None and len(arreglo_frecuencias) > 0:
                center_hz = (float(arreglo_frecuencias[0]) + float(arreglo_frecuencias[-1])) / 2.0
                freq_str = _formatear_frecuencia(center_hz)
                points_count = len(arreglo_frecuencias)
            else:
                freq_str = '—'
                points_count = 0
            if not dispositivo_conectado:
                state_str = 'Desconectado'
            elif modo_adquisicion.get('modo') == 'single':
                state_str = 'Capturando única' if modo_adquisicion.get('single_pending') else 'Captura única'
            elif pausado.get('v'):
                state_str = 'Pausado'
            else:
                state_str = 'Adquiriendo'
            fps_val = info_fps.get('fps', 0)
            comps: list[str] = [f'Frecuencia: {freq_str}', f'Puntos: {points_count}', f'Estado: {state_str}', f'FPS: {fps_val}']
            comps.extend(medicion_actual['components'])
            texto_estado_inferior.set_text('')
            try:
                nano_str = 'conectado' if dispositivo_conectado else 'no conectado'
                puerto_estado = puerto_aplicado.get('dev') or puerto_seleccionado.get('dev')
                if arreglo_frecuencias is not None and len(arreglo_frecuencias) > 0:
                    inicio_txt = _formatear_frecuencia(float(arreglo_frecuencias[0])).replace('\xa0', ' ')
                    fin_txt = _formatear_frecuencia(float(arreglo_frecuencias[-1])).replace('\xa0', ' ')
                    barrido_txt = f'{inicio_txt} - {fin_txt} | {points_count} p'
                else:
                    barrido_txt = 'sin datos'
                parametros_activos: list[str] = []
                try:
                    for nombre_parametro in ('S11', 'S21', 'S12', 'S22'):
                        var_parametro = variables_param_s.get(nombre_parametro)
                        if var_parametro is not None and var_parametro.get():
                            parametros_activos.append(nombre_parametro)
                except Exception:
                    parametros_activos = ['S12', 'S22'] if estado_switch.get('v') else ['S11', 'S21']
                s_txt = '/'.join(parametros_activos) if parametros_activos else '—'
                cal_txt = 'calibrado' if calibracion.aplicada else 'sin calibrar'
                lineas_estado_panel = [f'NanoVNA: {nano_str}']
                if puerto_estado:
                    lineas_estado_panel.append(f'COM: {puerto_estado}')
                lineas_estado_panel.extend([f'Barrido: {barrido_txt}', f'S: {s_txt} | Cal: {cal_txt}'])
                texto_estado_panel.set_text('\n'.join(lineas_estado_panel))
            except Exception:
                pass
        except Exception:
            pass
    ayuda_flotante = axM.annotate('', xy=(0, 0), xytext=(10, 10), textcoords='offset points', bbox=dict(boxstyle='round', fc='lightyellow', ec='black', lw=0.5), arrowprops=dict(arrowstyle='->'), fontsize=8)
    ayuda_flotante.set_visible(False)

    def _formatear_frecuencia(val_hz: float) -> str:
        try:
            v = float(val_hz)
        except Exception:
            return str(val_hz)
        if v >= 1000000000.0:
            return f'{v / 1000000000.0:.2f}\xa0GHz'
        elif v >= 1000000.0:
            s = f'{v / 1000000.0:.3f}'.rstrip('0').rstrip('.')
            return f'{s}\xa0MHz'
        elif v >= 1000.0:
            return f'{v / 1000.0:.0f}\xa0kHz'
        else:
            return f'{v:.0f}\xa0Hz'

    def actualizar_titulo():
        f = ultimos['f']
        if f is None or len(f) == 0:
            fig.suptitle(f'{dispositivo}')
            return
        start = float(f[0])
        stop = float(f[-1])
        fig.suptitle(f'{dispositivo}  |  {_formatear_frecuencia(start)}–{_formatear_frecuencia(stop)}  |  {len(f)} pts')
    actualizar_titulo()
    fig.subplots_adjust(left=0.07, right=0.86, top=0.8, wspace=0.28)
    fondo_cargado = False
    try:
        directorio_script = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        directorio_script = os.getcwd()
    ruta_imagen = os.path.join(directorio_script, 'carta_smith_fondo_v2.png')
    try:
        imagen_fondo = preparar_imagen_fondo_smith(mpimg.imread(ruta_imagen))
        dibujar_imagen_fondo_smith(axS, imagen_fondo)
        fondo_cargado = True
    except Exception:
        dibujar_rejilla_smith(axS)
        fondo_cargado = False
    lnS11smith, = axS.plot([], [], linewidth=1.4, animated=True, label='S11', color='tab:blue')
    lnS12smith, = axS.plot([], [], linewidth=1.4, animated=True, label='S12', color='tab:orange')
    lnS21smith, = axS.plot([], [], linewidth=1.4, animated=True, label='S21', color='tab:red')
    lnS22smith, = axS.plot([], [], linewidth=1.4, animated=True, label='S22', color='tab:green')
    axS.legend(loc='upper right')
    axM.grid(True, alpha=0.35)
    axM.set_xlabel('Frecuencia (MHz)')
    axM.set_ylabel('Magnitud [dB]')
    axM.set_ylim(-80, 5)
    axM.yaxis.set_major_locator(ticker.MultipleLocator(10))
    axM.xaxis.set_major_locator(ticker.MaxNLocator(nbins=8))
    axM.xaxis.set_major_formatter(ticker.FuncFormatter(lambda val, pos: f'{val:.3f}'.rstrip('0').rstrip('.') if abs(val - int(val)) < 1e-09 else f'{val:.3f}'))
    lnS11mag, = axM.plot([], [], linewidth=1.2, animated=True, label='mag(S11)', color='tab:blue')
    lnS12mag, = axM.plot([], [], linewidth=1.2, animated=True, label='mag(S12)', color='tab:orange')
    lnS21mag, = axM.plot([], [], linewidth=1.2, animated=True, label='mag(S21)', color='tab:red')
    lnS22mag, = axM.plot([], [], linewidth=1.2, animated=True, label='mag(S22)', color='tab:green')
    lnS11phase, = axPhase.plot([], [], linewidth=1.2, linestyle=':', animated=True, label='fase(S11)', color='tab:blue')
    lnS12phase, = axPhase.plot([], [], linewidth=1.2, linestyle=':', animated=True, label='fase(S12)', color='tab:orange')
    lnS21phase, = axPhase.plot([], [], linewidth=1.2, linestyle=':', animated=True, label='fase(S21)', color='tab:red')
    lnS22phase, = axPhase.plot([], [], linewidth=1.2, linestyle=':', animated=True, label='fase(S22)', color='tab:green')
    axM.legend(loc='upper right')
    axM.set_xlim(rango_x['lo'], rango_x['hi'])
    try:
        axP.set_theta_zero_location('E')
        axP.set_theta_direction(-1)
    except Exception:
        pass
    axP.grid(True, alpha=0.35)
    lnS11polar, = axP.plot([], [], linewidth=1.2, animated=True, label='S11', color='tab:blue')
    lnS12polar, = axP.plot([], [], linewidth=1.2, animated=True, label='S12', color='tab:orange')
    lnS21polar, = axP.plot([], [], linewidth=1.2, animated=True, label='S21', color='tab:red')
    lnS22polar, = axP.plot([], [], linewidth=1.2, animated=True, label='S22', color='tab:green')
    axP.legend(loc='upper right')
    axP.set_visible(False)
    ventana = fig.canvas.manager.window
    import tkinter as tk
    from tkinter import messagebox
    opciones_modo_cal = ['SOL (1 port)', 'SOLT (T/R)']
    variable_modo_cal = tk.StringVar(value=opciones_modo_cal[0])
    estado_cuatro_dialogos = {'win': None, 'contexts': None, 'param_order': None, 'paused': False}
    barra_menu = tk.Menu(ventana)
    ventana['menu'] = barra_menu
    menu_dispositivo = tk.Menu(barra_menu, tearoff=False)
    barra_menu.add_cascade(label='Dispositivo', menu=menu_dispositivo)
    menu_calibracion = tk.Menu(barra_menu, tearoff=False)
    for opt in opciones_modo_cal:
        menu_calibracion.add_radiobutton(label=opt, value=opt, variable=variable_modo_cal, command=lambda sel=opt: al_cambiar_modo_calibracion(sel))
    barra_menu.add_cascade(label='Calibración', menu=menu_calibracion)
    menu_guia_usuario = tk.Menu(barra_menu, tearoff=False)
    menu_guia_usuario.add_command(label='Abrir manual de usuario', command=abrir_manual_usuario)
    barra_menu.add_cascade(label='Guía de usuario', menu=menu_guia_usuario)

    def exportar_resultados() -> None:
        nonlocal inicio_hz, fin_hz, puntos
        param_s11 = ultimos.get('s11')
        param_s12 = ultimos.get('s12')
        param_s21 = ultimos.get('s21')
        param_s22 = ultimos.get('s22')
        frecuencias = ultimos.get('f')
        if frecuencias is None or (param_s11 is None and param_s12 is None and (param_s21 is None) and (param_s22 is None)):
            try:
                messagebox.showerror('Export', 'No hay datos para exportar.')
            except Exception:
                pass
            return
        if calibracion.aplicada:
            if hasattr(calibracion, 'aplicar_reflexion'):
                param_s11_cal = calibracion.aplicar_reflexion(param_s11) if param_s11 is not None else None
                param_s22_cal = calibracion.aplicar_reflexion(param_s22) if param_s22 is not None else None
                param_s21_cal = calibracion.corregir_transmision_thru(param_s21) if param_s21 is not None else None
                param_s12_cal = calibracion.corregir_transmision_thru(param_s12) if param_s12 is not None else None
            else:
                param_s11_cal = calibracion.corregir_medicion_sol(param_s11) if param_s11 is not None else None
                param_s22_cal = calibracion.corregir_medicion_sol(param_s22) if param_s22 is not None else None
                param_s21_cal = param_s21
                param_s12_cal = param_s12
        else:
            param_s11_cal = param_s11
            param_s12_cal = param_s12
            param_s21_cal = param_s21
            param_s22_cal = param_s22
        frecuencias_mhz = np.array([float(f) / 1000000.0 for f in frecuencias])
        from tkinter import filedialog, ttk
        opt_win = tk.Toplevel(ventana)
        opt_win.title('Exportar parámetros')
        opt_win.resizable(False, False)
        v11 = tk.BooleanVar(value=True)
        v12 = tk.BooleanVar(value=True)
        v21 = tk.BooleanVar(value=True)
        v22 = tk.BooleanVar(value=True)
        v_ft = tk.StringVar(value='txt')
        frm_opts = ttk.Frame(opt_win)
        frm_opts.pack(padx=12, pady=12)
        ttk.Label(frm_opts, text='Seleccionar parámetros a exportar:').grid(row=0, column=0, columnspan=2, sticky='w')
        chk11 = ttk.Checkbutton(frm_opts, text='S11', variable=v11)
        chk12 = ttk.Checkbutton(frm_opts, text='S12', variable=v12)
        chk21 = ttk.Checkbutton(frm_opts, text='S21', variable=v21)
        chk22 = ttk.Checkbutton(frm_opts, text='S22', variable=v22)
        chk11.grid(row=1, column=0, sticky='w')
        chk12.grid(row=1, column=1, sticky='w')
        chk21.grid(row=2, column=0, sticky='w')
        chk22.grid(row=2, column=1, sticky='w')
        ttk.Label(frm_opts, text='Formato de archivo:').grid(row=3, column=0, columnspan=2, pady=(10, 0), sticky='w')

        def actualizar_opciones_formato() -> None:
            if v_ft.get() == 's2p':
                for var in (v11, v21, v12, v22):
                    var.set(True)
                estado = 'disabled'
            else:
                estado = 'normal'
            for chk in (chk11, chk21, chk12, chk22):
                try:
                    chk.configure(state=estado)
                except Exception:
                    pass
        rb_txt = ttk.Radiobutton(frm_opts, text='.txt', variable=v_ft, value='txt', command=actualizar_opciones_formato)
        rb_s2p = ttk.Radiobutton(frm_opts, text='.s2p', variable=v_ft, value='s2p', command=actualizar_opciones_formato)
        rb_txt.grid(row=4, column=0, sticky='w')
        rb_s2p.grid(row=4, column=1, sticky='w')
        actualizar_opciones_formato()
        sel = {'params': None, 'ftype': None}

        def al_aplicar_opciones():
            if v_ft.get() == 's2p':
                names = ['S11', 'S21', 'S12', 'S22']
            else:
                names = []
                if v11.get():
                    names.append('S11')
                if v12.get():
                    names.append('S12')
                if v21.get():
                    names.append('S21')
                if v22.get():
                    names.append('S22')
            if not names:
                try:
                    messagebox.showwarning('Export', 'Selecciona al menos un parámetro.')
                except Exception:
                    pass
                return
            sel['params'] = names
            sel['ftype'] = v_ft.get()
            try:
                opt_win.destroy()
            except Exception:
                pass

        def al_cancelar_opciones():
            try:
                opt_win.destroy()
            except Exception:
                pass
        btn_fr = ttk.Frame(opt_win)
        btn_fr.pack(pady=8)
        ttk.Button(btn_fr, text='Aceptar', command=al_aplicar_opciones).pack(side='right', padx=6)
        ttk.Button(btn_fr, text='Cancelar', command=al_cancelar_opciones).pack(side='right')
        opt_win.grab_set()
        opt_win.transient(ventana)
        opt_win.wait_window()
        if not sel.get('params') or not sel.get('ftype'):
            return
        parametros_seleccionados = sel['params']
        tipo_archivo = sel['ftype']
        requiere_cuatro_parametros = tipo_archivo == 's2p' or set(parametros_seleccionados) == {'S11', 'S21', 'S12', 'S22'}
        if requiere_cuatro_parametros and dispositivo_conectado and hasattr(nv, 'medir_parametros_s'):
            if not _medir_parametros_s_completos_para_exportar():
                try:
                    messagebox.showerror('Export', 'No se pudo completar la medicion de las dos rutas del switch.\nPara exportar los 4 parametros S se requieren S11, S21, S12 y S22 medidos en el mismo barrido.')
                except Exception:
                    pass
                return
        param_s11 = ultimos.get('s11')
        param_s12 = ultimos.get('s12')
        param_s21 = ultimos.get('s21')
        param_s22 = ultimos.get('s22')
        frecuencias = ultimos.get('f')
        if frecuencias is None or len(frecuencias) == 0:
            try:
                messagebox.showerror('Export', 'No hay frecuencias para exportar.')
            except Exception:
                pass
            return
        if calibracion.aplicada:
            if hasattr(calibracion, 'aplicar_reflexion'):
                param_s11_cal = calibracion.aplicar_reflexion(param_s11) if param_s11 is not None else None
                param_s22_cal = calibracion.aplicar_reflexion(param_s22) if param_s22 is not None else None
                param_s21_cal = calibracion.corregir_transmision_thru(param_s21) if param_s21 is not None else None
                param_s12_cal = calibracion.corregir_transmision_thru(param_s12) if param_s12 is not None else None
            else:
                param_s11_cal = calibracion.corregir_medicion_sol(param_s11) if param_s11 is not None else None
                param_s22_cal = calibracion.corregir_medicion_sol(param_s22) if param_s22 is not None else None
                param_s21_cal = param_s21
                param_s12_cal = param_s12
        else:
            param_s11_cal = param_s11
            param_s12_cal = param_s12
            param_s21_cal = param_s21
            param_s22_cal = param_s22
        frecuencias_mhz = np.array([float(f) / 1000000.0 for f in frecuencias])
        parametros_calibrados = {'S11': param_s11_cal, 'S21': param_s21_cal, 'S12': param_s12_cal, 'S22': param_s22_cal}
        if tipo_archivo == 's2p':
            parametros_seleccionados = ['S11', 'S21', 'S12', 'S22']
            faltantes = [p for p in parametros_seleccionados if parametros_calibrados.get(p) is None or len(parametros_calibrados.get(p)) == 0]
            if faltantes:
                try:
                    messagebox.showerror('Export', f"Para exportar .s2p se requieren S11, S21, S12 y S22.\nFaltan datos de: {', '.join(faltantes)}")
                except Exception:
                    pass
                return
        if tipo_archivo == 'txt':
            def_ext = '.txt'
            tipos_archivo = [('Text files', '*.txt'), ('All files', '*.*')]
        else:
            def_ext = '.s2p'
            tipos_archivo = [('Touchstone files', '*.s2p'), ('All files', '*.*')]
        mascara = None
        try:
            arreglos_mascara = [np.asarray(parametros_calibrados[p]) for p in parametros_seleccionados if parametros_calibrados.get(p) is not None]
            if arreglos_mascara:
                n_mascara = min([len(frecuencias_mhz)] + [len(a) for a in arreglos_mascara])
                mascara = np.zeros(len(frecuencias_mhz), dtype=bool)
                if n_mascara > 0:
                    mascara[:n_mascara] = True
                    for arreglo in arreglos_mascara:
                        mascara[:n_mascara] &= np.isfinite(arreglo[:n_mascara])
        except Exception:
            mascara = None
        f_s = frecuencias_mhz
        if mascara is not None:
            try:
                f_s = frecuencias_mhz[mascara]
            except Exception:
                f_s = frecuencias_mhz
        if len(f_s) > 1:
            f_s = f_s[:-1]
        datos_parametros = {}
        datos_parametros['S11'] = limpiar_parametro_s(param_s11_cal, mascara)
        datos_parametros['S12'] = limpiar_parametro_s(param_s12_cal, mascara)
        datos_parametros['S21'] = limpiar_parametro_s(param_s21_cal, mascara)
        datos_parametros['S22'] = limpiar_parametro_s(param_s22_cal, mascara)
        incompletos = [p for p in parametros_seleccionados if datos_parametros.get(p) is None or len(datos_parametros[p]) < len(f_s) or len(f_s) == 0]
        if incompletos:
            try:
                if tipo_archivo == 's2p':
                    mensaje = 'No se puede exportar .s2p: S11, S21, S12 y S22 deben existir y tener datos finitos en el barrido.'
                else:
                    mensaje = 'No se puede exportar porque faltan datos reales de: ' + ', '.join(incompletos)
                messagebox.showerror('Export', mensaje)
            except Exception:
                pass
            return
        ruta_archivo = filedialog.asksaveasfilename(title='Guardar resultados', defaultextension=def_ext, filetypes=tipos_archivo)
        if not ruta_archivo:
            return
        try:
            with open(ruta_archivo, 'w', encoding='utf-8') as fp:
                if tipo_archivo == 's2p':
                    try:
                        import datetime as _dt
                        fecha = _dt.date.today().isoformat()
                    except Exception:
                        fecha = ''
                    try:
                        inicio_txt = f'{float(f_s[0]):.3f}'.rstrip('0').rstrip('.')
                        fin_txt = f'{float(f_s[-1]):.3f}'.rstrip('0').rstrip('.')
                        rango = f'{inicio_txt} MHz - {fin_txt} MHz'
                    except Exception:
                        rango = ''
                    if calibracion.aplicada:
                        cal_txt = 'SOLT aplicada' if isinstance(calibracion, CalibracionSOLT) else 'SOL aplicada'
                    else:
                        cal_txt = 'No aplicada'
                    fp.write('! Software: NANOVNA Visor\n')
                    if fecha:
                        fp.write(f'! Fecha: {fecha}\n')
                    fp.write(f'! Dispositivo: {dispositivo}\n')
                    if rango:
                        fp.write(f'! Rango: {rango}\n')
                    fp.write(f'! Puntos: {len(f_s)}\n')
                    fp.write(f'! Calibración: {cal_txt}\n')
                fp.write('# MHz S MA R 50\n')
                fp.write('! freq')
                for p in ('S11', 'S21', 'S12', 'S22'):
                    if p in parametros_seleccionados:
                        fp.write(f'   {p}')
                fp.write('\n')
                arrays = []
                for p in ('S11', 'S21', 'S12', 'S22'):
                    if p in parametros_seleccionados:
                        arreglo = datos_parametros[p]
                        if arreglo is None:
                            raise ValueError(f'Faltan datos de {p}')
                    else:
                        arreglo = None
                    arrays.append(arreglo)
                n = len(f_s)
                for i in range(n):
                    f = f_s[i]
                    fp.write(f'{f:8.3f}')
                    for arreglo in arrays:
                        if arreglo is None:
                            continue
                        try:
                            m = abs(arreglo[i])
                            a = np.angle(arreglo[i], deg=True)
                        except Exception:
                            m = 0.0
                            a = 0.0
                        fp.write(f' {m:9.5f} {a:9.2f}')
                    fp.write('\n')
        except Exception as ex:
            try:
                messagebox.showerror('Export', f'Error al guardar el archivo: {ex}')
            except Exception:
                pass
            return
        try:
            messagebox.showinfo('Export', f'Archivo guardado en:\n{ruta_archivo}')
        except Exception:
            pass
    barra_menu.add_command(label='Exportar', command=exportar_resultados)

    def exportar_informe() -> None:
        from tkinter import filedialog, messagebox, ttk
        nonlocal inicio_hz, fin_hz, puntos
        frecuencias = ultimos.get('f')
        if frecuencias is None or len(frecuencias) == 0:
            try:
                messagebox.showerror('Informe', 'No hay datos para exportar.')
            except Exception:
                pass
            return
        param_s11 = ultimos.get('s11')
        param_s21 = ultimos.get('s21')
        if calibracion.aplicada:
            if hasattr(calibracion, 'aplicar_reflexion'):
                param_s11_cal = calibracion.aplicar_reflexion(param_s11) if param_s11 is not None else None
                param_s21_cal = calibracion.corregir_transmision_thru(param_s21) if param_s21 is not None else None
            else:
                param_s11_cal = calibracion.corregir_medicion_sol(param_s11) if param_s11 is not None else None
                param_s21_cal = param_s21
        else:
            param_s11_cal = param_s11
            param_s21_cal = param_s21
        frecuencias_mhz = np.asarray(frecuencias, dtype=float) / 1000000.0
        mascara = None
        try:
            if param_s11_cal is not None and param_s21_cal is not None:
                mascara = np.isfinite(param_s11_cal) & np.isfinite(param_s21_cal)
            elif param_s11_cal is not None:
                mascara = np.isfinite(param_s11_cal)
            elif param_s21_cal is not None:
                mascara = np.isfinite(param_s21_cal)
        except Exception:
            mascara = None
        if mascara is not None:
            try:
                frecuencias_mhz_limpias = frecuencias_mhz[mascara]
            except Exception:
                frecuencias_mhz_limpias = frecuencias_mhz.copy()
        else:
            frecuencias_mhz_limpias = frecuencias_mhz.copy()
        s11_s = limpiar_parametro_s(param_s11_cal, mascara)
        s21_s = limpiar_parametro_s(param_s21_cal, mascara)
        metricas = calcular_metricas_analisis(frecuencias_mhz_limpias, s11_s, s21_s)

        def pedir_datos_informe() -> dict[str, str] | None:
            datos = {'dut': '', 'tipo': 'Parámetros S', 'observaciones': ''}
            try:
                dlg = tk.Toplevel(ventana)
                dlg.title('Datos del informe')
                dlg.resizable(False, False)
                frm = ttk.Frame(dlg)
                frm.pack(padx=12, pady=12, fill='both', expand=True)
                ttk.Label(frm, text='Nombre del dispositivo probado:').grid(row=0, column=0, sticky='w', pady=(0, 4))
                v_dut = tk.StringVar(value='')
                ttk.Entry(frm, textvariable=v_dut, width=42).grid(row=1, column=0, sticky='ew', pady=(0, 8))
                ttk.Label(frm, text='Tipo de medición:').grid(row=2, column=0, sticky='w', pady=(0, 4))
                v_tipo = tk.StringVar(value='Parámetros S')
                ttk.Entry(frm, textvariable=v_tipo, width=42).grid(row=3, column=0, sticky='ew', pady=(0, 8))
                ttk.Label(frm, text='Observaciones:').grid(row=4, column=0, sticky='w', pady=(0, 4))
                txt_obs = tk.Text(frm, width=42, height=5, wrap='word')
                txt_obs.grid(row=5, column=0, sticky='ew')
                resultado = {'ok': False}

                def aceptar() -> None:
                    datos['dut'] = v_dut.get().strip()
                    datos['tipo'] = v_tipo.get().strip()
                    datos['observaciones'] = txt_obs.get('1.0', 'end').strip()
                    resultado['ok'] = True
                    try:
                        dlg.destroy()
                    except Exception:
                        pass

                def cancelar() -> None:
                    try:
                        dlg.destroy()
                    except Exception:
                        pass
                btns = ttk.Frame(frm)
                btns.grid(row=6, column=0, sticky='e', pady=(10, 0))
                ttk.Button(btns, text='Aceptar', command=aceptar).pack(side='right', padx=(6, 0))
                ttk.Button(btns, text='Cancelar', command=cancelar).pack(side='right')
                dlg.grab_set()
                dlg.transient(ventana)
                dlg.wait_window()
                return datos if resultado.get('ok') else None
            except Exception:
                return datos
        datos_informe = pedir_datos_informe()
        if datos_informe is None:
            return
        lineas: list[str] = []
        if calibracion.aplicada:
            cal_usada = 'SOLT aplicada' if isinstance(calibracion, CalibracionSOLT) else 'SOL aplicada'
        else:
            cal_usada = 'No aplicada'
        dispositivo_probado = datos_informe.get('dut') or 'No especificado'
        tipo_medicion = datos_informe.get('tipo') or 'Parámetros S'
        observaciones = datos_informe.get('observaciones') or 'Sin observaciones.'
        lineas.append('Reporte de medición VNA')
        try:
            import datetime as _dt
            now_str = _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            now_str = ''
        if now_str:
            lineas.append(f'Fecha: {now_str}')
        lineas.append(f'Nombre del dispositivo probado: {dispositivo_probado}')
        lineas.append(f'Tipo de medición: {tipo_medicion}')
        try:
            fstart = float(frecuencias_mhz_limpias[0]) if len(frecuencias_mhz_limpias) else None
            fend = float(frecuencias_mhz_limpias[-1]) if len(frecuencias_mhz_limpias) else None
            if fstart is not None and fend is not None:
                lineas.append(f'Rango de frecuencia: {fstart:.3f}–{fend:.3f} MHz')
        except Exception:
            pass
        lineas.append(f'Número de puntos: {len(frecuencias_mhz_limpias)}')
        lineas.append(f'Calibración usada: {cal_usada}')
        lineas.append('')
        lineas.append('Resultados principales:')
        hay_resultados = False
        min_ret_db = metricas.get('min_return_db')
        min_ret_freq = metricas.get('min_return_freq')
        if min_ret_db is not None and min_ret_freq is not None:
            lineas.append(f'- Retorno mínimo: {min_ret_db:+.1f} dB a {min_ret_freq:.3f} MHz')
            hay_resultados = True
        max_gain_db = metricas.get('max_gain_db')
        max_gain_freq = metricas.get('max_gain_freq')
        if max_gain_db is not None and max_gain_freq is not None:
            lineas.append(f'- Ganancia máxima: {max_gain_db:+.1f} dB a {max_gain_freq:.3f} MHz')
            hay_resultados = True
        bw3db = metricas.get('bw3db')
        bw3db_low = metricas.get('bw3db_low')
        bw3db_high = metricas.get('bw3db_high')
        if bw3db is not None and bw3db_low is not None and (bw3db_high is not None):
            lineas.append(f'- Ancho de banda -3 dB: {bw3db:.3f} MHz ({bw3db_low:.3f}–{bw3db_high:.3f} MHz)')
            hay_resultados = True
        if not hay_resultados:
            lineas.append('- Sin resultados principales disponibles.')
        try:
            lineas_marcadores = construir_lineas_marcadores(frecuencias_mhz_limpias, {'S11': s11_s, 'S21': s21_s}, [('M1', selected_idx.get('v')), ('M2', selected_idx_B.get('v'))], ('S11', 'S21'))
            if lineas_marcadores:
                lineas.append('')
                lineas.append('Marcadores:')
                lineas.extend(lineas_marcadores)
        except Exception:
            pass
        lineas.append('')
        lineas.append('Observaciones:')
        for linea_obs in observaciones.splitlines():
            lineas.append(linea_obs if linea_obs.strip() else '')
        ruta_archivo = filedialog.asksaveasfilename(title='Guardar informe', defaultextension='.txt', filetypes=[('Archivo de texto', '*.txt'), ('Todos', '*.*')])
        if not ruta_archivo:
            return
        try:
            with open(ruta_archivo, 'w', encoding='utf-8') as f:
                for linea in lineas:
                    f.write(linea + '\n')
            try:
                messagebox.showinfo('Informe', f'Informe guardado en:\n{ruta_archivo}')
            except Exception:
                pass
        except Exception as ex:
            try:
                messagebox.showerror('Informe', f'No se pudo guardar el informe: {ex}')
            except Exception:
                pass
            registro.exception('Error al guardar informe', exc_info=ex)
    barra_menu.add_command(label='Informe', command=exportar_informe)

    def guardar_graficas() -> None:
        from tkinter import filedialog, messagebox
        w = estado_cuatro_dialogos.get('win')
        ctxs = estado_cuatro_dialogos.get('contexts')
        parametros = estado_cuatro_dialogos.get('param_order')
        pausa_original = pausado.get('v', False)
        pausado['v'] = True
        original_four_pause = estado_cuatro_dialogos.get('paused', False)
        estado_cuatro_dialogos['paused'] = True
        try:
            if w is not None and ctxs is not None and (parametros is not None) and w.winfo_exists():
                dir_path = filedialog.askdirectory(title='Seleccionar carpeta para guardar gráficas')
                if not dir_path:
                    return
                ok_files: list[str] = []
                for pname in parametros:
                    ctx = ctxs.get(pname)
                    if not ctx:
                        continue
                    fig_obj = ctx.get('fig')
                    if fig_obj is None:
                        continue
                    filename = os.path.join(dir_path, f'{pname}.png')
                    try:
                        fig_obj.canvas.draw()
                        fig_obj.savefig(filename)
                        ok_files.append(filename)
                    except Exception:
                        pass
                try:
                    if ok_files:
                        messagebox.showinfo('Guardar gráficas', 'Se guardaron las gráficas en:\n' + '\n'.join(ok_files))
                    else:
                        messagebox.showwarning('Guardar gráficas', 'No se pudieron guardar las gráficas.')
                except Exception:
                    pass
            else:
                ruta_archivo = filedialog.asksaveasfilename(title='Guardar gráfica', defaultextension='.png', filetypes=[('Imagen PNG', '*.png'), ('Todos los archivos', '*.*')])
                if not ruta_archivo:
                    return
                try:
                    fig.canvas.draw()
                    fig.savefig(ruta_archivo)
                except Exception as ex:
                    try:
                        messagebox.showerror('Guardar gráfica', f'Error al guardar: {ex}')
                    except Exception:
                        pass
                    return
                try:
                    messagebox.showinfo('Guardar gráfica', f'Archivo guardado en:\n{ruta_archivo}')
                except Exception:
                    pass
        except Exception as ex:
            try:
                messagebox.showerror('Guardar gráficas', f'Ocurrió un error: {ex}')
            except Exception:
                pass
        finally:
            pausado['v'] = pausa_original
            estado_cuatro_dialogos['paused'] = original_four_pause
    barra_menu.add_command(label='Guardar gráficas', command=guardar_graficas)

    def abrir_cuatro_ventanas() -> None:
        try:
            existing_win = estado_cuatro_dialogos.get('win')
            if existing_win is not None and existing_win.winfo_exists():
                try:
                    existing_win.lift()
                    existing_win.focus_force()
                except Exception:
                    pass
                return
        except Exception:
            pass
        frecuencias = ultimos.get('f')
        param_s11 = ultimos.get('s11')
        param_s12 = ultimos.get('s12')
        param_s21 = ultimos.get('s21')
        param_s22 = ultimos.get('s22')
        if frecuencias is None or (param_s11 is None and param_s12 is None and (param_s21 is None) and (param_s22 is None)):
            try:
                messagebox.showerror('4 diálogos', 'No hay datos para mostrar.')
            except Exception:
                pass
            return
        if calibracion.aplicada:
            if hasattr(calibracion, 'aplicar_reflexion'):
                param_s11_cal = calibracion.aplicar_reflexion(param_s11) if param_s11 is not None else None
                param_s22_cal = calibracion.aplicar_reflexion(param_s22) if param_s22 is not None else None
                param_s21_cal = calibracion.corregir_transmision_thru(param_s21) if param_s21 is not None else None
                param_s12_cal = calibracion.corregir_transmision_thru(param_s12) if param_s12 is not None else None
            else:
                param_s11_cal = calibracion.corregir_medicion_sol(param_s11) if param_s11 is not None else None
                param_s22_cal = calibracion.corregir_medicion_sol(param_s22) if param_s22 is not None else None
                param_s21_cal = param_s21
                param_s12_cal = param_s12
        else:
            param_s11_cal = param_s11
            param_s22_cal = param_s22
            param_s21_cal = param_s21
            param_s12_cal = param_s12
        try:
            frecuencias_mhz_completas = np.array([float(f) / 1000000.0 for f in frecuencias])
        except Exception:
            frecuencias_mhz_completas = np.array([])
        param_s11_limpio = limpiar_parametro_s(param_s11_cal)
        param_s12_limpio = limpiar_parametro_s(param_s12_cal)
        param_s21_limpio = limpiar_parametro_s(param_s21_cal)
        param_s22_limpio = limpiar_parametro_s(param_s22_cal)

        def recortar_freq(arreglo):
            return recortar_frecuencias(arreglo, frecuencias_mhz_completas)
        parametros = {'S11': param_s11_limpio, 'S12': param_s12_limpio, 'S21': param_s21_limpio, 'S22': param_s22_limpio}
        datos_parametros: dict[str, dict[str, np.ndarray | tuple[np.ndarray, np.ndarray]]] = {}
        for pname, arreglo in parametros.items():
            frecuencias_recortadas = recortar_freq(arreglo)
            if arreglo is not None and len(arreglo):
                try:
                    magnitud = 20 * np.log10(np.maximum(np.abs(arreglo), 1e-15))
                    magnitud = magnitud[:len(frecuencias_recortadas)]
                except Exception:
                    magnitud = np.array([])
                try:
                    valores_fase = (np.angle(arreglo) * 180.0 / np.pi)[:len(frecuencias_recortadas)]
                except Exception:
                    valores_fase = np.array([])
                try:
                    angulo = np.angle(arreglo)[:len(frecuencias_recortadas)]
                    radio = np.abs(arreglo)[:len(frecuencias_recortadas)]
                except Exception:
                    angulo = np.array([])
                    radio = np.array([])
                try:
                    mascara = np.abs(arreglo) > 1e-15
                    reales_smith = np.real(arreglo[mascara])
                    imag_smith = np.imag(arreglo[mascara])
                except Exception:
                    reales_smith = np.array([])
                    imag_smith = np.array([])
            else:
                magnitud = np.array([])
                valores_fase = np.array([])
                angulo = np.array([])
                radio = np.array([])
                reales_smith = np.array([])
                imag_smith = np.array([])
            datos_parametros[pname] = {'freq': frecuencias_recortadas, 'mag': magnitud, 'phase': valores_fase, 'polar': (angulo, radio), 'smith': (reales_smith, imag_smith)}
        try:
            import tkinter as tk
            try:
                directorio_script = os.path.dirname(os.path.abspath(__file__))
            except Exception:
                directorio_script = os.getcwd()
            ruta_imagen = os.path.join(directorio_script, 'carta_smith_fondo_v2.png')
            imagen_fondo = preparar_imagen_fondo_smith(mpimg.imread(ruta_imagen))
            has_bg_img = True
        except Exception:
            imagen_fondo = None
            has_bg_img = False
        win4 = tk.Toplevel(ventana)
        win4.title('Vista 4 diálogos')
        try:
            win4.iconbitmap(False, None)
        except Exception:
            pass
        for i in range(2):
            win4.rowconfigure(i, weight=1)
            win4.columnconfigure(i, weight=1)
        menu4 = tk.Menu(win4, tearoff=False)
        is_maximized = {'v': False}
        original_geom = {'geom': None}

        def _maximizar_ventana() -> None:
            if not is_maximized['v']:
                try:
                    original_geom['geom'] = win4.winfo_geometry()
                except Exception:
                    original_geom['geom'] = None
                done = False
                try:
                    win4.state('zoomed')
                    done = True
                except Exception:
                    pass
                if not done:
                    try:
                        win4.attributes('-zoomed', True)
                        done = True
                    except Exception:
                        pass
                if not done:
                    try:
                        sw = win4.winfo_screenwidth()
                        sh = win4.winfo_screenheight()
                        win4.geometry(f'{sw}x{sh}+0+0')
                    except Exception:
                        pass
                is_maximized['v'] = True
                try:
                    menu4.entryconfig(0, label='Restaurar')
                except Exception:
                    pass
            else:
                try:
                    win4.state('normal')
                except Exception:
                    pass
                if original_geom.get('geom'):
                    try:
                        win4.geometry(original_geom['geom'])
                    except Exception:
                        pass
                is_maximized['v'] = False
                try:
                    menu4.entryconfig(0, label='Maximizar')
                except Exception:
                    pass
        menu4.add_command(label='Maximizar', command=_maximizar_ventana)
        menu4.add_command(label='Guardar gráficas', command=guardar_graficas)
        try:
            win4.config(menu=menu4)
        except Exception:
            pass
        from tkinter import ttk
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        graph_types = ['Smith', 'Magnitud', 'Polar', 'Fase']
        graph_types_per_param = {'S11': ['Smith', 'Polar'], 'S12': graph_types, 'S21': graph_types, 'S22': ['Smith', 'Polar']}
        default_types = {'S11': 'Smith', 'S12': 'Magnitud', 'S21': 'Magnitud', 'S22': 'Smith'}
        color_map = {'S11': 'tab:blue', 'S12': 'tab:orange', 'S21': 'tab:red', 'S22': 'tab:green'}
        contexts: dict[str, dict[str, object]] = {}

        def actualizar_grafica(pname: str) -> None:
            ctx = contexts.get(pname)
            if not ctx:
                return
            fig_obj: Figure = ctx['fig']
            seleccionado: str = ctx['var'].get()
            prev_type: str | None = ctx.get('type')
            ax = ctx.get('ax')
            linea = ctx.get('line')
            if prev_type != seleccionado or ax is None or linea is None:
                fig_obj.clf()
                if seleccionado == 'Polar':
                    ax = fig_obj.add_subplot(111, projection='polar')
                    try:
                        ax.set_theta_zero_location('E')
                        ax.set_theta_direction(-1)
                    except Exception:
                        pass
                    ax.grid(True, alpha=0.35)
                    angulo, radio = datos_parametros[pname]['polar']
                    linea, = ax.plot(angulo, radio, color=color_map[pname], label=pname)
                    ax.set_title(f'{pname} (Polar)')
                    ax.legend(loc='upper right')
                else:
                    ax = fig_obj.add_subplot(111)
                    if seleccionado == 'Smith':
                        if has_bg_img:
                            dibujar_imagen_fondo_smith(ax, imagen_fondo)
                        else:
                            dibujar_rejilla_smith(ax)
                        reales_smith, imag_smith = datos_parametros[pname]['smith']
                        linea, = ax.plot(reales_smith, imag_smith, color=color_map[pname], label=pname)
                        ax.set_title(f'{pname} (Smith)')
                        ax.legend(loc='upper right')
                    elif seleccionado == 'Magnitud':
                        ax.grid(True, alpha=0.35)
                        ax.set_xlabel('Frecuencia (MHz)')
                        ax.set_ylabel('Magnitud [dB]')
                        frecuencia = datos_parametros[pname]['freq']
                        mag_vals = datos_parametros[pname]['mag']
                        linea, = ax.plot(frecuencia, mag_vals, color=color_map[pname], label=pname)
                        ax.set_title(f'{pname} (Magnitud)')
                        ax.legend(loc='upper right')
                    elif seleccionado == 'Fase':
                        ax.grid(True, alpha=0.35)
                        ax.set_xlabel('Frecuencia (MHz)')
                        ax.set_ylabel('Fase (°)')
                        frecuencia = datos_parametros[pname]['freq']
                        valores_fase = datos_parametros[pname]['phase']
                        linea, = ax.plot(frecuencia, valores_fase, color=color_map[pname], label=pname)
                        ax.set_title(f'{pname} (Fase)')
                        ax.legend(loc='upper right')
                    else:
                        linea, = ax.plot([], [])
                        ax.set_title(f'{pname}')
                ctx['ax'] = ax
                ctx['line'] = linea
                ctx['type'] = seleccionado
            else:
                try:
                    if seleccionado == 'Polar':
                        angulo, radio = datos_parametros[pname]['polar']
                        linea.set_data(angulo, radio)
                    elif seleccionado == 'Smith':
                        reales_smith, imag_smith = datos_parametros[pname]['smith']
                        linea.set_data(reales_smith, imag_smith)
                    elif seleccionado == 'Magnitud':
                        frecuencia = datos_parametros[pname]['freq']
                        mag_vals = datos_parametros[pname]['mag']
                        linea.set_data(frecuencia, mag_vals)
                    elif seleccionado == 'Fase':
                        frecuencia = datos_parametros[pname]['freq']
                        valores_fase = datos_parametros[pname]['phase']
                        linea.set_data(frecuencia, valores_fase)
                except Exception:
                    pass
            try:
                fig_obj.tight_layout(pad=1.5)
            except Exception:
                pass
            try:
                canvas_obj: FigureCanvasTkAgg = ctx['canvas']
                canvas_obj.draw_idle()
            except Exception:
                pass
        orden_parametros = ['S11', 'S12', 'S21', 'S22']
        frames = []
        for row in range(2):
            for col in range(2):
                marco = ttk.Frame(win4)
                marco.grid(row=row, column=col, sticky='nsew')
                frames.append(marco)
        for marco in frames:
            marco.rowconfigure(1, weight=1)
            marco.columnconfigure(0, weight=1)
        for indice, pname in enumerate(orden_parametros):
            marco = frames[indice]
            lbl = ttk.Label(marco, text=pname)
            lbl.grid(row=0, column=0, sticky='w', padx=2, pady=2)
            var = tk.StringVar(value=default_types[pname])
            types_for_p = graph_types_per_param.get(pname, graph_types)
            init_type = default_types.get(pname, types_for_p[0])
            if init_type not in types_for_p:
                init_type = types_for_p[0]
                var.set(init_type)
            option = ttk.OptionMenu(marco, var, init_type, *types_for_p, command=lambda sel, p=pname: actualizar_grafica(p))
            option.grid(row=0, column=1, sticky='e', padx=2, pady=2)
            fig_obj = Figure(figsize=(5, 3.5))
            canvas = FigureCanvasTkAgg(fig_obj, master=marco)
            canvas.get_tk_widget().grid(row=1, column=0, columnspan=2, sticky='nsew')
            marco.rowconfigure(1, weight=1)
            marco.columnconfigure(0, weight=1)
            contexts[pname] = {'var': var, 'fig': fig_obj, 'canvas': canvas}
        for pname in orden_parametros:
            actualizar_grafica(pname)
        try:
            estado_cuatro_dialogos['win'] = win4
            estado_cuatro_dialogos['contexts'] = contexts
            estado_cuatro_dialogos['param_order'] = orden_parametros
        except Exception:
            pass
        update_interval_ms: int = 500
        last_data_key = {'key': None}

        def actualizar_dialogos() -> None:
            try:
                if not win4.winfo_exists():
                    return
            except Exception:
                return
            try:
                if estado_cuatro_dialogos.get('paused'):
                    win4.after(update_interval_ms, actualizar_dialogos)
                    return
            except Exception:
                pass
            frecuencias = ultimos.get('f')
            param_s11 = ultimos.get('s11')
            param_s12 = ultimos.get('s12')
            param_s21 = ultimos.get('s21')
            param_s22 = ultimos.get('s22')
            try:
                data_key = (id(frecuencias), id(param_s11), id(param_s12), id(param_s21), id(param_s22))
                if last_data_key['key'] == data_key:
                    win4.after(update_interval_ms, actualizar_dialogos)
                    return
                last_data_key['key'] = data_key
            except Exception:
                pass
            if calibracion.aplicada:
                if hasattr(calibracion, 'aplicar_reflexion'):
                    param_s11_cal = calibracion.aplicar_reflexion(param_s11) if param_s11 is not None else None
                    param_s22_cal = calibracion.aplicar_reflexion(param_s22) if param_s22 is not None else None
                    param_s21_cal = calibracion.corregir_transmision_thru(param_s21) if param_s21 is not None else None
                    param_s12_cal = calibracion.corregir_transmision_thru(param_s12) if param_s12 is not None else None
                else:
                    param_s11_cal = calibracion.corregir_medicion_sol(param_s11) if param_s11 is not None else None
                    param_s22_cal = calibracion.corregir_medicion_sol(param_s22) if param_s22 is not None else None
                    param_s21_cal = param_s21
                    param_s12_cal = param_s12
            else:
                param_s11_cal = param_s11
                param_s22_cal = param_s22
                param_s21_cal = param_s21
                param_s12_cal = param_s12
            if frecuencias is not None:
                try:
                    frecuencias_mhz_completas = np.array([float(f) / 1000000.0 for f in frecuencias])
                except Exception:
                    frecuencias_mhz_completas = np.array([])
            else:
                frecuencias_mhz_completas = np.array([])
            param_s11_limpio = limpiar_parametro_s(param_s11_cal)
            param_s12_limpio = limpiar_parametro_s(param_s12_cal)
            param_s21_limpio = limpiar_parametro_s(param_s21_cal)
            param_s22_limpio = limpiar_parametro_s(param_s22_cal)
            nuevos_datos_parametros: dict[str, dict[str, np.ndarray | tuple[np.ndarray, np.ndarray]]] = {}
            parametros_locales = {'S11': param_s11_limpio, 'S12': param_s12_limpio, 'S21': param_s21_limpio, 'S22': param_s22_limpio}
            for pname, arreglo in parametros_locales.items():
                nuevos_datos_parametros[pname] = calcular_metricas_parametro_s(arreglo, frecuencias_mhz_completas)
            try:
                datos_parametros.clear()
                datos_parametros.update(nuevos_datos_parametros)
            except Exception:
                pass
            for pname in orden_parametros:
                try:
                    actualizar_grafica(pname)
                except Exception:
                    pass
            try:
                win4.after(update_interval_ms, actualizar_dialogos)
            except Exception:
                pass
        try:
            win4.after(update_interval_ms, actualizar_dialogos)
        except Exception:
            pass
        try:
            win4.transient(ventana)
        except Exception:
            pass

        def al_cerrar_cuatro() -> None:
            try:
                estado_cuatro_dialogos['win'] = None
                estado_cuatro_dialogos['contexts'] = None
                estado_cuatro_dialogos['param_order'] = None
            except Exception:
                pass
            try:
                win4.destroy()
            except Exception:
                pass
        try:
            win4.protocol('WM_DELETE_WINDOW', al_cerrar_cuatro)
        except Exception:
            pass
    v_selected = tk.StringVar(value=puerto_seleccionado['dev'] or '')
    v_show_tr = tk.BooleanVar(value=True)
    v_swap = tk.BooleanVar(value=False)
    variables_graficas = {'smith': tk.BooleanVar(value=True), 'mag': tk.BooleanVar(value=True), 'polar': tk.BooleanVar(value=False), 'phase': tk.BooleanVar(value=False)}
    variables_param_s = {'S11': tk.BooleanVar(value=True), 'S12': tk.BooleanVar(value=False), 'S21': tk.BooleanVar(value=True), 'S22': tk.BooleanVar(value=False)}
    menu_graficas = tk.Menu(barra_menu, tearoff=False)

    def _al_cambiar_menu() -> None:
        try:
            salir_pantalla_completa()
            actualizar_distribucion_ejes()
        except Exception:
            pass
        try:
            recapturar_fondo()
        except Exception:
            pass
        try:
            actualizar_frame()
        except Exception:
            pass
        try:
            actualizar_barra_estado()
        except Exception:
            pass
        try:
            fig.canvas.draw_idle()
        except Exception:
            pass
    for lbl, key in (('Smith', 'smith'), ('Magnitud', 'mag'), ('Polar', 'polar'), ('Fase', 'phase')):
        menu_graficas.add_checkbutton(label=lbl, variable=variables_graficas[key], command=_al_cambiar_menu)
    barra_menu.add_cascade(label='Ver Gráficas', menu=menu_graficas)
    menu_param_s = tk.Menu(barra_menu, tearoff=False)
    for lbl in ('S11', 'S12', 'S21', 'S22'):
        menu_param_s.add_checkbutton(label=lbl, variable=variables_param_s[lbl], command=_al_cambiar_menu)
    menu_param_s.add_separator()
    menu_param_s.add_command(label='Alternar S11/S21 - S12/S22', command=alternar_vista_parametros_s, accelerator='V')
    barra_menu.add_cascade(label='Parámetros S', menu=menu_param_s)
    barra_menu.add_command(label='4 Ventanas', command=abrir_cuatro_ventanas)
    fondo = {'smith': None, 'mag': None, 'polar': None, 'phase': None}

    def actualizar_distribucion_ejes() -> None:
        try:
            if estado_pantalla_completa['active']:
                return
            seleccionado = [name for name, var in variables_graficas.items() if var.get()]
            orden = ['smith', 'mag', 'polar', 'phase']
            seleccionados_ordenados = [n for n in orden if n in seleccionado]
            ancho_total = 0.79
            x0 = 0.07
            alto = 0.78
            if not seleccionados_ordenados:
                for name in orden:
                    if name == 'phase':
                        ax = axPhase
                    else:
                        ax = {'smith': axS, 'mag': axM, 'polar': axP}[name]
                    ax.set_visible(False)
                return
            n = len(seleccionados_ordenados)
            ancho = ancho_total / n
            for indice, name in enumerate(seleccionados_ordenados):
                if name == 'phase':
                    ax = axPhase
                else:
                    ax = {'smith': axS, 'mag': axM, 'polar': axP}[name]
                ax.set_visible(True)
                ax.set_position([x0 + indice * ancho, 0.1, ancho, alto])
            for name in orden:
                if name not in seleccionados_ordenados:
                    if name == 'phase':
                        ax = axPhase
                    else:
                        ax = {'smith': axS, 'mag': axM, 'polar': axP}[name]
                    ax.set_visible(False)
        except Exception:
            pass

    def recapturar_fondo() -> None:
        fig.canvas.draw()
        fondo['smith'] = fig.canvas.copy_from_bbox(axS.bbox)
        fondo['mag'] = fig.canvas.copy_from_bbox(axM.bbox)
        try:
            fondo['polar'] = fig.canvas.copy_from_bbox(axP.bbox)
        except Exception:
            fondo['polar'] = None
        try:
            fondo['phase'] = fig.canvas.copy_from_bbox(axPhase.bbox)
        except Exception:
            fondo['phase'] = None

    def salir_pantalla_completa() -> None:
        try:
            if not estado_pantalla_completa['active']:
                return
            for eje, pos in estado_pantalla_completa['positions'].items():
                try:
                    eje.set_position(pos)
                    eje.set_visible(estado_pantalla_completa['vis'].get(eje, True))
                except Exception:
                    pass
            estado_pantalla_completa['active'] = False
            estado_pantalla_completa['ax'] = None
            estado_pantalla_completa['positions'] = {}
            estado_pantalla_completa['vis'] = {}
            try:
                recapturar_fondo()
            except Exception:
                pass
            try:
                fig.canvas.draw_idle()
            except Exception:
                pass
        except Exception:
            pass

    def alternar_pantalla_completa(eje_clic: plt.Axes) -> None:
        try:
            if estado_pantalla_completa['active']:
                if estado_pantalla_completa['ax'] == eje_clic:
                    salir_pantalla_completa()
                    return
                salir_pantalla_completa()
        except Exception:
            pass
        posiciones: dict[plt.Axes, matplotlib.transforms.Bbox] = {}
        visibilidades: dict[plt.Axes, bool] = {}
        for eje in (axS, axM, axPhase, axP):
            try:
                posiciones[eje] = eje.get_position().frozen()
                visibilidades[eje] = eje.get_visible()
            except Exception:
                continue
            if eje != eje_clic:
                try:
                    eje.set_visible(False)
                except Exception:
                    pass
        try:
            eje_clic.set_position([0.07, 0.1, 0.79, 0.78])
        except Exception:
            pass
        try:
            eje_clic.set_visible(True)
        except Exception:
            pass
        estado_pantalla_completa['active'] = True
        estado_pantalla_completa['ax'] = eje_clic
        estado_pantalla_completa['positions'] = posiciones
        estado_pantalla_completa['vis'] = visibilidades
        try:
            recapturar_fondo()
        except Exception:
            pass
        try:
            fig.canvas.draw_idle()
        except Exception:
            pass

    def evento_doble_clic(event) -> None:
        try:
            if not getattr(event, 'dblclick', False):
                return
            ax = event.inaxes
            if ax in (axS, axM, axPhase, axP):
                alternar_pantalla_completa(ax)
        except Exception:
            pass
    try:
        fig.canvas.mpl_connect('button_press_event', evento_doble_clic)
    except Exception:
        pass
    tema_actual = {'v': 'light'}
    colores_tema: dict[str, str] = {'ACTIVE': '#2196F3', 'ACTIVE_HOVER': '#64B5F6', 'INACTIVE': '#E0E0E0', 'INACTIVE_HOVER': '#EEEEEE'}

    def alternar_vista_grafica(name: str) -> None:
        try:
            var = variables_graficas.get(name)
            if var is not None:
                var.set(not var.get())
                _al_cambiar_menu()
                for lbl, key, btn in botones_menu:
                    if key != 'theme':
                        if variables_graficas[key].get():
                            btn.color = colores_tema['ACTIVE']
                            btn.hovercolor = colores_tema['ACTIVE_HOVER']
                        else:
                            btn.color = colores_tema['INACTIVE']
                            btn.hovercolor = colores_tema['INACTIVE_HOVER']
                try:
                    fig.canvas.draw_idle()
                except Exception:
                    pass
        except Exception:
            pass

    def alternar_tema(_=None) -> None:
        try:
            modo_nuevo = 'dark' if tema_actual['v'] == 'light' else 'light'
            tema_actual['v'] = modo_nuevo
            aplicar_tema(modo_nuevo)
        except Exception:
            pass
    menu_superior_y = 0.92
    alto_menu_superior = 0.05
    definiciones_menu = [('Smith', 'smith'), ('Mag', 'mag'), ('Polar', 'polar'), ('Tema', 'theme')]
    botones_menu: list[tuple[str, str, Button]] = []
    ancho_boton = 0.79 / len(definiciones_menu)
    boton_x0 = 0.07
    for indice, (lbl, key) in enumerate(definiciones_menu):
        pass
    todos_botones: list[Button] = [btn for _, _, btn in botones_menu]

    def aplicar_tema(tema: str) -> None:
        try:
            if tema == 'light':
                fig.patch.set_facecolor('white')
                axS.set_facecolor('white')
                axM.set_facecolor('white')
                axP.set_facecolor('white')
                try:
                    axpanel.set_facecolor('#F5F5F5')
                except Exception:
                    pass
                for ax in (axS, axM, axP):
                    ax.tick_params(colors='black')
                    try:
                        for spine in ax.spines.values():
                            spine.set_color('black')
                    except Exception:
                        pass
                    try:
                        ax.grid(color='#DDDDDD')
                    except Exception:
                        pass
                try:
                    indicador_medicion.set_color('red')
                except Exception:
                    pass
                try:
                    texto_estado_inferior.set_color('black')
                except Exception:
                    pass
                try:
                    texto_estado_panel_titulo.set_color('black')
                    texto_estado_panel.set_color('black')
                    texto_estado_panel.set_bbox(dict(boxstyle='round,pad=0.25', facecolor='#F7FAFC', edgecolor='#1E88E5', linewidth=1.4, alpha=0.98))
                except Exception:
                    pass
                try:
                    status_txt.set_color('black')
                except Exception:
                    pass
                try:
                    if texto_estado_switch is not None:
                        texto_estado_switch.set_color('black')
                except Exception:
                    pass
                try:
                    if texto_titulo_switch is not None:
                        texto_titulo_switch.set_color('black')
                except Exception:
                    pass
                try:
                    lvl_ax.set_facecolor('whitesmoke')
                except Exception:
                    pass
                try:
                    if h_ax is not None:
                        h_ax.set_facecolor('whitesmoke')
                except Exception:
                    pass
                colores_tema['ACTIVE'] = '#2196F3'
                colores_tema['ACTIVE_HOVER'] = '#64B5F6'
                colores_tema['INACTIVE'] = '#E0E0E0'
                colores_tema['INACTIVE_HOVER'] = '#EEEEEE'
                try:
                    texto_estado_inferior.set_bbox(dict(facecolor='#F5F5F5', edgecolor='#CCCCCC', boxstyle='round,pad=0.25', alpha=0.9))
                except Exception:
                    pass
                theme_button_colour = '#9C27B0'
                theme_button_hover = '#BA68C8'
            else:
                fig.patch.set_facecolor('#121212')
                axS.set_facecolor('#000000')
                axM.set_facecolor('#000000')
                axP.set_facecolor('#000000')
                try:
                    axpanel.set_facecolor('#222222')
                except Exception:
                    pass
                for ax in (axS, axM, axP):
                    ax.tick_params(colors='white')
                    try:
                        for spine in ax.spines.values():
                            spine.set_color('white')
                    except Exception:
                        pass
                    try:
                        ax.grid(color='#444444')
                    except Exception:
                        pass
                try:
                    indicador_medicion.set_color('#76FF03')
                except Exception:
                    pass
                try:
                    texto_estado_inferior.set_color('white')
                except Exception:
                    pass
                try:
                    texto_estado_panel_titulo.set_color('white')
                    texto_estado_panel.set_color('white')
                    texto_estado_panel.set_bbox(dict(boxstyle='round,pad=0.25', facecolor='#202A33', edgecolor='#64B5F6', linewidth=1.4, alpha=0.98))
                except Exception:
                    pass
                try:
                    status_txt.set_color('white')
                except Exception:
                    pass
                try:
                    if texto_estado_switch is not None:
                        texto_estado_switch.set_color('white')
                except Exception:
                    pass
                try:
                    if texto_titulo_switch is not None:
                        texto_titulo_switch.set_color('white')
                except Exception:
                    pass
                try:
                    lvl_ax.set_facecolor('#333333')
                except Exception:
                    pass
                try:
                    if h_ax is not None:
                        h_ax.set_facecolor('#333333')
                except Exception:
                    pass
                colores_tema['ACTIVE'] = '#0066CC'
                colores_tema['ACTIVE_HOVER'] = '#3388CC'
                colores_tema['INACTIVE'] = '#444444'
                colores_tema['INACTIVE_HOVER'] = '#555555'
                try:
                    texto_estado_inferior.set_bbox(dict(facecolor='#333333', edgecolor='#666666', boxstyle='round,pad=0.25', alpha=0.9))
                except Exception:
                    pass
                theme_button_colour = '#8E24AA'
                theme_button_hover = '#9C27B0'
            for lbl, key, btn in botones_menu:
                if key != 'theme':
                    try:
                        if variables_graficas[key].get():
                            btn.color = colores_tema['ACTIVE']
                            btn.hovercolor = colores_tema['ACTIVE_HOVER']
                        else:
                            btn.color = colores_tema['INACTIVE']
                            btn.hovercolor = colores_tema['INACTIVE_HOVER']
                    except Exception:
                        pass
                else:
                    try:
                        btn.color = theme_button_colour
                        btn.hovercolor = theme_button_hover
                    except Exception:
                        pass
            try:
                fig.canvas.draw_idle()
            except Exception:
                pass
        except Exception:
            pass
    try:
        indicador_medicion.set_position((0.02, menu_superior_y + alto_menu_superior + 0.01))
    except Exception:
        pass
    aplicar_tema(tema_actual['v'])

    def aplicar_parametros_barrido():
        cur_start = float(ultimos['f'][0] / 1000000.0)
        cur_stop = float(ultimos['f'][-1] / 1000000.0)
        cur_pts = int(len(ultimos['f']))
        parametros = pedir_parametros_barrido(ParametrosBarrido(cur_start, cur_stop, cur_pts))
        if parametros is None:
            return
        nonlocal inicio_hz, fin_hz, puntos
        inicio_hz = parametros.inicio_mhz * 1000000.0
        fin_hz = parametros.fin_mhz * 1000000.0
        puntos = parametros.puntos
        if dispositivo_conectado:
            if hasattr(nv, 'configurar_barrido'):
                try:
                    nv.configurar_barrido(inicio_hz, fin_hz, puntos)
                except TypeError:
                    try:
                        nv.configurar_frecuencias_barrido(inicio_hz, fin_hz, puntos)
                        try:
                            nv.configurar_barrido(inicio_hz, fin_hz)
                        except Exception:
                            pass
                    except Exception:
                        pass
            if hasattr(nv, 'obtener_frecuencias'):
                try:
                    nv.obtener_frecuencias()
                except Exception:
                    pass
            ultimos['f'] = getattr(nv, 'frecuencias', np.linspace(inicio_hz, fin_hz, puntos))
        else:
            try:
                nv.frecuencias = np.linspace(inicio_hz, fin_hz, puntos)
            except Exception:
                pass
            ultimos['f'] = nv.frecuencias
        ultimos['s11'] = None
        ultimos['s21'] = None
        ultimos['s12'] = None
        ultimos['s22'] = None
        ultimos['s12'] = None
        ultimos['s22'] = None
        try:
            rango_x['lo'] = float(ultimos['f'][0] / 1000000.0)
            rango_x['hi'] = float(ultimos['f'][-1] / 1000000.0)
        except Exception:
            rango_x['lo'], rango_x['hi'] = (0.0, 1.0)
        axM.set_xlim(rango_x['lo'], rango_x['hi'])
        axM.set_ylim(-80, 5)
        actualizar_titulo()
        recapturar_fondo()
        try:
            actualizar_rango_slider_horizontal()
            selected_idx['v'] = 0
            if hslider is not None:
                hslider.set_val(0)
        except Exception:
            pass
        if modo_adquisicion.get('modo') == 'single':
            modo_adquisicion['single_pending'] = True
        fig.canvas.draw_idle()
        calibracion.limpiar_todo()
        actualizar_estado()
        actualizar_barra_estado()
    menu_dispositivo.add_command(label='Parámetros de barrido…', command=aplicar_parametros_barrido, accelerator='Ctrl+E')

    def al_alternar_tr():
        try:
            sparam_var = variables_param_s.get('S21')
        except Exception:
            sparam_var = None
        if sparam_var is not None:
            try:
                sparam_var.set(bool(v_show_tr.get()))
            except Exception:
                pass
        recapturar_fondo()
        try:
            actualizar_frame()
        except Exception:
            pass
        try:
            fig.canvas.draw_idle()
        except Exception:
            pass
    menu_dispositivo.add_checkbutton(label='Modo T/R', variable=v_show_tr, command=al_alternar_tr)

    def al_alternar_intercambio():
        recapturar_fondo()
        try:
            actualizar_frame()
        except Exception:
            pass
        try:
            fig.canvas.draw_idle()
        except Exception:
            pass
    menu_dispositivo.add_checkbutton(label='Intercambiar puertos', variable=v_swap, command=al_alternar_intercambio)
    menu_dispositivo.add_separator()
    ports_menu = tk.Menu(menu_dispositivo, tearoff=False)
    menu_dispositivo.add_cascade(label='Seleccionar dispositivo:', menu=ports_menu)

    def actualizar_menu_puertos():
        ports_menu.delete(0, 'end')
        puertos = listar_puertos_seriales()
        if not puertos:
            ports_menu.add_command(label='(no hay puertos)', state='disabled')
        else:
            for puerto, etiqueta in puertos:
                ports_menu.add_radiobutton(label=etiqueta, value=puerto, variable=v_selected)
        ports_menu.add_separator()
        ports_menu.add_command(label='Actualizar', command=actualizar_menu_puertos)
        ports_menu.add_command(label='Otro…', command=elegir_otro_puerto, accelerator='Ctrl+P')
        ports_menu.add_command(label='Aplicar puerto seleccionado', command=aplicar_puerto_seleccionado, accelerator='Ctrl+Shift+P')

    def elegir_otro_puerto():
        puerto = dialogo_elegir_puerto()
        if puerto:
            v_selected.set(puerto)
            aplicar_puerto_seleccionado()

    def usar_dispositivo_simulado():
        v_selected.set('')
        messagebox.showinfo('Mock', "Seleccionado modo Viewer (sin VNA). Use 'Apply selected port' para aplicar.")

    def aplicar_puerto_seleccionado(event=None):
        nonlocal evento_detener, nv, dispositivo_conectado, dispositivo, hilo_escaneo
        sel = v_selected.get()
        try:
            evento_detener.set()
            if hilo_escaneo is not None:
                hilo_escaneo.join(timeout=1.0)
            if hasattr(nv, 'cerrar'):
                nv.cerrar()
        except Exception:
            pass
        if not sel:
            dispositivo_conectado = False
            ultimos['f'] = np.linspace(inicio_hz or 200000000.0, fin_hz or 1425000000.0, puntos or 50)
            dispositivo = 'Viewer (sin VNA)'
        else:
            iniciar_dispositivo(sel)
            if dispositivo_conectado:
                ultimos['f'] = nv.frecuencias
        ultimos['s11'] = None
        ultimos['s21'] = None
        ultimos['s12'] = None
        ultimos['s22'] = None
        try:
            rango_x['lo'] = float(ultimos['f'][0] / 1000000.0)
            rango_x['hi'] = float(ultimos['f'][-1] / 1000000.0)
            axM.set_xlim(rango_x['lo'], rango_x['hi'])
        except Exception:
            pass
        axM.set_ylim(-80, 5)
        recapturar_fondo()
        try:
            actualizar_rango_slider_horizontal()
            selected_idx['v'] = 0
            if hslider is not None:
                hslider.set_val(0)
        except Exception:
            pass
        if modo_adquisicion.get('modo') == 'single':
            modo_adquisicion['single_pending'] = True
        calibracion.limpiar_todo()
        actualizar_titulo()
        reiniciar_colores()
        actualizar_estado()
        actualizar_barra_estado()
        evento_detener = threading.Event()
        hilo_escaneo = threading.Thread(target=hilo_medicion, daemon=True)
        hilo_escaneo.start()
    actualizar_menu_puertos()
    menu_dispositivo.add_command(label='Aplicar puerto seleccionado', command=aplicar_puerto_seleccionado, accelerator='Ctrl+Shift+P')
    menu_dispositivo.add_command(label='Dispositivo simulado (visualizador)', command=usar_dispositivo_simulado)
    axpanel = fig.add_axes([0.88, 0.1, 0.1, 0.78])
    axpanel.axis('off')
    axpanel.set_facecolor('#F5F5F5')
    y = 0.97
    BTN_HEIGHT = 0.05
    BTN_STEP = 0.065

    def _boton(etiqueta: str, cb) -> Button:
        nonlocal y
        axb = fig.add_axes([0.885, y - BTN_HEIGHT, 0.095, BTN_HEIGHT])
        b = Button(axb, etiqueta)
        try:
            b.color = colores_tema.get('INACTIVE', '#E0E0E0')
            b.hovercolor = colores_tema.get('INACTIVE_HOVER', '#EEEEEE')
        except Exception:
            pass
        b.on_clicked(cb)
        try:
            todos_botones.append(b)
        except Exception:
            pass
        y -= BTN_STEP
        return b
    INITIAL_COLOR = '#E0E0E0'
    OK_COLOR = '#4CAF50'
    APPLY_COLOR = '#2196F3'
    WARN_COLOR = '#F44336'

    def al_cambiar_modo_calibracion(sel: str) -> None:
        nonlocal calibracion
        if sel.startswith('SOLT'):
            calibracion = CalibracionSOLT()
            try:
                btn_thru.ax.set_visible(True)
            except Exception:
                pass
        else:
            calibracion = CalibracionSOL()
            try:
                btn_thru.ax.set_visible(False)
            except Exception:
                pass
        calibracion.limpiar_todo()
        reiniciar_colores()
        actualizar_estado()
        try:
            actualizar_frame()
            fig.canvas.draw_idle()
        except Exception:
            pass

    def _color_hover(color: str) -> str:
        try:
            color = str(color).strip()
            if not color.startswith('#') or len(color) != 7:
                return color
            r = int(color[1:3], 16)
            g = int(color[3:5], 16)
            b = int(color[5:7], 16)
            mix = 0.22
            r = int(r + (255 - r) * mix)
            g = int(g + (255 - g) * mix)
            b = int(b + (255 - b) * mix)
            return f'#{r:02X}{g:02X}{b:02X}'
        except Exception:
            return color

    def establecer_color_boton(b: Button, color: str) -> None:
        try:
            b.color = color
            b.hovercolor = _color_hover(color)
            b.ax.set_facecolor(color)
            fig.canvas.draw_idle()
        except Exception:
            pass

    def reiniciar_colores() -> None:
        for b in (btn_short, btn_open, btn_load, btn_thru, btn_apply_cal, btn_clear_meas, btn_clear):
            establecer_color_boton(b, INITIAL_COLOR)

    def actualizar_colores_calibracion() -> None:
        try:
            establecer_color_boton(btn_short, OK_COLOR if calibracion.m_corto is not None else INITIAL_COLOR)
        except Exception:
            pass
        try:
            establecer_color_boton(btn_open, OK_COLOR if calibracion.m_abierto is not None else INITIAL_COLOR)
        except Exception:
            pass
        try:
            establecer_color_boton(btn_load, OK_COLOR if calibracion.m_carga is not None else INITIAL_COLOR)
        except Exception:
            pass
        try:
            tiene_thru = hasattr(calibracion, 'm_thru') and getattr(calibracion, 'm_thru') is not None
            establecer_color_boton(btn_thru, OK_COLOR if tiene_thru else INITIAL_COLOR)
        except Exception:
            pass
        try:
            establecer_color_boton(btn_apply_cal, APPLY_COLOR if calibracion.aplicada else INITIAL_COLOR)
        except Exception:
            pass
    fig.text(0.885, y, 'Barrido/Puerto', fontsize=9, fontweight='bold', va='top', ha='left')
    y -= 0.035
    btn_sweep = _boton('Aplicar barrido', lambda _: aplicar_parametros_barrido())
    btn_pick = _boton('Elegir puerto', lambda _: elegir_otro_puerto())
    btn_apply_port = _boton('Aplicar puerto', lambda _: aplicar_puerto_seleccionado())
    status_txt = fig.text(0.885, 0.72, 'Measured: —\nApply: OFF', fontsize=8, va='top', ha='left', bbox=dict(boxstyle='round,pad=0.25', facecolor='white', edgecolor='black', alpha=0.8))
    status_txt_drag_info = {'dragging': False, 'offset': (0.0, 0.0)}

    def _al_presionar_estado(event):
        try:
            contains, _ = status_txt.contains(event)
        except Exception:
            contains = False
        if contains:
            status_txt_drag_info['dragging'] = True
            inv = fig.transFigure.inverted()
            click_x, click_y = inv.transform((event.x, event.y))
            pos_x, pos_y = status_txt.get_position()
            status_txt_drag_info['offset'] = (pos_x - click_x, pos_y - click_y)

    def _al_mover_estado(event):
        if not status_txt_drag_info.get('dragging'):
            return
        inv = fig.transFigure.inverted()
        click_x, click_y = inv.transform((event.x, event.y))
        dx, dy = status_txt_drag_info.get('offset', (0.0, 0.0))
        new_x = click_x + dx
        new_y = click_y + dy
        new_x = max(0.0, min(new_x, 0.98))
        new_y = max(0.0, min(new_y, 0.98))
        status_txt.set_position((new_x, new_y))
        try:
            fig.canvas.draw_idle()
        except Exception:
            pass

    def _al_soltar_estado(event):
        status_txt_drag_info['dragging'] = False
    fig.canvas.mpl_connect('button_press_event', _al_presionar_estado)
    fig.canvas.mpl_connect('motion_notify_event', _al_mover_estado)
    fig.canvas.mpl_connect('button_release_event', _al_soltar_estado)
    y -= 0.07
    texto_titulo_switch = fig.text(0.885, y, 'Switch', fontsize=9, fontweight='bold', va='top', ha='left')
    y -= 0.035
    boton_switch = _boton('S11/S21', alternar_switch)
    establecer_color_boton(boton_switch, WARN_COLOR)
    texto_estado_switch = fig.text(0.885, y - 0.02, 'Switch: S11/S21', fontsize=8, va='top', ha='left')
    try:
        puertos_excluidos: set[str] = set()
        try:
            dev_port = puerto_aplicado.get('dev')
            if dev_port:
                puertos_excluidos.add(str(dev_port))
        except Exception:
            pass
        puerto_switch_detectado = detectar_puerto_arduino(puertos_excluidos)
        if puerto_switch_detectado is None:
            _usar_boton_switch_como_vista()
        else:
            switch_hw_disponible['v'] = True
    except Exception:
        _usar_boton_switch_como_vista()
    y -= 0.07
    fig.text(0.885, y, 'Calibración', fontsize=9, fontweight='bold', va='top', ha='left')
    y -= 0.035

    def actualizar_estado() -> None:
        st: list[str] = []
        if calibracion.m_corto is not None:
            st.append('Short')
        if calibracion.m_abierto is not None:
            st.append('Open')
        if calibracion.m_carga is not None:
            st.append('Load')
        if hasattr(calibracion, 'm_thru') and getattr(calibracion, 'm_thru') is not None:
            st.append('Thru')
        if st:
            cap_lines = ['Measured:'] + st
        else:
            cap_lines = ['Measured: —']
        cur = 'ON' if calibracion.aplicada else 'OFF'
        status_txt.set_text('\n'.join(cap_lines + [f'Apply: {cur}']))
        actualizar_colores_calibracion()
        try:
            actualizar_barra_estado()
        except Exception:
            pass
    actualizar_estado()

    def al_short(_):
        param_s11 = ultimos.get('s11')
        if param_s11 is None:
            return
        calibracion.m_corto = param_s11.copy()
        calibracion.calcular()
        actualizar_estado()
        establecer_color_boton(btn_short, OK_COLOR)
        try:
            actualizar_frame()
            fig.canvas.draw_idle()
        except Exception:
            pass

    def al_open(_):
        param_s11 = ultimos.get('s11')
        if param_s11 is None:
            return
        calibracion.m_abierto = param_s11.copy()
        calibracion.calcular()
        actualizar_estado()
        establecer_color_boton(btn_open, OK_COLOR)
        try:
            actualizar_frame()
            fig.canvas.draw_idle()
        except Exception:
            pass

    def al_load(_):
        param_s11 = ultimos.get('s11')
        if param_s11 is None:
            return
        calibracion.m_carga = param_s11.copy()
        calibracion.calcular()
        actualizar_estado()
        establecer_color_boton(btn_load, OK_COLOR)
        try:
            actualizar_frame()
            fig.canvas.draw_idle()
        except Exception:
            pass

    def al_limpiar_mediciones(_):
        calibracion.limpiar_mediciones()
        calibracion.aplicada = False
        actualizar_estado()
        try:
            actualizar_frame()
            fig.canvas.draw_idle()
        except Exception:
            pass

    def al_limpiar(_):
        calibracion.limpiar_todo()
        actualizar_estado()
        reiniciar_colores()
        try:
            actualizar_frame()
            fig.canvas.draw_idle()
        except Exception:
            pass

    def al_aplicar_calibracion(_):
        if calibracion.tiene_todo() and calibracion.calcular():
            calibracion.aplicada = True
            actualizar_estado()
            establecer_color_boton(btn_apply_cal, APPLY_COLOR)
            try:
                actualizar_frame()
                fig.canvas.draw_idle()
            except Exception:
                pass

    def al_thru(_):
        try:
            from tkinter import messagebox
        except Exception:
            messagebox = None
        if not hasattr(calibracion, 'm_thru'):
            if messagebox is not None:
                try:
                    messagebox.showerror('Thru', "El modo de calibración seleccionado no admite la referencia Thru.\nSeleccione 'SOLT' para poder capturar la calibración de transmisión.")
                except Exception:
                    pass
            return
        param_s21 = ultimos.get('s21')
        param_s12 = ultimos.get('s12')
        use_s = None
        try:
            if estado_switch.get('v'):
                use_s = param_s12 if param_s12 is not None else param_s21
            else:
                use_s = param_s21 if param_s21 is not None else param_s12
        except Exception:
            use_s = param_s21 if param_s21 is not None else param_s12
        if use_s is None:
            if messagebox is not None:
                try:
                    messagebox.showerror('Thru', 'No hay medición de transmisión disponible para registrar como Thru.\nRealice un barrido con la referencia Thru conectada antes de pulsar este botón.')
                except Exception:
                    pass
            return
        try:
            calibracion.m_paso = use_s.copy()
        except Exception:
            calibracion.m_paso = use_s
        try:
            calibracion.calcular()
        except Exception:
            pass
        actualizar_estado()
        establecer_color_boton(btn_thru, OK_COLOR)
        try:
            actualizar_frame()
            fig.canvas.draw_idle()
        except Exception:
            pass

    def al_guardar_calibracion(_):
        from tkinter import filedialog, messagebox
        if not calibracion.tiene_todo():
            try:
                messagebox.showerror('Guardar calibración', 'No hay calibración completa para guardar.')
            except Exception:
                pass
            return
        ruta_archivo = filedialog.asksaveasfilename(title='Guardar calibración', defaultextension='.npz', filetypes=[('Calibración', '*.npz'), ('Todos', '*.*')])
        if not ruta_archivo:
            return
        try:
            data = {}
            data['type'] = 'SOLT' if isinstance(calibracion, CalibracionSOLT) else 'SOL'
            if calibracion.m_abierto is not None:
                data['m_open'] = calibracion.m_abierto
            if calibracion.m_corto is not None:
                data['m_short'] = calibracion.m_corto
            if calibracion.m_carga is not None:
                data['m_load'] = calibracion.m_carga
            if hasattr(calibracion, 'm_thru') and getattr(calibracion, 'm_thru') is not None:
                data['m_thru'] = getattr(calibracion, 'm_thru')
            if calibracion.Ed is not None:
                data['Ed'] = calibracion.Ed
            if calibracion.Es is not None:
                data['Es'] = calibracion.Es
            if calibracion.Er is not None:
                data['Er'] = calibracion.Er
            if hasattr(calibracion, 'thru_factor') and getattr(calibracion, 'thru_factor') is not None:
                data['thru_factor'] = getattr(calibracion, 'thru_factor')
            np.savez(ruta_archivo, **data)
            try:
                messagebox.showinfo('Guardar calibración', f'Calibración guardada en:\n{ruta_archivo}')
            except Exception:
                pass
        except Exception as exc:
            try:
                messagebox.showerror('Guardar calibración', f'Error al guardar calibración: {exc}')
            except Exception:
                pass
            registro.exception('Error al guardar calibración', exc_info=exc)

    def al_cargar_calibracion(_):
        nonlocal calibracion
        from tkinter import filedialog, messagebox
        ruta_archivo = filedialog.askopenfilename(title='Cargar calibración', filetypes=[('Calibración', '*.npz'), ('Todos', '*.*')])
        if not ruta_archivo:
            return
        try:
            data = np.load(ruta_archivo, allow_pickle=True)
            cal_type = str(data.get('type', 'SOL'))
            if cal_type == 'SOLT':
                calibracion = CalibracionSOLT()
            else:
                calibracion = CalibracionSOL()
            for key in ('m_open', 'm_short', 'm_load', 'm_thru', 'Ed', 'Es', 'Er', 'thru_factor'):
                if key in data:
                    setattr(calibracion, key, data[key])
            calibracion.aplicada = False
            try:
                calibracion.calcular()
            except Exception:
                pass
            actualizar_estado()
            try:
                if isinstance(calibracion, CalibracionSOLT):
                    btn_thru.ax.set_visible(True)
                else:
                    btn_thru.ax.set_visible(False)
            except Exception:
                pass
            actualizar_colores_calibracion()
            try:
                actualizar_frame()
                fig.canvas.draw_idle()
            except Exception:
                pass
            try:
                messagebox.showinfo('Cargar calibración', f'Calibración cargada desde:\n{ruta_archivo}')
            except Exception:
                pass
        except Exception as exc:
            try:
                messagebox.showerror('Cargar calibración', f'Error al cargar calibración: {exc}')
            except Exception:
                pass
            registro.exception('Error al cargar calibración', exc_info=exc)
    btn_short = _boton('Short', al_short)
    btn_open = _boton('Open', al_open)
    btn_load = _boton('Load', al_load)
    btn_thru = _boton('Thru', al_thru)
    try:
        btn_thru.ax.set_visible(False)
    except Exception:
        pass
    y -= 0.02
    btn_clear_meas = _boton('Limpiar\nMedición', al_limpiar_mediciones)
    btn_clear = _boton('Limpiar', al_limpiar)
    btn_apply_cal = _boton('Aplicar calibración', al_aplicar_calibracion)
    btn_save_cal = _boton('Guardar Cal', al_guardar_calibracion)
    btn_load_cal = _boton('Cargar Cal', al_cargar_calibracion)
    actualizar_colores_calibracion()
    fig.text(0.885, y, 'Métricas', fontsize=9, fontweight='bold', va='top', ha='left')
    y -= 0.035
    texto_metricas = fig.text(0.885, y, '—', fontsize=7, va='top', ha='left', wrap=True)
    y -= 0.07
    lineas_magnitud_guardadas: list[matplotlib.lines.Line2D] = []

    def al_guardar_traza(_):
        try:
            arreglo_frecuencias = ultimos.get('f')
            if arreglo_frecuencias is None or len(arreglo_frecuencias) == 0:
                return
            param_s11 = ultimos.get('s11')
            param_s21 = ultimos.get('s21')
            param_s12 = ultimos.get('s12')
            param_s22 = ultimos.get('s22')
            if v_swap.get():
                param_s11, param_s21 = (param_s21, param_s11)
            if calibracion.aplicada:
                if hasattr(calibracion, 'aplicar_reflexion'):
                    s11_corr = calibracion.aplicar_reflexion(param_s11) if param_s11 is not None else None
                    s21_corr = calibracion.corregir_transmision_thru(param_s21) if param_s21 is not None else None
                    s12_corr = calibracion.corregir_transmision_thru(param_s12) if param_s12 is not None else None
                    s22_corr = calibracion.aplicar_reflexion(param_s22) if param_s22 is not None else None
                else:
                    s11_corr = calibracion.corregir_medicion_sol(param_s11) if param_s11 is not None else None
                    s21_corr = param_s21
                    s12_corr = param_s12
                    s22_corr = calibracion.corregir_medicion_sol(param_s22) if param_s22 is not None else None
            else:
                s11_corr = param_s11
                s21_corr = param_s21
                s12_corr = param_s12
                s22_corr = param_s22
            frecuencias_mhz = np.array(arreglo_frecuencias) / 1000000.0
            parametros = {'S11': s11_corr, 'S12': s12_corr, 'S21': s21_corr, 'S22': s22_corr}
            colours = {'S11': 'tab:blue', 'S12': 'tab:orange', 'S21': 'tab:red', 'S22': 'tab:green'}
            for pname, arreglo in parametros.items():
                try:
                    if arreglo is None:
                        continue
                    if not (variables_param_s.get(pname) and variables_param_s[pname].get()):
                        continue
                    magnitud = 20.0 * np.log10(np.maximum(np.abs(arreglo), 1e-15))
                    line_style = '--'
                    linea = axM.plot(frecuencias_mhz, magnitud, linestyle=line_style, linewidth=1.0, color=colours.get(pname, 'gray'), alpha=0.5)[0]
                    lineas_magnitud_guardadas.append(linea)
                except Exception:
                    pass
            try:
                fig.canvas.draw_idle()
            except Exception:
                pass
        except Exception:
            pass
    btn_save_trace = _boton('Guardar\nTraza', al_guardar_traza)
    btn_modo_adquisicion = None

    def actualizar_boton_modo_adquisicion() -> None:
        try:
            if btn_modo_adquisicion is None:
                return
            if modo_adquisicion.get('modo') == 'single':
                btn_modo_adquisicion.label.set_text('LIVE')
                establecer_color_boton(btn_modo_adquisicion, WARN_COLOR)
            else:
                btn_modo_adquisicion.label.set_text('Captura\núnica')
                establecer_color_boton(btn_modo_adquisicion, APPLY_COLOR)
        except Exception:
            pass

    def al_alternar_modo_adquisicion(_):
        if modo_adquisicion.get('modo') == 'live':
            modo_adquisicion['modo'] = 'single'
            modo_adquisicion['single_pending'] = True
            pausado['v'] = False
        else:
            modo_adquisicion['modo'] = 'live'
            modo_adquisicion['single_pending'] = False
            pausado['v'] = False
        actualizar_boton_modo_adquisicion()
        try:
            actualizar_barra_estado()
            fig.canvas.draw_idle()
        except Exception:
            pass

    def al_alternar_hold(_):
        pausado['v'] = not pausado.get('v')
        try:
            if pausado['v']:
                indicador_medicion.set_text('● HOLD')
                indicador_medicion.set_color('orange')
            else:
                indicador_medicion.set_text('● LIVE')
        except Exception:
            pass
        try:
            fig.canvas.draw_idle()
        except Exception:
            pass
    btn_modo_adquisicion = _boton('Captura\núnica', al_alternar_modo_adquisicion)
    actualizar_boton_modo_adquisicion()
    btn_hold = _boton('HOLD', al_alternar_hold)
    for b in (btn_short, btn_open, btn_load, btn_clear_meas, btn_clear, btn_apply_cal):
        establecer_color_boton(b, INITIAL_COLOR)
    selected_idx: dict[str, int | None] = {'v': 0}
    selected_idx_B: dict[str, int | None] = {'v': None}
    level_db_current: dict[str, float] = {'v': 0.0}
    selected_line = None
    sel_marker_s11 = None
    sel_marker_s21 = None
    selected_line_B = None
    sel_marker_s11_B = None
    sel_marker_s21_B = None
    s21_val_text = None
    s11_val_text = None
    try:
        lvl_ax = fig.add_axes([0.02, 0.18, 0.035, 0.65], facecolor='whitesmoke')
        lvl_slider = Slider(ax=lvl_ax, label='Nivel (dB)', valmin=0.0, valmax=31.5, valinit=0.0, valstep=0.5, orientation='vertical', valfmt='%0.1f dB')
        try:
            lvl_slider.valtext.set_visible(False)
        except Exception:
            pass
        try:
            lvl_ax.get_xaxis().set_visible(False)
        except Exception:
            pass
        lvl_val_text = fig.text(0.02, 0.15, '0.0 dB', transform=fig.transFigure, fontsize=8)
        s21_val_text = fig.text(0.02, 0.12, '', transform=fig.transFigure, fontsize=8, color='tab:red')
        s11_val_text = fig.text(0.02, 0.09, '', transform=fig.transFigure, fontsize=8, color='tab:blue')
        initial_arduino_ok = False
        if not initial_arduino_ok:
            try:
                lvl_ax.set_visible(False)
                lvl_val_text.set_visible(False)
                s21_val_text.set_visible(False)
                s11_val_text.set_visible(False)
                if not switch_hw_disponible.get('v'):
                    _usar_boton_switch_como_vista()
            except Exception:
                pass
        level_db_current: dict[str, float] = {'v': 0.0}
        selected_idx: dict[str, int | None] = {'v': 0}
        selected_line = axM.axvline(0, color='gray', linestyle='--', linewidth=1.0)
        selected_line.set_visible(False)
        sel_marker_s21, = axM.plot([], [], marker='o', color='tab:red', markersize=6)
        sel_marker_s11, = axM.plot([], [], marker='o', color='tab:blue', markersize=6)
        selected_line_B = axM.axvline(0, color='gray', linestyle=':', linewidth=1.0)
        selected_line_B.set_visible(False)
        sel_marker_s21_B, = axM.plot([], [], marker='x', color='tab:red', markersize=6)
        sel_marker_s11_B, = axM.plot([], [], marker='x', color='tab:blue', markersize=6)
        hslider = None
        idx_text = None
        freq_text = None
        s21_text = None
        diff_text = None

        def actualizar_rango_slider_horizontal() -> None:
            nonlocal hslider
            try:
                if hslider is None:
                    return
                arreglo_frecuencias = ultimos.get('f')
                if arreglo_frecuencias is None or len(arreglo_frecuencias) == 0:
                    return
                max_idx = max(0, len(arreglo_frecuencias) - 2)
                if hslider.valmax != max_idx:
                    hslider.valmax = max_idx
                    hslider.ax.set_xlim(hslider.valmin, hslider.valmax)
                    if hslider.val > hslider.valmax:
                        hslider.set_val(hslider.valmax)
                if selected_idx.get('v') is None:
                    selected_idx['v'] = int(round(hslider.val))
            except Exception:
                pass
        bar_update_func: dict[str, callable | None] = {'func': None}
        try:
            h_ax = fig.add_axes([0.12, 0.022, 0.74, 0.022], facecolor='whitesmoke')
            h_ax.set_visible(True)
            arreglo_inicial = ultimos.get('f')
            puntos_iniciales = len(arreglo_inicial) if arreglo_inicial is not None else 0
            hslider = Slider(ax=h_ax, label='', valmin=0, valmax=max(0, puntos_iniciales - 2), valinit=0, valstep=1, orientation='horizontal')
            try:
                hslider.valtext.set_visible(False)
            except Exception:
                pass
            try:
                hslider.ax.set_xticks([])
                hslider.ax.set_yticks([])
                for _sp in hslider.ax.spines.values():
                    _sp.set_visible(False)
            except Exception:
                pass
            plus_text = fig.text(0.075, 0.064, 'M1', transform=fig.transFigure, fontsize=9, fontweight='bold')
            idx_text = fig.text(0.115, 0.064, '0', transform=fig.transFigure, fontsize=8)
            freq_text = fig.text(0.155, 0.064, '', transform=fig.transFigure, fontsize=8)
            s21_text = fig.text(0.275, 0.064, '', transform=fig.transFigure, fontsize=8, color='tab:red')
            diff_text = fig.text(0.34, 0.064, '', transform=fig.transFigure, fontsize=8, color='tab:blue')

            def _actualizar_textos_barra() -> None:
                nonlocal idx_text, freq_text, s21_text, diff_text
                try:
                    indice_val = selected_idx.get('v')
                except Exception:
                    indice_val = None
                if indice_val is None:
                    if idx_text is not None:
                        idx_text.set_text('')
                    if freq_text is not None:
                        freq_text.set_text('')
                    if s21_text is not None:
                        s21_text.set_text('')
                    if diff_text is not None:
                        diff_text.set_text('')
                    return
                try:
                    idx_text.set_text(f'{indice_val}')
                except Exception:
                    pass
                arreglo_frecuencias = ultimos.get('f')
                s11_arr = ultimos.get('s11')
                s21_arr = ultimos.get('s21')
                if arreglo_frecuencias is not None and 0 <= indice_val < len(arreglo_frecuencias):
                    try:
                        freq_text.set_text(f'{arreglo_frecuencias[indice_val] / 1000000.0:.2f} MHz')
                    except Exception:
                        freq_text.set_text('')
                else:
                    try:
                        freq_text.set_text('')
                    except Exception:
                        pass
                try:
                    s11_cur, s21_cur = (s21_arr, s11_arr) if v_swap.get() else (s11_arr, s21_arr)
                    if calibracion.aplicada:
                        if hasattr(calibracion, 'aplicar_reflexion'):
                            s11_corr = calibracion.aplicar_reflexion(s11_cur) if s11_cur is not None else None
                            s21_corr = calibracion.corregir_transmision_thru(s21_cur) if s21_cur is not None else None
                        else:
                            s11_corr = calibracion.corregir_medicion_sol(s11_cur) if s11_cur is not None else None
                            s21_corr = s21_cur
                    else:
                        s11_corr = s11_cur
                        s21_corr = s21_cur
                    y11_db = None
                    y21_db = None
                    if s11_corr is not None and 0 <= indice_val < len(s11_corr):
                        try:
                            y11_db = 20.0 * np.log10(max(abs(s11_corr[indice_val]), 1e-15))
                        except Exception:
                            y11_db = None
                    if s21_corr is not None and 0 <= indice_val < len(s21_corr):
                        try:
                            y21_db = 20.0 * np.log10(max(abs(s21_corr[indice_val]), 1e-15))
                        except Exception:
                            y21_db = None
                    if y21_db is not None and s21_text is not None:
                        try:
                            s21_text.set_text(f'{y21_db:+.1f} dB')
                        except Exception:
                            s21_text.set_text('')
                    elif s21_text is not None:
                        s21_text.set_text('')
                    if y11_db is not None and diff_text is not None:
                        try:
                            diff_text.set_text(f'{y11_db:+.1f} dB')
                        except Exception:
                            diff_text.set_text('')
                    elif diff_text is not None:
                        diff_text.set_text('')
                except Exception:
                    if s21_text is not None:
                        s21_text.set_text('')
                    if diff_text is not None:
                        diff_text.set_text('')
            bar_update_func['func'] = _actualizar_textos_barra
            plus_text.set_visible(True)
            idx_text.set_visible(True)
            freq_text.set_visible(True)
            s21_text.set_visible(True)
            diff_text.set_visible(True)
            selected_idx['v'] = int(round(hslider.val))

            def _al_cambiar_slider_horizontal(val):
                try:
                    indice_int = int(round(val))
                    selected_idx['v'] = indice_int
                    actualizar_puntos_seleccionados(draw=True)
                except Exception:
                    pass
            hslider.on_changed(_al_cambiar_slider_horizontal)
            actualizar_rango_slider_horizontal()
        except Exception:
            pass

        def actualizar_puntos_seleccionados_anterior(draw: bool=True) -> None:
            try:
                actualizar_barra_estado([])
            except Exception:
                pass
            indice = selected_idx.get('v')
            if indice is None:
                selected_line.set_visible(False)
                sel_marker_s21.set_data([], [])
                sel_marker_s11.set_data([], [])
                s21_val_text.set_text('')
                s11_val_text.set_text('')
                try:
                    actualizar_barra_estado([])
                except Exception:
                    pass
                try:
                    if bar_update_func.get('func'):
                        bar_update_func['func']()
                except Exception:
                    pass
                if draw:
                    try:
                        fig.canvas.draw_idle()
                    except Exception:
                        pass
                return
            arreglo_frecuencias = ultimos.get('f')
            param_s11 = ultimos.get('s11')
            param_s21 = ultimos.get('s21')
            if arreglo_frecuencias is None or param_s11 is None or param_s21 is None:
                selected_line.set_visible(False)
                sel_marker_s21.set_data([], [])
                sel_marker_s11.set_data([], [])
                s21_val_text.set_text('')
                s11_val_text.set_text('')
                try:
                    actualizar_barra_estado([])
                except Exception:
                    pass
                try:
                    if bar_update_func.get('func'):
                        bar_update_func['func']()
                except Exception:
                    pass
                if draw:
                    try:
                        fig.canvas.draw_idle()
                    except Exception:
                        pass
                return
            s11_cur, s21_cur = (param_s21, param_s11) if v_swap.get() else (param_s11, param_s21)
            s12_cur = ultimos.get('s12')
            s22_cur = ultimos.get('s22')
            if calibracion.aplicada:
                if hasattr(calibracion, 'aplicar_reflexion'):
                    s11_corr = calibracion.aplicar_reflexion(s11_cur) if s11_cur is not None else None
                    s21_corr = calibracion.corregir_transmision_thru(s21_cur) if s21_cur is not None else None
                    s12_corr = calibracion.corregir_transmision_thru(s12_cur) if s12_cur is not None else None
                    s22_corr = calibracion.aplicar_reflexion(s22_cur) if s22_cur is not None else None
                else:
                    s11_corr = calibracion.corregir_medicion_sol(s11_cur) if s11_cur is not None else None
                    s21_corr = s21_cur
                    s12_corr = s12_cur
                    s22_corr = calibracion.corregir_medicion_sol(s22_cur) if s22_cur is not None else None
            else:
                s11_corr = s11_cur
                s21_corr = s21_cur
                s12_corr = s12_cur
                s22_corr = s22_cur
            frecuencias_mhz = np.array(arreglo_frecuencias) / 1000000.0
            try:
                frecuencias_mhz_limpias, param_s11_limpio_sel, param_s21_limpio_sel = _limpiar_traza(frecuencias_mhz, s11_corr, s21_corr)
            except Exception:
                frecuencias_mhz_limpias, param_s11_limpio_sel, param_s21_limpio_sel = (frecuencias_mhz, s11_corr, s21_corr)
            try:
                mascara = np.isfinite(s11_corr) & np.isfinite(s21_corr)
            except Exception:
                mascara = None
            if s12_corr is not None and mascara is not None:
                try:
                    s12_masked = s12_corr[mascara]
                    if len(s12_masked) > len(param_s21_limpio_sel):
                        param_s12_limpio_sel = s12_masked[:len(param_s21_limpio_sel)]
                    else:
                        param_s12_limpio_sel = s12_masked.copy()
                except Exception:
                    param_s12_limpio_sel = None
            else:
                param_s12_limpio_sel = None
            if s22_corr is not None and mascara is not None:
                try:
                    s22_masked = s22_corr[mascara]
                    if len(s22_masked) > len(param_s11_limpio_sel):
                        param_s22_limpio_sel = s22_masked[:len(param_s11_limpio_sel)]
                    else:
                        param_s22_limpio_sel = s22_masked.copy()
                except Exception:
                    param_s22_limpio_sel = None
            else:
                param_s22_limpio_sel = None
            if indice < 0 or indice >= len(frecuencias_mhz_limpias):
                try:
                    actualizar_barra_estado([])
                except Exception:
                    pass
                return
            x_val = float(frecuencias_mhz_limpias[indice])

            def _calcular_db(arreglo, index):
                try:
                    return 20.0 * np.log10(max(abs(arreglo[index]), 1e-15))
                except Exception:
                    return None
            y_vals = {'S11': _calcular_db(param_s11_limpio_sel, indice) if param_s11_limpio_sel is not None else None, 'S12': _calcular_db(param_s12_limpio_sel, indice) if param_s12_limpio_sel is not None else None, 'S21': _calcular_db(param_s21_limpio_sel, indice) if param_s21_limpio_sel is not None else None, 'S22': _calcular_db(param_s22_limpio_sel, indice) if param_s22_limpio_sel is not None else None}
            y11_db = y_vals.get('S11')
            y21_db = y_vals.get('S21')
            selected_line.set_xdata([x_val, x_val])
            selected_line.set_visible(True)
            if y11_db is not None:
                sel_marker_s11.set_data([x_val], [y11_db])
                s11_val_text.set_text(f'{y11_db:+.1f} dB')
            else:
                sel_marker_s11.set_data([], [])
                s11_val_text.set_text('')
            if y21_db is not None:
                sel_marker_s21.set_data([x_val], [y21_db])
                s21_val_text.set_text(f'{y21_db:+.1f} dB')
            else:
                sel_marker_s21.set_data([], [])
                s21_val_text.set_text('')
            try:
                components = [f'M1: {x_val:.2f} MHz']
                for pname in ('S11', 'S21', 'S12', 'S22'):
                    try:
                        if variables_param_s.get(pname, None) and variables_param_s[pname].get():
                            val_db = y_vals.get(pname)
                            if val_db is not None:
                                components.append(f'{pname}: {val_db:+.1f} dB')
                    except Exception:
                        pass
                try:
                    if variables_param_s['S11'].get() and variables_param_s['S21'].get() and (y11_db is not None) and (y21_db is not None):
                        diff_db = y11_db - y21_db
                        components.append(f'Diferencia: {diff_db:+.1f} dB')
                except Exception:
                    pass
                actualizar_barra_estado(components)
            except Exception:
                pass
            try:
                if bar_update_func.get('func'):
                    bar_update_func['func']()
            except Exception:
                pass
            if draw:
                try:
                    fig.canvas.draw_idle()
                except Exception:
                    pass

        def al_cambiar_nivel(val) -> None:
            nonlocal serie_arduino
            try:
                level_db = float(val)
            except Exception:
                return
            step_value = int(round(level_db / 0.5))
            step_value = max(0, min(63, step_value))
            _escribir_linea_arduino(f'ATT {step_value}')
            level_db_current['v'] = level_db
            try:
                lvl_val_text.set_text(f'{level_db:.1f} dB')
            except Exception:
                pass
            actualizar_puntos_seleccionados(draw=True)
        lvl_slider.on_changed(al_cambiar_nivel)
        al_cambiar_nivel(0.0)

        def actualizar_puntos_seleccionados(draw: bool=True) -> None:
            actualizar_puntos_seleccionados_impl(draw)

        def actualizar_puntos_seleccionados_impl(draw: bool=True) -> None:
            try:
                actualizar_barra_estado([])
            except Exception:
                pass
            arreglo_frecuencias = ultimos.get('f')
            param_s11 = ultimos.get('s11')
            param_s21 = ultimos.get('s21')
            if arreglo_frecuencias is None or param_s11 is None or param_s21 is None or (len(arreglo_frecuencias) == 0):
                try:
                    selected_line.set_visible(False)
                    selected_line_B.set_visible(False)
                except Exception:
                    pass
                for mk in (sel_marker_s11, sel_marker_s21, sel_marker_s11_B, sel_marker_s21_B):
                    try:
                        mk.set_data([], [])
                    except Exception:
                        pass
                try:
                    s21_val_text.set_text('')
                    s11_val_text.set_text('')
                except Exception:
                    pass
                try:
                    if bar_update_func.get('func'):
                        bar_update_func['func']()
                except Exception:
                    pass
                if draw:
                    try:
                        fig.canvas.draw_idle()
                    except Exception:
                        pass
                return
            s11_cur, s21_cur = (param_s21, param_s11) if v_swap.get() else (param_s11, param_s21)
            s12_cur = ultimos.get('s12')
            s22_cur = ultimos.get('s22')
            if calibracion.aplicada:
                if hasattr(calibracion, 'aplicar_reflexion'):
                    s11_corr = calibracion.aplicar_reflexion(s11_cur) if s11_cur is not None else None
                    s21_corr = calibracion.corregir_transmision_thru(s21_cur) if s21_cur is not None else None
                    s12_corr = calibracion.corregir_transmision_thru(s12_cur) if s12_cur is not None else None
                    s22_corr = calibracion.aplicar_reflexion(s22_cur) if s22_cur is not None else None
                else:
                    s11_corr = calibracion.corregir_medicion_sol(s11_cur) if s11_cur is not None else None
                    s21_corr = s21_cur
                    s12_corr = s12_cur
                    s22_corr = calibracion.corregir_medicion_sol(s22_cur) if s22_cur is not None else None
            else:
                s11_corr = s11_cur
                s21_corr = s21_cur
                s12_corr = s12_cur
                s22_corr = s22_cur
            frecuencias_mhz = np.array(arreglo_frecuencias) / 1000000.0
            try:
                frecuencias_mhz_limpias, param_s11_limpio_sel, param_s21_limpio_sel = _limpiar_traza(frecuencias_mhz, s11_corr, s21_corr)
            except Exception:
                frecuencias_mhz_limpias, param_s11_limpio_sel, param_s21_limpio_sel = (frecuencias_mhz, s11_corr, s21_corr)
            try:
                mascara = np.isfinite(s11_corr) & np.isfinite(s21_corr)
            except Exception:
                mascara = None
            if s12_corr is not None and mascara is not None:
                try:
                    s12_masked = s12_corr[mascara]
                    if len(s12_masked) > len(param_s21_limpio_sel):
                        param_s12_limpio_sel = s12_masked[:len(param_s21_limpio_sel)]
                    else:
                        param_s12_limpio_sel = s12_masked.copy()
                except Exception:
                    param_s12_limpio_sel = None
            else:
                param_s12_limpio_sel = None
            if s22_corr is not None and mascara is not None:
                try:
                    s22_masked = s22_corr[mascara]
                    if len(s22_masked) > len(param_s11_limpio_sel):
                        param_s22_limpio_sel = s22_masked[:len(param_s11_limpio_sel)]
                    else:
                        param_s22_limpio_sel = s22_masked.copy()
                except Exception:
                    param_s22_limpio_sel = None
            else:
                param_s22_limpio_sel = None

            def _calcular_db(arreglo, indice):
                try:
                    return 20.0 * np.log10(max(abs(arreglo[indice]), 1e-15))
                except Exception:
                    return None
            arrays_dict = {'S11': param_s11_limpio_sel, 'S12': param_s12_limpio_sel, 'S21': param_s21_limpio_sel, 'S22': param_s22_limpio_sel}

            def _actualizar_cursor(indice_sel, line_obj, mk11, mk21):
                if indice_sel is None or indice_sel < 0 or indice_sel >= len(frecuencias_mhz_limpias):
                    try:
                        line_obj.set_visible(False)
                        mk11.set_data([], [])
                        mk21.set_data([], [])
                    except Exception:
                        pass
                    return None
                xloc = float(frecuencias_mhz_limpias[indice_sel])
                vals = {p: _calcular_db(a, indice_sel) if a is not None else None for p, a in arrays_dict.items()}
                try:
                    line_obj.set_xdata([xloc, xloc])
                    line_obj.set_visible(True)
                    y11 = vals.get('S11')
                    y21 = vals.get('S21')
                    if y11 is not None:
                        mk11.set_data([xloc], [y11])
                    else:
                        mk11.set_data([], [])
                    if y21 is not None:
                        mk21.set_data([xloc], [y21])
                    else:
                        mk21.set_data([], [])
                except Exception:
                    pass
                return (xloc, vals)
            resA = _actualizar_cursor(selected_idx.get('v'), selected_line, sel_marker_s11, sel_marker_s21)
            resB = _actualizar_cursor(selected_idx_B.get('v'), selected_line_B, sel_marker_s11_B, sel_marker_s21_B)
            try:
                if resA:
                    _, vA = resA
                    if vA.get('S21') is not None and variables_param_s['S21'].get():
                        s21_val_text.set_text(f"{vA['S21']:+.1f} dB")
                    else:
                        s21_val_text.set_text('')
                    if vA.get('S11') is not None and variables_param_s['S11'].get():
                        s11_val_text.set_text(f"{vA['S11']:+.1f} dB")
                    else:
                        s11_val_text.set_text('')
                else:
                    s21_val_text.set_text('')
                    s11_val_text.set_text('')
            except Exception:
                pass
            comps = []

            def _formatear_cursor(prefix, res):
                if not res:
                    return None
                xval, vdict = res
                elementos = [f'{prefix}: {xval:.2f} MHz']
                for p in ('S11', 'S21', 'S12', 'S22'):
                    try:
                        if variables_param_s.get(p) and variables_param_s[p].get():
                            vv = vdict.get(p)
                            if vv is not None:
                                elementos.append(f'{p}: {vv:+.1f} dB')
                    except Exception:
                        pass
                return ' | '.join(elementos)
            txtA = _formatear_cursor('M1', resA)
            txtB = _formatear_cursor('M2', resB)
            if txtA:
                comps.append(txtA)
            if txtB:
                comps.append(txtB)
            if resA and resB:
                xA, vA = resA
                xB, vB = resB
                df = xB - xA
                diffs = [f'Δf: {df:+.2f} MHz']
                for p in ('S11', 'S21', 'S12', 'S22'):
                    if variables_param_s.get(p) and variables_param_s[p].get():
                        v1 = vA.get(p)
                        v2 = vB.get(p)
                        if v1 is not None and v2 is not None:
                            diffs.append(f'Δ{p}: {v2 - v1:+.1f} dB')
                comps.append(' | '.join(diffs))
            try:
                actualizar_barra_estado(comps)
            except Exception:
                pass
            try:
                if bar_update_func.get('func'):
                    bar_update_func['func']()
            except Exception:
                pass
            if draw:
                try:
                    fig.canvas.draw_idle()
                except Exception:
                    pass

        def al_clic(event) -> None:
            if event.inaxes != axM:
                return
            if event.xdata is None:
                return
            try:
                arreglo_frecuencias = ultimos.get('f')
                if arreglo_frecuencias is None or len(arreglo_frecuencias) == 0:
                    return
                frecuencias_mhz = np.array(arreglo_frecuencias) / 1000000.0
                indice_cercano = int(np.argmin(np.abs(frecuencias_mhz - event.xdata)))
                btn = getattr(event, 'button', None)
                if btn == 3:
                    selected_idx_B['v'] = indice_cercano
                elif btn == 1:
                    selected_idx['v'] = indice_cercano
                    try:
                        if hslider is not None:
                            hslider.set_val(indice_cercano)
                    except Exception:
                        pass
                else:
                    return
                actualizar_puntos_seleccionados(draw=True)
            except Exception:
                pass
        fig.canvas.mpl_connect('button_press_event', al_clic)

        def al_mover(event) -> None:
            try:
                if ayuda_flotante.get_visible():
                    ayuda_flotante.set_visible(False)
                    fig.canvas.draw_idle()
            except Exception:
                pass
        fig.canvas.mpl_connect('motion_notify_event', al_mover)

        def al_scroll(event) -> None:
            if event.inaxes != axM or event.xdata is None:
                return
            try:
                if getattr(event, 'button', None) == 'up' or event.button == 1:
                    scale = 0.8
                else:
                    scale = 1.25
                xdata = event.xdata
                xlo, xhi = axM.get_xlim()
                new_lo = xdata + (xlo - xdata) * scale
                new_hi = xdata + (xhi - xdata) * scale
                if new_hi - new_lo < 1e-06:
                    return
                axM.set_xlim(new_lo, new_hi)
                try:
                    rango_x['lo'], rango_x['hi'] = (float(new_lo), float(new_hi))
                except Exception:
                    pass
                fig.canvas.draw_idle()
            except Exception:
                pass
        pan_state = {'active': False, 'x_start': 0.0, 'orig_xlim': (0.0, 1.0)}

        def al_presionar_pan(event) -> None:
            if event.inaxes != axM or event.xdata is None:
                return
            if getattr(event, 'button', None) == 2:
                pan_state['active'] = True
                pan_state['x_start'] = event.xdata
                pan_state['orig_xlim'] = axM.get_xlim()

        def al_soltar_pan(event) -> None:
            if getattr(event, 'button', None) == 2:
                pan_state['active'] = False

        def al_mover_pan(event) -> None:
            if not pan_state['active'] or event.inaxes != axM or event.xdata is None:
                return
            try:
                dx = event.xdata - pan_state['x_start']
                x0, x1 = pan_state['orig_xlim']
                axM.set_xlim(x0 - dx, x1 - dx)
                rango_x['lo'], rango_x['hi'] = (float(x0 - dx), float(x1 - dx))
                fig.canvas.draw_idle()
            except Exception:
                pass
        fig.canvas.mpl_connect('scroll_event', al_scroll)
        fig.canvas.mpl_connect('button_press_event', al_presionar_pan)
        fig.canvas.mpl_connect('button_release_event', al_soltar_pan)
        fig.canvas.mpl_connect('motion_notify_event', al_mover_pan)
    except Exception:
        pass
    recapturar_fondo()
    try:
        actualizar_distribucion_ejes()
    except Exception:
        pass
    recapturar_fondo()
    autoescala = {'v': True}
    y_min, y_max = (-80.0, 5.0)

    def al_redimensionar(evt):
        recapturar_fondo()
    fig.canvas.mpl_connect('resize_event', al_redimensionar)

    def alternar_teclas(event) -> None:
        if event.key in ('a', 'A'):
            autoescala['v'] = not autoescala['v']
        elif event.key in ('l', 'L'):
            alternar_switch()
        elif event.key in ('v', 'V'):
            alternar_vista_parametros_s()
    fig.canvas.mpl_connect('key_press_event', alternar_teclas)
    try:
        ventana.bind('<KeyPress-l>', lambda _e: alternar_switch())
        ventana.bind('<KeyPress-L>', lambda _e: alternar_switch())
        ventana.bind('<KeyPress-v>', lambda _e: alternar_vista_parametros_s())
        ventana.bind('<KeyPress-V>', lambda _e: alternar_vista_parametros_s())
    except Exception:
        pass
    fig.canvas.mpl_connect('key_press_event', lambda e: aplicar_puerto_seleccionado() if e.state & 4 and e.state & 1 and (e.key.lower() == 'p') else None)
    fig.canvas.mpl_connect('key_press_event', lambda e: aplicar_parametros_barrido() if e.key.lower() == 'e' and e.state & 4 else None)
    last_main_update_time = {'t': 0.0}

    def actualizar_frame() -> None:
        nonlocal y_min, y_max, texto_metricas
        try:
            if not dispositivo_conectado:
                indicador_medicion.set_text('●')
                indicador_medicion.set_color('red')
            elif modo_adquisicion.get('modo') == 'single':
                if modo_adquisicion.get('single_pending'):
                    indicador_medicion.set_text('● CAPTURANDO')
                    indicador_medicion.set_color('orange')
                else:
                    indicador_medicion.set_text('● CAPTURA ÚNICA')
                    indicador_medicion.set_color('#1E88E5')
            elif pausado.get('v'):
                indicador_medicion.set_text('● HOLD')
                indicador_medicion.set_color('yellow')
            elif dispositivo_conectado and ultimos.get('s11') is not None and (ultimos.get('s21') is not None):
                indicador_medicion.set_text('● LIVE')
                indicador_medicion.set_color('green')
            else:
                indicador_medicion.set_text('●')
                indicador_medicion.set_color('red')
        except Exception:
            pass
        try:
            info_fps['count'] += 1
            now_time = time.time()
            if now_time - info_fps['last_time'] >= 1.0:
                elapsed = now_time - info_fps['last_time']
                info_fps['fps'] = int(round(info_fps['count'] / elapsed)) if elapsed > 0 else 0
                info_fps['count'] = 0
                info_fps['last_time'] = now_time
        except Exception:
            pass
        try:
            pass
        except Exception:
            pass
        show_mag = variables_graficas['mag'].get()
        show_polar = variables_graficas['polar'].get()
        show_smith = variables_graficas['smith'].get()
        show_phase = variables_graficas['phase'].get()
        axM.set_visible(show_mag)
        axP.set_visible(show_polar)
        axS.set_visible(show_smith)
        axPhase.set_visible(show_phase)
        param_s11 = ultimos['s11']
        param_s21 = ultimos['s21']
        param_s12 = ultimos.get('s12')
        param_s22 = ultimos.get('s22')
        if v_swap.get():
            param_s11, param_s21 = (param_s21, param_s11)
        arreglo_frecuencias = ultimos.get('f')
        if arreglo_frecuencias is None or len(arreglo_frecuencias) == 0:
            return
        frecuencias_mhz = arreglo_frecuencias / 1000000.0
        try:
            new_lo = float(frecuencias_mhz[0])
            new_hi = float(frecuencias_mhz[-1])
            if new_lo != rango_x['lo'] or new_hi != rango_x['hi']:
                rango_x['lo'], rango_x['hi'] = (new_lo, new_hi)
                axM.set_xlim(new_lo, new_hi)
                try:
                    axPhase.set_xlim(new_lo, new_hi)
                except Exception:
                    pass
                recapturar_fondo()
        except Exception:
            pass
        if not dispositivo_conectado or param_s11 is None or param_s21 is None:
            z = np.zeros_like(frecuencias_mhz)
            lnS11smith.set_data([0.0], [0.0])
            lnS12smith.set_data([0.0], [0.0])
            lnS21smith.set_data([0.0], [0.0])
            lnS22smith.set_data([0.0], [0.0])
            lnS11mag.set_data(frecuencias_mhz, z)
            lnS12mag.set_data(frecuencias_mhz, z)
            lnS21mag.set_data(frecuencias_mhz, z)
            lnS22mag.set_data(frecuencias_mhz, z)
            lnS11polar.set_data([], [])
            lnS12polar.set_data([], [])
            lnS21polar.set_data([], [])
            lnS22polar.set_data([], [])
            for pname, linea in (('S11', lnS11smith), ('S12', lnS12smith), ('S21', lnS21smith), ('S22', lnS22smith)):
                try:
                    if pname in ('S12', 'S21'):
                        linea.set_visible(False)
                    else:
                        linea.set_visible(show_smith and variables_param_s[pname].get())
                except Exception:
                    pass
            for pname, linea in (('S11', lnS11mag), ('S12', lnS12mag), ('S21', lnS21mag), ('S22', lnS22mag)):
                try:
                    linea.set_visible(show_mag and variables_param_s[pname].get())
                except Exception:
                    pass
            for pname, linea in (('S11', lnS11polar), ('S12', lnS12polar), ('S21', lnS21polar), ('S22', lnS22polar)):
                try:
                    linea.set_visible(show_polar and variables_param_s[pname].get())
                except Exception:
                    pass
        else:
            if calibracion.aplicada:
                if hasattr(calibracion, 'aplicar_reflexion'):
                    param_s11_corr = calibracion.aplicar_reflexion(param_s11)
                    param_s21_corr = calibracion.corregir_transmision_thru(param_s21)
                    param_s22_corr = calibracion.aplicar_reflexion(param_s22) if param_s22 is not None else None
                    param_s12_corr = calibracion.corregir_transmision_thru(param_s12) if param_s12 is not None else None
                else:
                    param_s11_corr = calibracion.corregir_medicion_sol(param_s11)
                    param_s21_corr = param_s21
                    param_s22_corr = calibracion.corregir_medicion_sol(param_s22) if param_s22 is not None else None
                    param_s12_corr = param_s12
            else:
                param_s11_corr = param_s11
                param_s21_corr = param_s21
                param_s22_corr = param_s22
                param_s12_corr = param_s12
            frecuencias_mhz_limpias, param_s11_limpio_sel, param_s21_limpio_sel = _limpiar_traza(frecuencias_mhz, param_s11_corr, param_s21_corr)
            try:
                mascara = np.isfinite(param_s11_corr) & np.isfinite(param_s21_corr)
            except Exception:
                mascara = None
            if param_s12_corr is not None and mascara is not None:
                try:
                    s12_masked = param_s12_corr[mascara]
                    if len(s12_masked) > len(param_s21_limpio_sel):
                        param_s12_limpio_sel = s12_masked[:len(param_s21_limpio_sel)]
                    else:
                        param_s12_limpio_sel = s12_masked.copy()
                except Exception:
                    param_s12_limpio_sel = None
            else:
                param_s12_limpio_sel = None
            if param_s22_corr is not None and mascara is not None:
                try:
                    s22_masked = param_s22_corr[mascara]
                    if len(s22_masked) > len(param_s11_limpio_sel):
                        param_s22_limpio_sel = s22_masked[:len(param_s11_limpio_sel)]
                    else:
                        param_s22_limpio_sel = s22_masked.copy()
                except Exception:
                    param_s22_limpio_sel = None
            else:
                param_s22_limpio_sel = None
            params_p = {'S11': param_s11_limpio_sel, 'S12': param_s12_limpio_sel, 'S21': param_s21_limpio_sel, 'S22': param_s22_limpio_sel}
            try:
                metricas = calcular_metricas_analisis(frecuencias_mhz_limpias, param_s11_limpio_sel, param_s21_limpio_sel)
                lineas: list[str] = []
                min_ret_db = metricas.get('min_return_db')
                min_ret_freq = metricas.get('min_return_freq')
                if min_ret_db is not None and min_ret_freq is not None:
                    lineas.append(f'Retorno min: {min_ret_db:+.1f} dB a {min_ret_freq:.3f} MHz')
                else:
                    lineas.append('Retorno min: —')
                max_gain_db = metricas.get('max_gain_db')
                max_gain_freq = metricas.get('max_gain_freq')
                if max_gain_db is not None and max_gain_freq is not None:
                    lineas.append(f'Ganancia máx: {max_gain_db:+.1f} dB a {max_gain_freq:.3f} MHz')
                else:
                    lineas.append('Ganancia máx: —')
                bw3db = metricas.get('bw3db')
                bw3db_low = metricas.get('bw3db_low')
                bw3db_high = metricas.get('bw3db_high')
                if bw3db is not None and bw3db_low is not None and (bw3db_high is not None):
                    lineas.append(f'Ancho -3 dB: {bw3db:.3f} MHz [{bw3db_low:.3f}-{bw3db_high:.3f}]')
                else:
                    lineas.append('Ancho -3 dB: —')
                texto_metricas.set_text('\n'.join(lineas))
            except Exception as exc:
                registro.exception('Error updating analysis metrics', exc_info=exc)
                try:
                    texto_metricas.set_text('—')
                except Exception:
                    pass
            smith_coords = {}
            mag_values = {}
            polar_coords = {}
            for pname, arreglo in params_p.items():
                if arreglo is not None and arreglo.size:
                    mascara = np.abs(arreglo) > 1e-15
                    reales_smith = np.real(arreglo[mascara])
                    imag_smith = np.imag(arreglo[mascara])
                    magnitud = 20 * np.log10(np.maximum(np.abs(arreglo), 1e-15))
                    angulo = np.angle(arreglo)
                    r = np.abs(arreglo)
                else:
                    reales_smith = np.array([])
                    imag_smith = np.array([])
                    magnitud = np.array([])
                    angulo = np.array([])
                    r = np.array([])
                smith_coords[pname] = (reales_smith, imag_smith)
                mag_values[pname] = magnitud
                polar_coords[pname] = (angulo, r)
            for pname, linea in (('S11', lnS11smith), ('S12', lnS12smith), ('S21', lnS21smith), ('S22', lnS22smith)):
                reales_smith, imag_smith = smith_coords[pname]
                linea.set_data(reales_smith, imag_smith)
                try:
                    if pname in ('S12', 'S21'):
                        linea.set_visible(False)
                    else:
                        linea.set_visible(show_smith and variables_param_s[pname].get())
                except Exception:
                    pass
            for pname, linea in (('S11', lnS11mag), ('S12', lnS12mag), ('S21', lnS21mag), ('S22', lnS22mag)):
                magnitud = mag_values[pname]
                linea.set_data(frecuencias_mhz_limpias, magnitud)
                linea.set_visible(show_mag and variables_param_s[pname].get())
            phase_values = {}
            for pname, arreglo in params_p.items():
                if arreglo is not None and arreglo.size:
                    try:
                        phase_values[pname] = np.angle(arreglo) * 180.0 / np.pi
                    except Exception:
                        phase_values[pname] = np.array([])
                else:
                    phase_values[pname] = np.array([])
            for pname, linea in (('S11', lnS11phase), ('S12', lnS12phase), ('S21', lnS21phase), ('S22', lnS22phase)):
                try:
                    phase = phase_values[pname]
                    linea.set_data(frecuencias_mhz_limpias, phase)
                    linea.set_visible(show_phase and variables_param_s[pname].get())
                except Exception:
                    pass
            if show_phase:
                try:
                    visibilidades = []
                    for pname in ('S11', 'S12', 'S21', 'S22'):
                        if variables_param_s[pname].get():
                            arreglo = phase_values.get(pname)
                            if arreglo is not None and arreglo.size:
                                visibilidades.append(arreglo)
                    if visibilidades:
                        ymin = float(min((float(np.nanmin(v)) for v in visibilidades)))
                        ymax = float(max((float(np.nanmax(v)) for v in visibilidades)))
                        pad = 5.0
                        ylo_ph = min(ymin - pad, -190.0)
                        yhi_ph = max(ymax + pad, 190.0)
                        axPhase.set_ylim(ylo_ph, yhi_ph)
                except Exception:
                    pass
            for pname, linea in (('S11', lnS11polar), ('S12', lnS12polar), ('S21', lnS21polar), ('S22', lnS22polar)):
                angulo, r = polar_coords[pname]
                linea.set_data(angulo, r)
                linea.set_visible(show_polar and variables_param_s[pname].get())
            try:
                max_r = 0.0
                for pname in ('S11', 'S12', 'S21', 'S22'):
                    if not variables_param_s[pname].get():
                        continue
                    r = polar_coords[pname][1]
                    if r.size:
                        max_r = max(max_r, float(np.nanmax(r)))
                if max_r > 0:
                    axP.set_ylim(0, max_r * 1.1)
            except Exception:
                pass
            if autoescala['v']:
                try:
                    mags: list[np.ndarray] = []
                    for pname in ('S11', 'S12', 'S21', 'S22'):
                        if variables_param_s[pname].get():
                            arreglo = mag_values[pname]
                            if arreglo.size:
                                mags.append(arreglo)
                    if mags:
                        threshold_db = -80.0
                        global_max = None
                        for arreglo in mags:
                            arr_valid = arreglo[np.isfinite(arreglo) & (arreglo > threshold_db)]
                            if arr_valid.size > 0:
                                amax = float(arr_valid.max())
                                if global_max is None or amax > global_max:
                                    global_max = amax
                        if global_max is None:
                            try:
                                global_max = float(np.nanmax([arreglo.max() for arreglo in mags]))
                            except Exception:
                                global_max = None
                        if global_max is not None:
                            pad_high = 3.0
                            new_lo_y = -80.0
                            new_hi_y = max(5.0, global_max + pad_high)
                            if new_hi_y > y_max:
                                y_max = new_hi_y
                                y_min = new_lo_y
                                axM.set_ylim(y_min, y_max)
                                recapturar_fondo()
                except Exception:
                    pass
            try:
                indice_sel = selected_idx.get('v')
                if indice_sel is not None and selected_line is not None and (sel_marker_s11 is not None) and (sel_marker_s21 is not None) and (0 <= indice_sel < len(frecuencias_mhz_limpias)):
                    x_val = float(frecuencias_mhz_limpias[indice_sel])
                    magS11 = mag_values.get('S11', np.array([]))
                    magS21 = mag_values.get('S21', np.array([]))
                    if magS11.size and magS21.size:
                        y11_db = float(magS11[indice_sel])
                        y21_db = float(magS21[indice_sel])
                        selected_line.set_xdata([x_val, x_val])
                        selected_line.set_visible(show_mag and (variables_param_s['S11'].get() or variables_param_s['S21'].get()))
                        if variables_param_s['S11'].get() and sel_marker_s11 is not None:
                            sel_marker_s11.set_data([x_val], [y11_db])
                        else:
                            sel_marker_s11.set_data([], [])
                        if variables_param_s['S21'].get() and sel_marker_s21 is not None:
                            sel_marker_s21.set_data([x_val], [y21_db])
                        else:
                            sel_marker_s21.set_data([], [])
                        if s21_val_text is not None and s11_val_text is not None:
                            if variables_param_s['S21'].get():
                                s21_val_text.set_text(f'{y21_db:+.1f} dB')
                            else:
                                s21_val_text.set_text('')
                            if variables_param_s['S11'].get():
                                s11_val_text.set_text(f'{y11_db:+.1f} dB')
                            else:
                                s11_val_text.set_text('')
                        try:
                            if bar_update_func.get('func'):
                                bar_update_func['func']()
                        except Exception:
                            pass
                    else:
                        selected_line.set_visible(False)
                        sel_marker_s11.set_data([], [])
                        sel_marker_s21.set_data([], [])
                else:
                    if selected_line is not None:
                        selected_line.set_visible(False)
                    if sel_marker_s11 is not None:
                        sel_marker_s11.set_data([], [])
                    if sel_marker_s21 is not None:
                        sel_marker_s21.set_data([], [])
                    try:
                        if bar_update_func.get('func'):
                            bar_update_func['func']()
                    except Exception:
                        pass
            except Exception:
                pass
        if fondo.get('smith') is None or fondo.get('mag') is None or fondo.get('polar') is None:
            recapturar_fondo()
        show_mag = variables_graficas['mag'].get()
        show_polar = variables_graficas['polar'].get()
        show_smith = variables_graficas['smith'].get()
        try:
            fig.canvas.restore_region(fondo['smith'])
            if show_smith:
                for linea in (lnS11smith, lnS12smith, lnS21smith, lnS22smith):
                    if linea.get_visible():
                        axS.draw_artist(linea)
                fig.canvas.blit(axS.bbox)
        except Exception:
            pass
        try:
            fig.canvas.restore_region(fondo['mag'])
            if show_mag:
                for linea in (lnS11mag, lnS12mag, lnS21mag, lnS22mag):
                    if linea.get_visible():
                        axM.draw_artist(linea)
                try:
                    if selected_line is not None and selected_line.get_visible():
                        axM.draw_artist(selected_line)
                    if sel_marker_s11 is not None and len(sel_marker_s11.get_xdata()) > 0:
                        axM.draw_artist(sel_marker_s11)
                    if sel_marker_s21 is not None and len(sel_marker_s21.get_xdata()) > 0:
                        axM.draw_artist(sel_marker_s21)
                except Exception:
                    pass
                fig.canvas.blit(axM.bbox)
        except Exception:
            pass
        try:
            if fondo.get('phase') is not None:
                fig.canvas.restore_region(fondo['phase'])
            if show_phase:
                for linea in (lnS11phase, lnS12phase, lnS21phase, lnS22phase):
                    if linea.get_visible():
                        axPhase.draw_artist(linea)
                fig.canvas.blit(axPhase.bbox)
        except Exception:
            pass
        try:
            fig.canvas.restore_region(fondo['polar'])
            if show_polar:
                for linea in (lnS11polar, lnS12polar, lnS21polar, lnS22polar):
                    if linea.get_visible():
                        axP.draw_artist(linea)
                fig.canvas.blit(axP.bbox)
        except Exception:
            pass
        fig.canvas.flush_events()
        try:
            wnd = estado_cuatro_dialogos.get('win')
            if wnd is not None and wnd.winfo_exists():
                now = time.time()
                if now - last_main_update_time['t'] < 0.5:
                    return
                last_main_update_time['t'] = now
        except Exception:
            pass
    interval = max(5, int(1000 / fps_interfaz))
    timer = fig.canvas.new_timer(interval=interval)
    timer.add_callback(actualizar_frame)
    timer.start()

    def al_cerrar(evt) -> None:
        nonlocal hilo_escaneo, serie_arduino
        evento_detener.set()
        try:
            if hilo_escaneo is not None:
                hilo_escaneo.join(timeout=1.0)
        except Exception:
            pass
        try:
            if hasattr(nv, 'cerrar'):
                nv.cerrar()
        except Exception:
            pass
        try:
            if serie_arduino is not None:
                serie_arduino.close()
        except Exception:
            pass
    fig.canvas.mpl_connect('close_event', al_cerrar)
    plt.show()
