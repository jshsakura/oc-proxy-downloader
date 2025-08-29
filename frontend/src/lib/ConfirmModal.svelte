<script>
  import { createEventDispatcher } from "svelte";
  import { t } from "./i18n.js";
  import XIcon from "../icons/XIcon.svelte";
  export let showModal = false;
  export let message = "";
  export let confirmText = null; // 다국어 기본값 지원
  export let cancelText = null;
  export let icon = null;
  export let title = null;

  const dispatch = createEventDispatcher();

  function handleConfirm() {
    dispatch("confirm");
    showModal = false;
  }
  function handleCancel() {
    dispatch("cancel");
    showModal = false;
  }

  // 삭제/딜리트 버튼이면 빨강색
  $: isDelete =
    (confirmText || "").toLowerCase().includes("삭제") ||
    (confirmText || "").toLowerCase().includes("delete");
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
          class="button {isDelete ? 'button-danger' : 'button-primary'}"
          on:click={handleConfirm}>{confirmText || $t("button_confirm")}</button
        >
      </div>
    </div>
  </div>
{/if}

<style>
  .modal {
    max-height: 90vh;
    overflow-y: auto;
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
