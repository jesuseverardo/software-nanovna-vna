# Software NanoVNA para medición de parámetros S

Software desarrollado en Python para el control, calibración, visualización y exportación de mediciones con analizadores vectoriales de redes NanoVNA.

## Descripción

Este proyecto consiste en una aplicación de escritorio desarrollada para apoyar la caracterización de dispositivos de radiofrecuencia mediante un analizador vectorial de redes NanoVNA. El software permite establecer comunicación con el equipo, configurar barridos de frecuencia, realizar calibraciones, visualizar parámetros S y exportar los resultados obtenidos durante las mediciones.

El programa fue desarrollado como parte del proyecto terminal **"Desarrollo de software para analizadores vectoriales de redes (NanoVNA)"**.

## Funciones principales

- Conexión con el NanoVNA mediante puerto serial.
- Configuración del barrido de frecuencia.
- Calibración SOL y SOLT.
- Visualización de parámetros S.
- Representación de resultados en gráficas y carta de Smith.
- Vista de cuatro ventanas para el análisis independiente de parámetros.
- Exportación de mediciones para documentación y análisis posterior.
- Manual de usuario incluido en formato PDF.

## Requisitos

Para ejecutar correctamente el software se recomienda utilizar:

- Python 3.10.10
- matplotlib
- numpy
- pyserial

Las librerías principales se pueden instalar con el siguiente comando:

```bash
pip install matplotlib numpy pyserial
```

También se puede consultar el archivo **`Requerimientos de librería.md`** incluido en el proyecto.

## Ejecución

Ejecuta el programa desde la carpeta principal del proyecto con:

```bash
python principal.py
```

Se recomienda abrir la carpeta completa del proyecto en Visual Studio Code, no solamente un archivo individual.

## Estructura del proyecto

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

Este software fue desarrollado por **Jesús Everardo Díaz Alvarado**.

Si necesitas soporte, tienes dudas o deseas más información sobre el proyecto, puedes ponerte en contacto con el autor a través de los siguientes medios:

- **Correo**: jesuseverardo.diazalvarado@gmail.com
- **Telegram**: @jesuseverardo_diazalvarado

Se incluye un archivo **`AUTOR.txt`** en la raíz del proyecto con esta misma información. Por favor mantén este archivo para reconocer la autoría.

## Aviso de autoría

Este proyecto fue desarrollado con fines académicos como parte de un proyecto terminal. No se autoriza su copia, modificación, redistribución o uso comercial sin autorización del autor.
