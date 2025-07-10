<script>
  import { createEventDispatcher } from "svelte";
  import { t } from "./i18n.js";

  // --- Icons ---
  const icons = {
    lock: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-lock"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>',
    x: '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-x"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>',
  };

  export let showModal;
  let passwordInput = "";

  const dispatch = createEventDispatcher();

  function closeModal() {
    showModal = false;
    dispatch("close");
  }

  function handleSave() {
    dispatch("passwordSet", { password: passwordInput });
    closeModal();
  }
</script>

{#if showModal}
  <div
    class="modal-backdrop"
    role="button"
    tabindex="0"
    on:click={closeModal}
    on:keydown={(e) => {
      if (e.key === "Enter" || e.key === " ") closeModal();
      if (e.key === "Escape") closeModal();
    }}
  >
    <div class="modal" on:click|stopPropagation>
      <div class="modal-header">
        <div class="modal-title-group">
          {@html icons.lock}
          <h2>{$t("password_modal_title")}</h2>
        </div>
        <button class="button-icon close-button" on:click={closeModal}
          >{@html icons.x}</button
        >
      </div>
      <div class="form-group">
        <input
          id="password-input"
          type="text"
          class="input"
          placeholder={$t("password_placeholder")}
          bind:value={passwordInput}
          on:keydown={(e) => {
            if (e.key === "Enter") handleSave();
          }}
        />
      </div>
      <div class="modal-actions">
        <button on:click={closeModal} class="button button-secondary"
          >{$t("button_cancel")}</button
        >
        <button on:click={handleSave} class="button button-primary"
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
    border: none;
    display: flex;
    justify-content: center;
    align-items: center;
    z-index: 1000;
  }
  .modal {
    background: var(--card-background);
    color: var(--text-primary);
    padding: 1.5rem; /* Adjusted padding */
    border-radius: 12px; /* Slightly more rounded corners */
    width: 400px;
    max-width: 90%;
    box-shadow: var(--shadow-large); /* Stronger shadow */
    display: flex;
    flex-direction: column;
  }
  .modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.5rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid var(--card-border);
  }
  .modal-title-group {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }
  .modal-header h2 {
    margin: 0;
    font-size: 1.5rem;
    color: var(--text-primary);
  }
  .modal-header svg {
    color: var(--primary-color);
  }
  .close-button {
    background: none;
    border: none;
    padding: 0.5rem;
    cursor: pointer;
    color: var(--text-secondary);
    border-radius: 5px;
    transition: background-color 0.2s ease;
  }
  .close-button:hover {
    background-color: var(--card-border);
  }
  .close-button svg {
    width: 1.2rem;
    height: 1.2rem;
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
    border-radius: 10px;
    background-color: var(--input-bg);
    color: var(--text-primary);
    font-size: 1rem;
    transition: border-color 0.2s ease;
  }
  .input:focus {
    outline: none;
    border-color: var(--primary-color);
  }
  .modal-actions {
    display: flex;
    justify-content: flex-end;
    gap: 1rem;
    padding-top: 1rem; /* Added padding-top */
    border-top: 1px solid var(--card-border); /* Added border-top */
  }
  .button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0.5rem 1rem;
    font-size: 0.9rem;
    font-weight: 600;
    border-radius: 10px;
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
    color: #fff;
  }
  .button-primary:hover {
    background-color: var(--primary-hover);
  }
  .button-secondary {
    background-color: var(
      --button-secondary-background,
      #e0e0e0
    ); /* Default light gray */
    color: var(--button-secondary-text); /* Default dark text */
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

    --shadow-large: 0 10px 20px rgba(0, 0, 0, 0.19),
      0 6px 6px rgba(0, 0, 0, 0.23);
  }

  :root[data-theme="dark"] {
    --button-background: #555; /* Dark gray for dark theme buttons */
    --button-hover-background: #777; /* Slightly lighter gray on hover */
    --button-text: #f0f0f0; /* Light text for dark theme buttons */

    --button-secondary-background: #555;
    --button-secondary-text: #f0f0f0;
    --button-secondary-background-hover: #777;

    --shadow-large: 0 10px 20px rgba(0, 0, 0, 0.3),
      0 6px 6px rgba(0, 0, 0, 0.25);
  }

  /* Apply the theme-specific text color to the button */
  .button {
    color: var(--button-text);
  }
</style>
