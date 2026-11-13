#!/usr/bin/bash
# Omarchy Store desktop — user-space installer.
# No sudo, no hooks, no services, no network, nothing outside $HOME. Installs to ~/.local only.
# Run ./install.sh again to update; ./install.sh --uninstall removes exactly the files it installed.
set -euo pipefail

if [[ ${EUID} -eq 0 ]]; then
  echo "Run this as your own user, not as root. The app never needs root — not to install, not to run." >&2
  exit 1
fi

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# A relative XDG_DATA_HOME is invalid per the XDG spec; GLib ignores it and so do we (install and uninstall stay in step).
[[ "${XDG_DATA_HOME:-}" == /* ]] || XDG_DATA_HOME=""
data="${XDG_DATA_HOME:-$HOME/.local/share}"
app_dir="$data/omarchy-store"
launcher="$HOME/.local/bin/omarchy-store-desktop"
desktop_file="$data/applications/com.omarchystore.Store.desktop"
icon_file="$data/icons/hicolor/512x512/apps/com.omarchystore.Store.png"
icon_sizes=(48 64 128 256)          # 1.1.4: docks that look for a smaller size than 512 find one (named files, listed here)
lockup_file="$app_dir/lockup.png"   # 1.1.4: the official lockup PNG shown at the top of the app's sidebar

refresh_caches() {
  # Purely cosmetic (launcher menus); both tools are user-space and optional. They write $data/applications/mimeinfo.cache
  # and, if an index.theme exists there, $data/icons/hicolor/icon-theme.cache.
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$data/applications" 2>/dev/null || true
  command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q "$data/icons/hicolor" 2>/dev/null || true
}

if [[ "${1:-}" == "--uninstall" ]]; then
  # Named files only — never rm -rf a directory derived from an environment variable.
  rm -f "$app_dir/omarchy-store-desktop.py" "$lockup_file" "$launcher" "$desktop_file" "$icon_file"
  for s in "${icon_sizes[@]}"; do rm -f "$data/icons/hicolor/${s}x${s}/apps/com.omarchystore.Store.png"; done
  rmdir "$app_dir" 2>/dev/null || true
  if compgen -G "$data/applications/*.desktop" >/dev/null; then refresh_caches
  else rm -f "$data/applications/mimeinfo.cache"; fi      # ours was the only entry: leave no cache behind either
  echo "Omarchy Store desktop removed."
  echo "Your settings stay in ~/.config/omarchy-store and ~/.cache/omarchy-store — delete them if you like."
  exit 0
fi

# Dependencies are all in the official Arch repos and already present on every Omarchy install. This script only
# CHECKS for them (pacman -T, a read-only query that also accepts providers). It never installs anything and never runs
# sudo or anything with privileges.
command -v pacman >/dev/null 2>&1 || { echo "This installer is for Arch / Omarchy: pacman is needed to check the dependencies." >&2; exit 1; }
missing=()
mapfile -t missing < <(pacman -T gtk4 libadwaita webkitgtk-6.0 python-gobject xdg-terminal-exec hicolor-icon-theme || true)
if ((${#missing[@]})); then
  echo "Missing packages: ${missing[*]}"
  echo "Install them yourself first (this script never does it for you):  sudo pacman -S ${missing[*]}"
  echo "Then run ./install.sh again."
  exit 1
fi

# the version already installed, if any: read from its VERSION line as text (never run), only to say "Updated X -> Y"
old_ver=""
[[ -f "$app_dir/omarchy-store-desktop.py" ]] && old_ver=$(sed -n 's/^VERSION = "\([0-9][0-9.]*\)"$/\1/p' "$app_dir/omarchy-store-desktop.py" | head -1)
new_ver=$(sed -n 's/^VERSION = "\([0-9][0-9.]*\)"$/\1/p' "$here/omarchy-store-desktop.py" | head -1)
mkdir -p "$app_dir" "$HOME/.local/bin" "$(dirname "$desktop_file")" "$(dirname "$icon_file")"
install -m 0644 "$here/omarchy-store-desktop.py" "$app_dir/omarchy-store-desktop.py"
install -m 0644 "$here/data/lockup.png" "$lockup_file"
# The launcher: fixed shell, fixed interpreter run with -I (PYTHONPATH and the user's site-packages are ignored; the
# process otherwise trusts the user's own session environment, as any desktop app does), fixed
# script path, %q-quoted so an unusual $XDG_DATA_HOME cannot break out of the quoting. Written to a temp file and moved
# into place by install(1), which replaces — never follows — a pre-existing symlink at the destination.
printf '#!/usr/bin/bash\n# NVIDIA: WebKitGTK DMA-BUF renderer paints only part of the window (fixed kernel path, user value kept)\nif [[ -e /proc/driver/nvidia/version && -z "${WEBKIT_DISABLE_DMABUF_RENDERER+x}" ]]; then export WEBKIT_DISABLE_DMABUF_RENDERER=1; fi\nexec /usr/bin/python3 -I %q "$@"\n' "$app_dir/omarchy-store-desktop.py" > "$launcher.tmp.$$"
install -m 0755 "$launcher.tmp.$$" "$launcher" && rm -f "$launcher.tmp.$$"
# The menu entry must work even when ~/.local/bin is not on the session's PATH: point Exec= at the launcher itself,
# double-quoted as the Desktop Entry spec requires (spaces are fine). The few characters the spec would need escaping
# for are vanishingly rare in a home path; if one is present we keep the bare command and say so.
if [[ "$launcher" != *[\"\`\$\\%]* && "$launcher" != *$'\n'* ]]; then
  # every Exec= line (the main one and the three dock actions) gets the quoted launcher path; the rest of each line (a fixed
  # --updates / --update-all / --installed flag from our own file) is kept as is
  while IFS= read -r line; do
    if [[ "$line" == "Exec=omarchy-store-desktop"* ]]; then printf 'Exec="%s"%s\n' "$launcher" "${line#Exec=omarchy-store-desktop}"; else printf '%s\n' "$line"; fi
  done < "$here/data/com.omarchystore.Store.desktop" > "$desktop_file.tmp.$$"
  install -m 0644 "$desktop_file.tmp.$$" "$desktop_file" && rm -f "$desktop_file.tmp.$$"    # install(1): replaces, never follows a symlink
  menu_note=" (the menu entry already uses that path)"
else
  install -m 0644 "$here/data/com.omarchystore.Store.desktop" "$desktop_file"
  echo "Note: your home path contains a character the menu entry cannot quote; the entry needs ~/.local/bin on PATH."
  menu_note=""
fi
install -m 0644 "$here/data/com.omarchystore.Store.png" "$icon_file"
for s in "${icon_sizes[@]}"; do
  mkdir -p "$data/icons/hicolor/${s}x${s}/apps"
  install -m 0644 "$here/data/icons/$s.png" "$data/icons/hicolor/${s}x${s}/apps/com.omarchystore.Store.png"
done
refresh_caches

if [[ -n "$old_ver" && "$old_ver" == "$new_ver" ]]; then
  echo "Reinstalled $new_ver."
  echo "If Omarchy Store is open, close it (menu > Quit, or Ctrl+Q) and open it again."
elif [[ -n "$old_ver" ]]; then
  echo "Updated $old_ver -> $new_ver."
  echo "If Omarchy Store is open, close it (menu > Quit, or Ctrl+Q) and open it again to use the new version."
else
  echo "Installed. Launch 'Omarchy Store' from your app launcher, or run: omarchy-store-desktop"
fi
echo "Check it yourself any time:  omarchy-store-desktop --self-test"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "Note: ~/.local/bin is not on your PATH; run it as $launcher$menu_note." ;; esac
