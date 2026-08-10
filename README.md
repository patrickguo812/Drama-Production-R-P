# Drama Studio - Text Production

Local Mac/Windows desktop app that turns a `.docx` novel into an editable AI short-drama scene plan plus separately extractable photo and video prompts.

## Quick start

Requires Python 3.11+ with Tk support.

```bash
python3 app.py
```

No API key is required for **Demo mode**. For real processing, choose DeepSeek or Qwen in Settings, enter the API key, and test the connection. Keys are stored in macOS Keychain or Windows Credential Manager and are never written to project files.

## Project output

```text
Drama Projects/
└── Project Name/
├── Source/
│   └── Original Novel.docx
├── Project Plan/
│   ├── project.drama
│   ├── Scene Plan.txt
│   └── Characters.txt
└── Project Genre/
    ├── Character References/
    ├── Photos Prompts.txt
    ├── Videos Prompts.txt
    ├── Photos/
    └── Videos/
```

The image/video folders are prepared for the later generation stage. This MVP stops at reviewable prompts.

## Included workflow

- Plain-language theme/style and recurring-character editors
- Long-novel chunk analysis followed by episode-batched scene generation
- Editable scene ordering, duration, location, action, subtitle timing, camera and continuity
- Searchable Project Manager with open, rename, duplicate, Show Folder, and automatic folder creation
- Recoverable project Trash with restore controls and guarded automatic cleanup after 10 days
- Automatic scene-to-photo/video-prompt processing without a scene approval pause
- Editable Scene Board with selected-scene regeneration and a separate Prompt Board approval stage
- Draft/reviewed/approved status per prompt
- Editing any scene clears its obsolete prompts automatically
- Regenerate one field, both prompts, or the complete selected scene
- Automatic prompt character counts and atomic autosaving
- Cancellation between API calls and retry handling for temporary provider failures
- Approved-only instructions embedded in the prompt files for later generation agents

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Packaging

Install PyInstaller in a disposable build environment, then run:

```bash
pyinstaller DramaStudio.spec
```

Build macOS artifacts on macOS and Windows artifacts on Windows. The generated application is in `dist/`.

The local Mac build is ad-hoc/unsigned. For distribution to other Macs, sign and notarize it with an Apple Developer certificate. Windows should likewise be code-signed before broad distribution.

## API compatibility

- DeepSeek default endpoint: `https://api.deepseek.com/chat/completions` (current default model: `deepseek-v4-flash`)
- Qwen default endpoint: `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`

Both use an OpenAI-compatible chat-completions request. Endpoints and model names remain editable because provider offerings change.
