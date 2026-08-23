# DELTA Modern Analytics Workspace

This document is the visual source of truth for the DELTA frontend. Components use semantic tokens from `frontend/src/index.css`; raw color values do not belong in components.

## Visual thesis

A lightened dark analytics workspace built from cool graphite and blue-gray surfaces, restrained cyan interaction color, IBM Plex Sans with tabular mono numerals, balanced 4px-based spacing, and softly bordered 6–8px components with minimal elevation.

## Interaction thesis

Fast 120–200ms transitions change surface, border, opacity, or translate by at most one pixel; scrolling remains static, reduced motion is honored, and bounce, parallax, neon glow, large entrance motion, and decorative number animation are forbidden.

## Tokens

### Color

| Role | Token | Value |
| --- | --- | --- |
| App canvas | `--ws-canvas` | `#111820` |
| Navigation | `--ws-nav` | `#0d141b` |
| Surface 1 | `--ws-surface-1` | `#17232e` |
| Surface 2 | `--ws-surface-2` | `#1d2c38` |
| Surface 3 / hover | `--ws-surface-3` | `#253744` |
| Border | `--ws-border` | `#304451` |
| Border strong | `--ws-border-strong` | `#446071` |
| Text primary | `--ws-text-primary` | `#eef4f7` |
| Text secondary | `--ws-text-secondary` | `#b7c4cc` |
| Text muted | `--ws-text-muted` | `#91a2ac` |
| Primary cyan | `--ws-accent` | `#2eb7c4` |
| Primary hover | `--ws-accent-hover` | `#55c9d2` |
| Success | `--ws-success` | `#42be65` |
| Warning | `--ws-warning` | `#f1c21b` |
| Danger | `--ws-danger` | `#fa4d56` |
| Information | `--ws-info` | `#78a9ff` |

Semantic colors communicate state only. Cyan communicates interaction and selection. No decorative purple gradients or neon effects.

### Typography

- UI: IBM Plex Sans, Microsoft YaHei UI, Microsoft YaHei, PingFang SC, sans-serif.
- Numeric and identifiers: IBM Plex Mono, Cascadia Mono, Consolas, monospace.
- Page title 24/32 semibold; section title 15/22 semibold; body 13/20 regular; utility 11/16 medium.
- Financial values use tabular numerals. Uppercase is reserved for real codes and statuses.

### Geometry and spacing

- Spacing scale: 4, 8, 12, 16, 20, 24, 32, 40, 48px.
- Cards: 8px radius; controls: 6px radius; compact status tags: full radius.
- Controls: 36–40px height. Tables: approximately 40px row height.
- Desktop content maximum: 1800px. Page padding: 24px desktop, 20px tablet, 16px mobile.
- Shadows are limited to `--ws-shadow-1` for panels and `--ws-shadow-nav` for the mobile drawer.

### Motion

- `--ws-duration-fast`: 120ms.
- `--ws-duration-normal`: 160ms.
- `--ws-duration-slow`: 200ms.
- `--ws-ease`: cubic-bezier(.2, 0, 0, 1).
- Every interactive control implements default, hover, focus-visible, active, and disabled states.

## Component rules

- `workspace-header` identifies context and hosts only global state/actions.
- `page-heading` contains one page title, one concise description, and optional page-level controls.
- `panel` is the default grouping surface; nested content uses dividers or `surface-3`, not another generic panel.
- Metric cards emphasize one value and one concise label; color is used only when the value has semantic direction.
- Tables use a quiet header, tabular numerals, row hover, visible selected state, and horizontal scrolling below their minimum content width.
- Loading, empty, error, success, disabled, and selected states retain the same geometry to avoid layout shifts.
- Charts share canvas, grid, axis, crosshair, series, and tooltip colors with the workspace tokens.

## Responsive behavior

- 1440px: full navigation, multi-column data layouts.
- 1024px: collapsed navigation, two-column summaries, scrollable wide tables.
- 768px: overlay navigation, page controls wrap, primary information remains first.
- 375px: single-column panels and metrics, full-width controls, horizontal data-table scrolling.

