import type { Config } from 'tailwindcss';

// All design tokens resolve to CSS custom properties defined in
// src/styles/tokens.css, which switch on [data-theme="light"|"dark"].
// Tailwind never hardcodes a theme color — it only references the vars,
// so every utility is theme-aware for free. Source of truth: DESIGN.md §2 / §7.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        accent: 'var(--accent)',
        'accent-2': 'var(--accent-2)',
        grn: 'var(--grn)',
        red: 'var(--red)',
        ink: {
          1: 'var(--ink-1)',
          2: 'var(--ink-2)',
          3: 'var(--ink-3)',
          4: 'var(--ink-4)',
        },
        bd: {
          1: 'var(--bd-1)',
          2: 'var(--bd-2)',
          3: 'var(--bd-3)',
        },
        chart: {
          line: 'var(--chart-line)',
          bar: 'var(--chart-bar)',
          grid: 'var(--chart-grid)',
        },
        node: {
          DEFAULT: 'var(--node)',
          hot: 'var(--node-hot)',
        },
        // GUARDRAIL (DESIGN.md §1.3 / §7, adv-visual finding): the claim/cov/disp/
        // trust/sens groups below exist ONLY to color DOTS (a small indicator) and
        // borders/glows. Never use them as text color (text-claim-single, text-cov-
        // unknown, …): low-lightness signal hues can't reach 4.5:1 on the light
        // surface. Domain state in text = colored dot + --ink-1/2 label. Enforced
        // by the Dot/Badge primitives; don't bypass them.
        // §7.1 corroboration level — CorroborationBadge dot
        claim: {
          draft: 'var(--claim-draft)',
          single: 'var(--claim-single)',
          corroborated: 'var(--claim-corroborated)',
          'corroborated-employee': 'var(--claim-corroborated-employee)',
          validated: 'var(--claim-validated)',
          rejected: 'var(--claim-rejected)',
        },
        // §7.2 coverage state — CoverageStateBadge / CoverageMeter dot
        cov: {
          unknown: 'var(--cov-unknown)',
          partial: 'var(--cov-partial)',
          clear: 'var(--cov-clear)',
          disputed: 'var(--cov-disputed)',
          validated: 'var(--cov-validated)',
          stale: 'var(--cov-stale)',
        },
        // §7.3 dispute state — DisputeBadge dot
        disp: {
          disputed: 'var(--disp-disputed)',
          'resolved-for': 'var(--disp-resolved-for)',
          'resolved-against': 'var(--disp-resolved-against)',
        },
        // §7.4 trust tier — TrustTierBadge dot
        trust: {
          0: 'var(--trust-0)',
          1: 'var(--trust-1)',
          2: 'var(--trust-2)',
        },
        // §7.4 sensitivity — SensitivityBadge dot
        sens: {
          public: 'var(--sens-public)',
          team: 'var(--sens-team)',
          restricted: 'var(--sens-restricted)',
        },
        // §7.5 per-section color — nav rail + active state
        sec: {
          setup: 'var(--sec-setup)',
          interview: 'var(--sec-interview)',
          twin: 'var(--sec-twin)',
          settings: 'var(--sec-settings)',
          manager: 'var(--sec-manager)',
        },
      },
      fontFamily: {
        mono: ['DM Mono', 'ui-monospace', 'monospace'],
        body: ['Hanken Grotesk', 'system-ui', 'sans-serif'],
      },
      borderRadius: {
        xl: 'var(--r-xl)',
        lg: 'var(--r-lg)',
        md: 'var(--r-md)',
        sm: 'var(--r-sm)',
        btn: 'var(--r-btn)',
      },
      boxShadow: {
        elev: 'var(--elev)',
        'elev-hi': 'var(--elev-hi)',
      },
      backgroundImage: {
        'glass-card': 'var(--card-bg)',
        'glass-tray': 'var(--tray-bg)',
        screen: 'var(--screen-bg)',
        'btn-primary': 'var(--btn-primary)', // §3 terracota
      },
      spacing: {
        grid: '16px',
        card: '16px',
        'card-lg': '18px',
        tray: '22px',
      },
      // Quiet motion (§6): the active-session dot blinks. Ambient, gated with
      // motion-reduce in the component.
      keyframes: {
        blink: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.3' },
        },
      },
      animation: {
        blink: 'blink 1.4s ease-in-out infinite',
      },
    },
  },
  plugins: [],
} satisfies Config;
