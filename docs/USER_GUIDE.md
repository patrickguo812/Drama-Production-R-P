# User guide

## First run

1. Launch **Drama Studio - Text Production**.
2. Open **API Settings**.
3. Select **Demo** to explore safely, or select **DeepSeek** / **Qwen** and enter an API key.
4. For a real provider, choose **Test Connection**, then **Save**.
5. Open **Project Manager**, choose one Drama Projects parent folder, and create a named project.
6. The app automatically creates `Source`, `Project Plan`, and `Project Genre` inside that project.
7. Import one `.docx` novel and inspect the extracted preview. A safe copy is placed in `Source`.
8. Choose **Create scene plan**.

Long novels are read in sections. The provider creates the complete scene plan and then automatically creates both prompts for every scene. The sidebar shows separate Scenes and Prompts progress throughout the run.

## Project management

Project Manager keeps every project inside the selected Drama Projects parent folder. Use Search to find projects, or select one to open, rename, duplicate, reveal in Finder/Explorer, or move it to Trash. Renaming changes both the real folder name and the saved project name; duplicating copies the source, scenes, characters, prompts, and generated assets.

Deleted projects move to the hidden `.DramaStudio Trash` folder inside that same parent folder. The Trash tab shows the deletion time and days remaining. A project can be restored for 10 days; if its old name is already used, the app asks for a different one. Expired items are removed when the app starts or Project Manager refreshes. **Delete permanently** shows the exact folder and asks for confirmation. Automatic cleanup ignores unmarked folders and only removes valid projects previously trashed by Drama Studio.

## Review

The **Story & cast** section provides plain-language fields for the combined theme/style summary and recurring-character profiles. Projects autosave to `project.drama`, and reopening a project restores its scenes and characters.

The **Scene Board** lists generatable clips without an approval stage. Select a scene to edit its plot, location, character IDs, costume/state, action, subtitle timing, duration, camera, and continuity. Enter each subtitle on its own line as `start-end | speaker | text`. Scenes can be added, duplicated, deleted, reordered, or regenerated.

The separate **Prompt Board** is the only approval stage and edits or approves photo and video prompts independently. Photo prompts target dense, precise Chinese of approximately 100 characters. A slight overrun is allowed and never blocks saving.

**Regenerate selected scenes** shows the current and proposed versions before replacing one scene, and supports confirmed batches. Changing any scene clears its old photo/video prompts. Regenerate those missing rows from Prompt Board, where they return to draft for manual approval.

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

Every save uses atomic file replacement and maintains one recovery copy. Open a project through Project Manager to reload `project.drama`. `Photos Prompts.txt` and `Videos Prompts.txt` are rebuilt from approved prompt records only, so obsolete or draft prompts cannot be sent accidentally.

## Current boundary

This version prepares character descriptions, character-reference prompts, photo prompts, and video prompts. It does not train LoRAs or call an image/video generation API. `Character References`, `Photos`, and `Videos` are prepared for that later stage.
