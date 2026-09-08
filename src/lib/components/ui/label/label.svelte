<script lang="ts">
	import { Label as LabelPrimitive } from 'bits-ui';
	import { cn } from '$lib/utils.js';
	import type { WithElementRef } from '$lib/utils.js';
	import type { HTMLLabelAttributes } from 'svelte/elements';

	type Props = WithElementRef<HTMLLabelAttributes>;

	let { ref = $bindable(null), class: className, children, ...restProps }: Props = $props();
</script>

<LabelPrimitive.Root
	bind:ref
	class={cn(
		'text-sm leading-none font-medium peer-disabled:cursor-not-allowed peer-disabled:opacity-70',
		className
	)}
	data-slot="label"
	{...restProps}
>
	{@render children?.()}
</LabelPrimitive.Root>
