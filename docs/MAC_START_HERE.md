# Ezra on your Mac

This starter bundle contains the current app, your 12 original source files, their extracted archive, reconstruction candidates, persona drafts, and a snapshot of the development app's conversation database. No API key, `.env`, cloud credential, or virtual environment is included.

## First installation

1. Unzip `Ezra-Mac-Starter.zip` in Finder. Move the resulting **Ezra** folder somewhere permanent, such as your home folder. Avoid placing personal application data in a public/shared folder.
2. Install **Python 3.12** from the macOS downloads page at `https://www.python.org/downloads/macos/`. Choose the **macOS 64-bit universal2 installer**, which supports your Intel Mac. Run the downloaded installer. Setup will also accept an existing Python 3.11 or 3.13.
3. In the Ezra folder, double-click **Setup.command**. It opens the built-in Terminal automatically; you do not need to type commands. On the first run, macOS may require Control-click → Open for this unsigned script.
4. Setup downloads Python dependencies, verifies/restores the starter archive, and asks for your **actual Featherless API key**. Paste it at the prompt and press Return. The characters will be invisible; this is expected. Enter your model ID or press Return to accept the supplied non-secret default if shown.
5. When setup finishes, double-click **Start.command**. Your browser should open the app at `http://127.0.0.1:8000` on this Mac.

If Python installation shows an **Install Certificates.command** item in its Applications folder and downloads fail with a certificate-verification error, run that supplied Python certificate installer and retry Setup. Keep TLS verification enabled. If anything else fails, send the error wording; do not send the API key or the contents of `.env`.

## Daily use

- **Start.command** starts the app and opens your browser. If the app is already responding, it reopens it.
- **Stop.command** requests clean shutdown of the server started by this launcher.
- **Configure.command** changes local key/model settings. Stop and start the app afterward to load changes.
- Closing the browser does not stop the server. Closing the setup/start Terminal window after it finishes does not remove your data.
- The server binds to this Mac only. Phone/other-device access and automatic startup are separate future setup steps.
- Keep the Mac plugged in and awake while testing. Sleep pauses availability. Do not assume that closing a MacBook lid leaves the server running.

## Where your data lives

Finder → **Go → Go to Folder…**, then paste:

```text
~/Library/Application Support/ResurrectEzra
```

This private folder contains `.env`, `data/`, `server.log`, and the launch record. Data stays separate from the downloadable code folder. Original file bytes and all archived/reconstruction records remain unchanged. Existing data is never overwritten by the bundled starter snapshot on a later setup run.

The app does not activate a persona automatically. Review the existing proposal in **Persona & reconstruction**. Automatic archive recall and memory consolidation are not connected yet.

## Backups and updates

For a full manual backup, stop the app and copy the complete `ResurrectEzra` Application Support folder to a protected separate drive. It contains your local credential file as well as private content; keep that backup private. The in-app archive export excludes credentials and conversations.

For a later app update: stop the current server, preserve the current code folder until the new version works, place the new app folder separately, run its Setup.command, then Start.command. The shared Application Support data is retained. Stop the old server before using a new code folder; port 8000 can serve only one copy.

This bundle has been assembled and verified in the development workspace. macOS Finder/Gatekeeper behavior and installation on your particular Mac still need to be confirmed with you. No claim of a completed Mac installation is made.
