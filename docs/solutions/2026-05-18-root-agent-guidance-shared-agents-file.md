---
title: "Keep shared agent guidance in AGENTS.md with CLAUDE.md as an import shim"
tags: [agents, claude-code, codex, documentation]
date: 2026-05-18
---

## Problem
Repo-root agent guidance needs to work for both Codex and Claude Code without
forking the instructions. Putting shared rules directly in `CLAUDE.md` would
hide them from non-Claude agents, while stuffing large architecture docs into
the root instruction file would make the guidance brittle and noisy.

## Solution
Keep the canonical shared repository guidance in root `AGENTS.md` and make root
`CLAUDE.md` a minimal `@AGENTS.md` import shim. Store only durable intent,
workflow, and guardrails in `AGENTS.md`, and reference stable design sources
like `docs/system-design.md` instead of copying volatile implementation state or
enumerating transient docs.
