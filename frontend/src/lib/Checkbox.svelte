<script>
  // Reusable, theme-aware checkbox.
  // A visually-hidden native input keeps it accessible; the styled box
  // provides the visual. Supports an indeterminate state for "select all".
  export let checked = false;
  export let indeterminate = false;
  export let ariaLabel = "";

  let inputEl;

  // Keep the DOM indeterminate flag in sync (it can't be set via attribute).
  $: if (inputEl) inputEl.indeterminate = indeterminate;
</script>

<label class="checkbox" class:is-indeterminate={indeterminate}>
  <input
    bind:this={inputEl}
    type="checkbox"
    class="checkbox-input"
    bind:checked
    aria-label={ariaLabel}
    on:change
  />
  <span class="checkbox-box" aria-hidden="true">
    {#if indeterminate}
      <span class="checkbox-dash"></span>
    {:else}
      <svg class="checkbox-check" viewBox="0 0 16 16" fill="none">
        <path
          d="M3.5 8.5l3 3 6-7"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
    {/if}
  </span>
</label>

<style>
  .checkbox {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    line-height: 0;
  }

  /* Visually hidden but still focusable/accessible. */
  .checkbox-input {
    position: absolute;
    width: 1px;
    height: 1px;
    margin: -1px;
    padding: 0;
    border: 0;
    overflow: hidden;
    clip: rect(0 0 0 0);
    clip-path: inset(50%);
    white-space: nowrap;
  }

  .checkbox-box {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    border: 2px solid var(--card-border);
    border-radius: 5px;
    background: transparent;
    color: #fff;
    transition: background-color 0.15s ease, border-color 0.15s ease,
      box-shadow 0.15s ease, transform 0.1s ease;
  }

  .checkbox:hover .checkbox-box {
    border-color: var(--primary-color);
  }

  .checkbox-input:checked + .checkbox-box,
  .checkbox.is-indeterminate .checkbox-box {
    background: var(--primary-color);
    border-color: var(--primary-color);
  }

  .checkbox-input:active + .checkbox-box {
    transform: scale(0.92);
  }

  /* Focus ring for keyboard users. */
  .checkbox-input:focus-visible + .checkbox-box {
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary-color) 35%, transparent);
  }

  .checkbox-check {
    width: 14px;
    height: 14px;
    opacity: 0;
    transform: scale(0.6);
    transition: opacity 0.15s ease, transform 0.15s ease;
  }

  .checkbox-input:checked + .checkbox-box .checkbox-check {
    opacity: 1;
    transform: scale(1);
  }

  .checkbox-dash {
    width: 10px;
    height: 2px;
    border-radius: 1px;
    background: #fff;
  }
</style>
