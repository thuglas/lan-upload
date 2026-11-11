# LAN Upload

A tiny, zero-setup web server for sending large files from one computer to
another on the same local network. All the sending computer needs is a web browser.

1. Start **LAN Upload** on the computer that should **receive** the file.
2. On the other computer, open the address it prints (e.g. `http://192.168.1.50:8000`) in any web browser.
3. Pick a file, click **Upload**, and watch the progress bar.

Files are saved into the folder the server was started from.

- **No install.** Use the portable `lan-upload.exe` on Windows, or run the
  Python script anywhere (standard library only, nothing to install with pip).
- **Handles big files.** Uploads are streamed to disk in 1 MB chunks, so even
  multi-gigabyte files never sit in memory.
- **Local network only by default.** Connections from outside your local subnet(s) are refused.
- **Exits on its own.** It shuts down after 10 minutes with no connections and
  no transfer in progress, so you can't forget it and leave it running.
- **Never overwrites.** If `movie.mkv` already exists, the new upload is saved as `movie(1).mkv`.
- **No half files.** A file is written as `name.part` while it uploads and
  renamed when it finishes. If the upload is interrupted, the partial file is deleted.

> ⚠️ **No security.** There is no password and no encryption (plain HTTP).
> Anyone on your local network who can reach the port can upload files while it
> is running. Only use it on networks you trust, and close it when you're done.

---

## Quick start

### Windows (no Python needed)

1. Download `lan-upload.exe` from the [Releases](../../releases) page.
2. Put it in the folder where you want received files to go (for example `Downloads`).
3. Double-click it. A console window shows the address to open on the other computer.
4. If Windows Firewall asks, click **Allow access** for **Private networks**.

Close the window or press **Ctrl+C** to stop it.

### Any OS with Python 3.8+

```bash
cd /folder/to/receive/into
python upload_server.py
```

---

## Options

```
lan-upload.exe [options]          (or: python upload_server.py [options])

  -p, --port PORT        Port to listen on (default 8000)
  -d, --dir FOLDER       Folder to save uploads into (default: current folder)
  -t, --timeout MINUTES  Exit after this many idle minutes; 0 = never (default 10)
  -s, --subnet CIDR      Allowed client network, e.g. 192.168.1.0/24.
                         Can be given more than once. Default: the /24 around
                         each of this computer's network adapters.
      --allow-any        Accept connections from ANY address (turns off the subnet check)
      --version          Show version and exit
  -h, --help             Show help
```

Examples:

```bat
:: Save into D:\Incoming and never time out
lan-upload.exe --dir D:\Incoming --timeout 0

:: Use port 8080 and only accept clients from 10.0.0.0/16
lan-upload.exe --port 8080 --subnet 10.0.0.0/16
```

### How "local subnet only" works

At startup, LAN Upload looks up every IPv4 address on the computer's network
adapters (Ethernet, Wi-Fi, virtual machine adapters, …) and allows clients from
the `/24` network around each one (e.g. `192.168.1.0`–`192.168.1.255`). Requests
from the computer itself are always allowed. Anyone else gets a `403 Forbidden`,
and the console logs the blocked address.

If your network is bigger than a `/24` (for example `10.0.0.0/16`), pass it with `--subnet`.

### How the idle timeout works

The 10-minute clock resets on every request (opening the page, starting an
upload) and on every chunk of data received. While an upload is running, the
server never times out, however long the upload takes.

---

## Building the Windows exe

The exe is built with [PyInstaller](https://pyinstaller.org/). It bundles a
Python runtime and the script into a single portable file.

**Requirements (build machine only):** Windows with Python 3.8+ on `PATH`.

```bat
build.bat
```

The script will:

1. create a private virtual environment in `.venv\` (your global Python is left alone),
2. install the PyInstaller version pinned in `requirements-build.txt`,
3. build `dist\lan-upload.exe`.

After you edit `upload_server.py`, run `build.bat` again to rebuild. The
`build\`, `dist\`, `.venv\` and `*.spec` outputs are git-ignored.

> **Antivirus note:** Single-file PyInstaller executables are sometimes flagged
> by antivirus software as a false positive. If this happens, build the exe
> yourself from source with `build.bat`, or run the Python script directly.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| The other computer can't load the page | Make sure both computers are on the same network. Allow the app through Windows Firewall (Private network). Check that you typed the exact address shown. |
| `403 Forbidden` in the browser | The client is outside the allowed subnet. Use `--subnet` to add its network, or `--allow-any`. |
| "Could not start on port 8000" | Another program (or another copy of LAN Upload) is using that port. Try `--port 8080`. |
| The printed address is wrong (e.g. a VPN or VM adapter address) | Use the address of your real LAN adapter instead. Run `ipconfig` to find it. |
| The server closed by itself | That's the 10-minute idle timeout. Start it again, or use `--timeout 0`. |

---

## Files

| File | Purpose |
|---|---|
| `upload_server.py` | The server (single file, Python standard library only) |
| `build.bat` | Builds the portable Windows exe with PyInstaller |
| `requirements-build.txt` | Pinned build-time dependency (PyInstaller) |

## License

MIT. See [LICENSE](LICENSE).
