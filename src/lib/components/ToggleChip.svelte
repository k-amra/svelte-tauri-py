<script lang="ts">
	let {
		checked = $bindable(),
		label,
		title,
		disabled = false
	}: {
		checked: boolean;
		label: string;
		title?: string;
		disabled?: boolean;
	} = $props();
</script>

<label
	class="has-[:checked]:border-primary/40 has-[:checked]:bg-primary/10 border-border/60 hover:bg-muted flex cursor-pointer items-center gap-2 rounded-md border px-2.5 py-1.5 text-xs transition-colors"
	{title}
>
	<input type="checkbox" bind:checked {disabled} class="accent-primary size-3.5" />
	<span>{label}</span>
</label>
