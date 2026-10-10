/**
 * Initial theme detection. Loaded synchronously in <head> so the dark class
 * is set before first paint (prevents a light-mode flash).
 */
if (localStorage.theme === 'dark' || (!('theme' in localStorage) && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
    document.documentElement.classList.add('dark');
} else {
    document.documentElement.classList.remove('dark');
}
