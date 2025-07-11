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
    <div class="modal" on:click|stopPropagation>
      <div class="modal-header">
        <div class="modal-title-group">
          <LockIcon />
          <h2>{$t("password_modal_title")}</h2>
        </div>
        <button class="button-icon close-button" on:click={closeModal}
          ><XIcon /></button
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
        <div class="modal-actions-buttons">
          <button on:click={closeModal} class="button button-secondary"
            >{$t("button_cancel")}</button
          >
          <button on:click={handleSave} class="button button-primary"
            >{$t("button_save")}</button
          >
        </div>
      </div>
    </div>
  </div>
{/if}

<style>
  .modal {
    max-height: 90vh;
    overflow-y: auto;
  }
</style>
