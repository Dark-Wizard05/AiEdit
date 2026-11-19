<script lang="ts">
  import { onMount } from 'svelte';
  import UserMenu from '$lib/components/UserMenu.svelte';
  import {
    boostPremium50,
    fetchProfile,
    renewPlan,
    revertBoost,
    subscribePlan,
    upgradeToPremium,
    type UserProfile
  } from '$lib/api';

  let profile = $state<UserProfile | null>(null);
  let loading = $state(true);
  let actionMsg = $state<string | null>(null);
  let error = $state<string | null>(null);

  onMount(async () => {
    try {
      profile = await fetchProfile();
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to load profile';
    } finally {
      loading = false;
    }
  });

  async function act(fn: () => Promise<UserProfile>, ok: string) {
    error = null;
    actionMsg = null;
    try {
      profile = await fn();
      actionMsg = ok;
    } catch (e) {
      error = e instanceof Error ? e.message : 'Action failed';
    }
  }

</script>

<div class="min-h-screen bg-[#0a0a0f]">
  <header class="border-b border-zinc-800/80 bg-[#0a0a0f]/90 backdrop-blur-md">
    <div class="mx-auto flex max-w-3xl items-center justify-between px-4 py-4">
      <a href="/studio" class="text-sm text-zinc-400 hover:text-white">← Studio</a>
      <h1 class="text-lg font-bold text-white">Your profile</h1>
      <UserMenu {profile} showPlan={false} showProfileLink={false} />
    </div>
  </header>

  <main class="mx-auto max-w-3xl px-4 py-8">
    {#if loading}
      <p class="text-zinc-500">Loading…</p>
    {:else if profile}
      {#if error}
        <p class="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">{error}</p>
      {/if}
      {#if actionMsg}
        <p class="mb-4 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
          {actionMsg}
        </p>
      {/if}

      <div class="panel p-6">
        <p class="text-sm text-zinc-500">Director</p>
        <p class="text-xl font-semibold text-white">{profile.display_name}</p>
        <p class="text-sm text-zinc-400">{profile.email}</p>
      </div>

      <div class="panel mt-4 p-6">
        <h2 class="text-sm font-semibold uppercase tracking-wider text-zinc-400">Weekly plan</h2>

        {#if profile.subscription_status === 'none'}
          <p class="mt-2 text-zinc-300">No active plan — pick one to start editing.</p>
          <div class="mt-4 grid gap-3 sm:grid-cols-2">
            <button
              class="rounded-xl border border-zinc-700 p-4 text-left hover:border-accent"
              onclick={() => act(() => subscribePlan('normal'), 'Normal plan activated!')}
            >
              <p class="font-semibold text-white">Normal</p>
              <p class="text-2xl font-bold text-violet-300">₹79<span class="text-sm font-normal text-zinc-500">/week</span></p>
              <p class="mt-1 text-xs text-zinc-500">5 edits/day · built-in features</p>
            </button>
            <button
              class="rounded-xl border border-violet-500/40 bg-violet-950/30 p-4 text-left hover:border-accent"
              onclick={() => act(() => subscribePlan('premium'), 'Premium plan activated!')}
            >
              <p class="font-semibold text-white">Premium ✨</p>
              <p class="text-2xl font-bold text-violet-300">₹199<span class="text-sm font-normal text-zinc-500">/week</span></p>
              <p class="mt-1 text-xs text-zinc-500">12 edits/day · AI code-gen edits</p>
            </button>
          </div>
        {:else if profile.subscription_status === 'expired'}
          <p class="mt-2 text-amber-200">Plan expired. Renew to continue.</p>
          <button
            class="btn-primary mt-4"
            onclick={() =>
              act(
                () => renewPlan(profile!.plan.boost_count > 0),
                'Plan renewed!'
              )}
          >
            Renew week
          </button>
        {:else}
          <div class="mt-3 flex flex-wrap items-center gap-2">
            <span class="rounded-full bg-violet-600/30 px-3 py-1 text-sm font-medium text-violet-200">
              {profile.plan.name ?? profile.plan.kind}
            </span>
            <span class="text-zinc-400">₹{profile.plan.weekly_price_inr}/week</span>
            {#if profile.plan.codegen_enabled}
              <span class="text-xs text-emerald-400">Code-gen enabled</span>
            {/if}
          </div>

          <div class="mt-4 grid grid-cols-2 gap-4 text-sm">
            <div class="rounded-lg bg-surface p-3">
              <p class="text-zinc-500">Edits today</p>
              <p class="text-2xl font-bold text-white">
                {profile.usage.edits_today} / {profile.plan.daily_edit_limit}
              </p>
            </div>
            <div class="rounded-lg bg-surface p-3">
              <p class="text-zinc-500">Remaining</p>
              <p class="text-2xl font-bold" class:text-red-400={profile.usage.limit_reached}>
                {profile.usage.edits_remaining_today}
              </p>
            </div>
          </div>

          {#if profile.plan.week_ends_at}
            <p class="mt-3 text-xs text-zinc-500">
              Week ends {new Date(profile.plan.week_ends_at).toLocaleString()}
            </p>
          {/if}

          {#if profile.offers?.upgrade_to_premium}
            {@const o = profile.offers.upgrade_to_premium as { message: string; price_inr: number }}
            <div class="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/10 p-4">
              <p class="text-sm text-amber-100">{o.message}</p>
              <button
                class="btn-primary mt-3 text-xs"
                onclick={() => act(() => upgradeToPremium(), 'Upgraded to Premium for this week!')}
              >
                Upgrade to Premium · ₹{o.price_inr}
              </button>
            </div>
          {/if}

          {#if profile.offers?.boost_50}
            {@const b = profile.offers.boost_50 as {
              message: string;
              immediate_payment_inr: number;
              new_weekly_price_inr: number;
              new_daily_limit: number;
            }}
            <div class="mt-4 rounded-lg border border-violet-500/30 bg-violet-950/40 p-4">
              <p class="text-sm text-violet-100">{b.message}</p>
              <p class="mt-1 text-xs text-zinc-400">
                Pay ₹{b.immediate_payment_inr} now → ₹{b.new_weekly_price_inr}/week · {b.new_daily_limit} edits/day
              </p>
              <button
                class="btn-primary mt-3 text-xs"
                onclick={() => act(() => boostPremium50(), '+50% boost applied!')}
              >
                +50% limit · pay ₹{b.immediate_payment_inr}
              </button>
            </div>
          {/if}

          {#if profile.offers?.week_end_choice}
            {@const w = profile.offers.week_end_choice as {
              message: string;
              keep_boosted_price_inr: number;
              keep_boosted_limit: number;
              revert_price_inr: number;
              revert_limit: number;
            }}
            <div class="mt-4 rounded-lg border border-zinc-700 p-4">
              <p class="text-sm text-zinc-300">{w.message}</p>
              <div class="mt-3 flex flex-wrap gap-2">
                <button
                  class="btn-ghost text-xs"
                  onclick={() => act(() => renewPlan(true), 'Renewed with boosted plan')}
                >
                  Keep ₹{w.keep_boosted_price_inr} / {w.keep_boosted_limit} edits
                </button>
                <button
                  class="btn-ghost text-xs"
                  onclick={() => act(() => revertBoost(), 'Reverted to base plan pricing')}
                >
                  Revert to ₹{w.revert_price_inr} / {w.revert_limit} edits
                </button>
              </div>
            </div>
          {/if}
        {/if}
      </div>

      {#if profile.payments?.length}
        <div class="panel mt-4 p-6">
          <h2 class="text-sm font-semibold uppercase tracking-wider text-zinc-400">Recent payments</h2>
          <ul class="mt-3 space-y-2 text-sm">
            {#each profile.payments as p}
              <li class="flex justify-between text-zinc-400">
                <span>{p.payment_type.replace(/_/g, ' ')}</span>
                <span>₹{p.amount_inr}</span>
              </li>
            {/each}
          </ul>
          <p class="mt-3 text-[11px] text-zinc-600">Payments are simulated locally until Razorpay is connected.</p>
        </div>
      {/if}

      {#if profile.subscription_status === 'active' && profile.permissions.can_edit}
        <a href="/studio" class="btn-primary mt-6 inline-flex">Go edit videos →</a>
      {/if}
    {/if}
  </main>
</div>
