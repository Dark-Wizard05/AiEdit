<script lang="ts">
  import type { VideoInfo } from '$lib/api';
  import { formatDuration } from '$lib/api';

  interface Props {
    video: VideoInfo | null;
    src: string | null;
    compareSrc?: string | null;
    compareMode?: boolean;
    loading?: boolean;
  }

  let {
    video,
    src,
    compareSrc = null,
    compareMode = false,
    loading = false
  }: Props = $props();

  let videoEl = $state<HTMLVideoElement | null>(null);
  let playing = $state(false);

  function togglePlay() {
    if (!videoEl) return;
    if (videoEl.paused) {
      videoEl.play();
      playing = true;
    } else {
      videoEl.pause();
      playing = false;
    }
  }
</script>

<div class="panel relative overflow-hidden">
  {#if loading}
    <div class="flex aspect-video items-center justify-center bg-black/40">
      <div class="flex flex-col items-center gap-3 text-zinc-400">
        <div class="h-10 w-10 animate-spin rounded-full border-2 border-accent border-t-transparent"></div>
        <p class="text-sm">Uploading video…</p>
      </div>
    </div>
  {:else if !src}
    <div class="flex aspect-video flex-col items-center justify-center gap-4 bg-gradient-to-br from-surface to-black p-8 text-center">
      <div class="flex h-16 w-16 items-center justify-center rounded-2xl bg-accent/15 text-3xl">🎬</div>
      <div>
        <p class="text-lg font-medium text-zinc-200">Drop a video to start editing</p>
        <p class="mt-1 text-sm text-zinc-500">MP4, MOV, MKV, AVI, WebM</p>
      </div>
    </div>
  {:else}
    <div class="relative aspect-video bg-black">
      {#if compareMode && compareSrc}
        <div class="grid h-full grid-cols-2">
          <div class="relative border-r border-zinc-700">
            <span class="absolute left-3 top-3 z-10 rounded-md bg-black/60 px-2 py-0.5 text-xs text-zinc-300">Original</span>
            <video class="h-full w-full object-contain" src={src} muted playsinline></video>
          </div>
          <div class="relative">
            <span class="absolute left-3 top-3 z-10 rounded-md bg-accent/80 px-2 py-0.5 text-xs text-white">Result</span>
            <video class="h-full w-full object-contain" src={compareSrc} muted playsinline></video>
          </div>
        </div>
      {:else}
        <video
          bind:this={videoEl}
          class="h-full w-full object-contain"
          {src}
          controls
          playsinline
          onplay={() => (playing = true)}
          onpause={() => (playing = false)}
        ></video>
      {/if}
    </div>

    {#if video}
      <div class="flex items-center justify-between border-t border-zinc-800 px-4 py-2 text-xs text-zinc-500">
        <span>{video.filename}</span>
        <span>
          {formatDuration(video.duration_sec)}
          {#if video.width && video.height}
            · {video.width}×{video.height}
          {/if}
        </span>
      </div>
    {/if}
  {/if}
</div>
