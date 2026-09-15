<script>
  import { createEventDispatcher } from "svelte";
  import { t } from "./i18n.js";
  import { modalFocus } from "./modal.js";
  import LockIcon from "../icons/LockIcon.svelte";
  import UnlockIcon from "../icons/UnlockIcon.svelte";
  import XIcon from "../icons/XIcon.svelte";

  export let showModal;
  let passwordInput = "";
  let showPassword = false;

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
  <div class="modal-backdrop">
    <div
      class="modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="password-modal-title"
      tabindex="-1"
      use:modalFocus={{ onEscape: closeModal }}
    >
      <div class="modal-header">
        <div class="modal-title-group">
          <LockIcon />
          <h2 id="password-modal-title">{$t("password_modal_title")}</h2>
        </div>
        <button class="button-icon close-button" on:click={closeModal} aria-label={$t("button_cancel")}>
          <XIcon />
        </button>
      </div>
      <div class="modal-body">
        <div class="password-field">
          <input
            id="password-input"
            type={showPassword ? "text" : "password"}
            class="input"
            aria-label={$t("password_modal_title")}
            placeholder={$t("password_placeholder")}
            bind:value={passwordInput}
            data-modal-autofocus
            on:keydown={(e) => {
              if (e.key === "Enter") handleSave();
            }}
          />
          <button
            type="button"
            class="password-visibility"
            aria-label={$t("login_password")}
            title={$t("login_password")}
            aria-pressed={showPassword}
            on:click={() => (showPassword = !showPassword)}
          >
            {#if showPassword}<UnlockIcon />{:else}<LockIcon />{/if}
          </button>
        </div>
      </div>
      <div class="modal-actions">
        <button on:click={closeModal} class="button button-secondary">
          {$t("button_cancel")}
        </button>
        <button on:click={handleSave} class="button button-primary">
          {$t("button_save")}
        </button>
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
    background: rgba(0, 0, 0, 0.5);
    backdrop-filter: blur(4px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 20000;
  }

  .modal {
    background: var(--card-background);
    border-radius: 12px;
    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
    width: 90vw;
    max-width: 400px;
    max-height: 90vh;
    overflow-y: auto;
    position: relative;
    z-index: 20001;
  }

  .modal-header {
    padding: 0.75rem 1.25rem;
    border-bottom: 1px solid var(--card-border);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .modal-title-group {
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }

  .modal-title-group :global(svg) {
    width: 16px;
    height: 16px;
    color: var(--primary-color);
  }

  .modal-title-group h2 {
    margin: 0;
    font-size: 1.05rem;
    font-weight: 600;
    color: var(--text-primary);
  }

  .close-button {
    background: none;
    border: none;
    cursor: pointer;
    color: var(--text-secondary);
    padding: 4px;
    width: 28px;
    height: 28px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 6px;
    transition: all 0.2s ease;
  }

  .close-button:hover {
    background: var(--bg-secondary);
    color: var(--text-primary);
  }

  .close-button :global(svg) {
    width: 14px;
    height: 14px;
  }

  .modal-body {
    padding: 1rem 1.25rem;
  }

  .input {
    width: 100%;
    padding: 0.5rem 0.75rem;
    border: 1px solid var(--card-border);
    border-radius: 6px;
    background: var(--card-background);
    color: var(--text-primary);
    font-size: 0.85rem;
    transition: all 0.2s ease;
  }

  .password-field {
    position: relative;
  }

  .password-field .input {
    padding-right: 2.75rem;
  }

  .password-visibility {
    position: absolute;
    inset-inline-end: 0.25rem;
    top: 50%;
    width: 2rem;
    height: 2rem;
    padding: 0;
    transform: translateY(-50%);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 0;
    border-radius: 6px;
    background: transparent;
    color: var(--text-secondary);
    cursor: pointer;
  }

  .password-visibility:hover {
    background: var(--bg-secondary);
    color: var(--text-primary);
  }

  .password-visibility:focus-visible {
    outline: none;
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary-color) 35%, transparent);
  }

  .password-visibility :global(svg) {
    width: 1rem;
    height: 1rem;
  }

  .input:focus {
    outline: none;
    border-color: var(--primary-color);
    box-shadow: 0 0 0 3px rgba(116, 75, 223, 0.1);
  }

  .input::placeholder {
    color: var(--text-secondary);
  }

  .modal-actions {
    padding: 0.65rem 1.25rem 0.85rem;
    display: flex;
    gap: 0.5rem;
    justify-content: flex-end;
  }

</style>
