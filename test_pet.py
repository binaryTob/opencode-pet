import json
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pet import (OpencodeGateway, PetState, choose_window_backend, create_handler, import_pet,
                 install_plugin, installed_pets, load_pet_path, pet_slug, selected_pet)


class PetStateTest(unittest.TestCase):
    def test_install_plugin_is_idempotent_and_preserves_other_plugins(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "plugins" / "pet.js"
            install_plugin(target)
            original = target.read_bytes()
            self.assertEqual(install_plugin(target), target)
            self.assertEqual(target.read_bytes(), original)
            target.write_text("// otro plugin\n")
            with self.assertRaisesRegex(ValueError, "no lo sobrescribí"):
                install_plugin(target)
            self.assertEqual(target.read_text(), "// otro plugin\n")

    def test_xwayland_backend_for_always_on_top(self):
        env = {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}
        self.assertEqual(choose_window_backend(env), "x11")
        self.assertIsNone(choose_window_backend({"XDG_SESSION_TYPE": "wayland"}))
        self.assertIsNone(choose_window_backend({"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}))
        self.assertIsNone(choose_window_backend({**env, "GDK_BACKEND": "wayland"}))

    def test_priority_replies_and_expiration(self):
        clock = [0]
        state = PetState(lambda: clock[0])
        self.assertEqual(state.status, "idle")
        state.update({"type": "session.busy", "sessionID": "a"})
        state.update({"type": "session.waiting", "sessionID": "b"})
        self.assertEqual(state.status, "waiting")
        state.update({"type": "session.busy", "sessionID": "b"})
        self.assertEqual(state.status, "running")
        state.update({"type": "session.error", "sessionID": "a"})
        self.assertEqual(state.status, "blocked")
        state.update({"type": "session.busy", "sessionID": "a"})
        state.update({"type": "session.idle", "sessionID": "a"})
        self.assertEqual(state.status, "ready")
        clock[0] = 13
        self.assertEqual(state.status, "running")
        state.update({"type": "session.deleted", "sessionID": "b"})
        self.assertEqual(state.status, "idle")

    def test_disconnected_projects_expire(self):
        clock = [0]
        state = PetState(lambda: clock[0])
        state.register("/work", "http://127.0.0.1:4096")
        self.assertEqual(state.projects()[0], ["/work"])
        clock[0] = 21
        self.assertEqual(state.projects()[0], [])
        self.assertIsNone(state.server("/work"))
        state.register("/work", "http://127.0.0.1:4096")
        self.assertEqual(state.server("/work"), "http://127.0.0.1:4096")

    def test_local_http_bridge_only_accepts_small_valid_events(self):
        state = PetState()
        server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(state))
        server.daemon_threads = True
        thread = Thread(target=server.serve_forever)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(Request(base + "/event", data=json.dumps({
                "type": "session.busy", "sessionID": "test"
            }).encode())) as response:
                self.assertEqual(response.status, 204)
            with urlopen(base + "/health") as response:
                self.assertEqual(json.load(response)["status"], "running")
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(base + "/event", data=b"not-json"))
            self.assertEqual(error.exception.code, 400)
            with urlopen(Request(base + "/register", data=json.dumps({
                "directory": "/work", "url": "http://127.0.0.1:4488"
            }).encode())) as response:
                self.assertEqual(response.status, 204)
            self.assertEqual(state.server("/work"), "http://127.0.0.1:4488")
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(base + "/register", data=json.dumps({
                    "directory": "/work", "url": "http://example.com:4488"
                }).encode()))
            self.assertEqual(error.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_gateway_creates_session_sends_prompt_and_reads_replies(self):
        calls = []

        class FakeOpencode(BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append(("GET", self.path, None))
                if self.path.startswith("/models?"):
                    body = [{"id": "own/custom", "label": "Modelo propio"}]
                elif self.path.startswith("/session/s-1/message?"):
                    body = [{"info": {"role": "user"}, "parts": [{"type": "text", "text": "hola"}]},
                            {"info": {"role": "assistant"}, "parts": [{"type": "text", "text": "¡Hola!"}]}]
                else:
                    body = [{"id": "s-1", "title": "Prueba"}, {"id": "child", "parentID": "s-1"}]
                self.reply(body)

            def do_POST(self):
                length = int(self.headers["Content-Length"])
                calls.append(("POST", self.path, json.loads(self.rfile.read(length))))
                self.reply({"id": "s-1"} if self.path.startswith("/session?") else None)

            def reply(self, data):
                body = json.dumps(data).encode() if data is not None else b""
                self.send_response(200 if body else 204)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOpencode)
        server.daemon_threads = True
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            state = PetState()
            state.register("/work", f"http://127.0.0.1:{server.server_port}")
            gateway = OpencodeGateway(state)
            self.assertEqual(len(gateway.sessions("/work")), 1)
            self.assertEqual(gateway.models("/work"), [{"id": "own/custom", "label": "Modelo propio"}])
            self.assertEqual(gateway.send("/work", None, "hola"), "s-1")
            self.assertEqual(gateway.send("/work", "s-1", "siguiente", "own/custom"), "s-1")
            self.assertEqual(gateway.messages("/work", "s-1"),
                             [("user", "hola"), ("assistant", "¡Hola!")])
            self.assertIn("directory=%2Fwork", calls[2][1])
            self.assertEqual(calls[3][2], {"parts": [{"type": "text", "text": "hola"}]})
            self.assertEqual(calls[4][2]["model"], {"providerID": "own", "modelID": "custom"})
            with self.assertRaisesRegex(ValueError, "20 000"):
                gateway.send("/work", "s-1", "x" * 20_001)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_codex_atlas_and_manifest_validation(self):
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 1536, 2288)
            image.fill(0)
            image.savev(str(root / "spritesheet.png"), "png", [], [])
            (root / "pet.json").write_text(json.dumps({
                "spriteVersionNumber": 2, "spritesheetPath": "spritesheet.png"
            }))
            _, width, height = load_pet_path(root)
            self.assertEqual((width, height), (192, 208))
            (root / "pet.json").write_text(json.dumps({
                "spriteVersionNumber": 1, "spritesheetPath": "spritesheet.png"
            }))
            with self.assertRaisesRegex(ValueError, "spriteVersionNumber"):
                load_pet_path(root)
            v1 = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 1536, 1872)
            v1.fill(0)
            v1.savev(str(root / "spritesheet.png"), "png", [], [])
            _, width, height = load_pet_path(root)
            self.assertEqual((width, height), (192, 208))
            (root / "pet.json").write_text('{"spritesheetPath": 42}')
            with self.assertRaisesRegex(ValueError, "spritesheetPath"):
                load_pet_path(root)

    def test_import_user_sprite_keeps_it_local_and_selectable(self):
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library, settings = root / "pets", root / "config" / "settings.json"
            image = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 1536, 2288)
            image.fill(0x40a0ffff)
            source = root / "gatito.png"
            image.savev(str(source), "png", [], [])
            slug, folder = import_pet(source, library, settings)
            self.assertEqual(slug, "gatito")
            self.assertEqual(selected_pet(settings), "gatito")
            self.assertEqual((folder / "spritesheet.png").read_bytes(), source.read_bytes())
            self.assertEqual(json.loads((folder / "pet.json").read_text())["spriteVersionNumber"], 2)
            self.assertEqual(installed_pets(library), [("gatito", "gatito")])
            self.assertEqual(import_pet(source, library, settings)[0], "gatito")
            image.fill(0xff80ffff)
            image.savev(str(source), "png", [], [])
            self.assertEqual(import_pet(source, library, settings)[0], "gatito-2")
            self.assertEqual(pet_slug("Niño 🐱"), "nino")

    def test_import_eight_frame_strip_and_single_image(self):
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library, settings = root / "pets", root / "settings.json"
            strip = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 2206, 713)
            strip.fill(0)
            for frame in range(8):
                left = round(frame * 2206 / 8)
                strip.new_subpixbuf(left + 20, 220, 200, 260).fill(0x3399ffff)
            strip_path = root / "my-animated-pet.png"
            strip.savev(str(strip_path), "png", [], [])
            atlas, width, height, layout, rows = load_pet_path(strip_path, details=True)
            self.assertEqual((atlas.get_width(), atlas.get_height(), width, height, layout, rows),
                             (1536, 1872, 192, 208, "strip", 9))
            slug, folder = import_pet(strip_path, library, settings)
            self.assertEqual(json.loads((folder / "pet.json").read_text())["layout"], "strip")
            self.assertEqual(load_pet_path(folder, details=True)[3], "strip")
            self.assertEqual(slug, "my-animated-pet")

            still = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 1205, 1305)
            still.fill(0)
            still.new_subpixbuf(200, 300, 800, 700).fill(0xffbb33ff)
            still_path = root / "my-still-pet.png"
            still.savev(str(still_path), "png", [], [])
            self.assertEqual(load_pet_path(still_path, details=True)[3], "static")
            _, folder = import_pet(still_path, library, settings)
            self.assertEqual(json.loads((folder / "pet.json").read_text())["layout"], "static")

            strip.fill(0x3399ffff)
            strip.savev(str(strip_path), "png", [], [])
            self.assertEqual(load_pet_path(strip_path, details=True)[3], "static")


if __name__ == "__main__":
    unittest.main()
