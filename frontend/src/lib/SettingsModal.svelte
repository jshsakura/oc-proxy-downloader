<script>
  import { createEventDispatcher } from "svelte";
  import { theme } from "./theme.js";
  import { t } from "./i18n.js";

  export let showModal;
  export let currentSettings;

  let settings = { ...currentSettings };
  let selectedTheme = $theme;

  const dispatch = createEventDispatcher();

  function closeModal() {
    dispatch("close");
  }

  async function saveSettings() {
    theme.set(selectedTheme);
    settings.theme = selectedTheme; // Add theme to settings object
    try {
      const response = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });
      if (response.ok) {
        dispatch("settingsChanged", settings);
        closeModal();
      } else {
        alert("Failed to save settings");
      }
    } catch (error) {
      console.error("Error saving settings:", error);
      alert("Error saving settings");
    }
  }
</script>

{#if showModal}
  <div
    class="modal-backdrop"
    on:click={closeModal}
    role="button"
    tabindex="0"
    on:keydown={(e) => {
      if (e.key === "Escape") closeModal();
    }}
  >
    <div class="modal" on:click|stopPropagation>
      <h2>{$t("settings_title")}</h2>

      <div class="form-group">
        <label for="download-path">{$t("settings_download_path")}</label>
        <input
          id="download-path"
          type="text"
          class="input"
          bind:value={settings.download_path}
        />
      </div>

      <div class="form-group">
        <label>{$t("settings_theme")}</label>
        <div class="theme-options">
          <label class="theme-option-label">
            <input
              type="radio"
              bind:group={selectedTheme}
              value="light"
              hidden
            />
            <div class="theme-card light-theme-card">
              <span>{$t("theme_light")}</span>
            </div>
          </label>
          <label class="theme-option-label">
            <input
              type="radio"
              bind:group={selectedTheme}
              value="dark"
              hidden
            />
            <div class="theme-card dark-theme-card">
              <span>{$t("theme_dark")}</span>
            </div>
          </label>
          <label class="theme-option-label">
            <input
              type="radio"
              bind:group={selectedTheme}
              value="system"
              hidden
            />
            <div class="theme-card system-theme-card">
              <span>{$t("theme_system")}</span>
            </div>
          </label>
        </div>
      </div>

      <div class="modal-actions">
        <button on:click={closeModal} class="button button-secondary"
          >{$t("button_cancel")}</button
        >
        <button on:click={saveSettings} class="button button-primary"
          >{$t("button_save")}</button
        >
      </div>
    </div>
  </div>
{/if}

<style>
  .modal-backdrop {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.6);
    display: flex;
    justify-content: center;
    align-items: center;
    z-index: 1000;
  }
  .modal {
    background: var(--card-background);
    color: var(--text-primary);
    padding: 2rem;
    border-radius: 10px;
    width: 500px;
    max-width: 90%;
    box-shadow: var(--shadow-medium);
  }
  h2 {
    margin-top: 0;
    margin-bottom: 2rem;
    font-size: 1.8rem;
    color: var(--text-primary);
  }
  .form-group {
    margin-bottom: 1.5rem;
  }
  label {
    display: block;
    margin-bottom: 0.5rem;
    font-weight: 600;
    color: var(--text-secondary);
  }
  .input {
    width: 100%;
    padding: 0.75rem 1rem;
    border: 1px solid var(--input-border);
    border-radius: 10px; /* Changed to 10px */
    background-color: var(--input-bg);
    color: var(--text-primary);
    font-size: 1rem;
    transition: border-color 0.2s ease;
  }
  .input:focus {
    outline: none;
    border-color: var(--primary-color);
  }

  .theme-options {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 1rem;
  }
  .theme-option-label {
    cursor: pointer;
    display: block;
  }
  .theme-card {
    border: 2px solid var(--card-border);
    border-radius: 10px;
    padding: 0.5rem;
    text-align: center;
    transition: all 0.2s ease;
    color: var(--text-primary);
  }
  .theme-card:hover {
    border-color: var(--primary-color);
  }
  .theme-option-label input[type="radio"]:checked + .theme-card {
    border-color: var(--primary-color);
    box-shadow: 0 0 0 3px rgba(var(--primary-color-rgb), 0.3);
  }

  .light-theme-card {
    background-color: #f0f0f0;
    color: #333;
  }
  .dark-theme-card {
    background-color: #333;
    color: #f0f0f0;
  }
  .system-theme-card {
    background-color: var(
      --card-background
    ); /* Uses current theme background */
    color: var(--text-primary);
  }

  .modal-actions {
    display: flex;
    justify-content: flex-end;
    gap: 1rem;
  }
  .button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0.5rem 1rem;
    font-size: 0.9rem;
    font-weight: 600;
    border-radius: 10px; /* Changed to 10px */
    border: 1px solid transparent;
    cursor: pointer;
    transition:
      background-color 0.3s ease,
      border-color 0.3s ease,
      color 0.3s ease,
      box-shadow 0.3s ease;
    text-decoration: none;
    box-shadow: var(--shadow-light);
  }
  .button:hover {
    background-color: var(--button-hover-background);
  }
  .button-primary {
    background-color: var(--primary-color);
    color: #fff; /* White text for primary button */
  }
  .button-primary:hover {
    background-color: var(--primary-hover);
  }
  .button-secondary {
    background-color: var(
      --button-secondary-background,
      #e0e0e0
    ); /* Default light gray */
    color: var(--button-secondary-text, #333); /* Default dark text */
  }
  .button-secondary:hover {
    background-color: var(--button-secondary-background-hover, #c0c0c0);
  }

  /* Theme-specific variables for button backgrounds and text */
  :root[data-theme="light"] {
    --button-background: #f0f0f0; /* Light gray for light theme buttons */
    --button-hover-background: #d0d0d0; /* Slightly darker gray on hover */
    --button-text: #333; /* Dark text for light theme buttons */

    --button-secondary-background: #e0e0e0;
    --button-secondary-text: #333;
    --button-secondary-background-hover: #c0c0c0;
  }

  :root[data-theme="dark"] {
    --button-background: #555; /* Dark gray for dark theme buttons */
    --button-hover-background: #777; /* Slightly lighter gray on hover */
    --button-text: #f0f0f0; /* Light text for dark theme buttons */

    --button-secondary-background: #555;
    --button-secondary-text: #f0f0f0;
    --button-secondary-background-hover: #777;
  }

  /* Apply the theme-specific text color to the button */
  .button {
    color: var(--button-text);
  }
</style>
