# OpenCode Pet

[English](README.md) · **Español**

Mascota de escritorio para **OpenCode en Linux**. Flota sobre las ventanas, muestra cuándo trabaja o necesita una respuesta y permite abrir chats desde la propia mascota. Puedes usar **tu proveedor y modelo de OpenCode** y **tu mascota exportada de ChatGPT/Codex**. La imagen nunca se sube a este repositorio.

## Instalación sencilla en Ubuntu/Debian

Necesitas [OpenCode](https://opencode.ai/docs/) instalado. Descarga el archivo **`opencode-pet_0.2.2_all.deb`** desde [Releases](https://github.com/binaryTob/opencode-pet/releases/latest) y, desde la carpeta donde lo descargaste, ejecuta:

```bash
sudo apt install ./opencode-pet_0.2.2_all.deb
opencode-pet
```

También puedes abrir **OpenCode Pet** desde el menú de aplicaciones. `apt` instala Python, GTK y PyGObject cuando hacen falta. Al abrir la mascota, el lanzador instala o actualiza el plugin **para tu usuario**, sin pedirte claves ni tocar las imágenes personales. **Cierra y reinicia OpenCode** después del primer arranque o de actualizar el paquete para que cargue el plugin. Para cerrar la mascota: clic derecho → «Cerrar mascota». Si ya estaba abierta desde el código fuente, ciérrala antes de iniciar la versión instalada.

**Desde el código fuente** (o en otra distribución con GTK 3 y PyGObject disponibles):

```bash
git clone https://github.com/binaryTob/opencode-pet.git
cd opencode-pet
python3 pet.py --install
python3 pet.py
```

Si desarrollas en este repositorio, `packaging/build-deb.sh` genera el `.deb` en `dist/`. Elegimos `.deb` primero porque Ubuntu/Debian resuelven las dependencias GTK automáticamente; AppImage requeriría empaquetar y probar esas bibliotecas en distintas distribuciones.

## Elegir tu modelo

Configura tu proveedor en OpenCode con `/connect` ([guía de proveedores](https://opencode.ai/docs/providers/)). La mascota no recibe ni guarda claves de API. En **✎ Chats**, escoge un proyecto y abre el selector bajo **Modelo**: elige **Todos los proveedores** o filtra por uno conectado, y usa **Buscar modelo, proveedor o ID…** para encontrar cualquiera de sus modelos. Ahí aparecen **OpenCode Go** (`opencode-go`) y **OpenCode Zen** (`opencode`) cuando están disponibles en esa instancia de OpenCode. La lista muestra primero hasta 60 resultados para no ralentizar la ventana, pero el buscador consulta **todo el catálogo**, no solo los primeros 60. **Predeterminado de OpenCode** usa el modelo configurado allí; el botón **↻** refresca la lista después de conectar un proveedor. Elige una sesión o pulsa **+ Nueva** y escribe para empezar. Si el selector avisa **«Plugin antiguo»**, reinicia esa instancia de OpenCode: la mascota detectará el nuevo catálogo automáticamente.

## Importar tu mascota de ChatGPT

Descarga tu imagen transparente PNG/WebP de ChatGPT/Codex. Se admiten atlas Codex de **1536×1872** (8×9) o **1536×2288** (8×11), incluso a otra escala; **tiras horizontales de ocho fotogramas** con espacios transparentes (aunque el ancho no sea divisible por ocho); y **una sola imagen estática**. En tiras e imágenes sueltas, la mascota adapta los dibujos localmente al formato del renderizador y reutiliza los fotogramas en cada estado. También se acepta una carpeta con `pet.json` y `spritesheet.png`/`.webp`.

- En la ventana: **Mascota → Importar PNG/WebP…**, elige el archivo y cambia de mascota al instante.
- En la terminal: `opencode-pet --import-pet "/ruta/a/mi-spritesheet.png"`; reinicia la ventana para verla.
- `opencode-pet --list-pets` muestra las mascotas guardadas; `opencode-pet --pet nombre-importado` escoge una al iniciar.

### Cargar todas las animaciones generadas por GPT

Si ChatGPT te dio **una imagen distinta por tarea**, colócalas juntas en una carpeta **fuera del repositorio** y crea allí `states.json`. Así puedes importar en una sola operación las **nueve animaciones de estados** y, opcionalmente, **cuatro animaciones de mirada al cursor**. Declara cada imagen y su número de fotogramas: reposo, saludo, salto, espera y trabajo no usan la misma cantidad. Los nombres de archivo que aparecen abajo son ejemplos; reemplázalos por los tuyos.

```json
{
  "id": "mi-mascota",
  "displayName": "Mi mascota",
  "animations": {
    "idle":          { "file": "idle.png", "frames": 6 },
    "running-right": { "file": "right.png", "frames": 8 },
    "running-left":  { "file": "left.png", "frames": 8 },
    "waving":        { "file": "wave.png", "frames": 4 },
    "jumping":       { "file": "jump.png", "frames": 5 },
    "failed":        { "file": "error.png", "frames": 8 },
    "waiting":       { "file": "waiting.png", "frames": 6 },
    "running":       { "file": "working.png", "frames": 6 },
    "review":        { "file": "review.png", "frames": 6 }
  },
  "look": {
    "around": { "file": "look-around.png", "frames": 4 },
    "up":     { "file": "look-up.png", "frames": 8 },
    "right":  { "file": "look-right.png", "frames": 8 },
    "left":   { "file": "look-left.png", "frames": 8 }
  }
}
```

Importa con `opencode-pet --import-pet "/ruta/a/carpeta"` o **Mascota → Importar carpeta animada…**. El programa recorta cada tira según su propio recuento, compone el atlas y guarda el resultado solo en tu directorio de datos. Las imágenes originales permanecen en la carpeta de origen. El formato Codex admite como máximo ocho fotogramas por fila; por eso la importación comprueba los recuentos oficiales. El bloque `look` es opcional: sus animaciones se guardan aparte y hacen que la mascota **siga el cursor cuando está en reposo**, sin reemplazar estados como trabajo, espera o error. Cada tira de `look` puede tener entre uno y ocho fotogramas. Si GPT también generó una imagen base de referencia, puedes conservarla en la misma carpeta; no hace falta declararla porque la mascota usa las animaciones.

**Privacidad:** `states.json`, las imágenes originales, el atlas compilado, tu elección de mascota y las credenciales de tu proveedor se mantienen en tu equipo. El repositorio contiene solo código y un ejemplo genérico de la estructura; no copies tus archivos personales a Git.

Las mascotas se guardan **solo localmente** en `${XDG_DATA_HOME:-~/.local/share}/opencode-pet/pets/`. La selección se recuerda en `${XDG_CONFIG_HOME:-~/.config}/opencode-pet/settings.json`. Sin ninguna imagen funciona con un dibujo original incluido. Los assets de otras personas no forman parte de este repositorio: importa imágenes sobre las que tengas derecho de uso.

### Estados de animación

Con un atlas Codex 8×9, el reproductor sigue las [filas y duraciones oficiales de `hatch-pet` de OpenAI](https://github.com/openai/skills/blob/main/skills/.curated/hatch-pet/references/animation-rows.md). Una tira horizontal de ocho fotogramas contiene **una sola animación**: se repite en todos los estados, aunque la etiqueta de estado sí cambie.

| Estado en OpenCode | Fila del atlas | Comportamiento |
| --- | ---: | --- |
| Reposo | 0 · idle | Movimiento tranquilo, 6 fotogramas |
| Trabajando | 7 · running | Concentración, 6 fotogramas (no correr a pie) |
| Necesita respuesta | 6 · waiting | Esperar aprobación o respuesta, 6 fotogramas |
| Terminó | 3 · waving | Aviso de finalización, 4 fotogramas |
| Error | 5 · failed | Reacción al fallo, 8 fotogramas |

La fila 1 (8 fotogramas) se usa al mover la ventana hacia la derecha y la 2 (8) al moverla a la izquierda. La fila 4 (5) celebra brevemente al terminar y después pasa al saludo. La fila 8 (6) se activa si OpenCode emite el comando `review` o `code-review`. Actualmente «Terminó» dura 12 segundos en vez de comprobar mensajes sin leer.

## Uso y resolución de problemas

El botón **✎ Chats** abre las sesiones recientes de los proyectos donde esté abierto OpenCode. El chat actualiza mensajes y estados cada pocos segundos. Arrastra la mascota con clic izquierdo. En GNOME/Wayland usa XWayland para solicitar «siempre encima» si está disponible; en Wayland puro depende del compositor.

- **No aparecen proyectos / error de conexión:** ejecuta `opencode-pet --install`, cierra **todas** las instancias de OpenCode y vuelve a abrir una. El plugin debe cargarse después de instalarse. Puedes comprobar la mascota con `curl http://127.0.0.1:47829/health`.
- **No aparecen modelos:** conecta primero un proveedor en OpenCode con `/connect` y vuelve a abrir el panel.
- **La imagen no se anima:** usa PNG/WebP de hasta 20 MiB con ocho fotogramas separados por espacios transparentes. Si no detecta los espacios, la muestra como mascota estática.
- **Puerto 47829 ocupado:** ya hay otra ventana de la mascota en marcha; cierra esa instancia antes de iniciar una nueva.

`opencode-pet --install` es idempotente. Si actualiza un plugin previo de este proyecto, conserva una copia `pet.js.backup`. Para desinstalar el paquete, cierra la mascota y ejecuta `sudo apt remove opencode-pet`. El plugin de usuario permanece en `~/.config/opencode/plugins/pet.js`; quítalo si ya no lo quieres y reinicia OpenCode. Tus mascotas personales permanecen en el directorio de datos hasta que decidas eliminarlas.

## Desarrollo

```bash
python3 -m unittest -v test_pet.py
python3 -m unittest -v test_gui.py  # con sesión gráfica; CI usa Xvfb
bun test plugin.test.ts
```

El plugin `plugin/pet.js` expone únicamente cuatro operaciones de chat y la lista de modelos mediante un puente HTTP en `127.0.0.1` con puerto efímero. La ventana escucha eventos en `127.0.0.1:47829`. El cliente interno de OpenCode maneja la autenticación y el acceso a modelos; no es necesario ejecutar `opencode serve`.

Código bajo licencia [MIT](LICENSE). Consulta [CONTRIBUTING.md](CONTRIBUTING.md) para contribuir. Proyecto independiente, sin afiliación con OpenAI ni con los autores de OpenCode.
