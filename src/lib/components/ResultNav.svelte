<script module lang="ts">
	// Module script so consumers can `import { type ResultNavSection } from './ResultNav.svelte'`.
	export interface ResultNavSection {
		id: string;
		label: string;
	}
</script>

<script lang="ts">
	let {
		sections,
		stickyTopClass = 'top-0'
	}: { sections: ResultNavSection[]; stickyTopClass?: string } = $props();

	let active = $state('');
	// Falls back to the first section until the observer reports a real one
	// (avoids capturing the prop's initial value into $state).
	const current = $derived(active || sections[0]?.id || '');

	$effect(() => {
		// jsdom (tests) has no IntersectionObserver; degrade to first-tab-active.
		if (typeof IntersectionObserver === 'undefined') return;
		// rootMargin: bias the intersection box to the top third of the viewport,
		// so a section "activates" as it enters reading position, not when its
		// last pixel scrolls past. -70% bottom = ignore the lower 70% of screen.
		const observer = new IntersectionObserver(
			(entries) => {
				for (const entry of entries) {
					if (entry.isIntersecting) active = entry.target.id;
				}
			},
			{ rootMargin: '-15% 0px -70% 0px', threshold: 0 }
		);

		const cleanups: (() => void)[] = [];
		for (const s of sections) {
			const el = document.getElementById(s.id);
			if (el) {
				observer.observe(el);
				cleanups.push(() => observer.unobserve(el));
			}
		}
		return () => {
			cleanups.forEach((fn) => fn());
			observer.disconnect();
		};
	});
</script>

<nav
	class="bg-card/95 border-border/60 sticky {stickyTopClass} z-20 -mx-6 mb-4 border-b px-6 py-2 backdrop-blur lg:col-span-2"
	aria-label="Result sections"
>
	<ul class="flex gap-1 overflow-x-auto text-xs">
		{#each sections as s (s.id)}
			<li class="shrink-0">
				<a
					href="#{s.id}"
					onclick={() => {
						// Anchor navigation alone doesn't open a closed <details>;
						// the user lands on a collapsed section with no visible content.
						const el = document.getElementById(s.id);
						if (el instanceof HTMLDetailsElement && !el.open) el.open = true;
					}}
					class="rounded px-2.5 py-1 transition-colors {current === s.id
						? 'bg-primary text-primary-foreground'
						: 'text-muted-foreground hover:bg-muted hover:text-foreground'}"
				>
					{s.label}
				</a>
			</li>
		{/each}
	</ul>
</nav>
