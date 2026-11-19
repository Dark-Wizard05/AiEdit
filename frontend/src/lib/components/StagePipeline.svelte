<script lang="ts">
  interface Props {
    stage: string;
    progress: number;
    message: string;
    running: boolean;
  }

  let { stage, progress, message, running }: Props = $props();

  const steps = [
    { id: 'parse', label: 'Parse' },
    { id: 'validate', label: 'Validate' },
    { id: 'execute', label: 'Apply' },
    { id: 'export', label: 'Export' },
    { id: 'done', label: 'Done' }
  ];

  function stepState(id: string): 'done' | 'active' | 'pending' {
    const order = steps.map((s) => s.id);
    const cur = order.indexOf(stage);
    const idx = order.indexOf(id);
    if (stage === 'done' || stage === 'error') {
      if (id === 'done' && stage === 'done') return 'done';
      if (idx < cur || stage === 'done') return idx <= 3 ? 'done' : 'pending';
    }
    if (idx < cur) return 'done';
    if (idx === cur || (stage === 'queued' && id === 'parse')) return running ? 'active' : 'pending';
    return 'pending';
  }
</script>

<div class="panel p-4">
  <div class="mb-3 flex items-center justify-between">
    <p class="text-xs font-semibold uppercase tracking-wider text-zinc-500">Pipeline</p>
    {#if running}
      <span class="text-xs text-accent">{Math.round(progress * 100)}%</span>
    {/if}
  </div>

  <div class="flex items-center gap-1">
    {#each steps as step, i}
      {@const state = stepState(step.id)}
      <div class="flex flex-1 items-center gap-1">
        <div
          class="flex h-7 flex-1 items-center justify-center rounded-md text-[10px] font-semibold uppercase tracking-wide transition
            {state === 'done' ? 'bg-emerald-500/20 text-emerald-400' : ''}
            {state === 'active' ? 'bg-accent/25 text-violet-200 shadow-glow' : ''}
            {state === 'pending' ? 'bg-zinc-800/60 text-zinc-600' : ''}"
        >
          {state === 'done' ? '✓' : step.label}
        </div>
        {#if i < steps.length - 1}
          <div class="h-px w-2 shrink-0 bg-zinc-700"></div>
        {/if}
      </div>
    {/each}
  </div>

  {#if message}
    <p class="mt-3 truncate text-xs text-zinc-400">{message}</p>
  {/if}

  {#if running}
    <div class="mt-2 h-1 overflow-hidden rounded-full bg-zinc-800">
      <div
        class="h-full rounded-full bg-gradient-to-r from-accent-muted to-accent-glow transition-all duration-300"
        style="width: {Math.max(4, progress * 100)}%"
      ></div>
    </div>
  {/if}
</div>
