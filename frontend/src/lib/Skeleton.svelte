<script>
  export let width = '100%';
  export let height = '1rem';
  export let radius = '4px';
  export let circle = false;
</script>

<span
  class="skeleton"
  style="width:{width}; height:{height}; border-radius:{circle ? '50%' : radius};"
  aria-hidden="true"
></span>

<style>
  .skeleton {
    display: block;
    flex-shrink: 0;
  }
</style>
