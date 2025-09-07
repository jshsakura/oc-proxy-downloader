<script>
  import { createEventDispatcher } from "svelte";
  import { t } from "./i18n.js";
  import XIcon from "../icons/XIcon.svelte";
  export let showModal = false;
  export let message = "";
  export let confirmText = null;
  export let cancelText = null;
  export let icon = null;
  export let title = null;
  export let isDeleteAction = false;

  const dispatch = createEventDispatcher();

  function handleConfirm() {
    dispatch("confirm");
    showModal = false;
  }
  function handleCancel() {
    dispatch("cancel");
    showModal = false;
  }
</script>

{#if showModal}
  <div class="modal-backdrop" role="dialog" aria-modal="true" tabindex="0">
    <div class="modal" on:click|stopPropagation on:keydown={() => {}} role="dialog" tabindex="-1">
      <div class="modal-header">
        <div class="modal-title-group">
          {#if icon}
            <span class="modal-icon">{@html icon}</span>
          {/if}
          <h2>{title || $t("confirm_title")}</h2>
        </div>
        <button
          class="button-icon close-button"
          on:click={handleCancel}
          aria-label={$t("button_cancel")}
        >
          <XIcon />
        </button>
      </div>
      <div class="modal-body">
        <p>{message}</p>
      </div>
      <div class="modal-actions">
        <button class="button button-secondary" on:click={handleCancel}
          >{cancelText || $t("button_cancel")}</button
        >
        <button
          class="button {isDeleteAction ? 'button-danger' : 'button-primary'}"
          on:click={handleConfirm}>{confirmText || $t("button_confirm")}</button
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
    width: 100vw;
    height: 100vh;
    background: rgba(0, 0, 0, 0.5);
    backdrop-filter: blur(4px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 20000; /* SettingsModal(10000)보다 높게 설정 */
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

  .modal-body p {
    margin: 0;
    color: var(--text-primary);
    line-height: 1.5;
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

  .modal-icon {
    font-size: 2rem;
    margin-right: 0.5rem;
  }
  
  .button-danger {
    color: #fff;
    background: #e53935;
    border: none;
    transition: background 0.2s;
  }
  
  .button-danger:hover {
    background: #b71c1c;
  }
</style>
