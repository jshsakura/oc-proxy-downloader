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
      document.documentElement.classList.remove('dark', 'dracula', 'nord', 'solarized', 'monokai', 'ocean');
      document.body.classList.remove('dark', 'dracula', 'nord', 'solarized', 'monokai', 'ocean');

      if (currentTheme === 'dark') {
        document.documentElement.classList.add('dark');
        document.body.classList.add('dark');
      } else if (currentTheme === 'dracula') {
        document.documentElement.classList.add('dracula');
        document.body.classList.add('dracula');
      } else if (currentTheme === 'nord') {
        document.documentElement.classList.add('nord');
        document.body.classList.add('nord');
      } else if (currentTheme === 'solarized') {
        document.documentElement.classList.add('solarized');
        document.body.classList.add('solarized');
      } else if (currentTheme === 'monokai') {
        document.documentElement.classList.add('monokai');
        document.body.classList.add('monokai');
      } else if (currentTheme === 'ocean') {
        document.documentElement.classList.add('ocean');
        document.body.classList.add('ocean');
      } else if (currentTheme === 'system') {
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
          document.documentElement.classList.add('dark');
          document.body.classList.add('dark');
        }
      } else {
        // Light theme - no classes needed
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
