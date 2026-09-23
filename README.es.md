# OpenCode Pet

[English](README.md) · **Español**

Mascota de escritorio para **OpenCode en Linux**. Flota sobre las ventanas, muestra cuándo trabaja o necesita una respuesta y permite abrir chats desde la propia mascota. Puedes usar **tu proveedor y modelo de OpenCode** y **tu mascota exportada de ChatGPT/Codex**. La imagen nunca se sube a este repositorio.

## Instalación

Necesitas [OpenCode](https://opencode.ai/docs/) y Python 3 con GTK 3, PyGObject y el cargador SVG de GdkPixbuf. En Ubuntu/Debian:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-gdkpixbuf-2.0 librsvg2-common
git clone https://github.com/binaryTob/opencode-pet.git
cd opencode-pet
python3 pet.py --install
```

**Cierra y reinicia OpenCode** para cargar el plugin global. Abre OpenCode en tu proyecto y ejecuta `python3 pet.py` desde el repositorio en otra terminal. Si OpenCode ya estaba abierto, reinícialo también al actualizar el plugin. Para cerrar la mascota: clic derecho → «Cerrar mascota».

## Elegir tu modelo

Configura tu proveedor en OpenCode con `/connect` y selecciona un modelo con `/models` ([guía de proveedores](https://opencode.ai/docs/providers/)). La mascota no recibe ni guarda claves de API. En **✎ Chats**, escoge un proyecto, una sesión y un modelo conectado en el desplegable. **Predeterminado de OpenCode** usa el modelo configurado allí. Si tu modelo no aparece, escribe su ID en **O escribe proveedor/modelo**. Pulsa **+ Nueva** y escribe para crear otra sesión.

## Importar tu mascota de ChatGPT

Descarga tu imagen transparente PNG/WebP de ChatGPT/Codex. Se admiten atlas Codex de **1536×1872** (8×9) o **1536×2288** (8×11), incluso a otra escala; **tiras horizontales de ocho fotogramas** con espacios transparentes (aunque el ancho no sea divisible por ocho); y **una sola imagen estática**. En tiras e imágenes sueltas, la mascota adapta los dibujos localmente al formato del renderizador y reutiliza los fotogramas en cada estado. También se acepta una carpeta con `pet.json` y `spritesheet.png`/`.webp`.

- En la ventana: **Mascota → Importar PNG/WebP…**, elige el archivo y cambia de mascota al instante.
- En la terminal: `python3 pet.py --import-pet "/ruta/a/mi-spritesheet.png"`; reinicia la ventana para verla.
- `python3 pet.py --list-pets` muestra las mascotas guardadas; `python3 pet.py --pet nombre-importado` escoge una al iniciar.

Las mascotas se guardan **solo localmente** en `${XDG_DATA_HOME:-~/.local/share}/opencode-pet/pets/`. La selección se recuerda en `${XDG_CONFIG_HOME:-~/.config}/opencode-pet/settings.json`. Sin ninguna imagen funciona con un dibujo original incluido. Los assets de otras personas no forman parte de este repositorio: importa imágenes sobre las que tengas derecho de uso.

## Uso y resolución de problemas

El botón **✎ Chats** abre las sesiones recientes de los proyectos donde esté abierto OpenCode. El chat actualiza mensajes y estados cada pocos segundos. Arrastra la mascota con clic izquierdo. En GNOME/Wayland usa XWayland para solicitar «siempre encima» si está disponible; en Wayland puro depende del compositor.

- **No aparecen proyectos / error de conexión:** ejecuta `python3 pet.py --install`, cierra **todas** las instancias de OpenCode y vuelve a abrir una. El plugin debe cargarse después de instalarse. Puedes comprobar la mascota con `curl http://127.0.0.1:47829/health`.
- **No aparecen modelos:** conecta primero un proveedor en OpenCode con `/connect` y vuelve a abrir el panel.
- **La imagen no se anima:** usa PNG/WebP de hasta 20 MiB con ocho fotogramas separados por espacios transparentes. Si no detecta los espacios, la muestra como mascota estática.
- **Puerto 47829 ocupado:** ya hay otra ventana de la mascota en marcha; cierra esa instancia antes de iniciar una nueva.

`python3 pet.py --install` es idempotente. Si actualiza un plugin previo de este proyecto, conserva una copia `pet.js.backup`. Para desinstalar, cierra la mascota, quita `~/.config/opencode/plugins/pet.js` y reinicia OpenCode; tus mascotas personales permanecen en el directorio de datos hasta que decidas eliminarlas.

## Desarrollo

```bash
python3 -m unittest -v test_pet.py
bun test plugin.test.ts
```

El plugin `plugin/pet.js` expone únicamente cuatro operaciones de chat y la lista de modelos mediante un puente HTTP en `127.0.0.1` con puerto efímero. La ventana escucha eventos en `127.0.0.1:47829`. El cliente interno de OpenCode maneja la autenticación y el acceso a modelos; no es necesario ejecutar `opencode serve`.

Código bajo licencia [MIT](LICENSE). Consulta [CONTRIBUTING.md](CONTRIBUTING.md) para contribuir. Proyecto independiente, sin afiliación con OpenAI ni con los autores de OpenCode.
