# blender-gui v1.2.0

Hermes skill para controlar un Blender local desde la GUI, con un bridge localhost autenticado que ejecuta `bpy` en la main thread de la sesión abierta. `blender-gui-bridge` quedó deprecada y redirige aquí.

## Contenido

- `SKILL.md` — procedimiento, verificación, resolución de problemas y seguridad.
- `scripts/hermes_blender_bridge.py` — servidor JSON-lines autenticado en `127.0.0.1:7999` dentro de Blender.
- `scripts/bridge_auth.py` — token compartido (archivo 0600 fuera del repo).
- `scripts/blenderctl.py` — cliente autenticado (resultados JSON, progreso y cancelación).
- `tests/test_bridge_hardening.py` — 13 pruebas de regresión sin Blender.
- `.github/workflows/tests.yml` — CI al pushear.

## Instalación

Copiar esta carpeta a `$HERMES_HOME/skills/blender-gui` (por defecto `~/.hermes/skills/blender-gui`) y cargar la skill desde Hermes. El token se genera automáticamente la primera vez en `${HERMES_HOME:-$HOME/.hermes}/blender/bridge.token` con modo 0600; no se versiona.

## Uso rápido

```bash
BLENDER_BIN="${BLENDER_BIN:-$(command -v blender)}"
"$BLENDER_BIN" --python "${HERMES_HOME:-$HOME/.hermes}/skills/blender-gui/scripts/hermes_blender_bridge.py"

python3 "${HERMES_HOME:-$HOME/.hermes}/skills/blender-gui/scripts/blenderctl.py" \
  'import bpy\nRESULT=(bpy.app.version_string, bpy.data.filepath)'
```

Ver `SKILL.md` para el procedimiento completo, `PROGRESS()`/`CANCELLED()` y las precauciones.

## Compatibilidad

Probada con Blender 4.4.3 en Linux/X11 (versión fijada; el bridge avisa si difiere). Declarada como `platforms: [linux]`. La ruta del ejecutable se resuelve con `BLENDER_BIN`; no hay rutas personales fijas.

## Seguridad

- Autenticación obligatoria: cada petición lleva un token de 32 bytes aleatorios leído de un archivo 0600 o de `HERMES_BRIDGE_TOKEN` / `HERMES_BRIDGE_TOKEN_FILE`. Sin token o con token erróneo: `unauthorized`, sin ejecutar código.
- Arranque rechazado (`HERMES_BRIDGE_REFUSED`) si corre como root o si `who` muestra otros usuarios logueados. Solo se puede forzar con `HERMES_BRIDGE_ALLOW_SHARED=1`, asumiendo RCE local en ese host.
- Límites: 64 KB por request, 32 KB de código, 5 s para recibir, 16 comandos en cola, 8 clientes simultáneos, 120 s de ejecución. Variables: `HERMES_BRIDGE_PORT`, `HERMES_BRIDGE_READ_TIMEOUT`, `HERMES_BRIDGE_MAX_REQUEST_BYTES`, `HERMES_BRIDGE_MAX_CODE_BYTES`, `HERMES_BRIDGE_MAX_QUEUE`, `HERMES_BRIDGE_MAX_CLIENTS`.
- Sigue siendo ejecución de código por diseño: no exponer ni reenviar el puerto, no aceptar código de fuentes no confiables, y no instalar en hosts multiusuario.

## Tests

`python3 tests/test_bridge_hardening.py` — inyecta un `bpy` falso, levanta el bridge en un puerto efímero y comprueba las 13 defensas (guard, límites, auth, JSON estructurado, progreso, cancelación).

## Integridad

`SHA256SUMS` contiene los hashes de los archivos versionados; verificar con `sha256sum -c SHA256SUMS`. Los commits están firmados con una clave de firma dedicada; verificar con `git log --show-signature`.

## Licencia

MIT.
