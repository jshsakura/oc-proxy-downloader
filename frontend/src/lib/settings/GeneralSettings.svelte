<script>
  import { t } from "../i18n.js";
  import HomeIcon from "../../icons/HomeIcon.svelte";

  export let settings;
  export let environmentInfo;
  export let selectedLocale;
  export let selectedTheme;
  export let themeIcons;
  export let selectFolder;
  export let resetToDefault;
  export let changeLocale;

  // Local copy of theme icons if not provided
  const defaultThemeIcons = {
    light: "☀️",
    dark: "🌙",
    dracula: "🧛‍♂️",
    nord: "❄️",
    solarized: "🌞",
    monokai: "🎨",
    ocean: "🌊",
    system: "🖥️",
  };

  const icons = themeIcons || defaultThemeIcons;
</script>

<div class="form-group">
  <label for="download-path">{$t("settings_download_path")}</label>
  <div class="input-group path-input-group">
    <input
      id="download-path"
      type="text"
      class="input"
      bind:value={settings.download_path}
      placeholder={$t("download_path_placeholder_long")}
    />
    <div class="path-buttons">
      {#if !environmentInfo.is_docker}
        <button
          type="button"
          class="input-icon-button"
          on:click={selectFolder}
          title="폴더 선택"
          aria-label="폴더 선택"
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path
              d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-6l-2-2H5a2 2 0 0 0-2 2z"
            />
          </svg>
        </button>
      {/if}
      {#if environmentInfo.is_docker}
        <button
          type="button"
          class="input-icon-button reset-button"
          on:click={resetToDefault}
          title={$t("reset_to_default_tooltip")}
          aria-label={$t("reset_to_default_tooltip")}
        >
          <HomeIcon />
        </button>
      {/if}
    </div>
  </div>
</div>

<div class="form-group">
  <label for="locale">{$t("settings_language")}</label>
  <select
    id="locale"
    class="input"
    bind:value={selectedLocale}
    on:change={changeLocale}
  >
    <option value="ko">{$t("language_korean")}</option>
    <option value="en">{$t("language_english")}</option>
  </select>
</div>

<fieldset class="form-group">
  <legend>{$t("settings_theme")}</legend>
  <div class="theme-options">
    {#each Object.entries(icons) as [themeKey, icon]}
      <label class="theme-option-label">
        <input
          type="radio"
          bind:group={selectedTheme}
          value={themeKey}
          hidden
        />
        <div class="theme-card {themeKey}-theme-card" class:active={selectedTheme === themeKey}>
          <span class="theme-icon" aria-label={$t(`theme_${themeKey}_aria`)}
            >{icon}</span
          >
          <span>{$t(`theme_${themeKey}`)}</span>
        </div>
      </label>
    {/each}
  </div>
</fieldset>

<style>
  .form-group {
    margin-bottom: 1.5rem;
  }

  fieldset.form-group {
    border: none;
    padding: 0;
  }

  legend {
    display: block;
    margin-bottom: 0.5rem;
    font-weight: 600;
    font-size: 0.875rem;
    color: var(--text-primary);
    text-transform: uppercase;
    letter-spacing: 0.025em;
  }

  label {
    display: block;
    margin-bottom: 0.5rem;
    font-weight: 600;
    font-size: 0.875rem;
    color: var(--text-primary);
    text-transform: uppercase;
    letter-spacing: 0.025em;
  }

  .input-group {
    position: relative;
    display: flex;
    align-items: center;
  }

  .input {
    width: 100%;
    padding: 0.875rem 1rem;
    border: 2px solid var(--card-border, #e5e7eb);
    border-radius: 12px;
    background-color: var(--input-bg, #ffffff);
    color: var(--text-primary);
    font-size: 0.875rem;
    font-weight: 500;
    transition: all 0.2s ease;
  }

  .path-input-group .input {
    padding-right: 88px;
  }

  .path-buttons {
    position: absolute;
    right: 8px;
    display: flex;
    gap: 4px;
    align-items: center;
  }

  .input:focus {
    outline: none;
    border-color: var(--primary-color);
  }

  .input-icon-button {
    width: 2.5rem;
    height: 2.5rem;
    padding: 0;
    border: none !important;
    background-color: var(--input-bg);
    color: var(--text-secondary);
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: all 0.2s ease;
  }

  .input-icon-button:hover {
    background-color: var(--card-border);
    color: var(--text-primary);
  }

  .theme-options {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 0.5rem;
    margin-top: 0.75rem;
  }

  .theme-option-label {
    cursor: pointer;
    display: block;
  }

  .theme-card {
    border: 2px solid var(--card-border, #e5e7eb);
    border-radius: 8px;
    padding: 0.4rem 0.25rem;
    text-align: center;
    transition: all 0.2s ease;
    font-size: 0.75rem;
    font-weight: 500;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.25rem;
    background: var(--card-background);
    color: var(--text-primary);
  }

  .theme-card:hover {
    border-color: var(--primary-color);
  }

  .theme-card.active {
    border-color: var(--primary-color);
    background: rgba(var(--primary-color-rgb, 59, 130, 246), 0.05);
  }

  .theme-icon {
    font-size: 1.2rem;
  }

  .light-theme-card { background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%) !important; color: #1e293b !important; }
  .dark-theme-card { background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%) !important; color: #f8fafc !important; }
  .dracula-theme-card { background: linear-gradient(135deg, #282a36 0%, #21222c 100%) !important; color: #f8f8f2 !important; }
  .system-theme-card { background: linear-gradient(135deg, #64748b 0%, #475569 100%) !important; color: white !important; }
  .nord-theme-card { background: linear-gradient(135deg, #2e3440 0%, #3b4252 100%) !important; color: #eceff4 !important; }
  .solarized-theme-card { background: linear-gradient(135deg, #002b36 0%, #073642 100%) !important; color: #fdf6e3 !important; }
  .monokai-theme-card { background: linear-gradient(135deg, #272822 0%, #1e1f1c 100%) !important; color: #f8f8f2 !important; }
  .ocean-theme-card { background: linear-gradient(135deg, #0a192f 0%, #112240 100%) !important; color: #ccd6f6 !important; }

  @media (max-width: 640px) {
    .theme-options {
      grid-template-columns: repeat(4, 1fr);
    }
  }
</style>
