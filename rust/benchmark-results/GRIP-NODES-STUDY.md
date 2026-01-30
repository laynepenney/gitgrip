# Grip Nodes Study: Custom Git Graph Visualization

## Overview

This study explores custom node designs for `gr log --graph` that incorporate "grip" or "fist" imagery, along with various color schemes to enhance visual differentiation.

---

## Node Design Options

### Option A: Minimal Grip (Simple Fist)

```
Standard git:     *
Grip version:     ✊
```

**Example output:**
```
✊ abc1234 feat: add authentication
│
✊ def5678 fix: resolve race condition
│\
│ ✊ ghi9012 feat: new dashboard
✊ │ chore: update deps
│/
✊ jkl3456 Initial commit
```

**Pros:**
- Recognizable hand/fist emoji
- Works in most terminals with Unicode
- Simple implementation

**Cons:**
- May not render consistently across fonts
- Emoji width varies

---

### Option B: ASCII Grip (Claw)

```
Standard git:     *
Grip version:     }<
```

**Example output:**
```
}< abc1234 feat: add authentication
│
}< def5678 fix: resolve race condition
│\
│ }< ghi9012 feat: new dashboard
}< │ chore: update deps
│/
}< jkl3456 Initial commit
```

**Pros:**
- Pure ASCII, works everywhere
- Looks like a gripping claw
- Consistent width

**Cons:**
- Less immediately recognizable

---

### Option C: Power Grip (Bold Hand)

```
Standard git:     *
Grip version:     ◆
                 /|\
```

Single-line version:
```
◆ abc1234 feat: add authentication
```

Or with "fingers" indicator:
```
✋ abc1234 feat: add authentication
```

**Example output:**
```
✋ abc1234 feat: add authentication
│
✋ def5678 fix: resolve race condition
│\
│ ✋ ghi9012 feat: new dashboard
✋ │ chore: update deps
│/
✋ jkl3456 Initial commit
```

---

### Option D: G-Node (Letter Based)

```
Standard git:     *
Grip version:     G
```

**Example output:**
```
G abc1234 feat: add authentication
│
G def5678 fix: resolve race condition
│\
│ G ghi9012 feat: new dashboard
G │ chore: update deps
│/
G jkl3456 Initial commit
```

Or with parentheses:
```
(G) abc1234 feat: add authentication
 │
(G) def5678 fix: resolve race condition
 │\
 │ (G) ghi9012 feat: new dashboard
(G) │  chore: update deps
 │ /
(G) jkl3456 Initial commit
```

---

### Option E: Grip Symbol (Custom Unicode)

```
Standard git:     *
Grip version:     ⚡ (power/grip)
                  ◉  (dot with power)
                  ⊛  (circled asterisk)
                  ⦿  (circled bullet)
```

**Example with ⦿:**
```
⦿ abc1234 feat: add authentication
│
⦿ def5678 fix: resolve race condition
│\
│ ⦿ ghi9012 feat: new dashboard
⦿ │ chore: update deps
│/
⦿ jkl3456 Initial commit
```

---

### Option F: Knuckle Nodes (Multi-character)

```
Standard git:     *
Grip version:    [⬤]
```

**Example output:**
```
[⬤] abc1234 feat: add authentication
 │
[⬤] def5678 fix: resolve race condition
 │\
 │ [⬤] ghi9012 feat: new dashboard
[⬤] │  chore: update deps
 │ /
[⬤] jkl3456 Initial commit
```

---

## Color Scheme Options

### Scheme 1: Classic Git (Default)

```rust
Colors {
    node: Yellow,       // Commit nodes
    branch_line: Green, // Main branch
    merge_line: Cyan,   // Merge connections
    hash: Yellow,       // Commit hash
    message: White,     // Commit message
    author: Blue,       // Author name
    date: Magenta,      // Date
}
```

**Preview:**
```
[yellow]✊[/] [yellow]abc1234[/] [white]feat: add authentication[/]
[green]│[/]
[yellow]✊[/] [yellow]def5678[/] [white]fix: resolve race condition[/]
```

---

### Scheme 2: Ocean (Cool Tones)

```rust
Colors {
    node: Cyan,
    branch_line: Blue,
    merge_line: Cyan,
    hash: BrightCyan,
    message: White,
    author: BrightBlue,
    date: Blue,
}
```

**Preview:**
```
[cyan]✊[/] [bright_cyan]abc1234[/] [white]feat: add authentication[/]
[blue]│[/]
[cyan]✊[/] [bright_cyan]def5678[/] [white]fix: resolve race condition[/]
```

---

### Scheme 3: Sunset (Warm Tones)

```rust
Colors {
    node: Red,
    branch_line: Yellow,
    merge_line: Red,
    hash: BrightRed,
    message: White,
    author: Yellow,
    date: Red,
}
```

**Preview:**
```
[red]✊[/] [bright_red]abc1234[/] [white]feat: add authentication[/]
[yellow]│[/]
[red]✊[/] [bright_red]def5678[/] [white]fix: resolve race condition[/]
```

---

### Scheme 4: Forest (Natural)

```rust
Colors {
    node: Green,
    branch_line: Green,
    merge_line: BrightGreen,
    hash: BrightGreen,
    message: White,
    author: Cyan,
    date: Green,
}
```

**Preview:**
```
[green]✊[/] [bright_green]abc1234[/] [white]feat: add authentication[/]
[green]│[/]
[green]✊[/] [bright_green]def5678[/] [white]fix: resolve race condition[/]
```

---

### Scheme 5: Neon (High Contrast)

```rust
Colors {
    node: Magenta,
    branch_line: BrightMagenta,
    merge_line: Cyan,
    hash: BrightYellow,
    message: BrightWhite,
    author: BrightCyan,
    date: Magenta,
}
```

**Preview:**
```
[magenta]✊[/] [bright_yellow]abc1234[/] [bright_white]feat: add authentication[/]
[bright_magenta]│[/]
[magenta]✊[/] [bright_yellow]def5678[/] [bright_white]fix: resolve race condition[/]
```

---

### Scheme 6: Monochrome (Accessibility)

```rust
Colors {
    node: BrightWhite,
    branch_line: White,
    merge_line: BrightWhite,
    hash: BrightWhite,
    message: White,
    author: White,
    date: White,
}
```

**Preview:**
```
[bright_white]✊[/] [bright_white]abc1234[/] [white]feat: add authentication[/]
[white]│[/]
[bright_white]✊[/] [bright_white]def5678[/] [white]fix: resolve race condition[/]
```

---

### Scheme 7: Rainbow Branches (Per-Branch Color)

Each branch gets a unique color from a palette:

```rust
BranchColors: [
    Red,
    Green,
    Yellow,
    Blue,
    Magenta,
    Cyan,
]
```

**Preview:**
```
[red]✊[/] abc1234 feat: add authentication
[red]│[/]
[red]✊[/] def5678 fix: resolve race condition
[red]│[/][green]\[/]
[red]│[/] [green]✊[/] ghi9012 feat: new dashboard (feature branch)
[red]✊[/] [green]│[/]  chore: update deps
[red]│[/][green]/[/]
[red]✊[/] jkl3456 Initial commit
```

---

## Complete Example: Grip Graph with Rainbow Scheme

```
[red]✊[/] [bright_yellow]abc1234[/] [bright_white](HEAD -> main)[/] Merge pull request #42
[red]│[/][cyan]\[/]
[red]│[/] [cyan]✊[/] [bright_yellow]def5678[/] [bright_white](origin/feat/auth)[/] Add OAuth support
[red]│[/] [cyan]│[/]
[red]│[/] [cyan]✊[/] [bright_yellow]ghi9012[/] Implement token refresh
[red]│[/][cyan]/[/]
[red]✊[/] [bright_yellow]jkl3456[/] Update dependencies
[red]│[/]
[red]✊[/] [bright_yellow]mno7890[/] Initial commit
```

---

## Implementation Notes

### Terminal Compatibility

| Symbol | UTF-8 | ASCII Fallback |
|--------|-------|----------------|
| ✊     | Yes   | }< or G        |
| ✋     | Yes   | >< or H        |
| ⦿      | Yes   | O or *         |
| ◆      | Yes   | + or #         |

### Detection Strategy

```rust
fn get_node_symbol() -> &'static str {
    if supports_emoji() {
        "✊"
    } else if supports_unicode() {
        "⦿"
    } else {
        "><"
    }
}
```

### Color Support Detection

```rust
fn get_color_scheme() -> ColorScheme {
    match term_colors() {
        TrueColor => NEON_SCHEME,
        Colors256 => RAINBOW_SCHEME,
        Colors16 => CLASSIC_SCHEME,
        NoColor => MONOCHROME_SCHEME,
    }
}
```

---

## Recommendations

### For Default:
1. **Node**: `✊` (fist emoji) with `⦿` fallback
2. **Color**: Rainbow branches (Scheme 7) for visual branch distinction
3. **Fallback**: ASCII `><` or `G` for legacy terminals

### User Configurable:
```yaml
# .gitgrip/config.yaml
graph:
  node_style: grip      # grip | classic | minimal
  color_scheme: rainbow # rainbow | classic | ocean | sunset | forest | neon | mono
```

### Command Line Override:
```bash
gr log --graph --node-style=classic  # Use standard * nodes
gr log --graph --color-scheme=neon   # Use neon colors
gr log --graph --no-color            # Disable colors
```

---

## Next Steps

1. Pick preferred node design
2. Pick default color scheme
3. Implement graph renderer with configurable options
4. Add tests for various terminal capabilities
5. Document color customization options
