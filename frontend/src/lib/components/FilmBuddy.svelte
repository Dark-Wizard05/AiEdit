<script lang="ts">
  interface Props {
    mode?: 'idle' | 'email' | 'password' | 'success';
    message?: string;
  }

  let { mode = 'idle', message = "I'm Reel-y excited you're here!" }: Props = $props();

  const eyeOffset = $derived(mode === 'email' ? 'translate(4px, -2px)' : 'translate(0, 0)');
</script>

<div class="flex flex-col items-center">
  <!-- Clapper mascot (Tunnel Bear / AniLogin inspired) -->
  <div class="relative mb-4 select-none">
    <div
      class="relative flex h-32 w-32 items-center justify-center rounded-3xl bg-gradient-to-br from-zinc-800 to-zinc-950 shadow-card ring-2 ring-violet-500/30 transition-transform duration-300"
      class:scale-105={mode === 'password'}
    >
      <div class="text-5xl" class:opacity-30={mode === 'password'}>🎬</div>

      {#if mode !== 'password'}
        <div class="absolute inset-0 flex items-center justify-center gap-5 pt-2">
          <div class="h-5 w-5 rounded-full bg-white shadow-inner">
            <div
              class="h-2 w-2 rounded-full bg-zinc-900 transition-transform duration-200"
              style="transform: {eyeOffset}; margin: 6px"
            ></div>
          </div>
          <div class="h-5 w-5 rounded-full bg-white shadow-inner">
            <div
              class="h-2 w-2 rounded-full bg-zinc-900 transition-transform duration-200"
              style="transform: {eyeOffset}; margin: 6px"
            ></div>
          </div>
        </div>
        <div class="absolute bottom-8 left-1/2 h-1 w-6 -translate-x-1/2 rounded-full bg-zinc-600"></div>
      {:else}
        <div class="absolute text-4xl">🙈</div>
      {/if}
    </div>

    <!-- Speech bubble -->
    <div
      class="absolute -right-2 -top-2 max-w-[180px] rounded-2xl rounded-bl-sm border border-violet-500/30 bg-violet-950/90 px-3 py-2 text-xs leading-snug text-violet-100 shadow-glow"
    >
      {message}
    </div>
  </div>
  <p class="text-center text-sm font-medium text-zinc-400">Reel the Clapper · your edit buddy</p>
</div>
