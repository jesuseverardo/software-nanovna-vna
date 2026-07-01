# Control de conmutador RF con ESP32

Esta carpeta contiene el código utilizado en el ESP32 y el diagrama electrónico del circuito de conmutación de RF empleado junto con el software NanoVNA.

## Contenido

- `SwitchesRF_Software.ino`: código para el ESP32 encargado de controlar los switches de RF.
- `Circuito_SwitchRF.kicad_sch`: esquemático del circuito realizado en KiCad.
- `Diagrama electrónico conmutador RF.png`: imagen del diagrama electrónico del sistema.

## Función general

El circuito de conmutación de RF permite seleccionar diferentes trayectorias de medición para apoyar la obtención de parámetros S con el NanoVNA. El ESP32 se encarga de controlar los switches de RF de acuerdo con las señales enviadas o configuradas en el sistema.