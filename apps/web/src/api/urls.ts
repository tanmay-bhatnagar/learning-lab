export const topicPath = (id: string) => `/topics/${encodeURIComponent(id)}`;

export const filePath = (topic: string, fileId: string) => `${topicPath(topic)}/files/${encodeURIComponent(fileId)}`;

export const originalPdfUrl = (topic: string, fileId: string, page: number) =>
  `/api${filePath(topic, fileId)}/original#page=${page}`;

export const fileMarkdownPath = (topic: string, fileId: string) => `${filePath(topic, fileId)}/markdown`;

export const fileOriginalPath = (topic: string, fileId: string) => `${filePath(topic, fileId)}/original`;

export const fileChunksPath = (topic: string, fileId: string) => `${filePath(topic, fileId)}/chunks`;

export const assetApiUrl = (topic: string, fileId: string, assetId: string) =>
  `/api${filePath(topic, fileId)}/assets/${encodeURIComponent(assetId)}`;

export const retrievalTracePath = (topic: string) => `${topicPath(topic)}/retrieval/trace`;

export const learningGoalPath = (topic: string) => `${topicPath(topic)}/learning-goal`;

export const topicMessagesPath = (topic: string) => `${topicPath(topic)}/messages`;

export const topicFilesPath = (topic: string) => `${topicPath(topic)}/files`;

export const topicChatPath = (topic: string) => `${topicPath(topic)}/chat`;
