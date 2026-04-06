#!/usr/bin/env python3
import os
import json
import subprocess
import threading
import gi
import shutil
import sys

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, GObject

CONFIG_FILE = "/usr/share/edbian-apps-updater/packages.json"
VERSION_FILE = os.path.expanduser("~/.pkg_versions.json")  # Guardado en home

# Cargar versiones previas
if os.path.exists(VERSION_FILE):
    with open(VERSION_FILE, "r") as f:
        installed_versions = json.load(f)
else:
    installed_versions = {}

with open(CONFIG_FILE, "r") as f:
    packages = json.load(f)

def get_installed_version(pkg_name):
    """Devuelve la versión instalada de un paquete Debian"""
    try:
        result = subprocess.run(
            ["dpkg-query", "-W", "-f=${Version}", pkg_name],
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None

def version_tuple(v):
    """Convierte versión tipo v2.0.0-1 a tupla (2,0,0,1) para comparación"""
    v = v.replace("v", "")
    parts = []
    for p in v.replace("-", ".").split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)

class UpdaterWindow(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self, title="Edbian Apps Updater")
        self.set_border_width(10)
        self.set_default_size(700, 400)

        self.stop_event = threading.Event()
        self.rollback_list = []

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(vbox)

        # Lista de paquetes
        self.liststore = Gtk.ListStore(str, str, str)
        for pkg in packages:
            debian_name = pkg.get("debian_name", pkg["name"])
            current = get_installed_version(debian_name) or installed_versions.get(pkg["name"], "0.0.0")
            self.liststore.append([pkg["name"], current, "Pendiente"])

        treeview = Gtk.TreeView(model=self.liststore)
        for i, col_title in enumerate(["Paquete", "Versión instalada", "Estado"]):
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(col_title, renderer, text=i)
            treeview.append_column(column)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.add(treeview)
        vbox.pack_start(scrolled, True, True, 0)

        # Barra de progreso
        self.progress = Gtk.ProgressBar()
        vbox.pack_start(self.progress, False, False, 0)

        # Botones
        hbox = Gtk.Box(spacing=10)
        self.button_start = Gtk.Button(label="Actualizar paquetes")
        self.button_start.connect("clicked", self.start_update)
        hbox.pack_start(self.button_start, True, True, 0)

        self.button_cancel = Gtk.Button(label="Cancelar")
        self.button_cancel.connect("clicked", self.cancel_update)
        hbox.pack_start(self.button_cancel, True, True, 0)

        vbox.pack_start(hbox, False, False, 0)

        # Logs
        self.logs = Gtk.TextView()
        self.logs.set_editable(False)
        self.logs.set_wrap_mode(Gtk.WrapMode.WORD)
        self.log_buffer = self.logs.get_buffer()
        scrolled_logs = Gtk.ScrolledWindow()
        scrolled_logs.set_vexpand(True)
        scrolled_logs.add(self.logs)
        vbox.pack_start(scrolled_logs, True, True, 0)

    def log(self, message):
        GLib.idle_add(self._append_log, message)

    def _append_log(self, message):
        end_iter = self.log_buffer.get_end_iter()
        self.log_buffer.insert(end_iter, message + "\n")
        self.logs.scroll_to_iter(self.log_buffer.get_end_iter(), 0.0, True, 0.0, 1.0)

    def cancel_update(self, button):
        self.stop_event.set()
        self.log("Cancelando actualizaciones...")

    def start_update(self, button):
        self.button_start.set_sensitive(False)
        threading.Thread(target=self.update_packages).start()

    def update_packages(self):
        total = len(packages)
        for i, pkg in enumerate(packages):
            if self.stop_event.is_set():
                self.log("Actualización cancelada por usuario")
                break

            name = pkg["name"]
            debian_name = pkg.get("debian_name", name)
            installed = get_installed_version(debian_name) or installed_versions.get(name, "0.0.0")
            self.liststore[i][2] = "Comprobando..."
            self.log(f"Comprobando {name} -> instalado: {installed}")

            try:
                latest = self.get_latest_version(pkg["repo"])
            except Exception as e:
                self.liststore[i][2] = "Error"
                self.log(f"No se pudo obtener versión para {name}: {e}")
                continue

            if version_tuple(latest) <= version_tuple(installed):
                self.liststore[i][2] = "Ya actualizado"
                self.log(f"{name} ya actualizado")
                continue

            self.liststore[i][2] = "Descargando..."
            self.log(f"Descargando {name}")
            asset_file = self.download_asset(pkg)
            if not asset_file:
                self.liststore[i][2] = "Error"
                continue

            self.liststore[i][2] = "Instalando..."
            self.log(f"Instalando {asset_file}")
            success = self.install_package(asset_file)
            if success:
                self.rollback_list.append(debian_name)
                installed_versions[name] = latest
                self.liststore[i][1] = latest
                self.liststore[i][2] = "Actualizado"
            else:
                self.liststore[i][2] = "Error"
                self.log(f"Error instalando {name}")

            GLib.idle_add(self.progress.set_fraction, (i+1)/total)

        # Guardar versiones
        try:
            with open(VERSION_FILE, "w") as f:
                json.dump(installed_versions, f, indent=2)
            self.log(f"Archivo de versiones actualizado en {VERSION_FILE}")
        except PermissionError:
            self.log("No se pudo guardar el archivo de versiones (permiso denegado)")

        self.show_summary()

    def get_latest_version(self, repo):
        import requests
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        r = requests.get(url)
        r.raise_for_status()
        data = r.json()
        return data["tag_name"]

    def download_asset(self, pkg):
        import requests
        try:
            url = f"https://api.github.com/repos/{pkg['repo']}/releases/latest"
            r = requests.get(url)
            r.raise_for_status()
            data = r.json()
            asset_url = None
            asset_name = None
            for asset in data.get("assets", []):
                if pkg["asset_pattern"] in asset["name"]:
                    asset_url = asset["browser_download_url"]
                    asset_name = asset["name"]
                    break
            if not asset_url:
                self.log(f"No se encontró asset para {pkg['name']}")
                return None

            tmp_file = f"/tmp/{asset_name}"
            with requests.get(asset_url, stream=True) as resp:
                with open(tmp_file, "wb") as f:
                    shutil.copyfileobj(resp.raw, f)
            return tmp_file
        except Exception as e:
            self.log(f"Error descargando asset: {e}")
            return None

    def install_package(self, file_path):
        try:
            subprocess.run(["sudo", "dpkg", "-i", file_path], check=True)
            return True
        except subprocess.CalledProcessError as e:
            self.log(f"dpkg error: {e}")
            return False

    def show_summary(self):
        # Mostrar ventana final
        total = len(packages)
        updated = sum(1 for row in self.liststore if row[2] == "Actualizado")
        dialog = Gtk.MessageDialog(
            parent=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Actualización finalizada"
       )
        dialog.format_secondary_text(
           f"Se han actualizado {updated} de {total} paquetes."
       )	
        dialog.run()
        dialog.destroy()

win = UpdaterWindow()
win.connect("destroy", Gtk.main_quit)
win.show_all()
Gtk.main()
