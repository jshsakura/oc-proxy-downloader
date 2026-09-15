<script>
  import { createEventDispatcher } from "svelte";
  import { t } from "./i18n.js";
  import { modalFocus } from "./modal.js";
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
  <div class="modal-backdrop">
    <div
      class="modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-modal-title"
      tabindex="-1"
      use:modalFocus={{ onEscape: handleCancel }}
    >
      <div class="modal-header">
        <div class="modal-title-group">
          {#if icon}
            <span class="modal-icon">{@html icon}</span>
          {/if}
          <h2 id="confirm-modal-title">{title || $t("confirm_title")}</h2>
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
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.5);
    backdrop-filter: blur(4px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 20000; /* Set higher than SettingsModal (10000) */
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

  .modal-body p {
    margin: 0;
    color: var(--text-primary);
    font-size: 0.875rem;
    line-height: 1.5;
  }

  .modal-actions {
    padding: 0.65rem 1.25rem 0.85rem;
    display: flex;
    gap: 0.5rem;
    justify-content: flex-end;
  }

  .modal-icon {
    font-size: 1.25rem;
    margin-right: 0.35rem;
    display: inline-flex;
    align-items: center;
  }

  .modal-icon :global(svg) {
    width: 18px;
    height: 18px;
  }
</style>
