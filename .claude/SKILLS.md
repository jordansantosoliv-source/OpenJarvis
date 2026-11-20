# Project skills (Claude Code)

52 skills in `.claude/skills/`, copied from these repos (shallow clone, 2026-11-20).
Each skill keeps its upstream license file.

| Source | License | Skills |
|---|---|---|
| [anthropics/skills](https://github.com/anthropics/skills) | Apache-2.0 | academy-guide, algorithmic-art, brand-guidelines, canvas-design, claude-api, discernment-nudge, doc-coauthoring, docx, frontend-design, internal-comms, mcp-builder, pdf, pptx, skill-creator, slack-gif-creator, theme-factory, web-artifacts-builder, webapp-testing, xlsx |
| [zaddy99999/video-editing-skills](https://github.com/zaddy99999/video-editing-skills) | MIT | audio-polish, auto-cut, captions, hook-overlay, loops-gifs-stickers, render-qc, video-editing, youtube-publish |
| [iamaanahmad/agents-video-editing-skills](https://github.com/iamaanahmad/agents-video-editing-skills) | MIT | audio-mixing, captions-subtitles, ffmpeg-essentials, motion-design-craft, moviepy-python-video, platform-export, remotion-programmatic-video, screen-recording-demos, thumbnails, vertical-shorts, video-editing-router, video-planning, video-qa, voiceover-tts |
| [github774/claude-video-studio](https://github.com/github774/claude-video-studio) | MIT | video-director, video-edit, video-studio-qa |
| [TimoteoAltobrando/ai-video-skill](https://github.com/TimoteoAltobrando/ai-video-skill) | MIT | ai-video |
| [hint-shu/deep-research](https://github.com/hint-shu/deep-research) | MIT | quick-research, research, deep-research, expert-research, academic-research, ultra-research, osint-research |

## Local changes

- `video-studio-qa`: upstream name `video-qa`, renamed to avoid clashing with iamaanahmad's `video-qa`.
  References in `video-director` and `video-edit` updated.
- `video-tools` MCP server (needed by video-director/video-edit/video-studio-qa) is at
  `.claude/mcp/video_tools.py`, registered in `/.mcp.json`. Stdlib Python; needs `ffmpeg`/`ffprobe`.
- hint-shu research skills: shared helpers copied to `.claude/scripts/`; fallback paths now
  `.claude/scripts/...` instead of `scripts/...`. osint paths now `.claude/skills/osint-research/...`.
  The author's personal memory path in `ultra-research` was replaced with a placeholder.
- Integration docs referenced by deep-research/ultra-research are in `.claude/docs/`.

## Runtime requirements

- Video: `ffmpeg`, `ffprobe`; Node ≥18 (zaddy scripts, some need `sharp`); Python 3.
- `video-director` can install third-party plugins over the network (`scripts/ensure-specialist.sh`).
- Research: Firecrawl / Exa API keys; optional Codex CLI, Obsidian vault.
- `docx`/`pptx`/`xlsx`/`pdf`: LibreOffice, pandoc, Python libs per each SKILL.md.

## Update

Re-clone the source repos and re-copy. No auto-sync.
