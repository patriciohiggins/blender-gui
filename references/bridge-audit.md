# Auditoría de un bridge local de ejecución de código

Usar cuando pidan revisar o hardener un skill/servidor que ejecuta Python arbitrario en localhost (bridge de Blender, helper MCP, etc.). El entregable es evidencia de pruebas reales, no una descripción del código.

## Procedimiento

1. Identificar el artefacto: localizar el repo git local y la copia instalada; comparar con `diff -u <repo>/<archivo> <instalado>/<archivo>` para cada archivo. Ejecutar `git -C <repo> fsck --full`, `git -C <repo> remote -v` y `git -C <repo> log --oneline -5`. Si no hay remote, decir explícitamente que no se pudo verificar el repo remoto; no inferirlo.
2. Levantar el servicio aislado: iniciar Blender con `--factory-startup --python <bridge.py>` como proceso background, hacer poll del puerto hasta que acepte conexiones y confirmar con `ss -ltnp | grep <puerto>`.
3. Sondas de capacidad con el cliente incluido: versión/filepath/lista de objetos; una llamada `bpy.ops` (esperar `{'FINISHED'}`); crear un mesh con `bpy.data` + `from_pydata` + `collection.objects.link`; `save_as_mainfile` a una ruta scratch y `ls -lh`; `open_mainfile` de ese archivo y lista de objetos; `bpy.ops.screen.screenshot` y `ls -lh` del PNG. Verificar siempre en disco; no fiarse solo de la respuesta.
4. Sondas de seguridad con socket crudo y sin token: enviar una línea JSON cuyo `code` contenga sentencias Python separadas por saltos reales y leer una línea de respuesta. Si devuelve datos reales, el servicio es RCE sin autenticar. Medir `Threads:` en `/proc/<pid>/status` antes y después de ~40 conexiones inactivas para mostrar threads ilimitados por conexión. Enviar un comando que duerma y escriba un marcador, cerrar el cliente de inmediato y comprobar que el marcador aparece después: prueba de que no hay cancelación al desconectar. Provocar una excepción para revisar fuga de traceback. Comprobar si los tools que reciben rutas validan antes de escribir.
5. Limpieza: matar el proceso background y confirmar que el puerto quedó libre; guardar las salidas de las sondas en un JSON scratch como evidencia.

## Pitfalls

- `blenderctl.py` convierte la secuencia de salto de línea solo en su entry point CLI; `call(code)` pasa el string sin cambios: usar saltos reales, porque un `\n` doblemente escapado llega como barra + n y `compile()` falla con SyntaxError.
- No afirmar que se revisó un repo remoto cuando el repo local no tiene remote y no hay CLI disponible.
- Localhost es compartido por todos los usuarios/procesos locales: escuchar en 127.0.0.1 no es autenticación.
- El timeout del cliente no cancela el código encolado; los renders largos siguen ejecutándose tras la desconexión.

## Pruebas de regresión sin GUI

Cuando el bridge lee límites de variables de entorno, se testea con Python del sistema sin abrir Blender:

1. Elegir puerto efímero: bind en `127.0.0.1:0`, leer `getsockname()[1]`, cerrar y exportar `HERMES_BRIDGE_PORT` **antes** de importar el módulo (el bridge lee el env y llama a `start()` al importar).
2. Inyectar un `bpy` falso en `sys.modules` cuyo `app.timers.register` arranque un hilo daemon que ejecute la callback cada ~0.01 s; sin ese timer la cola nunca se drena y toda request espera el timeout.
3. Cargar con `importlib.util.spec_from_file_location`. Para probar el guard de host compartido, guardar la función real, poner `_started=False`, parchear `_shared_host_reason`, llamar a `start()` esperando `RuntimeError` y restaurar todo en `finally`.
4. Cubrir: happy path, código por encima del tope, línea por encima del tope, JSON inválido, cliente inactivo, tope de clientes, tope de cola, guard. Escribir los resultados a un archivo scratch y contar fallos; no dar por buena una prueba que solo imprimió PASS.
5. Después repetir un smoke test en Blender real con el script instalado y verificar el `.blend` en disco; matar el proceso y confirmar que el puerto quedó libre.

## Checklist de hardening

Token leído de un archivo 0600 o variable de entorno en cada request, o socket UNIX con `SO_PEERCRED`; timeout y tope de tamaño en `readline`; cola de requests y número de conexiones/hilos acotados; resultados estructurados en JSON y cancelación explícita; validación de rutas en los sinks de guardar/abrir/capturar; commits firmados y CI antes de publicar.
