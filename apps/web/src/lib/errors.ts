export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.';
}

export function aborted(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}
