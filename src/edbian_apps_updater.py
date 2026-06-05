#!/usr/bin/env python3

import os
import json
import subprocess
import threading
import gi
import shutil
import sys
import requests

print("dpkg-query path:", shutil.which("dpkg-query"))

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

# =========================
# 📁 BASE PATH
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# =========================
# 📁 PATHS INTELIGENTES
# =========================
DEV_CONFIG = os.path.join(BASE_DIR, "packages.json")
DEV_ICON = os.path.join(BASE_DIR, "edbian-apps-updater.png")

SYSTEM_CONFIG = "/usr/share/edbian-apps-updater/packages.json"
SYSTEM_ICON = "/usr/share/icons/hicolor/128x128/apps/edbian-apps-updater.png"

# Config
if os.path.exists(SYSTEM_CONFIG):
    CONFIG_FILE = SYSTEM_CONFIG
else:
    CONFIG_FILE = DEV_CONFIG

# Icono
if os.path.exists(SYSTEM_ICON):
    ICON_PATH = SYSTEM_ICON
else:
    ICON_PATH = DEV_ICON

VERSION_FILE = os.path.expanduser("~/.pkg_versions.json")

# =========================
# 📦 LOAD DATA
# =========================
if not os.path.exists(CONFIG_FILE):
    print(f"ERROR: No se encuentra {CONFIG_FILE}")
    sys.exit(1)

with open(CONFIG_FILE, "r") as f:
    packages = json.load(f)

# =========================
# 🔧 FUNCIONES VERSIONES
# =========================
def get_installed_version(pkg_name):
    try:
        result = subprocess.run(
            ["dpkg-query", "-W", "-f=${Status} ${Version}", pkg_name],
            capture_output=True,
            text=True,
            check=True
        )

        output = result.stdout.strip()

        if output.startswith("install ok installed"):
            return output.split()[-1]

        return None

    except subprocess.CalledProcessError:
        return None


def normalize_version(v):
    """
    Limpia versiones:
    v1.2.3 -> 1.2.3
    """
    if not v:
        return "0"

    v = v.lower().replace("v", "").strip()
    return v


def version_tuple(v):
    """
    Convierte versión a tupla comparable.
    """
    v = normalize_version(v)

    parts = []

    for p in v.replace("-", ".").split("."):
        try:
            parts.append(int(p))
        except:
            parts.append(0)

    return tuple(parts)


# =========================
# 🪟 MAIN WINDOW
# =========================
class UpdaterWindow(Gtk.Window):

    def __init__(self):
        Gtk.Window.__init__(self, title="Edbian Apps Updater")

        self.set_border_width(10)
        self.set_default_size(700, 400)

        # 🖼️ ICONO
        try:
            if ICON_PATH and os.path.exists(ICON_PATH):
                self.set_icon_from_file(ICON_PATH)
        except Exception as e:
            print("No se pudo cargar icono:", e)

        self.stop_event = threading.Event()

        # =========================
        # LAYOUT
        # =========================
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(vbox)

        # =========================
        # LISTA PAQUETES
        # =========================
        self.liststore = Gtk.ListStore(str, str, str)

        for pkg in packages:

            debian_name = pkg.get("debian_name", pkg["name"])

            # ✅ MOSTRAR VERSIÓN REAL INSTALADA
            current_version = get_installed_version(debian_name)

            if current_version is None:
                current_version = "No instalado"

            self.liststore.append([
                pkg["name"],
                current_version,
                "Pendiente"
            ])

        treeview = Gtk.TreeView(model=self.liststore)

        for i, col_title in enumerate([
            "Paquete",
            "Versión instalada",
            "Estado"
        ]):
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(col_title, renderer, text=i)
            treeview.append_column(column)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.add(treeview)

        vbox.pack_start(scrolled, True, True, 0)

        # =========================
        # PROGRESS BAR
        # =========================
        self.progress = Gtk.ProgressBar()
        vbox.pack_start(self.progress, False, False, 0)

        # =========================
        # BOTONES
        # =========================
        hbox = Gtk.Box(spacing=10)

        self.button_start = Gtk.Button(label="Actualizar paquetes")
        self.button_start.connect("clicked", self.start_update)

        hbox.pack_start(self.button_start, True, True, 0)

        self.button_cancel = Gtk.Button(label="Cancelar")
        self.button_cancel.connect("clicked", self.cancel_update)

        hbox.pack_start(self.button_cancel, True, True, 0)

        vbox.pack_start(hbox, False, False, 0)

        # =========================
        # LOGS
        # =========================
        self.logs = Gtk.TextView()

        self.logs.set_editable(False)
        self.logs.set_wrap_mode(Gtk.WrapMode.WORD)

        self.log_buffer = self.logs.get_buffer()

        scrolled_logs = Gtk.ScrolledWindow()
        scrolled_logs.set_vexpand(True)
        scrolled_logs.add(self.logs)

        vbox.pack_start(scrolled_logs, True, True, 0)

    # =========================
    # LOGS
    # =========================
    def log(self, message):
        GLib.idle_add(self._append_log, message)

    def _append_log(self, message):

        end_iter = self.log_buffer.get_end_iter()

        self.log_buffer.insert(
            end_iter,
            message + "\n"
        )

        self.logs.scroll_to_iter(
            self.log_buffer.get_end_iter(),
            0.0,
            True,
            0.0,
            1.0
        )

    # =========================
    # CANCELAR
    # =========================
    def cancel_update(self, button):
        self.stop_event.set()
        self.log("Cancelando actualizaciones...")

    # =========================
    # START
    # =========================
    def start_update(self, button):

        self.button_start.set_sensitive(False)

        threading.Thread(
            target=self.update_packages,
            daemon=True
        ).start()

    # =========================
    # UPDATE PACKAGES
    # =========================
    def update_packages(self):

        total = len(packages)

        for i, pkg in enumerate(packages):

            if self.stop_event.is_set():
                self.log("Actualización cancelada por usuario")
                break

            name = pkg["name"]
            debian_name = pkg.get("debian_name", name)

            # =========================
            # VERSIÓN INSTALADA REAL
            # =========================
            installed_version = get_installed_version(debian_name)
            is_new_install = installed_version is None

            if is_new_install:
                installed_version = "0"

            # =========================
            # OBTENER RELEASE GITHUB
            # =========================
            latest_version, asset_file = self.download_asset(pkg)

            if latest_version is None:

                self.liststore[i][2] = "Error"

                self.log(f"No se pudo obtener release de {name}")

                continue

            if is_new_install:
                self.log(
                    f"{name} no está instalado. Se instalará la versión {latest_version}"
                )
            else:
                self.log(
                f"{name} -> instalada: {installed_version} | github: {latest_version}"
            )

            # =========================
            # NO REINSTALAR SI ES IGUAL
            # =========================
            if not is_new_install and \
                version_tuple(installed_version) >= version_tuple(latest_version):

                self.liststore[i][2] = "Ya actualizado"

                self.log(f"{name} ya está actualizado")

                GLib.idle_add(
                    self.progress.set_fraction,
                    (i + 1) / total
                )

                continue

            # =========================
            # DESCARGA
            # =========================
            self.liststore[i][2] = "Descargando..."

            self.log(f"Descargando {name}")

            if not asset_file:

                self.liststore[i][2] = "Error"

                self.log(f"No se encontró asset para {name}")

                continue

            # =========================
            # INSTALACIÓN
            # =========================
            self.liststore[i][2] = "Instalando..."

            self.log(f"Instalando {asset_file}")

            success = self.install_package(asset_file)

            # =========================
            # ACTUALIZAR TABLA
            # =========================
            if success:

                new_version = get_installed_version(debian_name)

                if new_version:
                    self.liststore[i][1] = new_version

                self.liststore[i][2] = "Instalado"

                if is_new_install:
                    self.log(f"{name} instalado correctamente")
                else:
                    self.log(f"{name} actualizado correctamente")

            else:

                self.liststore[i][2] = "Error"

            GLib.idle_add(
                self.progress.set_fraction,
                (i + 1) / total
            )

        GLib.idle_add(self.button_start.set_sensitive, True)

        self.show_summary()

    # =========================
    # INSTALL PACKAGE
    # =========================
    def install_package(self, file_path):

        try:

            subprocess.run(
                ["pkexec", "dpkg", "-i", file_path],
                check=True
            )

            subprocess.run(
                ["pkexec", "apt-get", "-f", "install", "-y"],
                check=True
            )

            return True

        except subprocess.CalledProcessError as e:

            self.log(f"Error instalación: {e}")

            return False

    # =========================
    # DOWNLOAD ASSET
    # =========================
    def download_asset(self, pkg):

        try:

            url = f"https://api.github.com/repos/{pkg['repo']}/releases/latest"

            r = requests.get(url)

            r.raise_for_status()

            data = r.json()

            # VERSION GITHUB
            latest_version = data.get("tag_name", "0")

            for asset in data.get("assets", []):

                if pkg["asset_pattern"] in asset["name"]:

                    tmp_file = f"/tmp/{asset['name']}"

                    self.log(f"Descargando asset: {asset['name']}")

                    with requests.get(
                        asset["browser_download_url"],
                        stream=True
                    ) as resp:

                        with open(tmp_file, "wb") as f:
                            shutil.copyfileobj(resp.raw, f)

                    return latest_version, tmp_file

            return latest_version, None

        except Exception as e:

            self.log(f"Error descargando asset: {e}")

            return None, None

    # =========================
    # SUMMARY
    # =========================
    def show_summary(self):

        dialog = Gtk.MessageDialog(
            parent=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Actualización finalizada"
        )

        dialog.format_secondary_text(
            "Proceso completado."
        )

        dialog.run()
        dialog.destroy()


# =========================
# START GTK
# =========================
win = UpdaterWindow()

win.connect("destroy", Gtk.main_quit)

win.show_all()

Gtk.main()
