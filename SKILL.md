---
name: blender-gui
version: 1.2.0
author: k2
license: MIT
platforms: [linux]
description: Use when driving local Blender GUI via Hermes (bridge/bpy).
metadata:
  hermes:
    tags: [blender, gui, bpy, bridge]
    related_skills: [computer-use]
---

# Blender GUI con Hermes

## When to Use

Usar cuando el usuario quiere su Blender local desde Hermes con GUI: inspeccionar o editar un `.blend`, crear escenas nuevas, capturar la ventana o ejecutar `bpy` en la sesión abierta. Cargar antes la skill `computer-use` para las interacciones de pantalla. `blender-gui-bridge` quedó deprecada: esta es la única fuente de verdad.

## Setup

1. Resolver el binario sin hardcodear rutas personales:
   `BLENDER_BIN="${BLENDER_BIN:-$(command -v blender)}"`; verificar con `"$BLENDER_BIN" --version`.
   Versión probada y fijada: Blender 4.4.3 (Linux/X11). Si la versión difiere, el bridge avisa pero sigue funcionando.
2. Token (obligatorio desde v1.2.0): el bridge y los clientes comparten un token de 32 bytes en `${HERMES_HOME:-$HOME/.hermes}/blender/bridge.token`, creado automáticamente con permisos 0600. Se puede generar antes con `python3 .../scripts/bridge_auth.py`. Overrides: `HERMES_BRIDGE_TOKEN` (valor) o `HERMES_BRIDGE_TOKEN_FILE` (ruta). Si server y cliente no comparten token, el bridge responde `unauthorized`.
3. Si no hay bridge levantado, iniciarlo con el Blender del usuario:
   `"$BLENDER_BIN" --python "${HERMES_HOME:-$HOME/.hermes}/skills/blender-gui/scripts/hermes_blender_bridge.py"`.
   Escucha solo en `127.0.0.1:7999` e imprime `HERMES_BRIDGE_READY port 7999`.
   El bridge se niega a arrancar si corre como root o si hay otros usuarios logueados (`HERMES_BRIDGE_REFUSED`); en un host compartido no usarlo. El override explícito es `HERMES_BRIDGE_ALLOW_SHARED=1` y asume que se acepta RCE local.
4. Cliente (los scripts viajan con esta skill):
   `python3 "${HERMES_HOME:-$HOME/.hermes}/skills/blender-gui/scripts/blenderctl.py" 'import bpy\nRESULT=bpy.app.version_string'`.

## Procedure

- Preferir el bridge sobre teclear en la Python Console: ejecuta `bpy` en la main thread por `bpy.app.timers`, sin filtrar atajos al viewport.
- Abrir un archivo en la GUI: `bpy.ops.wm.open_mainfile(filepath="/ruta/absoluta/archivo.blend")`; consultar con `RESULT=(bpy.app.version_string, bpy.data.filepath, [(o.name,o.type) for o in bpy.context.scene.objects])`.
- Crear datos nuevos con la API de datos (`bpy.data.meshes.new` + `from_pydata` + `collection.objects.link`), no con `bpy.ops`, cuando no sea una acción de UI.
- Crear un `.blend` nuevo de forma determinista: `"$BLENDER_BIN" -b --factory-startup --python-expr "import bpy; bpy.ops.wm.save_as_mainfile(filepath='/ruta/archivo.blend')"` y después abrirlo en la GUI con `open_mainfile`.
- En Blender 4.4.3 el operador es `bpy.ops.wm.read_homefile()`; `bpy.ops.wm.read_factory_settings()` no existe (AttributeError).
- Resultados: asignar `RESULT` a dict/list/número devuelve JSON estructurado (ya no se fuerza a string). `PROGRESS("mensaje")` añade eventos al array `progress` de la respuesta.
- Operaciones largas: pasar `req_id` al cliente (`blenderctl.call(code, req_id=7)`) y, si el código coopera con `CANCELLED()`, cancelar con `blenderctl.cancel(7)` o la herramienta MCP `blender_cancel`. No cancela `bpy.ops` bloqueantes.
- Sin bridge, usar GUI pura: capturar con `app="Blender"` antes de cada entrada, `delivery_mode="foreground"`, y poner el mouse dentro de la Python Console antes de teclear. Si el mouse está en el viewport, las teclas se filtran y abren menús o Edit Mode; la `x` de `filepath` puede borrar el objeto seleccionado.

## Verification

Verificar siempre con tres señales antes de afirmar que terminó:

1. Título de la ventana de Blender con el nombre del archivo.
2. `bpy.data.filepath` y la lista de objetos vía bridge.
3. `ls -lh` del `.blend` en disco y, si hace falta, reapertura headless para confirmar el contenido.

## Tests

`python3 "${HERMES_HOME:-$HOME/.hermes}/skills/blender-gui/tests/test_bridge_hardening.py"` — 13 pruebas sin Blender (inyecta un `bpy` falso, puerto efímero). En CI: `.github/workflows/tests.yml`.

## Troubleshooting

- `unauthorized`: token del cliente distinto del servidor; usar el mismo archivo 0600 o la misma variable `HERMES_BRIDGE_TOKEN`. No reutilizar un cliente viejo sin token.
- `Connection refused` en 7999: el bridge no está corriendo; levantar Blender con el script de `scripts/`.
- `HERMES_BRIDGE_REFUSED`: root u otros usuarios logueados; no usar en hosts compartidos (override: `HERMES_BRIDGE_ALLOW_SHARED=1`).
- `code too large or invalid` / `request too large or incomplete` / `request timeout` / `command queue full` / `too many clients`: límites de v1.1.1/v1.2.0; dividir el código o reducir clientes, no subir los límites sin revisar el riesgo.
- Límites por defecto: 64 KB por request, 32 KB de código, 5 s para recibir, 16 comandos en cola, 8 clientes, 120 s de ejecución. Configurables con `HERMES_BRIDGE_MAX_REQUEST_BYTES`, `HERMES_BRIDGE_MAX_CODE_BYTES`, `HERMES_BRIDGE_READ_TIMEOUT`, `HERMES_BRIDGE_MAX_QUEUE`, `HERMES_BRIDGE_MAX_CLIENTS` y `HERMES_BRIDGE_PORT`.
- `AttributeError: read_factory_settings`: usar `read_homefile()` en 4.4.3.
- Menú Add / Edit Mode aparece solo: el mouse estaba en el viewport; moverlo a la consola o usar el bridge.
- La consola recibe solo una letra: el teclado sintético pierde ráfagas largas; dividir comandos o usar el bridge.
- Sin árbol de accesibilidad útil en Blender: confiar en capturas + coordenadas relativas a la ventana.

## Safety

- El bridge ejecuta código arbitrario en la sesión de Blender: exige token, escucha solo en localhost, no exponer ni reenviar el puerto 7999 y no aceptar código de fuentes no confiables.
- Rechaza root y hosts con otros usuarios logueados; no eliminar ese guard sin auditoría.
- Cambiar la ruta de un archivo del usuario requiere verificar primero que la escena es la esperada. El MCP valida que las rutas sean absolutas y sin `..`.
- No instalar MCP de terceros sin auditoría y commit fijado. No ejecutar `RUN_PYTHON` remoto (por ejemplo Higgsfield/3D Jutsu) sin autorización explícita.
- Mantener `bridge_auth.py`, el bridge y los clientes sincronizados; el token nunca se versiona.
