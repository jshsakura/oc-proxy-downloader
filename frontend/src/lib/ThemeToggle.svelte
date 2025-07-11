<script>
  import { onMount } from 'svelte';

  let isDarkMode;

  onMount(() => {
    isDarkMode = localStorage.getItem('theme') === 'dark' || 
                 (!('theme' in localStorage) && window.matchMedia('(prefers-color-scheme: dark)').matches);
    updateTheme();
  });

  function toggleTheme() {
    isDarkMode = !isDarkMode;
    localStorage.setItem('theme', isDarkMode ? 'dark' : 'light');
    updateTheme();
  }

  function updateTheme() {
    if (isDarkMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }
</script>

<button on:click={toggleTheme} class="theme-toggle">
  {#if isDarkMode}
    <span>☀️</span>
  {:else}
    <span>🌙</span>
  {/if}
</button>


