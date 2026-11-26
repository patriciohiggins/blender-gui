# blender-gui

Hermes skill para controlar un Blender local desde la GUI, con un bridge localhost que ejecuta `bpy` en la main thread de la sesión abierta.

## Contenido

- `SKILL.md` — procedimiento, verificación, resolución de problemas y seguridad.
- `scripts/hermes_blender_bridge.py` — servidor JSON-lines en `127.0.0.1:7999` que corre dentro de Blender.
- `scripts/blenderctl.py` — cliente para enviar código Python al bridge.
- `tests/test_bridge_hardening.py` — 8 pruebas de regresión del guard y los límites (sin necesidad de Blender).

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

El bridge ejecuta código arbitrario en la sesión de Blender y **no tiene autenticación**. Escucha solo en `127.0.0.1:7999`: no exponer el puerto a la red ni aceptar código de fuentes no confiables. v1.1.1 añade dos defensas:

- Arranque rechazado (`HERMES_BRIDGE_REFUSED`) si el proceso corre como root o si `who` muestra otros usuarios logueados. Solo se puede forzar de forma explícita con `HERMES_BRIDGE_ALLOW_SHARED=1`, asumiendo que se acepta RCE local en ese host.
- Límites: 64 KB por request, 32 KB de código, 5 s para recibir la petición, 16 comandos en cola, 8 clientes simultáneos, 120 s de ejecución. Variables de entorno: `HERMES_BRIDGE_PORT`, `HERMES_BRIDGE_READ_TIMEOUT`, `HERMES_BRIDGE_MAX_REQUEST_BYTES`, `HERMES_BRIDGE_MAX_CODE_BYTES`, `HERMES_BRIDGE_MAX_QUEUE`, `HERMES_BRIDGE_MAX_CLIENTS`.

Esto mitiga el abuso de recursos pero **no sustituye a la autenticación**: cualquier proceso local puede seguir ejecutando código. No instalar en equipos multiusuario.

## Tests

`python3 tests/test_bridge_hardening.py` — inyecta un `bpy` falso, levanta el bridge en un puerto efímero y comprueba las 8 defensas.

## Licencia

MIT.
