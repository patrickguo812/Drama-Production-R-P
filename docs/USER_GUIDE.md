# User guide

## First run

1. Launch Drama Studio.
2. Open **API Settings**.
3. Select **Demo** to explore safely, or select **DeepSeek** / **Qwen** and enter an API key.
4. For a real provider, choose **Test Connection**, then **Save**.
5. Choose the large parent project folder. Drama Studio creates `Project Plan` and `Project Genre` inside it.
6. Import one `.docx` novel and inspect the extracted preview.
7. Choose **Analyze and Create Scenes**.

Long novels are read in sections. The provider first extracts plot evidence from each section, then produces a unified adaptation. Do not close the application during an active API run.

## Review

The **Theme & Characters** tab provides plain-language fields for the combined theme/style summary and recurring-character profiles. Character profiles are saved individually by character ID.

The **Scene Board** lists generatable clips. Select a scene to edit its plot, location, character IDs, costume/state, action, subtitle timing, duration, camera, continuity, and prompts. Enter each subtitle on its own line as `start-end | speaker | text`. Use statuses:

- `draft`: not yet checked
- `reviewed`: checked but not final
- `approved`: ready for later generation

Photo prompts target dense, precise Chinese of approximately 100 characters. A slight overrun is allowed and never blocks saving.

Use **Regenerate field** to replace only the selected plot/action/shot/continuity/photo/video field. **Regenerate prompts** preserves the scene and rewrites both prompts. **Regenerate scene** rewrites the complete selected scene while preserving its place and ID.

## Prompt extraction contract

A later image agent should locate a block by `PROMPT_ID`, then read only the text between `<<<PHOTO_PROMPT_BEGIN>>>` and `<<<PHOTO_PROMPT_END>>>`. A later video agent uses the corresponding video markers. IDs are stable links among the scene, character files, prompt, future photo, and future video.

## Credentials and privacy

- macOS keys are stored in Keychain under service `DramaStudio`.
- Windows keys are stored as generic credentials in Windows Credential Manager.
- `DEEPSEEK_API_KEY` or `QWEN_API_KEY` can supply a session key for development.
- Keys are not written to project JSON or prompt files.
- The app does not store raw provider responses, processing history, or hidden reasoning.
- Novel text is sent to the selected provider only when real processing is started.

## Recovery

Every explicit save uses atomic file replacement. Open an existing parent project folder to reload its `Scene Plan.json`. Prompt files are rebuilt from the saved scene records, so they stay aligned with scene edits.

## Current boundary

This version prepares character descriptions, character-reference prompts, photo prompts, and video prompts. It does not train LoRAs or call an image/video generation API. `Character References` and `Photos` are prepared for that later stage.
