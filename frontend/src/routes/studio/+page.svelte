<script lang="ts">
  import { onMount } from 'svelte';
  import EditPlanPanel from '$lib/components/EditPlanPanel.svelte';
  import StagePipeline from '$lib/components/StagePipeline.svelte';
  import UserMenu from '$lib/components/UserMenu.svelte';
  import VideoPlayer from '$lib/components/VideoPlayer.svelte';
  import {
    downloadJobVideo,
    fetchProfile,
    fetchSystemStatus,
    getJob,
    jobVideoUrl,
    parsePrompt,
    submitJob,
    uploadReference,
    uploadVideo,
    videoStreamUrl,
    type JobStatus,
    type ParseResponse,
    type Preset,
    type SystemStatus,
    type UserProfile,
    type VideoInfo
  } from '$lib/api';
  import { goto } from '$app/navigation';

  const PROMPT_CHIPS = [
    'Trim from 0:05 to 0:30',
    'Slow motion 0.5x from 3s to 6s',
    'Crop to 9:16 for TikTok',
    'Fade in over 1 second',
    'Replace "GAME OVER" with "BOTH"',
    'Add a rain and storm atmosphere'
  ];

  let system = $state<SystemStatus | null>(null);
  let profile = $state<UserProfile | null>(null);
  let video = $state<VideoInfo | null>(null);
  let videoSrc = $state<string | null>(null);
  let resultSrc = $state<string | null>(null);
  let compareMode = $state(false);
  let preset = $state<Preset>('balanced');
  let prompt = $state('');
  let plan = $state<ParseResponse | null>(null);
  let job = $state<JobStatus | null>(null);
  let uploading = $state(false);
  let applying = $state(false);
  let parsing = $state(false);
  let error = $state<string | null>(null);
  let referenceIds = $state<string[]>([]);
  let referenceNames = $state<string[]>([]);
  let dragOver = $state(false);
  let downloading = $state(false);

  let pollTimer: ReturnType<typeof setInterval> | null = null;

  async function refreshProfile() {
    try {
      profile = await fetchProfile();
    } catch {
      /* keep last known profile */
    }
  }

  onMount(async () => {
    try {
      profile = await fetchProfile();
      if (profile.subscription_status !== 'active') {
        goto('/profile');
        return;
      }
      system = await fetchSystemStatus();
      preset = system.recommended_preset;
    } catch (e) {
      error = e instanceof Error ? e.message : 'Backend unreachable — start API on port 8000';
    }
  });

  async function handleVideoFile(file: File) {
    error = null;
    uploading = true;
    resultSrc = null;
    compareMode = false;
    job = null;
    plan = null;
    try {
      video = await uploadVideo(file);
      videoSrc = videoStreamUrl(video.video_id);
    } catch (e) {
      error = e instanceof Error ? e.message : 'Upload failed';
      video = null;
      videoSrc = null;
    } finally {
      uploading = false;
    }
  }

  function onFileInput(e: Event) {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) handleVideoFile(file);
    input.value = '';
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    dragOver = false;
    const file = e.dataTransfer?.files?.[0];
    if (file?.type.startsWith('video/')) handleVideoFile(file);
  }

  async function onReferenceInput(e: Event) {
    const input = e.target as HTMLInputElement;
    const files = input.files;
    if (!files) return;
    for (const file of Array.from(files)) {
      try {
        const ref = await uploadReference(file);
        referenceIds = [...referenceIds, ref.ref_id];
        referenceNames = [...referenceNames, ref.filename];
      } catch (e) {
        error = e instanceof Error ? e.message : 'Reference upload failed';
      }
    }
    input.value = '';
  }

  async function previewPlan() {
    if (!prompt.trim()) return;
    parsing = true;
    error = null;
    try {
      plan = await parsePrompt(prompt.trim());
    } catch (e) {
      error = e instanceof Error ? e.message : 'Parse failed';
    } finally {
      parsing = false;
    }
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function startPolling(jobId: string) {
    stopPolling();
    pollTimer = setInterval(async () => {
      try {
        job = await getJob(jobId);
        if (job.plan && !plan) plan = job.plan;
        if (job.state === 'done') {
          resultSrc = jobVideoUrl(jobId) + '?t=' + Date.now();
          compareMode = true;
          applying = false;
          stopPolling();
          await refreshProfile();
        } else if (job.state === 'error') {
          if (job.error_code === 'premium_required') {
            error = job.premium_message ?? job.error ?? 'Premium required';
          } else {
            error = job.error ?? 'Job failed';
          }
          if (job.plan) plan = job.plan as typeof plan;
          applying = false;
          stopPolling();
        }
      } catch (e) {
        error = e instanceof Error ? e.message : 'Poll failed';
        applying = false;
        stopPolling();
      }
    }, 1200);
  }

  async function applyEdit() {
    if (!video || !prompt.trim()) return;
    applying = true;
    error = null;
    resultSrc = null;
    compareMode = false;

    try {
      if (!plan) {
        plan = await parsePrompt(prompt.trim());
      }
      if (plan.needs_clarification) {
        error = plan.clarification_question ?? 'Please clarify your request';
        applying = false;
        return;
      }
      if (plan.premium_required && !profile?.permissions.codegen_enabled) {
        error = plan.premium_message ?? 'Premium plan required for this edit. Upgrade in Profile.';
        applying = false;
        return;
      }

      const useCodegen = !!(plan.premium_required && profile?.permissions.codegen_enabled);

      job = await submitJob(prompt.trim(), video.video_id, preset, referenceIds, useCodegen);
      startPolling(job.job_id);
    } catch (e) {
      error = e instanceof Error ? e.message : 'Apply failed';
      applying = false;
    }
  }

  function goProfile() {
    goto('/profile');
  }

  function useChip(text: string) {
    prompt = text;
    previewPlan();
  }

  async function downloadResult() {
    if (!job?.job_id) return;
    downloading = true;
    error = null;
    try {
      const name = video?.filename?.replace(/\.[^.]+$/, '') ?? 'aiedit';
      await downloadJobVideo(job.job_id, `${name}_edited.mp4`);
    } catch (e) {
      error = e instanceof Error ? e.message : 'Download failed';
    } finally {
      downloading = false;
    }
  }

  const running = $derived(applying || job?.state === 'running' || job?.state === 'queued');
  const confidence = $derived(
    plan?.metadata?.confidence != null ? Number(plan.metadata.confidence) : undefined
  );
</script>

<svelte:window />

<!-- Header -->
<header class="sticky top-0 z-50 border-b border-zinc-800/80 bg-[#0a0a0f]/90 backdrop-blur-md">
  <div class="mx-auto flex max-w-[1600px] items-center justify-between gap-4 px-4 py-3 sm:px-6">
    <div class="flex items-center gap-3">
      <div class="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-accent to-accent-glow text-lg shadow-glow">
        🎬
      </div>
      <div>
        <h1 class="text-lg font-bold tracking-tight text-white">AiEdit</h1>
        <p class="text-[11px] text-zinc-500">Prompt-based video editor</p>
      </div>
    </div>

    <div class="flex items-center gap-3">
      <UserMenu {profile} />

      <select
        bind:value={preset}
        class="rounded-lg border border-zinc-700 bg-surface-raised px-3 py-1.5 text-sm text-zinc-200 outline-none focus:border-accent"
      >
        <option value="fast">Fast</option>
        <option value="balanced">Balanced</option>
        <option value="quality">Quality</option>
      </select>

      {#if job?.state === 'done'}
        <button class="btn-primary text-sm" disabled={downloading} onclick={downloadResult}>
          {downloading ? '…' : 'Download MP4'}
        </button>
      {/if}
    </div>
  </div>
</header>

<main class="mx-auto max-w-[1600px] px-4 py-5 sm:px-6">
  {#if error}
    <div class="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
      {error}
      <button class="ml-2 underline opacity-70" onclick={() => (error = null)}>dismiss</button>
    </div>
  {/if}

  {#if system?.parser.warnings?.length}
    <div class="mb-4 rounded-lg border border-amber-500/20 bg-amber-500/5 px-4 py-2 text-xs text-amber-200/90">
      {system.parser.warnings[0]}
    </div>
  {/if}

  <!-- Upload drop zone wrapper -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="mb-5 {dragOver ? 'ring-2 ring-accent/50 rounded-xl' : ''}"
    ondragover={(e) => {
      e.preventDefault();
      dragOver = true;
    }}
    ondragleave={() => (dragOver = false)}
    ondrop={onDrop}
  >
    <div class="grid gap-5 lg:grid-cols-[1fr_340px]">
      <!-- Left: Video -->
      <div class="space-y-3">
        <div class="flex flex-wrap items-center gap-2">
          <label class="btn-ghost cursor-pointer text-xs">
            📁 Upload video
            <input type="file" accept="video/*" class="hidden" onchange={onFileInput} />
          </label>
          {#if resultSrc}
            <button
              class="chip {compareMode ? 'chip-active' : ''}"
              onclick={() => (compareMode = !compareMode)}
            >
              {compareMode ? 'Split view' : 'Single view'}
            </button>
          {/if}
        </div>

        <VideoPlayer {video} src={videoSrc} compareSrc={resultSrc} {compareMode} loading={uploading} />

        {#if job?.state === 'done'}
          <div class="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3">
            <div>
              <p class="text-sm font-medium text-emerald-100">Edit complete</p>
              <p class="text-xs text-emerald-200/80">
                Preview above (split view). Download your MP4 below.
                {#if profile}
                  · {profile.usage.edits_remaining_today} edit{profile.usage.edits_remaining_today === 1 ? '' : 's'} left today
                {/if}
              </p>
            </div>
            <button class="btn-primary text-sm" disabled={downloading} onclick={downloadResult}>
              {downloading ? 'Downloading…' : '⬇ Download MP4'}
            </button>
          </div>
        {/if}
      </div>

      <!-- Right: Plan + Pipeline -->
      <div class="flex flex-col gap-4">
        <EditPlanPanel
          {plan}
          confidence={confidence}
          hasPremium={profile?.permissions.codegen_enabled ?? false}
          onUpgrade={goProfile}
        />
        <StagePipeline
          stage={job?.stage ?? 'parse'}
          progress={job?.progress ?? 0}
          message={job?.message ?? (running ? 'Processing…' : 'Ready')}
          {running}
        />

        {#if system}
          <div class="panel p-4 text-xs text-zinc-500">
            <p class="font-medium text-zinc-400">System</p>
            <p class="mt-1">
              Parser: {system.parser.ollama_available ? `Ollama (${system.parser.ollama_model})` : 'Rule-based fallback'}
            </p>
            <p>Preset: {preset} · recommended {system.recommended_preset}</p>
          </div>
        {/if}
      </div>
    </div>
  </div>

  <!-- Prompt composer -->
  <div class="panel p-4 sm:p-5">
    <div class="mb-3 flex flex-wrap gap-2">
      {#each PROMPT_CHIPS as chip}
        <button class="chip" onclick={() => useChip(chip)}>{chip}</button>
      {/each}
    </div>

    <div class="flex flex-col gap-3 sm:flex-row sm:items-end">
      <div class="flex-1">
        <textarea
          bind:value={prompt}
          rows="2"
          placeholder='Describe your edit… e.g. Replace "Hello" with "Goodbye"'
          class="w-full resize-none rounded-xl border border-zinc-700 bg-surface px-4 py-3 text-sm text-zinc-100 placeholder:text-zinc-600 outline-none focus:border-accent/60 focus:ring-1 focus:ring-accent/30"
          onkeydown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) applyEdit();
          }}
        ></textarea>
      </div>

      <div class="flex shrink-0 gap-2">
        <label class="btn-ghost cursor-pointer" title="Reference images for object replacement">
          🖼 Ref
          <input type="file" accept="image/*" multiple class="hidden" onchange={onReferenceInput} />
        </label>
        <button class="btn-ghost" disabled={!prompt.trim() || parsing} onclick={previewPlan}>
          {parsing ? '…' : 'Preview plan'}
        </button>
        <button
          class="btn-primary min-w-[120px]"
          disabled={!video || !prompt.trim() || running || !profile?.permissions.can_edit}
          onclick={() => applyEdit()}
        >
          {running ? 'Processing…' : 'Apply Edit'}
        </button>
      </div>
    </div>

    {#if referenceNames.length}
      <div class="mt-2 flex flex-wrap gap-2">
        {#each referenceNames as name}
          <span class="rounded-full bg-surface px-2 py-0.5 text-xs text-zinc-400">📎 {name}</span>
        {/each}
      </div>
    {/if}

    <p class="mt-2 text-[11px] text-zinc-600">Ctrl+Enter to apply · Supports text, objects, hair, colors, atmosphere, commentary</p>
  </div>
</main>
