# Adala AI Desktop

This package turns the web/API project into a Windows desktop app shell.

The desktop app is designed for the lightweight installer path:

- The UI and API run on the user's machine.
- The model runs on a remote Ollama-compatible endpoint over the internet.
- End users do not need to install Ollama or download Qwen locally.
- Uploaded PDFs, OCR output, SQLite metadata, and indexes stay local in the app data folder.

## Remote Model Settings

On first launch, the desktop app creates:

```text
%APPDATA%\Adala AI\settings.json
```

Example:

```json
{
  "ollamaBaseUrl": "https://your-remote-ollama.example.com",
  "ollamaModel": "qwen3:1.7b",
  "ollamaApiKey": "",
  "ragLlmEnabled": false
}
```

`ollamaBaseUrl` must point to a server that exposes the Ollama `/api/chat` endpoint.

If the remote endpoint requires authentication, set `ollamaApiKey`. The API sends it as:

```text
Authorization: Bearer <ollamaApiKey>
```

## Development

Install desktop dependencies:

```powershell
cd apps/desktop
npm install
```

Start the desktop shell from the repository root:

```powershell
npm run dev:desktop
```

In development, the desktop shell starts:

- FastAPI from `apps/api`
- Next.js from `apps/web`
- Electron as the native app window

The backend Python environment must already exist:

```powershell
cd apps/api
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-local.txt
```

## Installer Build Path

Build the web app:

```powershell
npm run build:web
```

Package the Python API into an executable:

```powershell
cd apps/api
.\.venv\Scripts\Activate.ps1
pip install pyinstaller
pyinstaller --name adala-api --onedir launcher.py
```

Build the Windows installer:

```powershell
cd ../..
npm --prefix apps/desktop install
npm run build:desktop
```

The installer output is written to:

```text
apps/desktop/release
```

## Notes

- This is the lightweight installer architecture. It does not bundle model weights.
- The remote model server must be reachable from the user's machine.
- Keep `RAG_LLM_ENABLED=false` for safer legal answers unless you have thoroughly tested your remote model.
