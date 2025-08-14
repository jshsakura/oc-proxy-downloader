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
      console.log(`[Theme] Applying theme: ${currentTheme}`);
      
      // Remove all theme classes first
      document.documentElement.classList.remove('dark', 'dracula');
      document.body.classList.remove('dark', 'dracula');

      if (currentTheme === 'dark') {
        document.documentElement.classList.add('dark');
        document.body.classList.add('dark');
      } else if (currentTheme === 'dracula') {
        document.documentElement.classList.add('dracula');
        document.body.classList.add('dracula');
      } else if (currentTheme === 'system') {
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
          console.log('[Theme] System preference detected as dark');
          document.documentElement.classList.add('dark');
          document.body.classList.add('dark');
        } else {
          console.log('[Theme] System preference detected as light or no media query support');
          // Default to light if system is not dark
        }
      } else {
        console.log(`[Theme] Light theme applied (theme: ${currentTheme})`);
        // Light theme - no classes needed
      }
    }
  };

  // Subscribe to changes in the store
  subscribe(value => {
    if (typeof window !== 'undefined') {
      console.log(`[Theme] Theme changed to: ${value}`);
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