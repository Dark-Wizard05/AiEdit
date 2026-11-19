<script lang="ts">
  interface Props {
    message: string;
    hasPremium?: boolean;
    onUpgrade?: () => void;
  }

  let { message, hasPremium = false, onUpgrade }: Props = $props();
</script>

<div
  class="rounded-xl border border-violet-500/40 bg-gradient-to-br from-violet-950/50 to-surface p-4 shadow-glow"
>
  <div class="mb-2 flex items-center gap-2">
    <span class="rounded-md bg-violet-600/30 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-violet-200">
      Premium edit
    </span>
    <p class="text-sm font-semibold text-white">Needs Premium plan</p>
  </div>

  <p class="text-sm leading-relaxed text-zinc-300">{message}</p>

  <ul class="mt-3 space-y-1 text-xs text-zinc-400">
    <li>✦ AI-generated FFmpeg / MoviePy scripts</li>
    <li>✦ Slow-mo, zoom, replay, kill-cam montages</li>
    <li>✦ ₹199/week · 12 edits/day (boostable +50%)</li>
  </ul>

  <div class="mt-4">
    {#if hasPremium}
      <p class="text-xs text-emerald-400">Your Premium plan covers this — hit Apply Edit.</p>
    {:else}
      <button type="button" class="btn-primary text-xs" onclick={() => onUpgrade?.()}>
        Upgrade in Profile · ₹199/week
      </button>
    {/if}
  </div>
</div>
