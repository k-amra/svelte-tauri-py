<script lang="ts">
	import type { UrlCount } from '$lib/api/chatStats';
	import { openExternal } from '$lib/api/external';
	import { X } from '@lucide/svelte';

	let {
		open = $bindable(false),
		urls,
		maxCount,
		uniqueUrlCount
	}: {
		open: boolean;
		urls: UrlCount[];
		maxCount: number;
		uniqueUrlCount: number;
	} = $props();

	let dialogEl: HTMLDialogElement | null = $state(null);

	// `showModal()` / `close()` are imperative — the browser owns the actual
	// modal state, so we have to mirror our `open` boolean onto the element
	// whenever either side changes.
	$effect(() => {
		if (!dialogEl) return;
		if (open && !dialogEl.open) {
			dialogEl.showModal();
		} else if (!open && dialogEl.open) {
			dialogEl.close();
		}
	});

	function close() {
		open = false;
	}

	// Esc fires `cancel` on <dialog>. Don't preventDefault — let the browser
	// run its own close path; the effect above keeps our state in sync.
	function onCancel() {
		open = false;
	}

	// A click on the backdrop has the <dialog> element itself as its target;
	// clicks on the inner card have a descendant target. That's the whole
	// "click outside to close" check.
	function onBackdrop(e: MouseEvent) {
		if (e.target === dialogEl) close();
	}
</script>

<dialog
	bind:this={dialogEl}
	oncancel={onCancel}
	onclick={onBackdrop}
	class="all-links-dialog"
	aria-labelledby="all-links-title"
>
	<div
		class="bg-background flex max-h-[80vh] w-[min(56rem,90vw)] flex-col rounded-lg border shadow-2xl"
	>
		<header class="border-border/60 flex items-start justify-between border-b px-4 py-3">
			<div>
				<h2 id="all-links-title" class="text-base font-semibold">All links</h2>
				<p class="text-muted-foreground text-xs">
					{#if urls.length < uniqueUrlCount}
						Showing {urls.length.toLocaleString()} of
						{uniqueUrlCount.toLocaleString()} unique · ranked by paste count
					{:else}
						{uniqueUrlCount.toLocaleString()} unique · ranked by paste count
					{/if}
				</p>
			</div>
			<button
				type="button"
				class="hover:bg-muted rounded-md p-1.5 transition-colors"
				onclick={close}
				aria-label="Close"
			>
				<X class="size-4" />
			</button>
		</header>

		<!-- The only scroller. Bounded by max-h-[80vh] on the card, so the
		     header/footer stay pinned while this body scrolls. -->
		<div class="flex-1 overflow-y-auto p-4">
			<div class="space-y-1">
				{#each urls as u (u.url)}
					<div class="flex items-center gap-2 text-xs">
						<button
							type="button"
							class="text-primary w-80 truncate text-left hover:underline"
							title={u.url}
							onclick={() => void openExternal(u.url)}
						>
							{u.url}
						</button>
						<div class="bg-muted h-3 flex-1 overflow-hidden rounded-full">
							<div
								class="h-full rounded-full bg-sky-500"
								style="width: {(u.count / maxCount) * 100}%"
							></div>
						</div>
						<span class="w-12 text-right tabular-nums">{u.count.toLocaleString()}</span>
					</div>
				{/each}
			</div>
		</div>

		<footer class="border-border/60 flex items-center justify-between border-t px-4 py-3">
			<p class="text-muted-foreground text-[11px]">Esc or click outside to close</p>
			<button
				type="button"
				class="hover:bg-muted rounded-md border px-3 py-1.5 text-xs transition-colors"
				onclick={close}
			>
				Close
			</button>
		</footer>
	</div>
</dialog>

<style>
	/* Strip the browser's default dialog chrome so only our inner card shows,
	   and pin the modal to the viewport center. Resetting max-width/max-height
	   (needed so our card controls its own size) drops the UA stylesheet's
	   implicit centering in some engines — these explicit values restore it. */
	.all-links-dialog {
		padding: 0;
		border: none;
		background: transparent;
		max-width: none;
		max-height: none;
		position: fixed;
		inset: 0;
		margin: auto;
		width: fit-content;
		height: fit-content;
	}
	.all-links-dialog::backdrop {
		background: rgb(0 0 0 / 0.5);
		backdrop-filter: blur(2px);
	}
</style>
