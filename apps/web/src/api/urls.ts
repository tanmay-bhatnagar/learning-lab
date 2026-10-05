export const topicPath = (id: string) => `/topics/${encodeURIComponent(id)}`;

export const filePath = (topic: string, fileId: string) => `${topicPath(topic)}/files/${encodeURIComponent(fileId)}`;

export const originalPdfUrl = (topic: string, fileId: string, page: number) =>
  `/api${filePath(topic, fileId)}/original#page=${page}`;

export const fileMarkdownPath = (topic: string, fileId: string) => `${filePath(topic, fileId)}/markdown`;

export const fileOriginalPath = (topic: string, fileId: string) => `${filePath(topic, fileId)}/original`;

export const fileChunksPath = (topic: string, fileId: string) => `${filePath(topic, fileId)}/chunks`;

export const fileMapPath = (topic: string, fileId: string) => `${filePath(topic, fileId)}/map`;

export const fileSectionSummaryPath = (topic: string, fileId: string, sectionId: string) =>
  `${fileMapPath(topic, fileId)}/sections/${encodeURIComponent(sectionId)}/summary`;

export const assetApiUrl = (topic: string, fileId: string, assetId: string) =>
  `/api${filePath(topic, fileId)}/assets/${encodeURIComponent(assetId)}`;

export const retrievalTracePath = (topic: string) => `${topicPath(topic)}/retrieval/trace`;

export const learningGoalPath = (topic: string) => `${topicPath(topic)}/learning-goal`;

export const topicMessagesPath = (topic: string) => `${topicPath(topic)}/messages`;

export const topicFilesPath = (topic: string) => `${topicPath(topic)}/files`;

export const topicChatPath = (topic: string) => `${topicPath(topic)}/chat`;

export const conversationsPath = (topic: string) => `${topicPath(topic)}/conversations`;
export const conversationPath = (topic: string, id: string) => `${conversationsPath(topic)}/${encodeURIComponent(id)}`;
export const conversationMessagesPath = (topic: string, id: string) => `${conversationPath(topic, id)}/messages`;
export const conversationChatPath = (topic: string, id: string) => `${conversationPath(topic, id)}/chat`;
export const conversationSummaryImportsPath = (topic: string, id: string) =>
  `${conversationPath(topic, id)}/summary-imports`;
