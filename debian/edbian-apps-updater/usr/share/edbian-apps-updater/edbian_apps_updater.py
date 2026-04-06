#!/usr/bin/env python3
import json
import os
import requests
import subprocess
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GObject, GLib

CONFIG_FILE = "/usr/share/edbian-apps-updater/packages.json"
VERSION_FILE = "/usr/local/bin/.pkg_versions.json"

# Cargar versiones
if os.path.exists(VERSION_FILE):
    with open(VERSION_FILE, "r") as f:
        installed_versions = json.load(f)
else:
    installed_versions = {}

with open(CONFIG_FILE, "r") as f:
    packages = json.load(f)

class UpdaterWindow(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self, title="Ebian Apps Updater")
        self.set_border_width(10)
        self.set_default_size(600, 400)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(vbox)

        # Lista de paquetes
        self.liststore = Gtk.ListStore(str, str, str)
        for pkg in packages:
            current = installed_versions.get(pkg['name'], "0.0.0")
            self.liststore.append([pkg['name'], current, "Pendiente"])

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

        self.button = Gtk.Button(label="Actualizar paquetes")
        self.button.connect("clicked", self.start_update)
        vbox.pack_start(self.button, False, False, 0)

    def start_update(self, button):
        # Ejecutar en hilo de GTK
        GObject.idle_add(self.update_packages)

    def update_packages(self):
        total = len(packages)
        for i, pkg in enumerate(packages):
            self.liststore[i][2] = "Comprobando..."
            GLib.idle_add(lambda i=i: self.liststore[i][2] = "Comprobando...")

            latest = self.get_latest_version(pkg['repo'])
            installed = installed_versions.get(pkg['name'], "0.0.0")

            if latest != installed:
                self.liststore[i][2] = "Descargando..."
                GLib.idle_add(lambda i=i: self.liststore[i][2] = "Descargando...")
                self.download_and_install(pkg, latest)
                installed_versions[pkg['name']] = latest
                self.liststore[i][1] = latest
                self.liststore[i][2] = "Actualizado"
            else:
                self.liststore[i][2] = "Ya actualizado"

            self.progress.set_fraction((i+1)/total)
            while Gtk.events_pending():
                Gtk.main_iteration()

        # Guardar versiones
        with open(VERSION_FILE, "w") as f:
            json.dump(installed_versions, f, indent=2)
        self.progress.set_fraction(0)

    def get_latest_version(self, repo):
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        r = requests.get(url)
        r.raise_for_status()
        data = r.json()
        return data["tag_name"]

    def download_and_install(self, pkg, version):
        url = f"https://api.github.com/repos/{pkg['repo']}/releases/latest"
        r = requests.get(url)
        r.raise_for_status()
        data = r.json()

        asset_url = None
        for asset in data.get("assets", []):
            if pkg["asset_pattern"] in asset["name"]:
                asset_url = asset["browser_download_url"]
                asset_name = asset["name"]
                break
        if not asset_url:
            print(f"No se encontró asset para {pkg['name']}")
            return

        tmp_file = f"/tmp/{asset_name}"
        with requests.get(asset_url, stream=True) as resp:
            total_length = int(resp.headers.get('content-length', 0))
            downloaded = 0
            with open(tmp_file, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        GLib.idle_add(lambda dl=downloaded, tl=total_length: self.progress.set_fraction(dl/tl))
                        while Gtk.events_pending():
                            Gtk.main_iteration()

        # Instalar según tipo
        if tmp_file.endswith(".tar.gz") or tmp_file.endswith(".tgz"):
            subprocess.run(["tar", "-xzf", tmp_file, "-C", pkg["install_path"]], check=True)
        elif tmp_file.endswith(".deb"):
            subprocess.run(["sudo", "dpkg", "-i", tmp_file], check=True)
        else:
            subprocess.run(["cp", tmp_file, pkg["install_path"]], check=True)

        os.remove(tmp_file)
        self.progress.set_fraction(0)

win = UpdaterWindow()
win.connect("destroy", Gtk.main_quit)
win.show_all()
Gtk.main()
