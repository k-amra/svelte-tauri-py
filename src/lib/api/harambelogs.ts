export type ChannelIdType = 'channel' | 'channelid';
export type UserIdType = 'user' | 'userid';

export interface PreviousName {
	user_login: string;
	last_timestamp: string;
	first_timestamp: string;
}

export interface FullMessage {
	type: number;
	text: string;
	displayName: string;
	timestamp: string;
	id: string;
	tags: Record<string, any>;
	username: string;
	channel: string;
	raw: string;
}

export interface JsonLogsResponse {
	messages: FullMessage[];
}

export interface UserLogsStats {
	userId: string;
	userLogin: string | null;
	messageCount: number;
}

export interface TopChatter {
	userId: string;
	userLogin: string | null;
	messageCount: number;
}

export interface ChannelLogsStats {
	messageCount: number;
	topChatters: TopChatter[];
}