import { writable } from 'svelte/store';

const createThemeStore = () => {
  // Get initial theme from localStorage or system preference
  const initialTheme = typeof window !== 'undefined'
    ? localStorage.getItem('theme') || 'system'
    : 'system'; // Default for SSR or if window is not defined

  const { subscribe, set } = writable(initialTheme);

  // Function to apply the theme class to the document element
  const applyThemeClass = (currentTheme) => {
    if (typeof document !== 'undefined') {
      // Remove all theme classes first
      document.documentElement.classList.remove('dark', 'dracula');

      if (currentTheme === 'dark') {
        document.documentElement.classList.add('dark');
      } else if (currentTheme === 'dracula') {
        document.documentElement.classList.add('dracula');
      } else if (currentTheme === 'system') {
        if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
          document.documentElement.classList.add('dark');
        } else {
          // Default to light if system is not dark
        }
      }
    }
  };

  // Subscribe to changes in the store
  subscribe(value => {
    if (typeof window !== 'undefined') {
      localStorage.setItem('theme', value); // Save to localStorage
      applyThemeClass(value); // Apply the class
    }
  });

  // Immediately apply the initial theme class when the store is created
  applyThemeClass(initialTheme);

  return {
    subscribe,
    set,
  };
};

export const theme = createThemeStore();