# Nautilus extension: create a file from a template and name it right away.
#
# Templates are read from the folder saved by `nautilus-new-document replace on`
# (~/.config/nautilus-new-named-document/templates-dir), otherwise from the
# XDG Templates folder (~/Šablóny, ~/Templates, ...).

import gettext
import os

from gi.repository import GObject, Gio, GLib, Nautilus

CONF = os.path.join(GLib.get_user_config_dir(), "nautilus-new-named-document", "templates-dir")

# Own strings: Slovak, Czech, English. Menu label prefers Nautilus's own translation.
STRINGS = {
    "sk": {
        "menu": "Nový dokument",
        "name": "Názov súboru:",
        "invalid": "Neplatný názov súboru: {}",
        "exists": "„{}“ už existuje.",
        "failed": "Nepodarilo sa vytvoriť „{}“:\n{}",
    },
    "cs": {
        "menu": "Nový dokument",
        "name": "Název souboru:",
        "invalid": "Neplatný název souboru: {}",
        "exists": "„{}“ již existuje.",
        "failed": "Nepodařilo se vytvořit „{}“:\n{}",
    },
    "en": {
        "menu": "New Document",
        "name": "File name:",
        "invalid": "Invalid file name: {}",
        "exists": "“{}” already exists.",
        "failed": "Could not create “{}”:\n{}",
    },
}


def _lang_strings():
    for lang in GLib.get_language_names():
        code = lang.split(".")[0].split("@")[0].split("_")[0]
        if code in STRINGS:
            return STRINGS[code]
    return STRINGS["en"]


T = _lang_strings()


def _menu_label():
    # Same wording Nautilus uses for its built-in menu, in whatever language it runs in
    label = gettext.dgettext("nautilus", "New _Document").replace("_", "")
    if label == "New Document":
        label = T["menu"]
    return label


def _templates_dir():
    home = os.path.realpath(os.path.expanduser("~"))
    try:
        with open(CONF, encoding="utf-8") as f:
            saved = f.read().strip()
        if saved and os.path.isdir(saved):
            return saved
    except OSError:
        pass
    d = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_TEMPLATES)
    if not d or os.path.realpath(d) == home:
        return None
    return d if os.path.isdir(d) else None


def _auto_replace():
    # Hide the built-in "New Document" menu for this user (unless they opted out).
    # Takes effect on the next Nautilus start; the package restarts Nautilus itself.
    if os.path.exists(CONF):
        return
    try:
        Gio.Subprocess.new(["nautilus-new-document", "auto"], Gio.SubprocessFlags.NONE)
    except GLib.Error:
        pass


class NewNamedDocument(GObject.GObject, Nautilus.MenuProvider):

    def __init__(self):
        super().__init__()
        _auto_replace()

    def get_background_items(self, *args):
        # Nautilus 4.x API: (current_folder); 3.0 API: (window, current_folder)
        folder = args[-1]
        tdir = _templates_dir()
        if not tdir or folder is None:
            return []
        location = folder.get_location()
        if location is None:
            return []
        submenu = self._build_menu(tdir, location, "root")
        if submenu is None:
            return []
        top = Nautilus.MenuItem(name="NewNamedDocument::top", label=_menu_label())
        top.set_submenu(submenu)
        return [top]

    def _build_menu(self, path, location, prefix):
        try:
            entries = sorted(
                (e for e in os.scandir(path) if not e.name.startswith(".")),
                key=lambda e: (not e.is_dir(), e.name.lower()),
            )
        except OSError:
            return None
        menu = Nautilus.Menu()
        count = 0
        for e in entries:
            ident = f"{prefix}/{e.name}"
            if e.is_dir():
                sub = self._build_menu(e.path, location, ident)
                if sub is None:
                    continue
                item = Nautilus.MenuItem(name=f"NewNamedDocument::{ident}", label=e.name)
                item.set_submenu(sub)
            elif e.is_file():
                label = os.path.splitext(e.name)[0] or e.name
                item = Nautilus.MenuItem(name=f"NewNamedDocument::{ident}", label=label)
                item.connect("activate", self._on_activate, location, e.path)
            else:
                continue
            menu.append_item(item)
            count += 1
        return menu if count else None

    def _on_activate(self, _item, location, template):
        self._ask_name(location, template, os.path.basename(template))

    def _ask_name(self, location, template, initial):
        proc = Gio.Subprocess.new(
            [
                "zenity", "--entry",
                f"--title={_menu_label()}",
                f"--text={T['name']}",
                f"--entry-text={initial}",
                "--width=400",
            ],
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE,
        )
        proc.communicate_utf8_async(None, None, self._on_name, (location, template))

    def _on_name(self, proc, result, data):
        location, template = data
        try:
            _ok, out, _err = proc.communicate_utf8_finish(result)
        except GLib.Error:
            return
        if proc.get_exit_status() != 0:  # Cancel / Esc
            return
        name = (out or "").strip()
        if not name:
            return
        if "/" in name or name in (".", ".."):
            self._error(T["invalid"].format(name), location, template, name)
            return
        dest = location.get_child(name)
        if dest.query_exists(None):
            self._error(T["exists"].format(name), location, template, name)
            return
        try:
            Gio.File.new_for_path(template).copy(dest, Gio.FileCopyFlags.NONE, None, None)
        except GLib.Error as err:
            self._error(T["failed"].format(name, err.message), location, template, name)

    def _error(self, text, location, template, retry_name):
        proc = Gio.Subprocess.new(
            ["zenity", "--error", f"--title={_menu_label()}", f"--text={text}"],
            Gio.SubprocessFlags.STDERR_SILENCE,
        )
        proc.wait_async(None, lambda p, r: (p.wait_finish(r), self._ask_name(location, template, retry_name)))
