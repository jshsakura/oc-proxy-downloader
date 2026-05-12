<script>
  import { t } from "../i18n.js";
  import ClipboardIcon from "../../icons/ClipboardIcon.svelte";
  import LockIcon from "../../icons/LockIcon.svelte";
  import UnlockIcon from "../../icons/UnlockIcon.svelte";
  import DownloadIcon from "../../icons/DownloadIcon.svelte";

  export let url;
  export let password;
  export let hasPassword;
  export let useProxy;
  export let proxyAvailable;
  export let isAddingDownload;
  export let pasteFromClipboard;
  export let openPasswordModal;
  export let addDownload;
</script>

<div class="add-download-section">
  <form on:submit|preventDefault={() => addDownload()} class="add-download-form">
    <div class="input-group-container">
      <div class="url-input-group">
        <input
          type="text"
          class="url-input"
          placeholder={$t("url_placeholder")}
          bind:value={url}
          disabled={isAddingDownload}
        />
        <div class="input-actions">
          <button
            type="button"
            class="input-action-btn"
            on:click={pasteFromClipboard}
            title={$t("paste_from_clipboard")}
            aria-label={$t("paste_from_clipboard")}
          >
            <ClipboardIcon />
          </button>
          <button
            type="button"
            class="input-action-btn"
            class:has-password={hasPassword}
            on:click={openPasswordModal}
            title={hasPassword ? $t("password_set") : $t("add_password")}
            aria-label={hasPassword ? $t("password_set") : $t("add_password")}
          >
            {#if hasPassword}
              <LockIcon />
            {:else}
              <UnlockIcon />
            {/if}
          </button>
        </div>
      </div>
      <div class="proxy-toggle-container">
        <button
          type="button"
          class="proxy-toggle-btn"
          class:active={useProxy}
          class:disabled={!proxyAvailable}
          on:click={() => proxyAvailable && (useProxy = !useProxy)}
          title={!proxyAvailable ? $t("proxy_not_available") : useProxy ? $t("proxy_enabled") : $t("proxy_disabled")}
          aria-label={useProxy ? $t("proxy_enabled") : $t("proxy_disabled")}
        >
          <div class="proxy-toggle-slider"></div>
          <div class="proxy-toggle-icons"></div>
        </button>
      </div>
      <button
        type="submit"
        class="button button-primary add-download-button"
        disabled={isAddingDownload}
      >
        {#if isAddingDownload}
          <div class="spinner"></div>
          {$t("adding_download")}
        {:else}
          <DownloadIcon />
          {$t("add_download")}
        {/if}
      </button>
    </div>
  </form>
</div>
