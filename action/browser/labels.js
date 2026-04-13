// Vimium-style element labeling: find all interactive elements,
// assign two-letter labels, overlay visual hints on the page.
//
// Returns: Array of { label, tag, text, href, type, role, rect }

(function () {
    // Remove previous labels if any
    document.querySelectorAll('.ki-label-overlay').forEach(el => el.remove());
    const old = document.getElementById('ki-label-style');
    if (old) old.remove();

    // Inject label styles
    const style = document.createElement('style');
    style.id = 'ki-label-style';
    style.textContent = `
        .ki-label-overlay {
            position: absolute;
            z-index: 2147483647;
            background: #fbbf24;
            color: #000;
            font: bold 11px/1 monospace;
            padding: 1px 3px;
            border-radius: 2px;
            border: 1px solid #92400e;
            pointer-events: none;
            white-space: nowrap;
        }
    `;
    document.head.appendChild(style);

    // Selectors for interactive elements
    const selector = [
        'a[href]',
        'button',
        'input',
        'textarea',
        'select',
        '[role="button"]',
        '[role="link"]',
        '[role="tab"]',
        '[role="menuitem"]',
        '[role="checkbox"]',
        '[role="radio"]',
        '[role="switch"]',
        '[onclick]',
        '[tabindex]',
        'summary',
        'details',
        'video',
        'audio',
    ].join(',');

    const elements = Array.from(document.querySelectorAll(selector));

    // Filter to visible, in-viewport elements
    const visible = elements.filter(el => {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return false;
        const style = window.getComputedStyle(el);
        if (style.visibility === 'hidden' || style.display === 'none' || style.opacity === '0') return false;
        if (rect.bottom < 0 || rect.top > window.innerHeight) return false;
        if (rect.right < 0 || rect.left > window.innerWidth) return false;
        return true;
    });

    // Generate two-letter labels: aa, ab, ac, ...
    const chars = 'abcdefghijklmnopqrstuvwxyz';
    function makeLabel(index) {
        const a = Math.floor(index / chars.length);
        const b = index % chars.length;
        if (a >= chars.length) return String(index);
        return chars[a] + chars[b];
    }

    const results = [];
    const container = document.createElement('div');
    container.className = 'ki-label-overlay-container';
    document.body.appendChild(container);

    visible.forEach((el, i) => {
        const label = makeLabel(i);
        const rect = el.getBoundingClientRect();

        // Create visual overlay
        const overlay = document.createElement('span');
        overlay.className = 'ki-label-overlay';
        overlay.textContent = label;
        overlay.style.left = (window.scrollX + rect.left) + 'px';
        overlay.style.top = (window.scrollY + rect.top - 14) + 'px';
        document.body.appendChild(overlay);

        // Get descriptive text (truncated)
        let text = (
            el.textContent ||
            el.getAttribute('aria-label') ||
            el.getAttribute('title') ||
            el.getAttribute('placeholder') ||
            el.getAttribute('alt') ||
            ''
        ).trim().slice(0, 80).replace(/\s+/g, ' ');

        results.push({
            label: label,
            tag: el.tagName.toLowerCase(),
            text: text,
            href: el.href || null,
            type: el.type || null,
            role: el.getAttribute('role') || null,
            rect: {
                x: Math.round(rect.x + rect.width / 2),
                y: Math.round(rect.y + rect.height / 2),
                w: Math.round(rect.width),
                h: Math.round(rect.height),
            },
        });
    });

    return results;
})();
