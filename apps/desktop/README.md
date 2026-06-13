# Adala AI Desktop

This package turns the web/API project into a Windows desktop app shell.

The desktop app supports two installer modes:

- The UI and API run on the user's machine.
- End users do not need to install Node, Python, npm, Ollama, or Qwen locally.
- Uploaded PDFs, OCR output, SQLite metadata, and indexes stay local in the app data folder.
- No-server mode is free for users and uses local extractive legal answers with citations.
- Local AI Mode lets users install Ollama and download `qwen3:1.7b` from inside the app.
- Remote-model mode connects to a hosted Ollama-compatible endpoint for more conversational generation.

## No-Server Mode

Build without `-RemoteModelUrl`:

```powershell
.\scripts\build-windows-installer.ps1 -EnableOcr
```

This creates an installer that runs without a remote model server and does not show the remote Ollama warning. It can upload, OCR, index, search, cite, and answer from PDFs locally. General chat is handled by the app's built-in assistant logic until the user enables Local AI Mode.

Inside the app, users can open **AI mode**. The workspace blurs and shows the setup flow:

1. Install Ollama if it is not detected.
2. Press **Check again** after Ollama is running.
3. Press **Download qwen3:1.7b**.
4. Press **Enable AI mode**.

After that, Adala AI uses the user's local Ollama model for conversational answers.

## Remote Model Settings

On first launch, the desktop app creates:

```text
%APPDATA%\Adala AI\settings.json
```

Example:

```json
{
  "ollamaBaseUrl": "https://your-remote-ollama.example.com",
  "llmProvider": "extractive",
  "ollamaModel": "qwen3:1.7b",
  "ollamaApiKey": "",
  "ragLlmEnabled": false,
  "ocrEnabled": false
}
```

Use `"llmProvider": "extractive"` for no-server mode. Use `"llmProvider": "ollama"` only when `ollamaBaseUrl` points to a server that exposes the Ollama `/api/chat` endpoint.

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

From the repository root, build the no-server installer with:

```powershell
.\scripts\build-windows-installer.ps1 -EnableOcr
```

Or build the remote-model installer with:

```powershell
.\scripts\build-windows-installer.ps1 `
  -RemoteModelUrl "https://your-remote-ollama.example.com" `
  -RemoteModel "qwen3:1.7b"
```

For a protected endpoint:

```powershell
.\scripts\build-windows-installer.ps1 `
  -RemoteModelUrl "https://your-remote-ollama.example.com" `
  -RemoteModel "qwen3:1.7b" `
  -RemoteModelApiKey "YOUR_SERVER_TOKEN"
```

The installer output is written to:

```text
apps/desktop/release
```

End users only need the generated `Adala AI Setup.exe`.

## Compact vs OCR Builds

The default installer is compact:

```text
ocrEnabled: false
```

That avoids bundling EasyOCR/Torch and keeps the package much smaller. It still reads searchable PDFs through pypdf/PyMuPDF.

For a heavier all-in-one installer with local OCR dependencies, run the build script with `-EnableOcr`. This can significantly increase installer size.

## Notes

- No-server mode does not bundle model weights.
- A true ChatGPT-like local model requires bundling model weights, which makes the installer much larger.
- In remote-model mode, the remote model server must be reachable from the user's machine.
- Keep `RAG_LLM_ENABLED=false` for safer legal answers unless you have thoroughly tested your remote model.
