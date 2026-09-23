#!/usr/bin/env python3
"""Small floating Codex-format pet driven by local OpenCode events (Linux/GTK 3)."""

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from time import monotonic

HOST = "127.0.0.1"
PORT = 47829
CELL_WIDTH = 192
CELL_HEIGHT = 208
# OpenAI hatch-pet animation rows: https://github.com/openai/skills/blob/main/skills/.curated/hatch-pet/references/animation-rows.md
ATLAS_ANIMATIONS = {
    "idle": (0, (280, 110, 110, 140, 140, 320)),
    "running-right": (1, (120, 120, 120, 120, 120, 120, 120, 220)),
    "running-left": (2, (120, 120, 120, 120, 120, 120, 120, 220)),
    "waving": (3, (140, 140, 140, 280)),
    "jumping": (4, (140, 140, 140, 140, 280)),
    "failed": (5, (140, 140, 140, 140, 140, 140, 140, 240)),
    "waiting": (6, (150, 150, 150, 150, 150, 260)),
    "running": (7, (120, 120, 120, 120, 120, 220)),
    "review": (8, (150, 150, 150, 150, 150, 280)),
}
LOOK_ROWS = {"around": 0, "up": 1, "right": 2, "left": 3}
STATUS_ANIMATIONS = {"idle": "idle", "running": "running", "waiting": "waiting",
                     "ready": "waving", "blocked": "failed", "review": "review",
                     "moving-right": "running-right", "moving-left": "running-left",
                     "celebrating": "jumping"}
LABELS = {
    "idle": "OpenCode · en reposo",
    "running": "OpenCode · trabajando",
    "waiting": "OpenCode · necesita tu respuesta",
    "ready": "OpenCode · terminado",
    "blocked": "OpenCode · error",
    "review": "OpenCode · revisando",
}


def animation_frame(status, elapsed_ms, layout="atlas", reduced_motion=False):
    """Pick an occupied frame with the official atlas timing for a status."""
    row, durations = ATLAS_ANIMATIONS[STATUS_ANIMATIONS[status]]
    if layout == "static" or reduced_motion:
        return (0 if layout != "atlas" else row), 0
    if layout == "strip":
        return 0, int(max(0, elapsed_ms) // 160) % 8
    if layout != "atlas":
        raise ValueError(f"Formato de animación desconocido: {layout}")
    position = max(0, elapsed_ms) % sum(durations)
    for index, duration in enumerate(durations):
        if position < duration:
            return row, index
        position -= duration
    return row, 0


def look_direction(x, y):
    """Choose a cursor animation within the 180×165 pet image."""
    if x < 60:
        return "left"
    if x > 120:
        return "right"
    if y < 55:
        return "up"
    return "around"


def filter_available_models(models, provider="all", query=""):
    """Search the complete connected-model catalog by provider, name or ID."""
    needle = query.strip().casefold()
    return sorted((item for item in models
                   if (provider == "all" or item["providerID"] == provider)
                   and (not needle or any(needle in str(item[field]).casefold()
                                          for field in ("id", "providerName", "modelName")))),
                  key=lambda item: (item["providerName"].casefold(), item["modelName"].casefold(), item["id"]))


def config_home():
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def pet_library():
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "opencode-pet" / "pets"


def settings_file():
    return config_home() / "opencode-pet" / "settings.json"


def selected_pet(path=None):
    try:
        value = json.loads(Path(path or settings_file()).read_text(encoding="utf-8"))
        return value.get("selected_pet") if isinstance(value.get("selected_pet"), str) else None
    except (FileNotFoundError, ValueError, OSError, AttributeError):
        return None


def save_selected_pet(slug, path=None):
    target = Path(path or settings_file())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"selected_pet": slug}, indent=2) + "\n", encoding="utf-8")


def install_plugin(destination=None):
    """Install one global plugin so the pet works in any OpenCode project."""
    source = Path(__file__).resolve().parent / "plugin" / "pet.js"
    destination = Path(destination) if destination else config_home() / "opencode" / "plugins" / "pet.js"
    if destination.exists():
        current = destination.read_bytes()
        updated = source.read_bytes()
        if current == updated:
            return destination
        text = current.decode("utf-8", errors="replace")
        if not (text.startswith("// opencode-pet:") or
                (text.startswith("// OpenCode project plugin:") and "export const PetPlugin" in text)):
            raise ValueError(f"Ya existe otro plugin en {destination}; no lo sobrescribí")
        backup = destination.with_name(destination.name + ".backup")
        if not backup.exists():
            shutil.copy2(destination, backup)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def choose_window_backend(env):
    """Use XWayland for the desktop pet when Wayland won't honor keep-above."""
    if (env.get("XDG_SESSION_TYPE", "").lower() == "wayland"
            and env.get("DISPLAY") and not env.get("GDK_BACKEND")):
        return "x11"
    return None


def pet_source(path):
    """Resolve a Codex pet folder, manifest or bare sprite sheet."""
    path = Path(path).expanduser().resolve()
    if path.is_dir():
        manifest = path / "pet.json"
        if manifest.exists():
            path = manifest
        else:
            path = next((p for p in (path / "spritesheet.webp", path / "spritesheet.png") if p.exists()), path)
    version = None
    metadata = {}
    if path.name == "pet.json":
        metadata = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            raise ValueError("pet.json debe contener un objeto JSON")
        version = metadata.get("spriteVersionNumber")
        filename = metadata.get("spritesheetPath", "spritesheet.webp")
        if not isinstance(filename, str) or filename not in ("spritesheet.webp", "spritesheet.png"):
            raise ValueError("spritesheetPath debe ser spritesheet.webp o spritesheet.png")
        path = path.parent / filename
    if path.suffix.lower() not in (".webp", ".png") or not path.is_file():
        raise ValueError("Indica una carpeta con pet.json, o un spritesheet PNG/WebP")
    return path, version, metadata


def strip_boundaries(image):
    """Find eight near-equal frames separated by transparent columns."""
    width, height = image.get_width(), image.get_height()
    if not image.get_has_alpha() or width < 128:
        return None
    pixels = image.get_pixels()
    stride, channels = image.get_rowstride(), image.get_n_channels()
    boundaries = [0]
    for frame in range(1, 8):
        center = round(frame * width / 8)
        radius = max(8, round(width / 8 / 12))
        gap = next((x for offset in range(radius + 1)
                    for x in (center - offset, center + offset)
                    if 0 < x < width and all(pixels[y * stride + x * channels + 3] == 0
                                               for y in range(height))), None)
        if gap is None or gap <= boundaries[-1]:
            return None
        boundaries.append(gap)
    return boundaries + [width]


def visible_bounds(image, left, right):
    """Trim empty margins and isolated anti-aliasing pixels from a frame."""
    height = image.get_height()
    if not image.get_has_alpha():
        return left, 0, right - left, height
    pixels = image.get_pixels()
    stride, channels = image.get_rowstride(), image.get_n_channels()
    columns = [0] * (right - left)
    rows = [0] * height
    for y in range(height):
        offset = y * stride + left * channels + 3
        for x in range(right - left):
            if pixels[offset + x * channels] > 24:
                columns[x] += 1
                rows[y] += 1
    xs = [x for x, count in enumerate(columns) if count >= 3]
    ys = [y for y, count in enumerate(rows) if count >= 3]
    if not xs or not ys:
        return left, 0, right - left, height
    return left + xs[0], ys[0], xs[-1] - xs[0] + 1, ys[-1] - ys[0] + 1


def normalize_pet(image, boundaries):
    """Place strip or single-image frames into the renderer's 8×9 grid."""
    from gi.repository import GdkPixbuf

    atlas = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 1536, 1872)
    atlas.fill(0)
    boxes = [visible_bounds(image, boundaries[index], boundaries[index + 1])
             for index in range(len(boundaries) - 1)]
    for column in range(8):
        index = column if len(boundaries) == 9 else 0
        x, y, width, height = boxes[index]
        frame = image.new_subpixbuf(x, y, width, height)
        scale = min(176 / width, 184 / height)
        scaled_width, scaled_height = max(1, round(width * scale)), max(1, round(height * scale))
        scaled = frame.scale_simple(scaled_width, scaled_height, GdkPixbuf.InterpType.BILINEAR)
        for row in range(9):
            scaled.copy_area(0, 0, scaled_width, scaled_height, atlas,
                             column * 192 + (192 - scaled_width) // 2,
                             row * 208 + 196 - scaled_height)
    return atlas


def build_state_atlas(folder, spec):
    """Assemble independently generated animation strips into a Codex atlas."""
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    animations = spec.get("animations") if isinstance(spec, dict) else None
    if not isinstance(animations, dict):
        raise ValueError("states.json necesita un objeto 'animations'")
    missing = set(ATLAS_ANIMATIONS) - set(animations)
    if missing:
        raise ValueError("Faltan animaciones: " + ", ".join(sorted(missing)))
    atlas = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 1536, 1872)
    atlas.fill(0)
    digest = hashlib.sha256()
    for state, (row, durations) in ATLAS_ANIMATIONS.items():
        image, count, path = load_animation_strip(folder, animations[state], state, len(durations))
        digest.update(state.encode())
        digest.update(path.read_bytes())
        copy_animation_row(image, count, atlas, row)
    return atlas, digest.hexdigest()


def load_animation_strip(folder, entry, name, expected=None):
    from gi.repository import GdkPixbuf

    if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
        raise ValueError(f"'{name}' necesita 'file' y 'frames'")
    filename, count = entry["file"], entry.get("frames")
    if type(count) is not int or not 1 <= count <= 8 or (expected and count != expected):
        detail = f"{expected}" if expected else "entre 1 y 8"
        raise ValueError(f"'{name}' necesita {detail} fotogramas, no {count}")
    if filename != Path(filename).name or Path(filename).suffix.lower() not in (".png", ".webp"):
        raise ValueError(f"'{name}' debe señalar un PNG/WebP dentro de la carpeta")
    path = folder / filename
    if path.resolve().parent != folder.resolve() or not path.is_file():
        raise ValueError(f"No se encontró la imagen de '{name}' en la carpeta")
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError(f"La imagen de '{name}' supera 20 MiB")
    return GdkPixbuf.Pixbuf.new_from_file(str(path)), count, path


def copy_animation_row(image, count, atlas, row):
    from gi.repository import GdkPixbuf

    for column in range(count):
        left, right = round(column * image.get_width() / count), round((column + 1) * image.get_width() / count)
        x, y, width, height = visible_bounds(image, left, right)
        frame = image.new_subpixbuf(x, y, width, height)
        scale = min(176 / width, 184 / height)
        scaled_width, scaled_height = max(1, round(width * scale)), max(1, round(height * scale))
        scaled = frame.scale_simple(scaled_width, scaled_height, GdkPixbuf.InterpType.BILINEAR)
        scaled.copy_area(0, 0, scaled_width, scaled_height, atlas,
                         column * 192 + (192 - scaled_width) // 2,
                         row * 208 + 196 - scaled_height)


def build_look_sheet(folder, spec):
    """Keep optional cursor animations separate from the nine official rows."""
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    looks = spec.get("look", {})
    if not isinstance(looks, dict) or set(looks) - set(LOOK_ROWS):
        raise ValueError("'look' debe usar around, up, right o left")
    if not looks:
        return None, {}, ""
    sheet = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 1536, 832)
    sheet.fill(0)
    digest = hashlib.sha256()
    counts = {}
    for name, row in LOOK_ROWS.items():
        if name not in looks:
            continue
        image, count, path = load_animation_strip(folder, looks[name], name)
        digest.update(name.encode())
        digest.update(path.read_bytes())
        copy_animation_row(image, count, sheet, row)
        counts[name] = count
    return sheet, counts, digest.hexdigest()


def load_look_sheet(path):
    """Read the optional locally generated cursor sheet for an installed pet."""
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    folder = Path(path).expanduser().resolve()
    if not folder.is_dir() or not (folder / "pet.json").is_file():
        return None, {}
    metadata = json.loads((folder / "pet.json").read_text(encoding="utf-8"))
    if "lookSheetPath" not in metadata:
        return None, {}
    if metadata["lookSheetPath"] != "looksheet.png":
        raise ValueError("Nombre de lámina de mirada inválido")
    image = GdkPixbuf.Pixbuf.new_from_file(str(folder / "looksheet.png"))
    if (image.get_width(), image.get_height()) != (1536, 832):
        raise ValueError("La lámina de mirada debe medir 1536×832")
    counts = metadata.get("lookFrames", {})
    if not isinstance(counts, dict) or any(name not in LOOK_ROWS or type(count) is not int or not 1 <= count <= 8
                                            for name, count in counts.items()):
        raise ValueError("Fotogramas de mirada inválidos")
    return image, counts


def import_state_pet(folder, library=None, settings=None):
    """Install a states.json package without publishing any source artwork."""
    folder = Path(folder).expanduser().resolve()
    spec = json.loads((folder / "states.json").read_text(encoding="utf-8"))
    atlas, fingerprint = build_state_atlas(folder, spec)
    look_sheet, look_counts, look_fingerprint = build_look_sheet(folder, spec)
    if look_sheet is not None:
        fingerprint = hashlib.sha256((fingerprint + look_fingerprint).encode()).hexdigest()
    name = str(spec.get("displayName") or folder.name).strip()[:100] or "Mascota"
    library = Path(library or pet_library())
    base, slug = pet_slug(str(spec.get("id") or name)), None
    for counter in range(1, 1000):
        candidate = base if counter == 1 else f"{base}-{counter}"
        target = library / candidate
        manifest = target / "pet.json"
        if not target.exists():
            slug = candidate
            break
        try:
            if json.loads(manifest.read_text(encoding="utf-8")).get("sourceDigest") == fingerprint:
                slug = candidate
                break
        except (OSError, ValueError, AttributeError):
            pass
    if slug is None:
        raise ValueError("Demasiadas mascotas con el mismo nombre")
    target = library / slug
    target.mkdir(parents=True, exist_ok=True)
    atlas.savev(str(target / "spritesheet.png"), "png", [], [])
    if look_sheet is not None:
        look_sheet.savev(str(target / "looksheet.png"), "png", [], [])
    (target / "pet.json").write_text(json.dumps({
        "id": slug, "displayName": name, "spritesheetPath": "spritesheet.png",
        "spriteVersionNumber": 1, "sourceDigest": fingerprint,
        **({"lookSheetPath": "looksheet.png", "lookFrames": look_counts} if look_sheet else {}),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    save_selected_pet(slug, settings)
    return slug, target


def load_pet_path(path, details=False):
    """Open a Codex atlas, an eight-frame strip or a single transparent pet."""
    path, version, metadata = pet_source(path)
    # Import GTK only when handling an atlas or launching the UI; state tests stay headless.
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    image = GdkPixbuf.Pixbuf.new_from_file(str(path))
    width, height = image.get_width(), image.get_height()
    layout = metadata.get("layout")
    if layout not in (None, "atlas", "strip", "static"):
        raise ValueError("Formato de mascota desconocido en pet.json")
    cell = width // 8
    rows = next((count for count in (9, 11) if width % 8 == 0 and height % count == 0
                 and (height // count) * 12 == cell * 13), None)
    if rows and layout not in ("strip", "static"):
        if version in (1, 2) and rows != (9 if version == 1 else 11):
            raise ValueError("spriteVersionNumber no coincide con el tamaño del atlas")
        result = (image, cell, height // rows)
        return (*result, "atlas", rows) if details else result
    if version in (1, 2) and layout not in ("strip", "static"):
        raise ValueError("El atlas Codex no coincide con su versión en pet.json")
    boundaries = strip_boundaries(image) if layout != "static" else None
    if layout == "strip" and boundaries is None:
        raise ValueError("La tira de 8 fotogramas necesita separaciones transparentes")
    normalized = normalize_pet(image, boundaries or [0, width])
    result = (normalized, 192, 208)
    return (*result, "strip" if boundaries else "static", 9) if details else result


def pet_slug(name):
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")[:48] or "mascota"


def import_pet(path, library=None, settings=None):
    """Copy a user-owned atlas, eight-frame strip or single pet locally."""
    if (Path(path).expanduser() / "states.json").is_file():
        return import_state_pet(path, library, settings)
    source, _, metadata = pet_source(path)
    if source.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("El spritesheet no debe superar 20 MiB")
    _, _, _, layout, rows = load_pet_path(path, details=True)
    name = metadata.get("displayName") or (source.parent.name if source.stem == "spritesheet" else source.stem)
    name = str(name).strip()[:100] or "Mascota"
    library = Path(library or pet_library())
    base = pet_slug(str(metadata.get("id") or name))
    slug = base
    content = hashlib.sha256(source.read_bytes()).digest()
    for counter in range(2, 1000):
        target = library / slug
        sprite = target / f"spritesheet{source.suffix.lower()}"
        if not target.exists() or (sprite.is_file() and hashlib.sha256(sprite.read_bytes()).digest() == content):
            break
        slug = f"{base}-{counter}"
    else:
        raise ValueError("Demasiadas mascotas con el mismo nombre")
    target.mkdir(parents=True, exist_ok=True)
    if source != sprite:
        shutil.copy2(source, sprite)
    manifest = {"id": slug, "displayName": name, "spritesheetPath": sprite.name,
                **({"spriteVersionNumber": 2 if rows == 11 else 1} if layout == "atlas" else {"layout": layout})}
    (target / "pet.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    save_selected_pet(slug, settings)
    return slug, target


def installed_pets(library=None):
    library = Path(library or pet_library())
    if not library.exists():
        return []
    entries = []
    for folder in sorted(library.iterdir()):
        if not folder.is_dir() or not (folder / "pet.json").is_file():
            continue
        try:
            metadata = json.loads((folder / "pet.json").read_text(encoding="utf-8"))
            entries.append((folder.name, metadata.get("displayName", folder.name)))
        except (ValueError, OSError):
            continue
    return entries


class PetState:
    """Aggregate activity across sessions; prioritize input, errors, and completions."""

    def __init__(self, now=monotonic):
        self.sessions = {}
        self.servers = {}
        self.session_directories = {}
        self.active_directory = None
        self.now = now
        self.lock = Lock()

    def update(self, event):
        kind = event.get("type")
        session = event.get("sessionID")
        if not isinstance(session, str) or not session:
            return False
        directory = event.get("directory")
        if kind == "session.deleted":
            with self.lock:
                self.sessions.pop(session, None)
                self.session_directories.pop(session, None)
            return True
        transitions = {
            "session.busy": "running",
            "session.review": "review",
            "session.idle": "ready",
            "session.waiting": "waiting",
            "session.error": "blocked",
            "session.disposed": None,
        }
        if kind not in transitions:
            return False
        with self.lock:
            if isinstance(directory, str) and directory:
                self.session_directories[session] = directory
                self.active_directory = directory
            if transitions[kind] is None:
                self.sessions.pop(session, None)
                self.session_directories.pop(session, None)
            else:
                self.sessions[session] = (transitions[kind], self.now())
        return True

    def register(self, directory, url):
        if not isinstance(directory, str) or not directory or not isinstance(url, str):
            raise ValueError("Registro inválido")
        parsed = urlsplit(url)
        if (parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
                or not parsed.port or parsed.username or parsed.password or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment):
            raise ValueError("OpenCode debe usar un servidor HTTP local")
        with self.lock:
            self.servers[directory] = (url.rstrip("/"), self.now())
            if self.active_directory is None:
                self.active_directory = directory

    def projects(self):
        with self.lock:
            available = [directory for directory, (_, seen) in self.servers.items()
                         if self.now() - seen < 20]
            return available, self.active_directory

    def server(self, directory):
        with self.lock:
            entry = self.servers.get(directory)
            return entry[0] if entry and self.now() - entry[1] < 20 else None

    def session_status(self, session_id):
        with self.lock:
            record = self.sessions.get(session_id)
        if record is None:
            return "idle"
        status, timestamp = record
        return "idle" if status == "ready" and self.now() - timestamp >= 12 else status

    @property
    def status(self):
        active = set()
        with self.lock:
            sessions = list(self.sessions.values())
        for status, timestamp in sessions:
            if status != "ready" or self.now() - timestamp < 12:
                active.add(status)
        for status in ("waiting", "blocked", "ready", "review", "running"):
            if status in active:
                return status
        return "idle"


def create_handler(state):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/health":
                self.send_error(404)
                return
            body = json.dumps({"status": state.status, "projects": len(state.projects()[0])}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path not in ("/event", "/register"):
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    raise ValueError("Tamaño de evento inválido")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("Datos inválidos")
                if self.path == "/register":
                    state.register(data.get("directory"), data.get("url"))
                elif not state.update(data):
                    raise ValueError("Evento inválido")
            except (ValueError, json.JSONDecodeError):
                self.send_error(400)
                return
            self.send_response(204)
            self.end_headers()

        def log_message(self, *_args):
            pass

    return Handler


class OpencodeGateway:
    """Call the local plugin relay, which uses OpenCode's configured providers."""

    def __init__(self, state, timeout=4):
        self.state = state
        self.timeout = timeout

    def request(self, directory, method, path, body=None, **query):
        server = self.state.server(directory)
        if not server:
            raise ValueError("Abre OpenCode en el proyecto seleccionado y reinícialo")
        params = urlencode({"directory": directory, **query})
        payload = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(server + path + "?" + params, data=payload, method=method,
                          headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except HTTPError as exc:
            raise ValueError(f"OpenCode respondió {exc.code}: revisa el proyecto o la sesión") from exc
        except (URLError, TimeoutError) as exc:
            raise ValueError("No se pudo conectar con OpenCode; comprueba que siga abierto") from exc

    def sessions(self, directory):
        sessions = self.request(directory, "GET", "/session", limit=20)
        return [item for item in sessions if not item.get("parentID")][:20]

    def models(self, directory):
        return self.request(directory, "GET", "/models")

    def messages(self, directory, session_id):
        messages = self.request(directory, "GET", f"/session/{quote(session_id, safe='')}/message", limit=30)
        result = []
        for message in messages:
            role = message.get("info", {}).get("role")
            if role not in ("user", "assistant"):
                continue
            text = "\n".join(part["text"] for part in message.get("parts", [])
                             if part.get("type") == "text" and not part.get("synthetic")
                             and not part.get("ignored") and part.get("text"))
            if text:
                result.append((role, text))
        return result

    def send(self, directory, session_id, text, model=None):
        if not text or not text.strip() or len(text) > 20_000:
            raise ValueError("Escribe un mensaje de entre 1 y 20 000 caracteres")
        selected = None
        if model:
            provider_id, separator, model_id = model.partition("/")
            if not separator or not provider_id or not model_id:
                raise ValueError("El modelo debe tener el formato proveedor/modelo")
            selected = {"providerID": provider_id, "modelID": model_id}
        if not session_id:
            session = self.request(directory, "POST", "/session", {})
            session_id = session["id"]
        self.request(directory, "POST", f"/session/{quote(session_id, safe='')}/prompt_async",
                     {"parts": [{"type": "text", "text": text}], **({"model": selected} if selected else {})})
        return session_id


def placeholder(status, tick):
    """Create a tiny original SVG character without an external image dependency."""
    colors = {"idle": "#75c2f5", "running": "#75e6a6", "waiting": "#ffc261",
              "ready": "#c09fff", "blocked": "#ff7a7d", "review": "#64c6d9"}
    extra = "?" if status == "waiting" else "!" if status == "blocked" else ""
    bounce = math.sin(tick / 3) * (3 if status == "running" else 1)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="180" height="165" viewBox="0 0 180 165">
      <ellipse cx="90" cy="145" rx="55" ry="12" fill="#141924" opacity=".25"/>
      <g transform="translate(0 {bounce:.2f})">
        <circle cx="90" cy="80" r="57" fill="{colors[status]}"/>
        <circle cx="69" cy="72" r="5" fill="#283344"/>
        <circle cx="111" cy="72" r="5" fill="#283344"/>
        <path d="M 77 91 Q 90 110 103 91" fill="none" stroke="#283344" stroke-width="3" stroke-linecap="round"/>
        <text x="130" y="39" fill="#283344" font-size="30">{extra}</text>
      </g>
    </svg>'''.encode()


def pixbuf_from_svg(svg):
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
    loader.write(svg)
    loader.close()
    return loader.get_pixbuf()


def create_chat_panel(pet_window, state, gateway, Gtk, GLib):
    """A small quick-chat window with a per-project conversation tray."""
    panel = Gtk.Window(title="Chats · OpenCode Pet")
    panel.set_default_size(390, 510)
    panel.set_transient_for(pet_window)
    panel.set_keep_above(True)
    panel.set_skip_taskbar_hint(True)
    panel.connect("delete-event", lambda *_: panel.hide() or True)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
    box.set_border_width(10)
    panel.add(box)

    project_label = Gtk.Label(label="Proyecto")
    project_label.set_xalign(0)
    box.pack_start(project_label, False, False, 0)
    projects = Gtk.ComboBoxText()
    box.pack_start(projects, False, False, 0)
    model_label = Gtk.Label(label="Modelo")
    model_label.set_xalign(0)
    box.pack_start(model_label, False, False, 0)
    model_controls = Gtk.Box(spacing=6)
    box.pack_start(model_controls, False, False, 0)
    model_button = Gtk.MenuButton(label="Predeterminado de OpenCode")
    model_controls.pack_start(model_button, True, True, 0)
    refresh_models = Gtk.Button(label="↻")
    refresh_models.set_tooltip_text("Actualizar proveedores y modelos de OpenCode")
    model_controls.pack_end(refresh_models, False, False, 0)
    model_popover = Gtk.Popover.new(model_button)
    model_button.set_popover(model_popover)
    model_options = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    model_options.set_border_width(8)
    model_popover.add(model_options)
    provider_filter = Gtk.ComboBoxText()
    provider_filter.append("all", "Todos los proveedores")
    provider_filter.set_active_id("all")
    model_options.pack_start(provider_filter, False, False, 0)
    model_search = Gtk.SearchEntry()
    model_search.set_placeholder_text("Buscar modelo, proveedor o ID…")
    model_options.pack_start(model_search, False, False, 0)
    results_scroll = Gtk.ScrolledWindow()
    results_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    results_scroll.set_size_request(400, 260)
    model_options.pack_start(results_scroll, True, True, 0)
    model_results = Gtk.ListBox()
    model_results.set_activate_on_single_click(True)
    results_scroll.add(model_results)
    result_count = Gtk.Label(label="Conecta OpenCode para ver modelos")
    result_count.set_xalign(0)
    model_options.pack_start(result_count, False, False, 0)
    custom_model = Gtk.Entry()
    custom_model.set_placeholder_text("O escribe proveedor/modelo")
    box.pack_start(custom_model, False, False, 0)

    top = Gtk.Box(spacing=6)
    box.pack_start(top, False, False, 0)
    top.pack_start(Gtk.Label(label="Conversaciones"), True, True, 0)
    new_button = Gtk.Button(label="+ Nueva")
    top.pack_end(new_button, False, False, 0)

    tray_scroll = Gtk.ScrolledWindow()
    tray_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    tray_scroll.set_size_request(-1, 128)
    box.pack_start(tray_scroll, False, False, 0)
    tray = Gtk.ListBox()
    tray_scroll.add(tray)

    messages_scroll = Gtk.ScrolledWindow()
    messages_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    box.pack_start(messages_scroll, True, True, 0)
    transcript = Gtk.TextView()
    transcript.set_editable(False)
    transcript.set_cursor_visible(False)
    transcript.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    transcript.set_left_margin(8)
    transcript.set_right_margin(8)
    transcript.get_buffer().set_text("Elige una conversación o escribe para empezar.")
    messages_scroll.add(transcript)

    composer = Gtk.Box(spacing=6)
    box.pack_start(composer, False, False, 0)
    entry = Gtk.Entry()
    entry.set_placeholder_text("Escribe a OpenCode…")
    composer.pack_start(entry, True, True, 0)
    send_button = Gtk.Button(label="Enviar")
    composer.pack_end(send_button, False, False, 0)
    feedback = Gtk.Label(label="Abre OpenCode para conectar el chat.")
    feedback.set_xalign(0)
    feedback.set_line_wrap(True)
    box.pack_start(feedback, False, False, 0)

    ui = {"directory": None, "session": None, "building": False, "loading_list": False,
          "loading_models": False, "models_loaded_for": None, "selected_models": {}, "available_models": [],
          "loading_messages": False, "sending": False, "projects": (), "rows": (), "generation": 0}

    def background(operation, complete):
        def execute():
            try:
                result, error = operation(), None
            except (ValueError, KeyError, TypeError, OSError) as exc:
                result, error = None, str(exc)

            def finish():
                complete(result, error)
                return False

            GLib.idle_add(finish)

        Thread(target=execute, daemon=True).start()

    def show_projects():
        available, active = state.projects()
        names = tuple(available)
        if names == ui["projects"]:
            return
        previous = ui["directory"]
        ui["projects"] = names
        projects.remove_all()
        for directory in names:
            projects.append(directory, directory)
        chosen = previous if previous in names else active if active in names else names[0] if names else None
        if chosen:
            projects.set_active_id(chosen)
            feedback.set_text("")
        else:
            ui["directory"] = None
            feedback.set_text("Abre o reinicia OpenCode para conectar el chat.")

    def update_list():
        directory = ui["directory"]
        if not panel.get_visible() or not directory or ui["loading_list"]:
            return
        ui["loading_list"] = True

        def complete(items, error):
            ui["loading_list"] = False
            if directory != ui["directory"]:
                return
            if error:
                feedback.set_text(error)
                return
            signature = tuple((item["id"], item.get("title"), state.session_status(item["id"]))
                              for item in items)
            if signature == ui["rows"]:
                return
            ui["rows"] = signature
            ui["building"] = True
            for row in tray.get_children():
                tray.remove(row)
            for session_id, title, status in signature:
                row = Gtk.ListBoxRow()
                row.session_id = session_id
                row.add(Gtk.Label(label=f"{title or 'Sin título'} · {LABELS[status].split(' · ')[1]}",
                                  xalign=0, max_width_chars=44, ellipsize=3))
                tray.add(row)
                if session_id == ui["session"]:
                    tray.select_row(row)
            tray.show_all()
            ui["building"] = False

        background(lambda: gateway.sessions(directory), complete)

    def show_selected_model():
        directory = ui["directory"]
        chosen = ui["selected_models"].get(directory, "default")
        if chosen == "default":
            model_button.set_label("Predeterminado de OpenCode")
            return
        current = next((item for item in ui["available_models"] if item["id"] == chosen), None)
        title = current["label"] if current else chosen
        model_button.set_label(title[:40] + "…" if len(title) > 40 else title)

    def render_model_results(*_args):
        for row in model_results.get_children():
            model_results.remove(row)
        provider = provider_filter.get_active_id() or "all"
        query = model_search.get_text()
        matches = filter_available_models(ui["available_models"], provider, query)
        if provider == "all" and not query.strip():
            row = Gtk.ListBoxRow()
            row.model_id = "default"
            row.add(Gtk.Label(label="Predeterminado de OpenCode", xalign=0))
            model_results.add(row)
        for item in matches[:60]:
            row = Gtk.ListBoxRow()
            row.model_id = item["id"]
            labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            title = Gtk.Label(label=item["modelName"], xalign=0)
            title.set_max_width_chars(46)
            title.set_ellipsize(3)
            detail = Gtk.Label(label=f"{item['providerName']} · {item['id']}", xalign=0)
            detail.set_max_width_chars(46)
            detail.set_ellipsize(3)
            labels.pack_start(title, False, False, 0)
            labels.pack_start(detail, False, False, 0)
            row.add(labels)
            model_results.add(row)
        model_results.show_all()
        if matches:
            result_count.set_text(f"{len(matches)} modelos · mostrando {min(len(matches), 60)}")
        else:
            result_count.set_text("No hay resultados. Prueba otro nombre o ID.")

    def update_models():
        directory = ui["directory"]
        if (not panel.get_visible() or not directory or ui["loading_models"] or
                ui["models_loaded_for"] == directory):
            return
        ui["loading_models"] = True

        def complete(items, error):
            ui["loading_models"] = False
            if directory != ui["directory"]:
                return
            if error:
                feedback.set_text(error)
                return
            if not isinstance(items, list):
                feedback.set_text("OpenCode devolvió un catálogo de modelos inválido.")
                return
            ui["models_loaded_for"] = directory
            catalog = []
            for item in items:
                if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                    continue
                provider_id, separator, model_id = item["id"].partition("/")
                if not separator or not provider_id or not model_id:
                    continue
                catalog.append({"id": item["id"],
                                "providerID": item.get("providerID") or provider_id,
                                "providerName": item.get("providerName") or provider_id,
                                "modelName": item.get("modelName") or model_id,
                                "label": item.get("label") or item["id"]})
            ui["available_models"] = catalog
            selected = ui["selected_models"].get(directory, "default")
            if selected != "default" and not any(item["id"] == selected for item in catalog):
                ui["selected_models"][directory] = "default"
                feedback.set_text("El modelo elegido ya no está conectado; se usará el predeterminado.")
            provider_filter.remove_all()
            provider_filter.append("all", "Todos los proveedores")
            providers = {item["providerID"]: item["providerName"] for item in catalog}
            for provider_id, name in sorted(providers.items(), key=lambda entry: entry[1].casefold()):
                provider_filter.append(provider_id, name)
            provider_filter.set_active_id("all")
            show_selected_model()
            render_model_results()

        background(lambda: gateway.models(directory), complete)

    def update_messages():
        directory, session_id = ui["directory"], ui["session"]
        if not panel.get_visible() or not directory or not session_id or ui["loading_messages"]:
            return
        ui["loading_messages"] = True
        generation = ui["generation"]

        def complete(messages, error):
            ui["loading_messages"] = False
            if (directory, session_id, generation) != (ui["directory"], ui["session"], ui["generation"]):
                return
            if error:
                feedback.set_text(error)
                return
            text = "\n\n".join(f"{'Tú' if role == 'user' else 'OpenCode'}\n{content}"
                               for role, content in messages)
            text = text or "Esperando la respuesta de OpenCode…"
            buffer = transcript.get_buffer()
            if buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True) != text:
                buffer.set_text(text)
                GLib.idle_add(lambda: transcript.scroll_to_mark(buffer.get_insert(), 0, False, 0, 0) or False)

        background(lambda: gateway.messages(directory, session_id), complete)

    def change_project(combo):
        ui["directory"] = combo.get_active_id()
        ui["models_loaded_for"] = None
        ui["available_models"] = []
        ui["session"] = None
        ui["generation"] += 1
        ui["rows"] = ()
        ui["building"] = True
        for row in tray.get_children():
            tray.remove(row)
        ui["building"] = False
        transcript.get_buffer().set_text("Elige una conversación o escribe para empezar.")
        model_search.set_text("")
        custom_model.set_text("")
        show_selected_model()
        render_model_results()
        update_list()
        update_models()

    def select_catalog_model(_list, row):
        if row is None or not ui["directory"]:
            return
        ui["selected_models"][ui["directory"]] = row.model_id
        custom_model.set_text("")
        show_selected_model()
        model_popover.hide()

    def refresh_model_catalog(_button):
        ui["models_loaded_for"] = None
        update_models()

    def select_session(_tray, row):
        if ui["building"] or row is None:
            return
        ui["session"] = row.session_id
        ui["generation"] += 1
        transcript.get_buffer().set_text("Cargando conversación…")
        update_messages()

    def new_chat(_button):
        ui["session"] = None
        ui["generation"] += 1
        tray.unselect_all()
        transcript.get_buffer().set_text("Nueva conversación. Escribe tu primer mensaje.")
        entry.grab_focus()

    def send(_widget):
        directory, session_id, text = ui["directory"], ui["session"], entry.get_text()
        selected_model = custom_model.get_text().strip() or ui["selected_models"].get(directory, "default")
        generation = ui["generation"]
        if ui["sending"]:
            return
        if not directory:
            feedback.set_text("Abre OpenCode para poder enviar mensajes.")
            return
        if not text.strip():
            return
        ui["sending"] = True
        send_button.set_sensitive(False)
        feedback.set_text("Enviando…")

        def complete(created_id, error):
            ui["sending"] = False
            send_button.set_sensitive(True)
            if error:
                feedback.set_text(error)
                return
            entry.set_text("")
            feedback.set_text("Enviado. OpenCode está trabajando.")
            if ui["directory"] == directory and ui["generation"] == generation:
                ui["session"] = created_id
                ui["generation"] += 1
                ui["rows"] = ()
                update_list()
                update_messages()

        background(lambda: gateway.send(directory, session_id, text,
                                        None if selected_model == "default" else selected_model), complete)

    projects.connect("changed", change_project)
    provider_filter.connect("changed", render_model_results)
    model_search.connect("changed", render_model_results)
    model_results.connect("row-activated", select_catalog_model)
    model_popover.connect("show", lambda *_: model_search.grab_focus())
    refresh_models.connect("clicked", refresh_model_catalog)
    tray.connect("row-selected", select_session)
    new_button.connect("clicked", new_chat)
    send_button.connect("clicked", send)
    entry.connect("activate", send)

    def refresh():
        show_projects()
        if panel.get_visible():
            update_list()
            update_models()
            update_messages()
        return True

    GLib.timeout_add(2500, refresh)

    def toggle(_button):
        if panel.get_visible():
            panel.hide()
            return
        panel.show_all()
        x, y = pet_window.get_position()
        screen = pet_window.get_screen()
        monitor = screen.get_monitor_geometry(screen.get_monitor_at_window(pet_window.get_window()))
        width, height = panel.get_size()
        target_x = x + pet_window.get_size()[0] + 8
        if target_x + width > monitor.x + monitor.width:
            target_x = max(monitor.x, x - width - 8)
        panel.move(target_x, max(monitor.y, min(y, monitor.y + monitor.height - height)))
        refresh()
        entry.grab_focus()

    return toggle


def run_gui(state, image=None, cell_width=CELL_WIDTH, cell_height=CELL_HEIGHT,
            pet_name=None, pet_layout="atlas", look_image=None, look_counts=None):
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

    window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    window.set_title("OpenCode Pet")
    window.set_default_size(180, 236)
    window.set_decorated(False)
    window.set_keep_above(True)
    window.set_skip_taskbar_hint(True)
    window.set_app_paintable(True)
    screen = window.get_screen()
    visual = screen.get_rgba_visual()
    if visual:
        window.set_visual(visual)
    window.connect("destroy", Gtk.main_quit)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    window.add(box)
    canvas = Gtk.Image()
    canvas.set_size_request(180, 165)
    box.pack_start(canvas, True, True, 0)
    label = Gtk.Label(label=LABELS[state.status])
    label.set_margin_bottom(5)
    box.pack_start(label, False, False, 0)
    chat_button = Gtk.Button(label="✎  Chats")
    chat_button.set_tooltip_text("Escribir a OpenCode y ver conversaciones")
    buttons = Gtk.Box(spacing=2)
    box.pack_start(buttons, False, False, 0)
    buttons.pack_start(chat_button, True, True, 0)
    chat_button.connect("clicked", create_chat_panel(window, state, OpencodeGateway(state), Gtk, GLib))
    pet_button = Gtk.Button(label="Mascota")
    pet_button.set_tooltip_text("Importar o cambiar mascota")
    buttons.pack_start(pet_button, True, True, 0)

    sprite = {"image": image, "width": cell_width, "height": cell_height,
              "name": pet_name, "layout": pet_layout,
              "look_image": look_image, "look_counts": look_counts or {}}

    def select_sprite(slug):
        if slug:
            try:
                pixbuf, width, height, layout, _ = load_pet_path(pet_library() / slug, details=True)
                look_pixbuf, frames = load_look_sheet(pet_library() / slug)
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                error = Gtk.MessageDialog(transient_for=window, flags=0, message_type=Gtk.MessageType.ERROR,
                                          buttons=Gtk.ButtonsType.CLOSE, text="No se pudo cargar la mascota")
                error.format_secondary_text(str(exc))
                error.run()
                error.destroy()
                return
            sprite.update(image=pixbuf, width=width, height=height, name=slug, layout=layout,
                          look_image=look_pixbuf, look_counts=frames)
        else:
            sprite.update(image=None, width=CELL_WIDTH, height=CELL_HEIGHT, name=None, layout="static",
                          look_image=None, look_counts={})
        save_selected_pet(slug)

    def choose_image(_item):
        dialog = Gtk.FileChooserDialog(title="Importar mascota de ChatGPT/Codex", transient_for=window,
                                       action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Importar", Gtk.ResponseType.OK)
        image_filter = Gtk.FileFilter()
        image_filter.set_name("Sprites PNG o WebP")
        for pattern in ("*.png", "*.webp", "*.PNG", "*.WEBP"):
            image_filter.add_pattern(pattern)
        dialog.add_filter(image_filter)
        filename = dialog.get_filename() if dialog.run() == Gtk.ResponseType.OK else None
        dialog.destroy()
        if filename:
            try:
                slug, _ = import_pet(filename)
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                error = Gtk.MessageDialog(transient_for=window, flags=0, message_type=Gtk.MessageType.ERROR,
                                          buttons=Gtk.ButtonsType.CLOSE, text="No se pudo importar la mascota")
                error.format_secondary_text(str(exc))
                error.run()
                error.destroy()
                return
            select_sprite(slug)

    def choose_folder(_item):
        dialog = Gtk.FileChooserDialog(title="Importar animaciones con states.json", transient_for=window,
                                       action=Gtk.FileChooserAction.SELECT_FOLDER)
        dialog.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Importar", Gtk.ResponseType.OK)
        folder = dialog.get_filename() if dialog.run() == Gtk.ResponseType.OK else None
        dialog.destroy()
        if folder:
            try:
                slug, _ = import_pet(folder)
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                error = Gtk.MessageDialog(transient_for=window, flags=0, message_type=Gtk.MessageType.ERROR,
                                          buttons=Gtk.ButtonsType.CLOSE, text="No se pudo importar la carpeta")
                error.format_secondary_text(str(exc))
                error.run()
                error.destroy()
                return
            select_sprite(slug)

    def show_pets(button):
        menu = Gtk.Menu()
        import_item = Gtk.MenuItem(label="Importar PNG/WebP…")
        import_item.connect("activate", choose_image)
        menu.append(import_item)
        folder_item = Gtk.MenuItem(label="Importar carpeta animada…")
        folder_item.connect("activate", choose_folder)
        menu.append(folder_item)
        default_item = Gtk.MenuItem(label="Mascota original")
        default_item.connect("activate", lambda *_: select_sprite(None))
        menu.append(default_item)
        for slug, name in installed_pets():
            item = Gtk.MenuItem(label=f"{'✓ ' if slug == sprite['name'] else ''}{name}")
            item.connect("activate", lambda _item, selected=slug: select_sprite(selected))
            menu.append(item)
        menu.show_all()
        menu.popup_at_widget(button, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)

    pet_button.connect("clicked", show_pets)

    css = Gtk.CssProvider()
    css.load_from_data(b"window { background: transparent; } label { color: #ffffff; background: #20242c; border-radius: 12px; padding: 5px 8px; font: 11px sans-serif; }")
    window.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    label.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def popup(_widget, event):
        if event.button == 1:
            window.begin_move_drag(event.button, int(event.x_root), int(event.y_root), event.time)
        elif event.button == 3:
            menu = Gtk.Menu()
            quit_item = Gtk.MenuItem(label="Cerrar mascota")
            quit_item.connect("activate", lambda *_: Gtk.main_quit())
            menu.append(quit_item)
            menu.show_all()
            menu.popup_at_pointer(event)
        return True

    pointer = {"inside": False, "x": 90, "y": 82}

    def pointer_moved(_window, event):
        pointer.update(inside=0 <= event.x < 180 and 0 <= event.y < 165, x=event.x, y=event.y)
        return False

    def pointer_left(_window, _event):
        pointer["inside"] = False
        return False

    window.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.POINTER_MOTION_MASK |
                      Gdk.EventMask.LEAVE_NOTIFY_MASK)
    window.connect("button-press-event", popup)
    window.connect("motion-notify-event", pointer_moved)
    window.connect("leave-notify-event", pointer_left)

    tick = [0]
    phase = {"status": None, "layout": None, "since": monotonic()}
    activity = {"status": None, "since": monotonic()}
    motion = {"x": None, "name": None, "until": 0}

    def animate():
        tick[0] += 1
        status = state.status
        layout = sprite["layout"]
        now = monotonic()
        if status != activity["status"]:
            activity.update(status=status, since=now)
        visual = status
        if layout == "atlas":
            x, _ = window.get_position()
            if motion["x"] is not None and abs(x - motion["x"]) >= 2:
                motion.update(name="moving-right" if x > motion["x"] else "moving-left", until=now + 0.7)
            motion["x"] = x
            if status not in ("waiting", "blocked") and now < motion["until"]:
                visual = motion["name"]
            elif status == "ready" and now - activity["since"] < sum(ATLAS_ANIMATIONS["jumping"][1]) / 1000:
                visual = "celebrating"
            if visual == "idle" and pointer["inside"] and sprite["look_image"] is not None:
                direction = look_direction(pointer["x"], pointer["y"])
                if direction in sprite["look_counts"]:
                    visual = "look-" + direction
        if visual != phase["status"] or layout != phase["layout"]:
            phase.update(status=visual, layout=layout, since=now)
        reduced_motion = not Gtk.Settings.get_default().get_property("gtk-enable-animations")
        if sprite["image"] is not None:
            if visual.startswith("look-"):
                direction = visual[5:]
                row = LOOK_ROWS[direction]
                count = sprite["look_counts"][direction]
                frame = 0 if reduced_motion else int((now - phase["since"]) * 1000 // 140) % count
                frame_image = sprite["look_image"].new_subpixbuf(frame * 192, row * 208, 192, 208)
            else:
                row, frame = animation_frame(visual, (now - phase["since"]) * 1000,
                                             layout, reduced_motion)
                frame_image = sprite["image"].new_subpixbuf(frame * sprite["width"], row * sprite["height"],
                                                             sprite["width"], sprite["height"])
            canvas.set_from_pixbuf(frame_image.scale_simple(148, 160, GdkPixbuf.InterpType.NEAREST))
        else:
            canvas.set_from_pixbuf(pixbuf_from_svg(placeholder(status, 0 if reduced_motion else tick[0])))
        label.set_text(LABELS[state.status])
        return True

    GLib.timeout_add(50, animate)
    window.show_all()
    animate()
    Gtk.main()


def main():
    parser = argparse.ArgumentParser(description="Mascota flotante de OpenCode (Linux/GTK 3)")
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument("--install", action="store_true", help="Instala o actualiza el plugin global de OpenCode")
    commands.add_argument("--import-pet", metavar="ARCHIVO", help="Importa una mascota PNG/WebP o carpeta Codex")
    commands.add_argument("--list-pets", action="store_true", help="Lista las mascotas importadas")
    parser.add_argument("--pet", help="Mascota importada por nombre, carpeta Codex o spritesheet PNG/WebP")
    args = parser.parse_args()
    if args.install:
        try:
            target = install_plugin()
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        print(f"Plugin instalado en {target}. Reinicia OpenCode para activarlo.")
        return
    if args.import_pet:
        try:
            slug, target = import_pet(args.import_pet)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            parser.error(str(exc))
        print(f"Mascota '{slug}' importada en {target}. Aparecerá al iniciar la ventana.")
        return
    if args.list_pets:
        for slug, name in installed_pets():
            print(f"{slug}\t{name}")
        return
    backend = choose_window_backend(os.environ)
    if backend:
        os.environ["GDK_BACKEND"] = backend
    state = PetState()
    image = None
    cell_width, cell_height = CELL_WIDTH, CELL_HEIGHT
    layout = "static"
    look_image, look_counts = None, {}
    chosen = args.pet or selected_pet()
    slug = None
    if chosen:
        try:
            installed = {name for name, _ in installed_pets()}
            slug = chosen if chosen in installed else None
            if args.pet or slug:
                image, cell_width, cell_height, layout, _ = load_pet_path(
                    pet_library() / slug if slug else chosen, details=True)
                look_image, look_counts = load_look_sheet(pet_library() / slug if slug else chosen)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            if args.pet:
                parser.error(str(exc))
            slug = None
    try:
        server = ThreadingHTTPServer((HOST, PORT), create_handler(state))
    except OSError as exc:
        parser.error(f"No se pudo abrir {HOST}:{PORT}: {exc}")
    server.daemon_threads = True
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        run_gui(state, image, cell_width, cell_height, slug, layout, look_image, look_counts)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
