<script lang="ts">
  import type { ParseResponse } from '$lib/api';
  import { operationLabel } from '$lib/api';
  import PremiumUpsell from './PremiumUpsell.svelte';

  interface Props {
    plan: ParseResponse | null;
    confidence?: number;
    hasPremium?: boolean;
    onUpgrade?: () => void;
  }

  let { plan, confidence, hasPremium = false, onUpgrade }: Props = $props();

  function paramEntries(params: Record<string, unknown>): [string, string][] {
    return Object.entries(params)
      .filter(([k, v]) => v != null && v !== '' && !k.startsWith('_'))
      .map(([k, v]) => [k.replace(/_/g, ' '), String(v)]);
  }
</script>

<div class="panel flex h-full flex-col p-5">
  <h2 class="mb-4 text-sm font-semibold uppercase tracking-wider text-zinc-400">Edit Plan</h2>

  {#if !plan}
    <div class="flex flex-1 flex-col items-center justify-center gap-2 text-center text-zinc-500">
      <p class="text-3xl opacity-40">✨</p>
      <p class="text-sm">Describe your edit below.<br />The parsed plan will appear here.</p>
    </div>
  {:else}
    <div class="space-y-4">
      <div>
        <p class="text-xs text-zinc-500">Operation</p>
        <p class="mt-0.5 text-base font-semibold text-white">{operationLabel(plan.operation)}</p>
        <p class="mt-1 text-sm text-zinc-400">{plan.summary}</p>
      </div>

      {#if paramEntries(plan.parameters).length > 0}
        <div class="space-y-2 rounded-lg bg-surface p-3">
          {#each paramEntries(plan.parameters) as [key, val]}
            <div class="flex justify-between gap-3 text-sm">
              <span class="capitalize text-zinc-500">{key}</span>
              <span class="truncate text-right font-medium text-zinc-200">{val}</span>
            </div>
          {/each}
        </div>
      {/if}

      {#if confidence != null}
        <div class="flex items-center gap-2">
          <span class="text-xs text-zinc-500">Confidence</span>
          <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-zinc-800">
            <div
              class="h-full rounded-full bg-gradient-to-r from-emerald-600 to-emerald-400"
              style="width: {Math.round(confidence * 100)}%"
            ></div>
          </div>
          <span class="text-xs font-medium text-emerald-400">{Math.round(confidence * 100)}%</span>
        </div>
      {/if}

      {#if plan.needs_clarification}
        <div class="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
          {plan.clarification_question ?? 'More details needed.'}
        </div>
      {/if}

      {#if plan.warnings?.length}
        {#each plan.warnings as w}
          <p class="text-xs text-amber-400/90">⚠ {w}</p>
        {/each}
      {/if}

      {#if plan.premium_required}
        <PremiumUpsell
          message={plan.premium_message ?? plan.user_message ?? plan.summary}
          {hasPremium}
          {onUpgrade}
        />
      {:else if plan.validation && !plan.validation.ok}
        <div class="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">
          {plan.user_message || (plan.validation.errors ?? []).join('; ') || 'Validation failed'}
        </div>
      {/if}
    </div>
  {/if}
</div>
