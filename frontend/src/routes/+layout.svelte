<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import '../app.css';
  import { isLoggedIn } from '$lib/auth';

  let { children } = $props();

  $effect(() => {
    const path = $page.url.pathname;
    if (path === '/login') return;
    if (!isLoggedIn()) goto('/login');
  });
</script>

<div class="min-h-screen">
  {@render children()}
</div>
