# blender-gui

Hermes skill para controlar un Blender local desde la GUI, con un bridge localhost que ejecuta `bpy` en la main thread de la sesión abierta.

## Contenido

- `SKILL.md` — procedimiento, verificación, resolución de problemas y seguridad.
- `scripts/hermes_blender_bridge.py` — servidor JSON-lines en `127.0.0.1:7999` que corre dentro de Blender.
- `scripts/blenderctl.py` — cliente para enviar código Python al bridge.

## Instalación

Copiar esta carpeta a `$HERMES_HOME/skills/blender-gui` (por defecto `~/.hermes/skills/blender-gui`) y cargar la skill desde Hermes.

## Uso rápido

```bash
BLENDER_BIN="${BLENDER_BIN:-$(command -v blender)}"
"$BLENDER_BIN" --python "${HERMES_HOME:-$HOME/.hermes}/skills/blender-gui/scripts/hermes_blender_bridge.py"

python3 "${HERMES_HOME:-$HOME/.hermes}/skills/blender-gui/scripts/blenderctl.py" \
  'import bpy\nRESULT=(bpy.app.version_string, bpy.data.filepath)'
```

Ver `SKILL.md` para el procedimiento completo y las precauciones.

## Compatibilidad

Probada con Blender 4.4.3 en Linux/X11. Declarada como `platforms: [linux]`. La ruta del ejecutable se resuelve con `BLENDER_BIN`; no hay rutas personales fijas.

## Seguridad

El bridge ejecuta código arbitrario en la sesión de Blender. Escucha solo en `127.0.0.1:7999`: no exponer el puerto a la red ni aceptar código de fuentes no confiables.

## Licencia

MIT.
