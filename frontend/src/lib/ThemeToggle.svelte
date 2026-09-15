<script>
  import { theme } from './theme.js';
  import { t } from './i18n.js';
  import SunIcon from '../icons/SunIcon.svelte';
  import MoonIcon from '../icons/MoonIcon.svelte';

  function toggleTheme() {
    theme.set($theme === 'dark' ? 'light' : 'dark');
  }
</script>

<button
  type="button"
  on:click={toggleTheme}
  class="theme-toggle"
  aria-label={$theme === 'dark' ? $t('theme_light') : $t('theme_dark')}
  title={$theme === 'dark' ? $t('theme_light') : $t('theme_dark')}
>
  {#if $theme === 'dark'}
    <SunIcon />
  {:else}
    <MoonIcon />
  {/if}
</button>
