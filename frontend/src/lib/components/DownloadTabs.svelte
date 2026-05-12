<script>
  import { t } from "../i18n.js";
  import DownloadIcon from "../../icons/DownloadIcon.svelte";
  import CheckCircleIcon from "../../icons/CheckCircleIcon.svelte";
  import SearchIcon from "../../icons/SearchIcon.svelte";
  import CloseIcon from "../../icons/CloseIcon.svelte";

  export let currentTab;
  export let workingCount;
  export let completedCount;
  export let onTabChange;
  export let searchExpanded;
  export let searchQuery;
  export let handleSearchInput;
  export let clearSearch;
  export let openSearch;
  export let closeSearch;
  export let searchInputEl;
</script>

<div class="tabs-container">
  <div class="tabs">
    <button
      class="tab"
      class:active={currentTab === "working"}
      on:click={() => onTabChange("working")}
      title={$t("tab_working")}
    >
      <span class="tab-icon"><DownloadIcon /></span>
      <span class="tab-label">{$t("tab_working")} ({workingCount})</span>
      <span class="tab-count">{workingCount}</span>
    </button>
    <button
      class="tab"
      class:active={currentTab === "completed"}
      on:click={() => onTabChange("completed")}
      title={$t("tab_completed")}
    >
      <span class="tab-icon"><CheckCircleIcon /></span>
      <span class="tab-label">{$t("tab_completed")} ({completedCount})</span>
      <span class="tab-count">{completedCount}</span>
    </button>
  </div>

  <!-- 검색 필터 -->
  <div class="search-actions" class:expanded={searchExpanded}>
    <button
      type="button"
      class="button-icon search-toggle-btn"
      on:click={openSearch}
      title={$t("search_placeholder")}
      aria-label={$t("search_placeholder")}
    >
      <SearchIcon />
    </button>
    <div class="search-container">
      <input
        type="text"
        class="search-input"
        placeholder={$t("search_placeholder")}
        bind:this={searchInputEl}
        bind:value={searchQuery}
        on:input={handleSearchInput}
        on:focus={() => (searchExpanded = true)}
      />
      {#if searchQuery && searchQuery.trim()}
        <button
          type="button"
          class="search-clear-btn"
          on:click={clearSearch}
          title="검색어 지우기"
          aria-label="검색어 지우기"
        >
          <CloseIcon />
        </button>
      {:else if searchExpanded}
        <button
          type="button"
          class="search-clear-btn search-collapse-btn"
          on:click={closeSearch}
          title="검색창 닫기"
          aria-label="검색창 닫기"
        >
          <CloseIcon />
        </button>
      {:else}
        <div class="search-icon">
          <SearchIcon />
        </div>
      {/if}
    </div>
  </div>
</div>
