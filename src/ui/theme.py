"""
Injected CSS for the visual identity.

Locked archetype: Linear x Perplexity hybrid - dense, dark-first, one sharp
accent, near-invisible motion. Uses CSS variables and Streamlit's own
[data-theme] attribute rather than hardcoding colors, so dark mode (toggled
via Streamlit's native theme switch) is respected instead of fought.

Existing class names (quiz-card, quiz-confidence-row, quiz-chip, etc.) are
kept stable - components.py and views.py bind to these and must not break.
New classes added at the bottom are additive, for later UI passes.
"""

THEME_CSS = """
<style>
:root {
    /* Signal accent: teal, not the stock Streamlit/Google blue. */
    --quiz-accent: #14b8a6;
    --quiz-accent-soft: rgba(20, 184, 166, 0.12);
    --quiz-accent-strong: #0d9488;
    --quiz-border: rgba(120, 120, 120, 0.16);
    --quiz-border-strong: rgba(120, 120, 120, 0.30);
    --quiz-radius: 10px;
    --quiz-radius-lg: 16px;
    --quiz-mono: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
    --quiz-ease: cubic-bezier(0.2, 0.8, 0.2, 1);
}

/* ---------- Type scale (tight, technical - Linear-esque) ---------- */

.quiz-eyebrow {
    font-family: var(--quiz-mono);
    font-size: 0.72rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    opacity: 0.6;
    margin-bottom: 0.3rem;
}

/* ---------- Core question card ---------- */

.quiz-card {
    border: 1px solid var(--quiz-border);
    border-radius: var(--quiz-radius-lg);
    padding: 1.15rem 1.35rem;
    margin-bottom: 1rem;
    background: color-mix(in srgb, currentColor 3%, transparent);
    transition: border-color 160ms var(--quiz-ease);
}

.quiz-card:hover {
    border-color: var(--quiz-border-strong);
}

.quiz-card-question {
    font-size: 1.05rem;
    font-weight: 600;
    margin-bottom: 0.6rem;
    line-height: 1.4;
}

.quiz-confidence-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 0.5rem 0 0.8rem 0;
    font-size: 0.78rem;
    opacity: 0.75;
}

.quiz-confidence-bar-track {
    flex: 1;
    height: 5px;
    border-radius: 3px;
    background: var(--quiz-border);
    overflow: hidden;
    max-width: 140px;
}

.quiz-confidence-bar-fill {
    height: 100%;
    background: var(--quiz-accent);
    border-radius: 3px;
    transition: width 300ms var(--quiz-ease);
}

.quiz-source-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin-top: 0.7rem;
}

.quiz-chip {
    font-family: var(--quiz-mono);
    font-size: 0.72rem;
    padding: 0.18rem 0.55rem;
    border-radius: 999px;
    background: var(--quiz-accent-soft);
    border: 1px solid var(--quiz-border);
    white-space: nowrap;
}

/* ---------- Skeleton / loading ---------- */

.quiz-skeleton {
    border: 1px solid var(--quiz-border);
    border-radius: var(--quiz-radius-lg);
    padding: 1.15rem 1.35rem;
    margin-bottom: 1rem;
}

.quiz-skeleton-line {
    height: 12px;
    border-radius: 6px;
    background: linear-gradient(
        90deg,
        var(--quiz-border) 25%,
        var(--quiz-accent-soft) 50%,
        var(--quiz-border) 75%
    );
    background-size: 200% 100%;
    animation: quiz-shimmer 1.4s ease-in-out infinite;
    margin-bottom: 0.5rem;
}

@keyframes quiz-shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
}

/* ---------- Sidebar history ---------- */

.quiz-history-item {
    font-size: 0.85rem;
    padding: 0.4rem 0.5rem;
    border-radius: 8px;
    margin-bottom: 0.25rem;
    border: 1px solid transparent;
    transition: background 120ms var(--quiz-ease), border-color 120ms var(--quiz-ease);
}

.quiz-history-item:hover {
    border-color: var(--quiz-border);
    background: var(--quiz-accent-soft);
}

/* ==================================================================
   Additive - new primitives for upcoming files (nav, stats, badges,
   hero, glass panels). Nothing above this line changes behavior.
   ================================================================== */

.quiz-glass {
    border: 1px solid var(--quiz-border);
    border-radius: var(--quiz-radius-lg);
    background: color-mix(in srgb, currentColor 4%, transparent);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
}

.quiz-gradient-bg {
    background:
        radial-gradient(1200px 400px at 10% -10%, var(--quiz-accent-soft), transparent 60%),
        radial-gradient(800px 300px at 90% 0%, rgba(99, 102, 241, 0.10), transparent 60%);
}

.quiz-stat-card {
    border: 1px solid var(--quiz-border);
    border-radius: var(--quiz-radius-lg);
    padding: 1rem 1.2rem;
    background: color-mix(in srgb, currentColor 3%, transparent);
}

.quiz-stat-value {
    font-size: 1.6rem;
    font-weight: 700;
    line-height: 1.1;
    font-variant-numeric: tabular-nums;
}

.quiz-stat-label {
    font-size: 0.78rem;
    opacity: 0.65;
    margin-top: 0.2rem;
}

.quiz-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    font-size: 0.72rem;
    font-weight: 600;
    padding: 0.15rem 0.55rem;
    border-radius: 999px;
    border: 1px solid var(--quiz-border);
}

.quiz-badge-accent {
    background: var(--quiz-accent-soft);
    color: var(--quiz-accent-strong);
    border-color: transparent;
}

.quiz-nav-item {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.5rem 0.65rem;
    border-radius: 8px;
    font-size: 0.88rem;
    transition: background 120ms var(--quiz-ease);
}

.quiz-nav-item:hover {
    background: var(--quiz-accent-soft);
}

.quiz-nav-item-active {
    background: var(--quiz-accent-soft);
    color: var(--quiz-accent-strong);
    font-weight: 600;
}

/* Reduced-motion: respect user preference, kill shimmer/transitions. */
@media (prefers-reduced-motion: reduce) {
    .quiz-skeleton-line { animation: none; }
    .quiz-card, .quiz-history-item, .quiz-confidence-bar-fill, .quiz-nav-item {
        transition: none;
    }
}

/* ---------- Responsive: wide layout still needs a readable content width ---------- */

.block-container {
    max-width: 1180px;
}

@media (max-width: 640px) {
    .block-container {
        padding-left: 1rem;
        padding-right: 1rem;
    }
    .quiz-stat-value {
        font-size: 1.3rem;
    }
    .quiz-card, .quiz-glass {
        padding: 0.9rem 1rem;
    }
}
</style>
"""