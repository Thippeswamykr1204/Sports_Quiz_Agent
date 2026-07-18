"""
Injected CSS for the Perplexity-inspired visual identity.

Uses CSS variables and Streamlit's own [data-theme] attribute rather than
hardcoding colors, so dark mode (toggled via Streamlit's native theme
switch) is respected instead of fought.
"""

THEME_CSS = """
<style>
:root {
    --quiz-accent: #4a86e8;
    --quiz-accent-soft: rgba(74, 134, 232, 0.12);
    --quiz-border: rgba(120, 120, 120, 0.18);
    --quiz-radius: 12px;
    --quiz-mono: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
}

.quiz-card {
    border: 1px solid var(--quiz-border);
    border-radius: var(--quiz-radius);
    padding: 1.1rem 1.3rem;
    margin-bottom: 1rem;
    background: color-mix(in srgb, currentColor 3%, transparent);
}

.quiz-card-question {
    font-size: 1.05rem;
    font-weight: 600;
    margin-bottom: 0.6rem;
}

.quiz-confidence-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 0.5rem 0 0.8rem 0;
    font-size: 0.8rem;
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

.quiz-skeleton {
    border: 1px solid var(--quiz-border);
    border-radius: var(--quiz-radius);
    padding: 1.1rem 1.3rem;
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

.quiz-history-item {
    font-size: 0.85rem;
    padding: 0.4rem 0.5rem;
    border-radius: 8px;
    margin-bottom: 0.25rem;
    border: 1px solid transparent;
}

.quiz-history-item:hover {
    border-color: var(--quiz-border);
    background: var(--quiz-accent-soft);
}
</style>
"""
