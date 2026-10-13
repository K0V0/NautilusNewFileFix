# How nautilus-new-named-document works

This explains how `build/nautilus-new-file-fix_1.2.0_all.deb` is built. Its
contents are unpacked in `package/`, and `./build.sh` turns them back into a `.deb`.

## The problem it solves

In GNOME Files (Nautilus), right-click → **New Document → *template*** creates a
file named after the template (e.g. `Text.txt`). You then have to find it and
rename it. This package swaps in its own **New Document** submenu that **asks for
the name first** and then creates the file.

## Repository layout

```
build.sh                         # builds package/ into build/<name>_<version>_all.deb
build/                           # the original built .deb
package/                         # the exact tree that goes into the .deb
├── DEBIAN/                      # package metadata + maintainer scripts (not installed as files)
│   ├── control                  # name, version, dependencies, description
│   ├── postinst                 # runs after install/upgrade
│   ├── prerm                    # runs before removal
│   └── postrm                   # runs after removal/purge
└── usr/
    ├── bin/nautilus-new-document                              # small helper CLI (shell)
    ├── share/nautilus-python/extensions/new_named_document.py # the actual Nautilus extension
    └── share/doc/nautilus-new-named-document/copyright
```

Anything under `package/` except `DEBIAN/` is copied to `/` when you install,
so `package/usr/bin/x` ends up at `/usr/bin/x`.

## The two key ideas

### 1. Nautilus Python extensions

`python3-nautilus` (nautilus-python) loads every `.py` file from
`/usr/share/nautilus-python/extensions/` (system-wide) and
`~/.local/share/nautilus-python/extensions/` (per user) when Nautilus starts.
A class that subclasses `GObject.GObject` and `Nautilus.MenuProvider` can add items
to the right-click menus:

- `get_file_items(files)`: menu for selected files (not used here)
- `get_background_items(folder)`: menu for right-clicking **empty space** in a folder (this is the one used here)

### 2. Hiding the built-in "New Document" menu

Nautilus has no setting to turn off its own **New Document** menu. But it hides
the menu by itself when the **XDG Templates folder is the same as `$HOME`**. It
does that so it won't list your whole home folder as templates.

The package uses that rule:

1. It saves the real Templates folder (e.g. `~/Šablóny` or `~/Templates`) into
   `~/.config/nautilus-new-named-document/templates-dir`.
2. It points the XDG Templates folder at `$HOME`
   (`xdg-user-dirs-update --set TEMPLATES "$HOME"`, which edits `~/.config/user-dirs.dirs`),
   so the built-in menu disappears.
3. The extension reads templates from the saved folder and builds its own menu.

Uninstalling reverses this. **Side effect:** while the package is installed, other
apps that read the XDG Templates folder (e.g. LibreOffice, other file managers) see
`$HOME` as the Templates folder.

## Component by component

### `DEBIAN/control`

Package metadata. Note that the **package name** is `nautilus-new-named-document`,
even though the original `.deb` file is named `nautilus-new-file-fix_…`.
`build.sh` names its output from the package name, so a rebuild produces
`nautilus-new-named-document_1.2.0_all.deb`.

Dependencies and why each is needed:

| Dependency | Used for |
|---|---|
| `python3-nautilus (>= 4.0)` | loads the Python extension into Nautilus |
| `zenity` | the "File name:" input dialog and error dialogs |
| `xdg-user-dirs` | `xdg-user-dir` / `xdg-user-dirs-update` to read/change the Templates folder |
| `libglib2.0-bin` | `gdbus`, to tell Nautilus to quit/start |
| `procps` | `ps`, `pgrep`, `pkill` in the maintainer scripts |

### `usr/share/nautilus-python/extensions/new_named_document.py`: the extension

Runs **inside the Nautilus process**, as the logged-in user.

Flow:

1. **On load** (`__init__` → `_auto_replace()`, line 74): if the user has no
   `templates-dir` config yet, it runs `nautilus-new-document auto`. This covers
   users who did not exist or had no home folder when the package was installed.
   The change only takes effect the next time Nautilus starts.
2. **Right-click on empty space** → `get_background_items()` (line 91):
   - `_templates_dir()` (line 59) picks the folder: first the saved one from the
     config file, otherwise the XDG Templates folder. It returns nothing if that
     folder is `$HOME`, so it won't list your home folder.
   - `_build_menu()` (line 107) walks the folder **recursively**: sub-folders become
     submenus, files become items with the extension removed from the label (`Text.txt` → "Text").
     Hidden files are skipped. Folders come first, then everything is sorted by name
     ignoring case. Empty folders are left out.
   - The top item's label is Nautilus's own translation of "New _Document" via
     `gettext.dgettext("nautilus", …)`, so it matches the language Nautilus runs in.
     If there's no translation, it uses the built-in `STRINGS` table (sk / cs / en).
3. **Click on a template** → `_ask_name()` starts
   `zenity --entry` **asynchronously** (`Gio.Subprocess` + `communicate_utf8_async`),
   so Nautilus doesn't freeze while the dialog is open. The field is pre-filled with the
   template's file name.
4. **Dialog closed** → `_on_name()` (line 151):
   - Cancel/Esc (non-zero exit) or an empty name → does nothing.
   - The name contains `/`, or is `.` or `..` → error.
   - The target already exists → error (it never overwrites).
   - Otherwise `Gio.File.copy(template → folder/name)`. Nautilus notices the new file by itself.
5. **Errors** → `_error()` (line 174) shows `zenity --error`, then **opens the name
   dialog again** with what you typed, so you can fix it.

Why use Gio instead of `shutil`/`os`? `location` is a `Gio.File`, so this also works
in non-local folders that Nautilus can browse (SFTP, SMB, MTP…).

### `usr/bin/nautilus-new-document`: helper CLI

A POSIX `sh` script that turns the menu switch on or off for **one user**.
Its state is kept in `~/.config/nautilus-new-named-document/`:

| File | Meaning |
|---|---|
| `templates-dir` | holds the real Templates path; if it exists, the menu has been replaced |
| `keep-builtin` | the user chose to keep the built-in menu; `auto` will not switch it again |

Commands:

| Command | What it does |
|---|---|
| `nautilus-new-document auto` | used by the package and the extension: switches over unless `keep-builtin` exists. Never fails. |
| `nautilus-new-document replace on` | switches over and restarts Files |
| `nautilus-new-document replace off` | restores the Templates folder, creates `keep-builtin`, restarts Files |
| `nautilus-new-document replace status` | shows the current state |

`do_on` refuses to switch if Templates is already `$HOME` or the folder doesn't exist,
because there would be nothing to save. The `replace` commands refuse to run as root,
because they must change the calling user's own `user-dirs.dirs`.

"Restart Files" means sending a D-Bus `quit` action to `org.gnome.Nautilus`. The next
time you open Files, it starts again and loads the new state.

### Maintainer scripts (`DEBIAN/postinst`, `prerm`, `postrm`)

These run **as root** during `apt`/`dpkg` operations. The first argument tells them
which operation is running (`configure`, `remove`, `purge`, `upgrade`…).

All three scripts contain their own copies of these helpers:

- `for_each_user CMD`: runs CMD for every real login user (UID 1000–59999 with an existing home folder).
- `as_user user uid home CMD…`: runs a command as that user with a clean environment
  that still reaches their D-Bus session bus (`/run/user/<uid>/bus`).
  Without this, `gdbus` and `xdg-user-dirs-update` would act on root's session or files.
- `restart_nautilus`: for every user running Nautilus:
  1. Ask it to `quit` via D-Bus.
  2. Wait up to 5 s for it to exit (`pgrep` loop).
  3. If it's still running, `pkill -TERM` it.
  4. Send a D-Bus `Ping` to `org.gnome.Nautilus`. D-Bus **activation** then starts
     Nautilus again in the background with no window, so the desktop and other Nautilus
     features keep working.

What each script does:

| Script | When | Action |
|---|---|---|
| `postinst` | `configure` (install or upgrade) | `nautilus-new-document auto` for each user, then restart Nautilus |
| `prerm` | `remove` only (**not** on upgrade) | for each user: restore the saved Templates folder and delete the config folder |
| `postrm` | `remove` or `purge` | restart Nautilus so the built-in menu returns and the extension is unloaded |

`prerm` skips upgrades on purpose. During an upgrade the old version's `prerm` runs
with `upgrade`, and restoring the folder there would undo the switch for no reason.

## Building

```sh
./build.sh
# → build/nautilus-new-named-document_<version>_all.deb
```

`build.sh` sets the file permissions explicitly (git doesn't keep every mode bit)
and uses `dpkg-deb --root-owner-group`, so the files are owned by `root:root`
inside the package. I checked that the rebuilt package has the same contents as
the original `.deb`.

Install / remove:

```sh
sudo apt install ./build/nautilus-new-named-document_1.2.0_all.deb
sudo apt remove nautilus-new-named-document
```

## Making changes

**Faster loop while working on the extension.** You don't need to reinstall each
time. Copy the `.py` into your user extension folder and restart Files:

```sh
mkdir -p ~/.local/share/nautilus-python/extensions
cp package/usr/share/nautilus-python/extensions/new_named_document.py ~/.local/share/nautilus-python/extensions/
nautilus -q; nautilus &        # run in a terminal to see Python errors / print() output
```

If the package is installed at the same time, both copies load and you get two
menus. Uninstall the package, or test with the system copy instead
(`sudo cp … /usr/share/nautilus-python/extensions/`).

**Ideas and where to make them:**

- *Add a language*: add an entry to `STRINGS` in the `.py`. The key is the language
  code (`de`, `pl`, …).
- *Pre-select only the base name in the dialog* (so typing replaces `Text` but keeps
  `.txt`): zenity can't do this. You would need a GTK dialog instead, which is more
  work inside Nautilus 4 / GTK4.
- *Open the new file right after it's created*: after a successful copy in
  `_on_name`, call `Gio.AppInfo.launch_default_for_uri(dest.get_uri(), None)`.
- *Add a "Empty file" item when there are no templates*: in `get_background_items`,
  add a menu item that creates the file with `dest.create(...)` instead of copying.
- *Remove the copied helpers*: the helper functions are repeated in all three
  maintainer scripts. You could move them into one file, e.g.
  `/usr/lib/nautilus-new-named-document/common.sh`, and `.` (source) it. But
  `postrm` runs after the package's files are deleted, so it would still need its
  own copy of `restart_nautilus`.

**Releasing a new version:** bump `Version:` in `package/DEBIAN/control`, then run
`./build.sh`. apt treats a package with the same version as the installed one as
already installed.

## Troubleshooting

- *No menu at all*: run `nautilus-new-document replace status`. Check that the
  templates folder has files in it. Run Nautilus from a terminal (`nautilus -q; nautilus`)
  and look for Python tracebacks.
- *Two "New Document" menus*: Files hasn't been restarted since the switch. Run
  `nautilus -q`.
- *Built-in menu wanted back while keeping the package*: `nautilus-new-document replace off`.
