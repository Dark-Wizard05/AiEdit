<script lang="ts">
  import { goto } from '$app/navigation';
  import FilmBuddy from '$lib/components/FilmBuddy.svelte';
  import { onMount } from 'svelte';
  import { authLogin, authRegister, checkAuthApi, setAuth } from '$lib/api';

  let mode = $state<'login' | 'register'>('login');
  let apiReady = $state(true);
  let email = $state('');
  let password = $state('');
  let displayName = $state('');
  let focusField = $state<'idle' | 'email' | 'password'>('idle');
  let error = $state<string | null>(null);
  let loading = $state(false);
  let showPassword = $state(false);

  const buddyMessage = $derived(
    focusField === 'password'
      ? "Eyes shut! I won't peek at your password 🙈"
      : focusField === 'email'
        ? email.length > 0
          ? `Rolling out the red carpet for ${email.split('@')[0]}…`
          : 'Drop your director email here ✉️'
        : mode === 'register'
          ? 'New star on set? Love that energy! ⭐'
          : 'Welcome back, auteur. Ready to edit? 🍿'
  );

  onMount(async () => {
    apiReady = await checkAuthApi();
    if (!apiReady) {
      error =
        'Backend auth is offline or outdated. Restart it: py -m uvicorn backend.api:app --reload --host 127.0.0.1 --port 8000';
    }
  });

  async function submit(e: Event) {
    e.preventDefault();
    error = null;
    loading = true;
    try {
      const res =
        mode === 'login'
          ? await authLogin(email, password)
          : await authRegister(email, password, displayName || email.split('@')[0]);
      setAuth(res.token, res.user);
      goto('/profile');
    } catch (err) {
      error = err instanceof Error ? err.message : 'Something went wrong';
    } finally {
      loading = false;
    }
  }
</script>

<div class="flex min-h-screen items-center justify-center bg-[#0a0a0f] px-4 py-10">
  <div class="grid w-full max-w-4xl gap-8 lg:grid-cols-2 lg:items-center">
    <div class="hidden lg:block">
      <FilmBuddy mode={focusField} message={buddyMessage} />
      <ul class="mt-8 space-y-2 text-sm text-zinc-500">
        <li>🎞 Normal · ₹79/week · 5 edits/day · built-in tools</li>
        <li>✨ Premium · ₹199/week · 12 edits/day · AI code-gen</li>
        <li>🚀 Premium +50% boost when you need more juice</li>
      </ul>
    </div>

    <div class="panel p-6 sm:p-8">
      <div class="mb-6 lg:hidden">
        <FilmBuddy mode={focusField} message={buddyMessage} />
      </div>

      <h1 class="text-2xl font-bold text-white">
        {mode === 'login' ? 'Action! Log in' : 'Join the cast'}
      </h1>
      <p class="mt-1 text-sm text-zinc-500">AiEdit — prompt your cut, export the magic.</p>

      <div class="mt-4 flex gap-2">
        <button
          type="button"
          class="chip {mode === 'login' ? 'chip-active' : ''}"
          onclick={() => {
            mode = 'login';
            error = null;
          }}
        >
          Log in
        </button>
        <button
          type="button"
          class="chip {mode === 'register' ? 'chip-active' : ''}"
          onclick={() => {
            mode = 'register';
            error = null;
          }}
        >
          Sign up
        </button>
      </div>

      {#if !apiReady}
        <p class="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
          API not ready — signup will not work until you restart the backend on port 8000.
        </p>
      {/if}

      {#if error}
        <p class="mt-4 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
          {error}
        </p>
      {/if}

      <form class="mt-6 space-y-4" onsubmit={submit}>
        {#if mode === 'register'}
          <div>
            <label class="mb-1 block text-xs text-zinc-500" for="name">Stage name</label>
            <input
              id="name"
              bind:value={displayName}
              class="w-full rounded-xl border border-zinc-700 bg-surface px-4 py-3 text-sm outline-none focus:border-accent"
              placeholder="Director Aditya"
            />
          </div>
        {/if}
        <div>
          <label class="mb-1 block text-xs text-zinc-500" for="email">Email</label>
          <input
            id="email"
            type="email"
            bind:value={email}
            required
            class="w-full rounded-xl border border-zinc-700 bg-surface px-4 py-3 text-sm outline-none focus:border-accent"
            placeholder="you@studio.com"
            onfocus={() => (focusField = 'email')}
            onblur={() => (focusField = 'idle')}
          />
        </div>
        <div>
          <label class="mb-1 block text-xs text-zinc-500" for="password">Password</label>
          <div class="relative">
            <input
              id="password"
              type={showPassword ? 'text' : 'password'}
              bind:value={password}
              required
              minlength="6"
              class="w-full rounded-xl border border-zinc-700 bg-surface px-4 py-3 pr-11 text-sm outline-none focus:border-accent"
              placeholder="At least 6 characters"
              onfocus={() => (focusField = 'password')}
              onblur={() => (focusField = 'idle')}
            />
            <button
              type="button"
              class="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-1 text-zinc-500 hover:text-zinc-200"
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              onclick={() => (showPassword = !showPassword)}
            >
              {#if showPassword}
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M3.98 8.223A10.477 10.477 0 001.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88" />
                </svg>
              {:else}
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
                  <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
              {/if}
            </button>
          </div>
          <p class="mt-1 text-[11px] text-zinc-600">Password must be at least 6 characters.</p>
        </div>
        <button type="submit" class="btn-primary w-full" disabled={loading || !apiReady}>
          {loading ? 'Rolling camera…' : mode === 'login' ? 'Enter studio' : 'Create account'}
        </button>
      </form>

      <p class="mt-4 text-center text-[11px] text-zinc-600">
        After login you'll pick a weekly plan. No plan = no edits (fair's fair).
      </p>
    </div>
  </div>
</div>
