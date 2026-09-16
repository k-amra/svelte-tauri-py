/**
 * View registry for the app shell (App.svelte + AppNav.svelte).
 *
 * Adding a new view:
 *   1. Create the component under src/lib/components/
 *   2. Add one entry below (id, label, icon, component)
 * The nav menu picks it up automatically — no other wiring needed.
 */
import type { Component } from 'svelte';
import { Database, Home, Terminal, TrendingUp } from '@lucide/svelte';
import ChatStatsPanel from '$lib/components/ChatStatsPanel.svelte';
import HarambelogsPanel from '$lib/components/HarambelogsPanel.svelte';
import HelloWorld from '$lib/components/HelloWorld.svelte';
import ScriptsPanel from '$lib/components/ScriptsPanel.svelte';

// Every lucide icon shares the same component shape; anchor the type to one.
export type ViewIcon = typeof Home;

export interface ViewDefinition {
	id: string;
	label: string;
	icon: ViewIcon;
	component: Component;
}

/** Tab shown on startup. */
export const DEFAULT_VIEW = 'chat-stats';

export const views: ViewDefinition[] = [
	{ id: 'home', label: 'Home', icon: Home, component: HelloWorld },
	{ id: 'sidecar', label: 'Python Sidecar', icon: Terminal, component: ScriptsPanel },
	{ id: 'harambelogs', label: 'Harambelogs', icon: Database, component: HarambelogsPanel },
	{ id: 'chat-stats', label: 'Chat Statistics', icon: TrendingUp, component: ChatStatsPanel }
];
