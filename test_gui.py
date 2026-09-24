"""Exercise the real GTK model picker under a display (xvfb-run in CI)."""

import unittest

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from pet import PetState, create_chat_panel


def widgets(widget):
    yield widget
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            yield from widgets(child)


class Gateway:
    def __init__(self):
        self.sent = []

    def sessions(self, _directory):
        return []

    def messages(self, _directory, _session):
        return []

    def models(self, _directory):
        models = [{"id": f"own/model-{number}", "label": f"My provider · Model {number}",
                   "providerID": "own", "providerName": "My provider", "modelName": f"Model {number}"}
                  for number in range(250)]
        models.append({"id": "local/llama", "label": "Local · Llama",
                       "providerID": "local", "providerName": "Local", "modelName": "Llama"})
        return models

    def send(self, _directory, _session, _text, model):
        self.sent.append(model)
        return "session-1"


class ModelPickerTest(unittest.TestCase):
    def test_search_and_filter_select_a_model_for_the_prompt(self):
        gateway = Gateway()
        state = PetState()
        state.register("/demo", "http://127.0.0.1:45818")
        pet = Gtk.Window(title="Picker test pet")
        pet.show_all()
        toggle = create_chat_panel(pet, state, gateway, Gtk, GLib)
        failures = []
        phase = [0]

        def exercise():
            try:
                panel = next(window for window in Gtk.Window.list_toplevels()
                             if window.get_title() == "Chats · OpenCode Pet")
                button = next(widget for widget in widgets(panel) if isinstance(widget, Gtk.MenuButton))
                prompt = next(widget for widget in widgets(panel)
                              if isinstance(widget, Gtk.Entry) and
                              widget.get_placeholder_text() == "Escribe a OpenCode…")
                if phase[0] == 0:
                    popover = button.get_popover()
                    if not popover.get_visible():
                        button.clicked()
                    count = next(widget for widget in widgets(popover)
                                 if isinstance(widget, Gtk.Label) and "modelos" in widget.get_text())
                    if "251 modelos" not in count.get_text():
                        return True  # Wait for the background catalog request.
                    search = next(widget for widget in widgets(popover) if isinstance(widget, Gtk.SearchEntry))
                    assert popover.get_child().get_visible() and search.get_visible(), \
                        "El selector existe pero su contenido no se muestra"
                    search.set_text("model-249")
                    results = next(widget for widget in widgets(popover) if isinstance(widget, Gtk.ListBox))
                    rows = results.get_children()
                    assert len(rows) == 1 and rows[0].model_id == "own/model-249", rows
                    results.emit("row-activated", rows[0])
                    prompt.set_text("Hello")
                    prompt.emit("activate")
                    phase[0] = 1
                    return True
                if phase[0] == 1:
                    if gateway.sent != ["own/model-249"]:
                        return True
                    button.clicked()
                    popover = button.get_popover()
                    search = next(widget for widget in widgets(popover) if isinstance(widget, Gtk.SearchEntry))
                    search.set_text("")
                    provider = next(widget for widget in widgets(popover) if isinstance(widget, Gtk.ComboBoxText))
                    provider.set_active_id("local")
                    results = next(widget for widget in widgets(popover) if isinstance(widget, Gtk.ListBox))
                    rows = results.get_children()
                    assert len(rows) == 1 and rows[0].model_id == "local/llama", rows
                    results.emit("row-activated", rows[0])
                    prompt.set_text("Again")
                    prompt.emit("activate")
                    phase[0] = 2
                    return True
                if gateway.sent == ["own/model-249", "local/llama"]:
                    Gtk.main_quit()
                    return False
            except Exception as error:
                failures.append(error)
                Gtk.main_quit()
                return False
            return True

        GLib.timeout_add(100, lambda: toggle(None) or False)
        GLib.timeout_add(1000, exercise)
        GLib.timeout_add(6000, lambda: Gtk.main_quit() or False)
        Gtk.main()
        for window in Gtk.Window.list_toplevels():
            window.destroy()
        if failures:
            raise failures[0]
        self.assertEqual(gateway.sent, ["own/model-249", "local/llama"])


if __name__ == "__main__":
    unittest.main()
