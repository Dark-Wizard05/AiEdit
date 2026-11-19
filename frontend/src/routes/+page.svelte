<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { isLoggedIn } from '$lib/auth';

  onMount(() => {
    if (!isLoggedIn()) goto('/login');
    else goto('/profile');
  });
</script>

<p class="p-8 text-zinc-500">Redirecting…</p>
