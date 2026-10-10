/** Previously set inline as tailwind.config for the Play CDN; see package.json. */
module.exports = {
  content: [
    './src/load_harness/templates/**/*.html',
    './src/load_harness/static/js/**/*.js',
  ],
  darkMode: 'class',
  // Metric bars render their width as w-pct-<0..100> (no style attribute, so
  // style-src needs no 'unsafe-inline'); the names are built in templates.
  safelist: [{ pattern: /^w-pct-\d+$/ }],
  theme: {
    extend: {
      width: Object.fromEntries(Array.from({ length: 101 }, (_, i) => [`pct-${i}`, `${i}%`])),
      colors: {
        primary: {
          50: '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          300: '#93c5fd',
          400: '#60a5fa',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          800: '#1e40af',
          900: '#1e3a8a',
          950: '#172554',
        },
      },
    },
  },
};
