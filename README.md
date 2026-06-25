# NanoVNA modular en español

Ejecuta el programa desde esta carpeta con:

```bash
python principal.py
```

Estructura:

- `principal.py`: punto de entrada del programa.
- `aplicacion_nanovna/configuracion.py`: configuración general y constantes.
- `aplicacion_nanovna/puertos.py`: detección y selección de puertos seriales.
- `aplicacion_nanovna/parseo.py`: lectura y conversión de respuestas del NanoVNA.
- `aplicacion_nanovna/procesamiento.py`: limpieza, recorte y métricas de parámetros S.
- `aplicacion_nanovna/marcadores.py`: generación de texto para marcadores.
- `aplicacion_nanovna/instrumento.py`: comunicación con el NanoVNA.
- `aplicacion_nanovna/barrido.py`: parámetros del barrido de frecuencia.
- `aplicacion_nanovna/carta_smith.py`: carta Smith y fondo gráfico.
- `aplicacion_nanovna/calibracion.py`: calibración SOL y SOLT.
- `aplicacion_nanovna/interfaz.py`: interfaz principal del software.

## Autor y contacto

Este software fue desarrollado por **Jesús Everardo Díaz Alvarado** como parte del proyecto terminal "Desarrollo de software para analizadores vectoriales de redes (NanoVNA)".

Si necesitas soporte, tienes dudas o deseas más información sobre el proyecto, puedes ponerte en contacto con el autor a través de los siguientes medios:

* **Correo**: jesuseverardo.diazalvarado@gmail.com
* **Telegram**: @jesuseverardo_diazalvarado

Se incluye un archivo **`AUTOR.txt`** en la raíz del proyecto con esta misma información.  Por favor mantén este archivo para reconocer la autoría.
