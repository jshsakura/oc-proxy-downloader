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
