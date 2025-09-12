<script>
  import { createEventDispatcher, onMount, onDestroy } from "svelte";
  import { t } from "./i18n.js";
  import LockIcon from "../icons/LockIcon.svelte";
  import XIcon from "../icons/XIcon.svelte";

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

  onMount(() => {
    document.body.style.overflow = "hidden";
  });
  onDestroy(() => {
    document.body.style.overflow = "";
  });
</script>

{#if showModal}
  <div
    class="modal-backdrop"
    role="dialog"
    aria-label="Password"
    aria-modal="true"
    tabindex="0"
    on:click={closeModal}
    on:keydown={(e) => {
      if (e.key === "Escape") closeModal();
    }}
  >
    <div class="modal" on:click|stopPropagation on:keydown={() => {}} role="dialog" tabindex="-1">
      <div class="modal-header">
        <div class="modal-title-group">
          <LockIcon />
          <h2>{$t("password_modal_title")}</h2>
        </div>
        <button class="button-icon close-button" on:click={closeModal} aria-label={$t("button_cancel")}>
          <XIcon />
        </button>
      </div>
      <div class="modal-body">
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
    width: 100vw;
    height: 100vh;
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
    padding: 1.5rem 2rem 1rem 2rem;
    border-bottom: 1px solid var(--card-border);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .modal-title-group {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .modal-title-group h2 {
    margin: 0;
    font-size: 1.25rem;
    font-weight: 600;
    color: var(--text-primary);
  }

  .close-button {
    background: none;
    border: none;
    cursor: pointer;
    color: var(--text-secondary);
    padding: 0.5rem;
    border-radius: 6px;
    transition: all 0.2s ease;
  }

  .close-button:hover {
    background: var(--bg-secondary);
    color: var(--text-primary);
  }

  .modal-body {
    padding: 1.5rem 2rem;
  }

  .input {
    width: 100%;
    padding: 0.75rem 1rem;
    border: 1px solid var(--card-border);
    border-radius: 8px;
    background: var(--card-background);
    color: var(--text-primary);
    font-size: 0.875rem;
    transition: all 0.2s ease;
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
    padding: 1rem 2rem 1.5rem 2rem;
    display: flex;
    gap: 0.75rem;
    justify-content: flex-end;
  }

  .button {
    padding: 0.75rem 1.5rem;
    border-radius: 8px;
    font-size: 0.875rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s ease;
    border: 1px solid transparent;
  }

  .button-secondary {
    background: var(--card-background);
    color: var(--text-secondary);
    border-color: var(--card-border);
  }

  .button-secondary:hover {
    background: var(--bg-secondary);
    color: var(--text-primary);
  }

  .button-primary {
    background: var(--primary-color);
    color: white;
  }

  .button-primary:hover {
    background: var(--primary-hover);
  }
</style>
