<script lang="ts">
  import { goto } from '$app/navigation';
  import { authLogout, type UserProfile } from '$lib/api';

  interface Props {
    profile?: UserProfile | null;
    showPlan?: boolean;
    showProfileLink?: boolean;
  }

  let { profile = null, showPlan = true, showProfileLink = true }: Props = $props();

  async function logout() {
    await authLogout();
    goto('/login');
  }
</script>

<div class="flex items-center gap-2 sm:gap-3">
  {#if profile && showPlan}
    <a
      href="/profile"
      class="hidden rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300 hover:border-accent sm:inline"
    >
      {profile.plan.name ?? profile.plan.kind} · {profile.usage.edits_remaining_today} left today
    </a>
  {/if}
  {#if showProfileLink}
    <a href="/profile" class="btn-ghost text-xs py-1.5">Profile</a>
  {/if}
  <button type="button" class="text-xs text-zinc-500 hover:text-red-300" onclick={logout}>
    Log out
  </button>
</div>
