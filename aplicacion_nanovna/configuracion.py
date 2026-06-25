from __future__ import annotations
import logging
import re
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s', handlers=[logging.FileHandler('vna_app.log'), logging.StreamHandler()])
registro = logging.getLogger('aplicacion_nanovna')
plt.rcParams.update({'font.size': 9, 'axes.titlesize': 11})
VIDPIDS_VNA = {(1155, 22336), (1204, 8)}
VIDPIDS_ARDUINO = {(9025, 67), (9025, 1), (9025, 579), (9025, 32822), (10755, 67), (10755, 1), (10755, 579), (6790, 29987), (6790, 21795), (4292, 60000), (1027, 24577)}
_NUMERO_RE = re.compile('[-+]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][-+]?\\d+)?')
NOMBRE_MANUAL_USUARIO = 'manual_de_usuario_software_nanovna.pdf'
