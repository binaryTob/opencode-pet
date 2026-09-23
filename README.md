# OpenCode Pet

**English** · [Español](README.es.md)

A floating desktop companion for **OpenCode on Linux**. It shows when your agent is working or needs input, lets you start chats from the pet, uses **your own OpenCode provider and model**, and displays **your own ChatGPT/Codex pet sprite sheet**. Your images stay on your computer.

## Install

You need [OpenCode](https://opencode.ai/docs/) and Python 3 with GTK 3, PyGObject and the GdkPixbuf SVG loader. On Ubuntu/Debian:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-gdkpixbuf-2.0 librsvg2-common
git clone https://github.com/binaryTob/opencode-pet.git
cd opencode-pet
python3 pet.py --install
```

**Quit and restart OpenCode** to load the global plugin. Open OpenCode in any project and run `python3 pet.py` from this repository in another terminal. After upgrading the plugin, restart OpenCode again. Right-click the pet to close it.

## Use your own model

Configure your provider with `/connect` in OpenCode, then select a model with `/models` ([provider guide](https://opencode.ai/docs/providers/)). The pet never asks for or stores API keys. Click **✎ Chats** to pick an active project, a conversation and a connected model. **Predeterminado de OpenCode** uses the model already configured in OpenCode. You can also type a provider/model ID in **O escribe proveedor/modelo** to use a custom model that is not listed. Click **+ Nueva** and type to start a new conversation. The current UI labels are in Spanish.

## Import your ChatGPT pet

Download your transparent PNG/WebP pet image from ChatGPT/Codex. Supported formats: **1536×1872** (8×9) or **1536×2288** (8×11) Codex sprite grids (including cleanly scaled versions), **eight frames in one horizontal strip** separated by transparent gaps (even when the width isn't divisible by eight), or a **single image** for a still pet. For one-row strips and single images, the pet adapts the art locally to the renderer; it reuses the available frames across work states. Codex pet folders containing `pet.json` and `spritesheet.png`/`.webp` also work.

- In the window: **Mascota → Importar PNG/WebP…** selects the image and switches immediately.
- In a terminal: `python3 pet.py --import-pet "/path/to/spritesheet.png"`; restart the window to see it.
- `python3 pet.py --list-pets` lists saved pets; `python3 pet.py --pet imported-name` picks one at startup.

Imported pets live **only on your machine** at `${XDG_DATA_HOME:-~/.local/share}/opencode-pet/pets/`. Your selection is saved at `${XDG_CONFIG_HOME:-~/.config}/opencode-pet/settings.json`. Without an image, the window uses its own included placeholder. Third-party artwork is not bundled; import only art you are permitted to use.

## Usage and troubleshooting

**✎ Chats** lists recent sessions in projects with OpenCode running. Messages and activity refresh every few seconds. Drag the pet with the left mouse button. On GNOME/Wayland it uses XWayland, when available, to request always-on-top; on pure Wayland the compositor decides.

- **No projects / connection error:** run `python3 pet.py --install`, quit **all** running OpenCode instances, then start OpenCode again. Check the pet with `curl http://127.0.0.1:47829/health`.
- **No models listed:** connect a provider inside OpenCode using `/connect`, then reopen the panel.
- **Image isn't animating:** use a PNG/WebP under 20 MiB with eight frames separated by transparent gaps. Without recognizable frame gaps, the image is displayed as a still pet.
- **Port 47829 in use:** another pet window is already running; close it before starting a second one.

`python3 pet.py --install` is idempotent and backs up a previous version of this plugin as `pet.js.backup` before updating it. To uninstall, close the window, remove `~/.config/opencode/plugins/pet.js`, and restart OpenCode. Your personal pet files remain in the data directory until you choose to remove them.

## Development

```bash
python3 -m unittest -v test_pet.py
bun test plugin.test.ts
```

`plugin/pet.js` exposes only four chat operations plus a model list through a loopback HTTP bridge on a random port. The window listens for activity on `127.0.0.1:47829`. OpenCode's own client manages provider authentication; you do not need to run `opencode serve`.

Code is [MIT licensed](LICENSE). See [CONTRIBUTING.md](CONTRIBUTING.md) to contribute. Independent project, not affiliated with OpenAI or the OpenCode maintainers.
